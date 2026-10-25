"""spotDL worker, run in a child process started by the GUI.

Instead of running spotDL's own `download` command, the worker drives spotDL
as a library so that it can:
- complete track metadata and check what is already downloaded with many
  threads, and use the profile's thread count only for actual downloads;
- re-download tracks whose existing file does not match the selected format
  and bitrate, or is clearly shorter than the track (left incomplete);
- work around spotDL creating its YouTube Music client in German, a language
  for which YouTube Music currently returns no search results at all.
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse


# Threads used to fetch metadata and check existing files. Downloads use the
# profile's own thread count, which is what triggers provider rate limits.
CHECK_THREADS = 8
# Formats offered by the GUI; lossless ones have no meaningful bitrate.
FORMATS = ["mp3", "m4a", "opus", "ogg", "flac", "wav"]
LOSSLESS_FORMATS = {"flac", "wav"}
BITRATES = ["auto", "128k", "160k", "192k", "256k", "320k"]
# Encoders do not hit the requested bitrate exactly (VBR, container overhead).
# Opus is variable bitrate and measured at 72-81% of the requested value.
BITRATE_TOLERANCE = 0.9
BITRATE_TOLERANCE_BY_FORMAT = {"opus": 0.65}
# A file shorter than this fraction of the track is considered incomplete.
MIN_DURATION_RATIO = 0.75
# yt-dlp errors that concern one video only, so another search result may
# work. Bot checks and rate limits are left out: they apply to every video.
BLOCKED_VIDEO_ERRORS = re.compile(
    r"confirm your age|age.restricted|video unavailable|not available in your country"
    r"|private video|members.only|join this channel",
    re.IGNORECASE,
)
# How many other search results to try after a blocked video.
MAX_ALTERNATIVE_RESULTS = 3
# Spotify data cached between runs (see SpotifyCache), stored with the
# configuration in data\ (see config_manager.config_dir).
CACHE_FILENAME = "spotify_cache.json"
TRACK_CACHE_DAYS = 30
SPOTIFY_TRACK_URL = re.compile(r"open\.spotify\.com/(?:intl-[\w-]+/)?track/(\w+)")
WEB_PLAYER_HASH = re.compile(r'"\w+","(?:query|mutation)","[0-9a-f]{64}"')
# Output lines starting with this prefix carry a JSON progress event for the
# GUI instead of a log message.
PROGRESS_PREFIX = "@@progress "


def emit(event, **data):
    """Send a progress event to the GUI.

    Events, in order:
    - phase: phase="fetching" | "checking" (total=...) | "downloading"
    - total: total tracks and how many are already up to date ("done")
    - track: one download finished, ok=True/False, name=..., url=... (Spotify)
    - cleanup: at the end of a complete run, files the user may want to move
      to the Recycle Bin: removed=[...] (tracks no longer in the playlist)
      and other_formats=[...] (older copies in another audio format), paths
      relative to the destination folder
    """
    # A single write, so log lines from other threads cannot split the event.
    sys.stdout.write(PROGRESS_PREFIX + json.dumps({"event": event, **data}) + "\n")
    sys.stdout.flush()


def hide_child_consoles():
    """Start every console child (FFmpeg, FFprobe, Deno) without a window.

    In the packaged windowed build the worker has no console, so Windows opens
    a new, visible console for each console program spotDL starts, which then
    flashes on screen. spotDL and yt-dlp do not pass CREATE_NO_WINDOW, so it is
    added here to every subprocess.Popen, which asyncio subprocesses also use.
    """
    if sys.platform != "win32":
        return
    import subprocess

    original_init = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):
        flags = kwargs.get("creationflags", 0)
        if not flags & (subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS):
            kwargs["creationflags"] = flags | subprocess.CREATE_NO_WINDOW
        original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__


def use_english_youtube_music():
    """Create spotDL's YouTube Music clients in English.

    spotDL hardcodes language="de"; with any non-English language YouTube Music
    returns no results, so every track fails with "no usable results".
    """
    from ytmusicapi import YTMusic
    from spotdl.providers.audio.ytmusic import YouTubeMusic

    YouTubeMusic._create_client = staticmethod(lambda: YTMusic(language="en"))


def share_spotify_web_session():
    """Authenticate to the Spotify web player once per worker.

    spotDL reads Spotify through spotapi, which creates a new client for every
    track, album and artist lookup. Each client loads the web player page,
    requests new tokens and downloads about 80 JavaScript files to find the
    same query hashes: roughly 250 requests and 7 seconds per track, which
    quickly gets the user's IP rate limited (HTTP 429). The session state is
    shared between clients instead; an expired token is still refreshed by
    spotapi itself.
    """
    import threading
    from spotapi.client import BaseClient

    lock = threading.RLock()
    state = {}
    # Each step and the attributes it sets; get_client_token may call get_session.
    steps = {
        "get_session": ("js_pack", "client_version", "device_id", "access_token",
                        "client_id", "access_token_expires_at_ms"),
        "get_client_token": ("client_token",),
        "get_sha256_hash": ("raw_hashes",),
    }

    original_init = BaseClient.__init__

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        with lock:
            for name, value in state.items():
                setattr(self, name, value)

    BaseClient.__init__ = __init__

    def shared(method, names):
        original = getattr(BaseClient, method)

        def wrapper(self, *args, **kwargs):
            # Other threads wait for the first client instead of repeating its requests.
            with lock:
                if all(name in state for name in names):
                    for name in names:
                        setattr(self, name, state[name])
                    return None
                result = original(self, *args, **kwargs)
                for name in names:
                    state[name] = getattr(self, name)
                return result

        setattr(BaseClient, method, wrapper)

    for method, names in steps.items():
        shared(method, names)


class SpotifyCache:
    """Spotify data kept between runs, so repeated runs on the same playlist
    cost almost no requests and do not get the IP rate limited (HTTP 429).

    Holds each track's metadata for TRACK_CACHE_DAYS days, and the Spotify web
    player query hashes for as long as the web player build does not change.
    A missing or damaged file is simply treated as an empty cache.
    """

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.changed = False
        self.data = {"tracks": {}, "web_hashes": None}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("tracks"), dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass

    def get_track(self, track_id):
        entry = self.data["tracks"].get(track_id)
        if entry and time.time() - entry.get("fetched", 0) < TRACK_CACHE_DAYS * 86400:
            return entry.get("data")
        return None

    def put_track(self, track_id, data):
        with self.lock:
            self.data["tracks"][track_id] = {"fetched": time.time(), "data": data}
            self.changed = True

    def get_web_hashes(self, js_pack):
        entry = self.data.get("web_hashes")
        if isinstance(entry, dict) and entry.get("js_pack") == js_pack:
            return entry.get("hashes")
        return None

    def put_web_hashes(self, js_pack, hashes):
        with self.lock:
            self.data["web_hashes"] = {"js_pack": js_pack, "hashes": hashes}
            self.changed = True

    def save(self):
        with self.lock:
            if not self.changed:
                return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = self.path.with_suffix(".tmp")
                temp_path.write_text(json.dumps(self.data), encoding="utf-8")
                temp_path.replace(self.path)
                self.changed = False
            except OSError as exc:
                print(f"[Cache] Could not save the Spotify cache: {exc}", flush=True)


def spotify_track_id(url):
    """Return the track id of a Spotify track URL, or None."""
    match = SPOTIFY_TRACK_URL.search(url or "")
    return match.group(1) if match else None


def cache_spotify_lookups(cache):
    """Serve track metadata and web player hashes from the cache when possible.

    Must be called before share_spotify_web_session, which then shares the
    cached hashes between clients like freshly downloaded ones.
    """
    from spotapi.client import BaseClient
    from spotapi.types.alias import _Undefined
    from spotdl.types.song import Song

    original_from_url = Song.from_url.__func__

    def from_url(cls, url):
        track_id = spotify_track_id(url)
        data = cache.get_track(track_id) if track_id else None
        if data is not None:
            try:
                return cls(**data)
            except TypeError:
                # Saved by a spotDL version with other fields: fetch it again.
                pass
        song = original_from_url(cls, url)
        if track_id:
            cache.put_track(track_id, song.json)
        return song

    Song.from_url = classmethod(from_url)

    original_hashes = BaseClient.get_sha256_hash

    def get_sha256_hash(self):
        if self.js_pack is _Undefined:
            self.get_session()
        js_pack = str(self.js_pack)
        hashes = cache.get_web_hashes(js_pack)
        if hashes:
            self.raw_hashes = hashes
            return
        original_hashes(self)
        # Keep only the "name","query|mutation","sha256" entries spotapi looks up.
        hashes = ",".join(WEB_PLAYER_HASH.findall(str(self.raw_hashes)))
        if hashes:
            self.raw_hashes = hashes
            cache.put_web_hashes(js_pack, hashes)

    BaseClient.get_sha256_hash = get_sha256_hash


def video_id(url):
    """Return the YouTube video id of a watch URL, or None."""
    if not url:
        return None
    return parse_qs(urlparse(url).query).get("v", [None])[0]


def skip_blocked_videos():
    """Exclude videos that cannot be downloaded from later search results.

    Some results are age restricted (or private, region locked...). This is
    attached to the video itself, so music.youtube.com and youtube.com fail
    alike. When yt-dlp reports such an error, the video id is recorded and
    filtered out of YouTube Music results, so that searching again picks the
    next best result. Returns the {video id: reason} dict that is filled in.
    """
    from spotdl.providers.audio.base import AudioProvider, AudioProviderError
    from spotdl.providers.audio.ytmusic import YouTubeMusic

    blocked = {}

    original_metadata = AudioProvider.get_download_metadata

    def get_download_metadata(self, url, download=False):
        try:
            return original_metadata(self, url, download=download)
        except AudioProviderError as exc:
            match = BLOCKED_VIDEO_ERRORS.search(str(exc.__cause__ or ""))
            if match and video_id(url):
                blocked[video_id(url)] = match.group(0).lower()
            raise

    AudioProvider.get_download_metadata = get_download_metadata

    # To break ties between close results, spotDL reads every candidate's view
    # count through yt-dlp, so a single blocked candidate made the whole search
    # fail. Count it as 0 views instead; if it is still picked, the download
    # fails and the track is retried without it.
    original_views = AudioProvider.get_views

    def get_views(self, url):
        try:
            return original_views(self, url)
        except AudioProviderError:
            if video_id(url) in blocked:
                return 0
            raise

    AudioProvider.get_views = get_views

    original_results = YouTubeMusic.get_results

    def get_results(self, search_term, **kwargs):
        results = original_results(self, search_term, **kwargs)
        return [result for result in results if result.result_id not in blocked]

    YouTubeMusic.get_results = get_results
    return blocked


def track_downloads(downloader, blocked_videos):
    """Retry blocked videos with another result and report each download.

    Patches the spotDL downloader instance: each track whose video turns out
    to be blocked (see skip_blocked_videos) is searched and downloaded again,
    up to MAX_ALTERNATIVE_RESULTS times, then a "track" progress event is
    emitted; spotDL returns no path on failure.
    """
    # Remember which video each track was matched to.
    searched_urls = {}
    search = downloader.search

    def tracked_search(song):
        url = search(song)
        searched_urls[song.url] = url
        return url

    downloader.search = tracked_search

    search_and_download = downloader.async_search_and_download

    async def tracked_search_and_download(song):
        blocked_urls = []
        for attempt in range(MAX_ALTERNATIVE_RESULTS + 1):
            result_song, path = await search_and_download(song)
            url = searched_urls.get(song.url)
            reason = blocked_videos.get(video_id(url))
            if path is not None or reason is None or attempt == MAX_ALTERNATIVE_RESULTS:
                break
            blocked_urls.append(url)
            # Make spotDL search again rather than reuse the blocked video.
            song.download_url = None
            print(f"[Retry] {song.display_name}: {reason} ({url}), "
                  f"trying another search result...", flush=True)
        if path is not None and blocked_urls:
            # Do not report the blocked attempts as errors at the end.
            downloader.errors[:] = [
                error for error in downloader.errors
                if not any(blocked in error for blocked in blocked_urls)
            ]
        emit("track", ok=path is not None, name=result_song.display_name, url=song.url)
        return result_song, path

    downloader.async_search_and_download = tracked_search_and_download


def select_tracks(songs, urls):
    """The songs whose Spotify track is in urls, in playlist order."""
    wanted = {spotify_track_id(url) for url in urls}
    return [song for song in songs if spotify_track_id(song.url) in wanted]


def playlist_file_name(list_name):
    """File name of the .m3u8 playlist written in the destination folder."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", list_name or "").strip(" .")
    return f"{name or 'playlist'}.m3u8"


