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
import sys
from pathlib import Path


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
# Output lines starting with this prefix carry a JSON progress event for the
# GUI instead of a log message.
PROGRESS_PREFIX = "@@progress "


def emit(event, **data):
    """Send a progress event to the GUI.

    Events, in order:
    - phase: phase="fetching" | "checking" (total=...) | "downloading"
    - total: total tracks and how many are already up to date ("done")
    - track: one download finished, ok=True/False, name=...
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


def parse_options(argv):
    parser = argparse.ArgumentParser(prog="spotdl-worker")
    parser.add_argument("--url", required=True)
    parser.add_argument("--format", choices=FORMATS, default="mp3")
    parser.add_argument("--bitrate", choices=BITRATES, default="128k")
    parser.add_argument("--threads", type=int, default=1)
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
    share_spotify_web_session()

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

    def check(song):
        output_file = create_file_name(
            song=song,
            template=settings["output"],
            file_extension=settings["format"],
            restrict=settings["restrict"],
            file_name_length=settings["max_filename_length"],
        )
        candidates = [output_file] + downloader.known_songs.get(song.url, [])
        existing = [path for path in candidates if path.exists()]
        if not existing:
            return song, "missing", None
        reasons = [describe_mismatch(path, target_bps, song.duration) for path in existing]
        if None in reasons:
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

    if to_download:
        # Report each finished download; spotDL returns no path on failure.
        search_and_download = downloader.async_search_and_download

        async def tracked_search_and_download(song):
            result_song, path = await search_and_download(song)
            emit("track", ok=path is not None, name=result_song.display_name)
            return result_song, path

        downloader.async_search_and_download = tracked_search_and_download

        emit("phase", phase="downloading")
        print(f"[Download] Downloading {len(to_download)} tracks with "
              f"{settings['threads']} thread(s)...", flush=True)
        downloader.download_multiple_songs(to_download)
    downloader.progress_handler.close()
