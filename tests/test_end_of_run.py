"""End of a run: notification and retry of the failed tracks."""

import unittest
from pathlib import Path

from helpers import AppTestCase

import downloads
import worker


class CompletionMessageTests(unittest.TestCase):

    def test_summary(self):
        progress = {"total": 194, "done": 194, "failed": 2, "up_to_date": 10}
        self.assertEqual(downloads.completion_message(progress),
                         "194 tracks: 182 downloaded, 10 already up to date, 2 failed.")

    def test_no_failure(self):
        progress = {"total": 3, "done": 3, "failed": 0, "up_to_date": 3}
        self.assertEqual(downloads.completion_message(progress),
                         "3 tracks: 0 downloaded, 3 already up to date.")

    def test_unknown_total(self):
        self.assertEqual(downloads.completion_message({"total": None}), "The download finished.")


class SelectTracksTests(unittest.TestCase):

    def test_keeps_playlist_order_and_matches_by_track_id(self):
        class Song:
            def __init__(self, track_id):
                self.url = f"https://open.spotify.com/track/{track_id}"
        songs = [Song("A"), Song("B"), Song("C")]
        selected = worker.select_tracks(songs, ["https://open.spotify.com/track/C?si=x",
                                                "https://open.spotify.com/track/A"])
        self.assertEqual([song.url for song in selected], [songs[0].url, songs[2].url])


class EndOfRunTests(AppTestCase):

    def setUp(self):
        super().setUp()
        self.window = self.make_window()
        self.notifications = []
        self.window._notify = lambda title, message: self.notifications.append((title, message))

    def run_to_end(self, mode, start=None):
        (start or (lambda: self.start(self.window, mode)))()
        self.wait_finished(self.window)

    def test_retry_button_appears_after_failures(self):
        self.run_to_end("full")
        self.assertFalse(self.window.retry_button.isHidden())
        self.assertTrue(self.window.retry_button.isEnabled())
        self.assertEqual(self.window.retry_button.text(), "Retry failed (1)")

    def test_retry_downloads_only_the_failed_tracks(self):
        self.run_to_end("full")
        self.mode = "full"
        self.window.retry_button.click()
        self.assertFalse(self.window.retry_button.isEnabled(), "disabled while the retry runs")
        self.assertIn("--only-tracks", self.started_args)
        self.assertEqual(self.retried_urls, ["https://open.spotify.com/track/T1"])
        retry_file = Path(self.started_args[self.started_args.index("--only-tracks") + 1])
        self.assertIn("Retrying 1 failed track(s)", self.window.logs.toPlainText())
        self.wait_finished(self.window)
        self.assertFalse(retry_file.exists(), "the list of tracks is removed after the run")

    def test_normal_start_downloads_the_whole_playlist(self):
        self.run_to_end("full")
        self.start(self.window, "full")
        self.assertNotIn("--only-tracks", self.started_args)
        self.wait_finished(self.window)

    def test_no_retry_button_without_failures(self):
        self.run_to_end("empty")
        self.assertTrue(self.window.retry_button.isHidden())

    def test_notification_with_the_summary(self):
        self.run_to_end("full")
        self.assertEqual(self.notifications,
                         [("Download finished", "10 tracks: 3 downloaded, 6 already up to date, 1 failed.")])

    def test_notification_when_the_worker_fails(self):
        self.run_to_end("early-exit")
        self.assertEqual(self.notifications[0][0], "Download failed")

    def test_no_notification_after_stop(self):
        self.start(self.window, "progress-stop")
        self.assertTrue(self.wait(lambda: self.window.progress_label.text().startswith("8 / 10")))
        self.window._stop_download()
        self.wait_finished(self.window)
        self.assertEqual(self.notifications, [])


if __name__ == "__main__":
    unittest.main()
