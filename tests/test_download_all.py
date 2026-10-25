"""Download all: every profile in turn, without interrupting the queue."""

import unittest
from pathlib import Path
from unittest import mock

from helpers import AppTestCase

import downloads
from PySide6.QtWidgets import QMessageBox


class QueueSummaryTests(unittest.TestCase):

    def test_counts_by_status(self):
        results = [("A", "completed"), ("B", "skipped"), ("C", "completed")]
        self.assertEqual(downloads.queue_summary(results, 3), "3 profile(s): 2 completed, 1 skipped.")

    def test_profiles_not_reached_after_stop(self):
        self.assertEqual(downloads.queue_summary([("A", "stopped")], 3),
                         "3 profile(s): 1 stopped, 2 not started.")


class DownloadAllTests(AppTestCase):

    def setUp(self):
        super().setUp()
        self.config["profiles"] = [self.profile(name) for name in ("One", "Two", "Three")]
        self.window = self.make_window()
        self.notifications = []
        self.window._notify = lambda title, message: self.notifications.append((title, message))
        self.questions = []
        # Any dialog during the queue would block it: fail instead.
        patcher = mock.patch.object(QMessageBox, "warning",
                                    side_effect=AssertionError("no dialog during Download all"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def profile(self, name, url="https://open.spotify.com/playlist/x"):
        folder = self.out / name
        return {"id": name.lower(), "name": name, "url": url, "destination": str(folder), "threads": 1}

    def download_all(self, modes, timeout=20):
        self.mode = list(modes)
        self.window.download_all_button.click()
        self.assertTrue(self.wait(lambda: self.window._queue is None, timeout), "queue did not finish")

    def started_profiles(self):
        return [line.split(": ", 1)[1] for line in self.window.logs.toPlainText().splitlines()
                if line.startswith("> Starting profile: ")]

    def test_every_profile_in_turn(self):
        self.download_all(["full", "empty", "full"])
        self.assertEqual(self.started_profiles(), ["One", "Two", "Three"])
        logs = self.window.logs.toPlainText()
        self.assertIn("[Download all] 3 profile(s): 3 completed.", logs)
        self.assertIn("> Download all: profile 2 of 3", logs)
        self.assertEqual(self.notifications, [("Download all finished", "3 profile(s): 3 completed.")],
                         "one notification for the whole queue")
        self.assertTrue(self.window.start_button.isEnabled())
        self.assertTrue(self.window.download_all_button.isEnabled())

    def test_buttons_while_the_queue_runs(self):
        self.mode = ["progress-stop"]
        self.window.download_all_button.click()
        self.assertFalse(self.window.download_all_button.isEnabled())
        self.assertFalse(self.window.start_button.isEnabled())
        self.assertTrue(self.window.stop_button.isEnabled())
        self.window._stop_download()
        self.assertTrue(self.wait(lambda: self.window._queue is None, 10))

    def test_invalid_profile_is_skipped_without_dialog(self):
        self.config["profiles"][1]["url"] = "not a playlist"
        self.download_all(["empty", "empty"])
        self.assertEqual(self.started_profiles(), ["One", "Three"])
        logs = self.window.logs.toPlainText()
        self.assertIn("[Download all] Skipped Two: Invalid playlist URL.", logs)
        self.assertIn("3 profile(s): 2 completed, 1 skipped.", logs)

    def test_a_failed_profile_does_not_stop_the_queue(self):
        self.download_all(["early-exit", "empty", "empty"])
        self.assertEqual(self.started_profiles(), ["One", "Two", "Three"])
        self.assertIn("3 profile(s): 1 failed, 2 completed.", self.window.logs.toPlainText())

    def test_stop_cancels_the_rest(self):
        self.mode = ["progress-stop", "empty", "empty"]
        self.window.download_all_button.click()
        self.assertTrue(self.wait(lambda: self.window.progress_label.text().startswith("8 / 10")))
        self.window._stop_download()
        self.assertTrue(self.wait(lambda: self.window._queue is None, 10))
        self.wait(lambda: False, 0.5)
        self.assertEqual(self.started_profiles(), ["One"])
        self.assertIn("3 profile(s): 1 stopped, 2 not started.", self.window.logs.toPlainText())
        self.assertEqual(self.notifications, [], "no notification after Stop")
        self.assertTrue(self.window.download_all_button.isEnabled())

    def test_clean_up_questions_wait_for_the_end(self):
        asked_when = []

        def confirm(title, text, question, names):
            asked_when.append((title, self.window._queue is None))
            return False
        self.window._confirm_cleanup = confirm
        self.download_all(["cleanup", "empty", "cleanup"])
        self.assertEqual(asked_when, [("Tracks removed from the playlist (One)", True),
                                      ("Tracks removed from the playlist (Three)", True)])

    def test_each_profile_has_its_own_log(self):
        self.download_all(["empty", "empty", "empty"])
        names = sorted(path.name.split(" ", 2)[2] for path in self.logs_folder.glob("*.log"))
        self.assertEqual(names, ["One.log", "Three.log", "Two.log"])


if __name__ == "__main__":
    unittest.main()