def write_playlist_file(path, songs, files):
    """Write an extended M3U playlist (UTF-8) of the songs, in playlist order.

    files maps a song URL to its file, relative to the playlist's folder.
    Songs without a file (not downloaded yet, or failed) are left out.
    """
    lines = ["#EXTM3U"]
    for song in songs:
        file = files.get(song.url)
        if file is None or not (Path(path).parent / file).is_file():
            continue
        lines.append(f"#EXTINF:{int(song.duration or 0)},{song.display_name}")
        lines.append(str(file))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return (len(lines) - 1) // 2


def find_removed_tracks(known_songs, songs):
    """Files of known tracks (by the Spotify URL in their metadata) that are no
    longer in the playlist, sorted."""
    playlist_ids = {spotify_track_id(song.url) for song in songs}
    removed = []
    for url, paths in known_songs.items():
        if spotify_track_id(url) not in playlist_ids:
            removed.extend(path for path in paths if Path(path).is_file())
    return sorted({Path(path) for path in removed}, key=lambda path: str(path).lower())


def find_other_format_copies(songs, files, audio_format):
    """Copies of the songs in another audio format, next to their file in the
    selected format (same name, other extension), sorted. Only songs whose
    file in the selected format exists are considered, so an older copy is
    never the only one."""
    copies = []
    for song in songs:
        file = files.get(song.url)
        if file is None or not Path(file).is_file():
            continue
        for other in FORMATS:
            if other != audio_format:
                copy = Path(file).with_suffix(f".{other}")
                if copy.is_file():
                    copies.append(copy)
    return sorted(set(copies), key=lambda path: str(path).lower())


