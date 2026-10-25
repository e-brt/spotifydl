"""Keeping the destination folder in sync with the playlist: .m3u8 playlist
file and tracks removed from the playlist."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import AppTestCase

import downloads
import worker


class Song:
    def __init__(self, track_id, name, duration=200):
        self.url = f"https://open.spotify.com/track/{track_id}"
        self.display_name = name
        self.duration = duration


class PlaylistFileTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_file_name(self):
        self.assertEqual(worker.playlist_file_name("Rock"), "Rock.m3u8")
        self.assertEqual(worker.playlist_file_name('AC/DC: "Best"?'), "AC_DC_ _Best__.m3u8")
        self.assertEqual(worker.playlist_file_name(None), "playlist.m3u8")
        self.assertEqual(worker.playlist_file_name(" .. "), "playlist.m3u8")

    def test_tracks_in_playlist_order_and_only_existing_files(self):
        songs = [Song("B", "Artist - Second", 125.7), Song("A", "Artist - First"), Song("C", "Artist - Missing")]
        (self.dir / "second.mp3").write_bytes(b"x")
        (self.dir / "sub").mkdir()
        (self.dir / "sub" / "first.mp3").write_bytes(b"x")
        files = {songs[0].url: Path("second.mp3"), songs[1].url: Path("sub/first.mp3"),
                 songs[2].url: Path("missing.mp3")}
        count = worker.write_playlist_file(self.dir / "Rock.m3u8", songs, files)
        self.assertEqual(count, 2)
        lines = (self.dir / "Rock.m3u8").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, [
            "#EXTM3U",
            "#EXTINF:125,Artist - Second", "second.mp3",
            "#EXTINF:200,Artist - First", str(Path("sub/first.mp3")),
        ])

    def test_removed_tracks_are_files_whose_track_left_the_playlist(self):
        (self.dir / "kept.mp3").write_bytes(b"x")
        (self.dir / "gone.mp3").write_bytes(b"x")
        known = {
            "https://open.spotify.com/track/A": [self.dir / "kept.mp3"],
            "https://open.spotify.com/track/Z": [self.dir / "gone.mp3", self.dir / "already-deleted.mp3"],
        }
        removed = worker.find_removed_tracks(known, [Song("A", "Kept")])
        self.assertEqual(removed, [self.dir / "gone.mp3"])


class CleanupDialogTests(AppTestCase):
    """The GUI side: confirmation, then the Recycle Bin."""

    def setUp(self):
        super().setUp()
        self.recycled = []
        patcher = mock.patch.object(downloads, "move_to_recycle_bin",
                                    lambda files: self.recycled.extend(files) or [])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = self.make_window()
        self.questions = []

    def answer(self, accept):
        def confirm(title, text, question, names):
            self.questions.append(names)
            return accept
        self.window._confirm_cleanup = confirm

    def run_to_end(self, mode):
        self.start(self.window, mode)
        self.wait_finished(self.window)

    def test_confirmed_files_go_to_the_recycle_bin(self):
        self.answer(True)
        self.run_to_end("cleanup")
        self.assertEqual(self.questions, [["Old Track.mp3"]])
        self.assertEqual(self.recycled, [self.out / "Old Track.mp3"])
        self.assertIn("Moved 1 file(s) to the Recycle Bin", self.window.logs.toPlainText())

    def test_nothing_is_moved_without_confirmation(self):
        self.answer(False)
        self.run_to_end("cleanup")
        self.assertEqual(self.recycled, [])
        self.assertTrue((self.out / "Old Track.mp3").exists())
        self.assertIn("Kept 1 file(s) no longer in the playlist", self.window.logs.toPlainText())

    def test_no_question_when_there_is_nothing_to_clean(self):
        self.answer(True)
        self.run_to_end("cleanup-none")
        self.assertEqual(self.questions, [])

    def test_no_question_after_a_failed_run(self):
        self.answer(True)
        self.run_to_end("early-exit")
        self.assertEqual(self.questions, [])


if __name__ == "__main__":
    unittest.main()
