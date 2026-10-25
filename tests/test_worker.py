"""Worker logic that does not need the network (SPECIFICATION.md, section 9)."""

import asyncio
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT

import worker

FFMPEG = ROOT / "vendor" / "ffmpeg.exe"


class BlockedVideoRetryTests(unittest.TestCase):
    """track_downloads() with a fake downloader: no network involved."""

    class Song:
        def __init__(self):
            self.url = "https://open.spotify.com/track/1"
            self.display_name = "Artist - Song"
            self.download_url = None

    class FakeDownloader:
        """search() returns the first candidate not blocked yet; downloading a
        video listed in blocked_ids fails and records it, like spotDL does
        through skip_blocked_videos()."""

        def __init__(self, candidates, blocked_ids, blocked):
            self.candidates = candidates
            self.blocked_ids = blocked_ids
            self.blocked = blocked
            self.errors = []
            self.attempts = 0

        def search(self, song):
            return next(url for url in self.candidates if worker.video_id(url) not in self.blocked)

        async def async_search_and_download(self, song):
            self.attempts += 1
            url = self.search(song)
            if worker.video_id(url) in self.blocked_ids:
                self.blocked[worker.video_id(url)] = "confirm your age"
                self.errors.append(f"{song.url} - AudioProviderError: YT-DLP download error - {url}")
                return song, None
            return song, f"{song.display_name}.mp3"

    def download(self, candidate_ids, blocked_ids):
        blocked = {}
        urls = [f"https://music.youtube.com/watch?v={video}" for video in candidate_ids]
        downloader = self.FakeDownloader(urls, set(blocked_ids), blocked)
        worker.track_downloads(downloader, blocked)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            _, path = asyncio.run(downloader.async_search_and_download(self.Song()))
        return downloader, path, output.getvalue()

    def test_blocked_result_is_replaced_by_the_next_one(self):
        downloader, path, output = self.download(["A", "B"], ["A"])
        self.assertEqual(path, "Artist - Song.mp3")
        self.assertEqual(downloader.attempts, 2)
        self.assertIn("[Retry] Artist - Song: confirm your age", output)
        self.assertEqual(downloader.errors, [], "the blocked attempt must not be reported")
        self.assertIn('"event": "track", "ok": true', output)

    def test_gives_up_after_the_maximum_number_of_results(self):
        ids = ["A", "B", "C", "D", "E"]
        downloader, path, output = self.download(ids, ids)
        self.assertIsNone(path)
        self.assertEqual(downloader.attempts, 1 + worker.MAX_ALTERNATIVE_RESULTS)
        self.assertEqual(len(downloader.errors), downloader.attempts)
        self.assertIn('"ok": false', output)

    def test_normal_download_is_not_retried(self):
        downloader, path, output = self.download(["A"], [])
        self.assertTrue(path)
        self.assertEqual(downloader.attempts, 1)
        self.assertNotIn("[Retry]", output)

    def test_video_id(self):
        self.assertEqual(worker.video_id("https://music.youtube.com/watch?v=f1IdyrhOrGs"), "f1IdyrhOrGs")
        self.assertIsNone(worker.video_id(None))


class SpotifyCacheTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "spotify_cache.json"
        self.addCleanup(self._tmp.cleanup)

    def patch_lookups(self, cache):
        """Apply cache_spotify_lookups over a fake network lookup, and restore
        spotDL and spotapi afterwards."""
        from spotapi.client import BaseClient
        from spotdl.types.song import Song

        self.lookups = []

        def fake_from_url(cls, url):
            self.lookups.append(url)
            return cls(
                name="N", artists=["A"], artist="A", genres=[], disc_number=1, disc_count=1,
                album_name="Al", album_artist="A", duration=200, year=2000, date="2000",
                track_number=1, tracks_count=1, song_id=url[-4:], explicit=False, publisher="",
                url=url, isrc="X", cover_url=None, copyright_text=None,
            )

        for target, attribute, value in [
            (Song, "from_url", classmethod(fake_from_url)),
            (BaseClient, "get_sha256_hash", BaseClient.get_sha256_hash),
        ]:
            patcher = mock.patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        worker.cache_spotify_lookups(cache)
        return Song

    def test_second_lookup_is_served_from_the_cache(self):
        cache = worker.SpotifyCache(self.path)
        song_class = self.patch_lookups(cache)
        url = "https://open.spotify.com/track/2RsAajgo0g7bMCHxwH3Sk0"
        song_class.from_url(url)
        song = song_class.from_url(url + "?si=abc")
        self.assertEqual(self.lookups, [url])
        self.assertEqual(song.name, "N")

    def test_saved_and_reloaded(self):
        cache = worker.SpotifyCache(self.path)
        song_class = self.patch_lookups(cache)
        song_class.from_url("https://open.spotify.com/track/ABC")
        cache.save()
        self.assertIn("ABC", json.loads(self.path.read_text(encoding="utf-8"))["tracks"])
        self.assertEqual(worker.SpotifyCache(self.path).get_track("ABC")["name"], "N")

    def test_entries_expire(self):
        cache = worker.SpotifyCache(self.path)
        cache.put_track("OLD", {"name": "x"})
        cache.data["tracks"]["OLD"]["fetched"] = time.time() - (worker.TRACK_CACHE_DAYS + 1) * 86400
        self.assertIsNone(cache.get_track("OLD"))

    def test_incompatible_entry_is_fetched_again(self):
        cache = worker.SpotifyCache(self.path)
        song_class = self.patch_lookups(cache)
        cache.put_track("OLD", {"name": "x", "field_from_another_version": 1})
        song_class.from_url("https://open.spotify.com/track/OLD")
        self.assertEqual(self.lookups, ["https://open.spotify.com/track/OLD"])

    def test_damaged_file_gives_an_empty_cache(self):
        self.path.write_text("{broken", encoding="utf-8")
        self.assertEqual(worker.SpotifyCache(self.path).data["tracks"], {})

    def test_web_hashes_are_tied_to_the_web_player_build(self):
        cache = worker.SpotifyCache(self.path)
        cache.put_web_hashes("build-1", '"getTrack","query","' + "a" * 64 + '"')
        self.assertTrue(cache.get_web_hashes("build-1"))
        self.assertIsNone(cache.get_web_hashes("build-2"))

    def test_nothing_written_when_unchanged(self):
        worker.SpotifyCache(self.path).save()
        self.assertFalse(self.path.exists())

    def test_track_id_parsing(self):
        self.assertEqual(worker.spotify_track_id("https://open.spotify.com/intl-fr/track/ABC123?si=x"), "ABC123")
        self.assertIsNone(worker.spotify_track_id("https://open.spotify.com/playlist/XYZ"))


@unittest.skipUnless(FFMPEG.is_file(), "needs vendor/ffmpeg.exe to create test files")
class QualityCheckTests(unittest.TestCase):
    """describe_mismatch() on audio files generated with FFmpeg."""

    DURATION = 30

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        noise = f"anoisesrc=duration={cls.DURATION}:amplitude=0.2:color=pink"
        for name, codec, bitrate, source in [
            ("a128.mp3", "libmp3lame", "128k", noise),
            ("a320.mp3", "libmp3lame", "320k", noise),
            ("a128.m4a", "aac", "128k", noise),
            ("a256.m4a", "aac", "256k", noise),
            ("a160.opus", "libopus", "160k", noise),
            ("a256.opus", "libopus", "256k", noise),
            ("a192.ogg", "libvorbis", "192k", noise),
            ("short.mp3", "libmp3lame", "320k", "sine=frequency=440:duration=10"),
        ]:
            subprocess.run(
                [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", source, "-ac", "2",
                 "-c:a", codec, "-b:a", bitrate, str(cls.dir / name)],
                check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        (cls.dir / "broken.mp3").write_bytes(b"garbage")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def mismatch(self, name, bitrate, track_seconds=DURATION):
        return worker.describe_mismatch(self.dir / name, worker.bitrate_to_bps(bitrate), track_seconds)

    def test_file_accepted_for_its_bitrate_and_lower_ones(self):
        for name, ok_up_to in [("a128.mp3", "128k"), ("a320.mp3", "320k"), ("a128.m4a", "128k"),
                               ("a256.m4a", "256k"), ("a160.opus", "160k"), ("a256.opus", "256k"),
                               ("a192.ogg", "192k")]:
            for bitrate in worker.BITRATES[1:]:
                expected_ok = int(bitrate[:-1]) <= int(ok_up_to[:-1])
                with self.subTest(file=name, bitrate=bitrate):
                    result = self.mismatch(name, bitrate)
                    if expected_ok:
                        self.assertIsNone(result)
                    else:
                        self.assertIn("below", result)

    def test_auto_bitrate_checks_nothing_but_the_file(self):
        self.assertIsNone(self.mismatch("a128.mp3", "auto"))

    def test_truncated_file_is_downloaded_again(self):
        self.assertIn("incomplete", self.mismatch("short.mp3", "auto", track_seconds=60))
        self.assertIsNone(self.mismatch("short.mp3", "auto", track_seconds=11))

    def test_unreadable_file_is_downloaded_again(self):
        self.assertEqual(self.mismatch("broken.mp3", "auto"), "file cannot be read")


class SelfCheckTests(unittest.TestCase):

    def test_self_check_passes(self):
        # In a separate process: the self-check patches spotDL globally.
        result = subprocess.run(
            [sys.executable, str(ROOT / "src" / "main.py"), "--self-check"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Self-check OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