def bitrate_to_bps(bitrate):
    """Return "320k" as 320000, or None for "auto"."""
    if bitrate.endswith("k") and bitrate[:-1].isdigit():
        return int(bitrate[:-1]) * 1000
    return None


def describe_mismatch(path, target_bps, track_seconds):
    """Return why an existing file must be downloaded again, or None if it is fine."""
    import mutagen

    try:
        audio = mutagen.File(path)
    except Exception:
        audio = None
    if audio is None or not getattr(audio, "info", None) or not audio.info.length:
        return "file cannot be read"

    length = audio.info.length
    if track_seconds and length < track_seconds * MIN_DURATION_RATIO:
        return f"file is incomplete ({length:.0f}s of {track_seconds:.0f}s)"

    if target_bps:
        # Opus files expose no bitrate; derive an average one from the size.
        measured = getattr(audio.info, "bitrate", 0) or path.stat().st_size * 8 / length
        tolerance = BITRATE_TOLERANCE_BY_FORMAT.get(path.suffix.lower().lstrip("."), BITRATE_TOLERANCE)
        if measured < target_bps * tolerance:
            return f"bitrate {measured / 1000:.0f}k is below {target_bps // 1000}k"
    return None


def self_check():
    """Import everything the worker needs and apply every patch, without any
    network access. Used by build.ps1 to check a packaged build: it catches
    modules missing from the build and spotDL internals that changed.
    Returns a process exit code.
    """
    try:
        from spotapi.client import BaseClient
        from spotdl.download.downloader import Downloader
        from spotdl.providers.audio.base import AudioProvider
        from spotdl.providers.audio.ytmusic import YouTubeMusic
        from spotdl.types.song import Song
        import curl_cffi  # noqa: F401
        import mutagen  # noqa: F401
        import spotdl

        # Everything patched here or used through the downloader instance.
        expected = {
            BaseClient: ["get_session", "get_client_token", "get_sha256_hash", "raw_hashes", "js_pack"],
            AudioProvider: ["get_download_metadata", "get_views"],
            YouTubeMusic: ["get_results", "_create_client"],
            Downloader: ["search", "async_search_and_download", "download_multiple_songs"],
            Song: ["from_url", "json"],
        }
        missing = [f"{owner.__name__}.{name}" for owner, names in expected.items()
                   for name in names if not hasattr(owner, name)]
        if missing:
            print(f"Self-check FAILED: spotDL internals changed, missing: {', '.join(missing)}")
            return 1

        hide_child_consoles()
        cache_spotify_lookups(SpotifyCache(Path("self-check-not-saved.json")))
        use_english_youtube_music()
        share_spotify_web_session()
        skip_blocked_videos()
    except Exception as exc:
        print(f"Self-check FAILED: {type(exc).__name__}: {exc}")
        return 1
    print(f"Self-check OK (spotDL {spotdl.__version__})")
    return 0


