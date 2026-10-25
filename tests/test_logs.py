"""Saving each run's log to a file in data\\logs\\."""

import os
import sys
import time
import unittest
from datetime import datetime

from helpers import AppTestCase

import downloads


def text_lines(text):
    return [line for line in text.splitlines() if line.strip()]


class LogFileNameTests(unittest.TestCase):

    def test_name_sorts_by_date_and_has_no_forbidden_characters(self):
        moment = datetime(2026, 10, 25, 14, 30, 5)
        self.assertEqual(downloads.log_file_name("Rock", moment), "2026-10-25 14-30-05 Rock.log")
        self.assertEqual(downloads.log_file_name('AC/DC: "Live"?', moment), "2026-10-25 14-30-05 AC_DC_ _Live__.log")
        self.assertEqual(downloads.log_file_name("", moment), "2026-10-25 14-30-05 profile.log")


class SavedLogTests(AppTestCase):

    def setUp(self):
        super().setUp()
        self.window = self.make_window()

    def log_files(self):
        return sorted(self.logs_folder.glob("*.log"))

    def run_to_end(self, mode):
        self.start(self.window, mode)
        self.wait_finished(self.window)

    def test_the_file_has_what_the_window_shows(self):
        self.run_to_end("full")
        files = self.log_files()
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.endswith(" Test.log"))
        saved = files[0].read_text(encoding="utf-8")
        self.assertTrue(saved.startswith("Spotify Playlist Downloader "), saved[:60])
        self.assertNotIn("@@progress", saved)
        self.assertEqual(text_lines(saved), text_lines(self.window.logs.toPlainText()),
                         "the file has the same lines as the log view, header included")
        for expected in ("> Starting profile: Test", 'Downloaded "Track 3"',
                         "[Application] Download process finished.", "1 track(s) failed"):
            self.assertIn(expected, saved)

    def test_clearing_the_view_keeps_the_file(self):
        self.run_to_end("full")
        self.window.logs.clear()
        self.assertIn('Downloaded "Track 3"', self.log_files()[0].read_text(encoding="utf-8"))

    def test_each_run_has_its_own_file(self):
        self.run_to_end("full")
        time.sleep(1.1)  # file names have a one-second resolution
        self.run_to_end("empty")
        files = self.log_files()
        self.assertEqual(len(files), 2)
        self.assertIn('Downloaded "Track 3"', files[0].read_text(encoding="utf-8"))
        self.assertNotIn('Downloaded "Track 3"', files[1].read_text(encoding="utf-8"))

    @unittest.skipUnless(sys.platform == "win32", "the partial file check is Windows specific")
    def test_messages_after_the_end_are_saved_too(self):
        self.start(self.window, "writer")
        self.assertTrue(self.wait(lambda: "WRITING" in self.window.logs.toPlainText()))
        self.wait(lambda: False, 0.5)
        self.window._stop_download()
        self.wait_finished(self.window, 8)
        self.assertTrue(self.wait(lambda: "Removed incomplete file" in self.window.logs.toPlainText(), 5))
        saved = self.log_files()[0].read_text(encoding="utf-8")
        self.assertIn("Download stopped by user.", saved)
        self.assertIn("Removed incomplete file: Partial Song.mp3", saved)

    def test_only_the_latest_files_are_kept(self):
        for day in range(1, 106):  # 105 older logs
            old = self.logs_folder / f"2020-01-01 00-00-{day:03d} Old.log"
            old.write_text("old", encoding="utf-8")
        self.run_to_end("empty")
        files = self.log_files()
        self.assertEqual(len(files), downloads.MAX_LOG_FILES)
        self.assertTrue(files[-1].name.endswith(" Test.log"), "the new log is kept")
        self.assertFalse((self.logs_folder / "2020-01-01 00-00-001 Old.log").exists(), "the oldest are removed")

    def test_a_folder_that_cannot_be_used_does_not_stop_the_run(self):
        def unavailable():
            raise OSError("access denied")
        downloads.logs_dir, original = unavailable, downloads.logs_dir
        try:
            self.run_to_end("empty")
        finally:
            downloads.logs_dir = original
        self.assertIn("The log of this run cannot be saved", self.window.logs.toPlainText())
        self.assertEqual(self.window.status_label.text(), "Completed")


if __name__ == "__main__":
    unittest.main()