def parse_options(argv):
    parser = argparse.ArgumentParser(prog="spotdl-worker")
    parser.add_argument("--url", required=True)
    parser.add_argument("--format", choices=FORMATS, default="mp3")
    parser.add_argument("--bitrate", choices=BITRATES, default="128k")
    parser.add_argument("--threads", type=int, default=1)
    # JSON file listing the Spotify track URLs to download, out of the
    # playlist: used to retry the tracks that failed.
    parser.add_argument("--only-tracks")
    return parser.parse_args(argv)


def run(argv):
    options = parse_options(argv)

    home_value = (
        os.environ.get("USERPROFILE")
        or os.environ.get("HOME")
        or str(Path(sys.executable).resolve().parent)
    )
    os.environ["HOME"] = home_value
    os.environ["USERPROFILE"] = home_value

    hide_child_consoles()
    use_english_youtube_music()
    from config_manager import config_dir

    spotify_cache = SpotifyCache(config_dir() / CACHE_FILENAME)
    cache_spotify_lookups(spotify_cache)
    share_spotify_web_session()
    blocked_videos = skip_blocked_videos()

    from spotdl.download.downloader import Downloader
    from spotdl.utils.arguments import parse_arguments
    from spotdl.utils.config import create_settings
    from spotdl.utils.console import generate_initial_config
    from spotdl.utils.ffmpeg import FFmpegError, is_ffmpeg_installed
    from spotdl.utils.formatter import create_file_name
    from spotdl.utils.logging import init_logging
    from spotdl.utils.search import get_simple_songs, reinit_song
    from spotdl.utils.spotify import SpotifyClient

    bitrate = "auto" if options.format in LOSSLESS_FORMATS else options.bitrate
    target_bps = bitrate_to_bps(bitrate)

    # Let spotDL build its settings from the same arguments as its CLI. Every
    # track handed to the downloader must be (re)downloaded, hence "force".
    generate_initial_config()
    sys.argv = [
        "spotdl", "download", options.url,
        "--format", options.format,
        "--bitrate", bitrate,
        "--threads", str(max(1, options.threads)),
        "--overwrite", "force",
        "--scan-for-songs",
    ]
    spotify_settings, settings, _ = create_settings(parse_arguments())
    init_logging(settings["log_level"], settings["log_format"])

    if not is_ffmpeg_installed(settings["ffmpeg"]):
        raise FFmpegError("FFmpeg was not found. Check the vendor folder.")

    SpotifyClient.init(**spotify_settings)

    emit("phase", phase="fetching")
    songs = get_simple_songs(
        [options.url],
        use_ytm_data=settings["ytm_data"],
        playlist_numbering=settings["playlist_numbering"],
        albums_to_ignore=settings["ignore_albums"],
        album_type=settings["album_type"],
        playlist_retain_track_cover=settings["playlist_retain_track_cover"],
    )
    playlist_name = songs[0].list_name if songs else None
    # A retry only handles some tracks: the playlist file and the removed
    # tracks would then be wrong, so they are left for complete runs.
    complete_run = not options.only_tracks
    if not complete_run:
        wanted = json.loads(Path(options.only_tracks).read_text(encoding="utf-8"))
        total_in_playlist = len(songs)
        songs = select_tracks(songs, wanted)
        print(f"[Retry] Retrying {len(songs)} of {total_in_playlist} tracks.", flush=True)

    emit("phase", phase="checking", total=len(songs))
    print(f"[Check] Fetching track details with {CHECK_THREADS} threads...", flush=True)

    def complete(song):
        try:
            return reinit_song(song)
        except Exception:
            # The downloader retries this itself if the track is downloaded.
            return song

    with concurrent.futures.ThreadPoolExecutor(max_workers=CHECK_THREADS) as executor:
        songs = list(executor.map(complete, songs))

    # Creating the downloader scans the destination for known tracks.
    downloader = Downloader(settings)

    # File of each track in the destination, for the .m3u8 playlist: the
    # expected name, or an existing file found through its metadata.
    track_files = {}

    def check(song):
        output_file = create_file_name(
            song=song,
            template=settings["output"],
            file_extension=settings["format"],
            restrict=settings["restrict"],
            file_name_length=settings["max_filename_length"],
        )
        track_files[song.url] = output_file
        candidates = [output_file] + downloader.known_songs.get(song.url, [])
        existing = [path for path in candidates if path.exists()]
        if not existing:
            return song, "missing", None
        reasons = [describe_mismatch(path, target_bps, song.duration) for path in existing]
        if None in reasons:
            track_files[song.url] = existing[reasons.index(None)]
            return song, "ok", None
        return song, "redownload", reasons[0]

    with concurrent.futures.ThreadPoolExecutor(max_workers=CHECK_THREADS) as executor:
        results = list(executor.map(check, songs))

    to_download = []
    up_to_date = missing = 0
    for song, state, reason in results:
        if state == "ok":
            up_to_date += 1
        elif state == "missing":
            missing += 1
            to_download.append(song)
        else:
            print(f"[Check] Downloading again {song.display_name}: {reason}", flush=True)
            to_download.append(song)

    print(
        f"[Check] {len(songs)} tracks: {up_to_date} up to date, {missing} missing, "
        f"{len(to_download) - missing} to download again "
        f"(format {options.format}, bitrate {bitrate}).",
        flush=True,
    )
    emit("total", total=len(songs), done=up_to_date)
    # Saved now so that a stopped run keeps what it fetched.
    spotify_cache.save()

    if to_download:
        track_downloads(downloader, blocked_videos)
        emit("phase", phase="downloading")
        print(f"[Download] Downloading {len(to_download)} tracks with "
              f"{settings['threads']} thread(s)...", flush=True)
        downloader.download_multiple_songs(to_download)
    downloader.progress_handler.close()
    spotify_cache.save()

    if not complete_run:
        return

    # Downloaded tracks are at their expected name; a failed one has no file.
    playlist_path = Path(playlist_file_name(playlist_name))
    count = write_playlist_file(playlist_path, songs, track_files)
    print(f"[Sync] Playlist file {playlist_path} written with {count} of {len(songs)} tracks.", flush=True)

    removed = find_removed_tracks(downloader.known_songs, songs)
    if removed:
        print(f"[Sync] {len(removed)} file(s) in this folder are no longer in the playlist:", flush=True)
        for path in removed:
            print(f"  - {path}", flush=True)

    other_formats = find_other_format_copies(songs, track_files, options.format)
    if other_formats:
        print(f"[Sync] {len(other_formats)} track(s) also have an older copy in another format:", flush=True)
        for path in other_formats:
            print(f"  - {path}", flush=True)
    emit("cleanup", removed=[str(path) for path in removed],
         other_formats=[str(path) for path in other_formats])
