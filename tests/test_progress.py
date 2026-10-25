"""Progress bar and track counter (SPECIFICATION.md, section 7)."""

import unittest

from helpers import AppTestCase


class ProgressTests(AppTestCase):

    def setUp(self):
        super().setUp()
        self.window = self.make_window()
        self.bar = self.window.progress_bar
        self.label = self.window.progress_label

    def run_to_end(self, mode):
        self.start(self.window, mode)
        self.wait_finished(self.window)

    def test_full_run(self):
        self.start(self.window, "full")
        self.assertEqual(self.bar.maximum(), 0, "should be indeterminate at start")
        self.assertTrue(self.wait(lambda: self.label.text() == "10 tracks"), "checking phase")
        self.assertTrue(self.wait(lambda: self.label.text().startswith("6 / 10")), "total event")
        self.wait_finished(self.window)
        self.assertEqual(self.label.text(), "10 / 10 tracks · 100% · 1 failed")
        self.assertEqual((self.bar.value(), self.bar.maximum()), (10, 10))
        self.assertEqual(self.window.status_label.text(), "Completed")

    def test_events_are_hidden_from_the_logs(self):
        self.run_to_end("full")
        logs = self.window.logs.toPlainText()
        self.assertNotIn("@@progress", logs)
        self.assertIn("log line before", logs)
        self.assertIn('Downloaded "Track 3"', logs)

    def test_failed_tracks_are_listed(self):
        self.run_to_end("full")
        self.assertIn("[Application] 1 track(s) failed:\n  - Track 1", self.window.logs.toPlainText())

    def test_stop_keeps_the_last_progress(self):
        self.start(self.window, "progress-stop")
        self.assertTrue(self.wait(lambda: self.label.text().startswith("8 / 10")))
        self.window._stop_download()
        self.wait_finished(self.window)
        self.assertTrue(self.label.text().startswith("8 / 10"))
        self.assertEqual(self.bar.value(), 8)
        self.assertEqual(self.window.status_label.text(), "Stopped")

    def test_new_run_resets_the_progress(self):
        self.run_to_end("full")
        self.start(self.window, "progress-stop")
        self.assertEqual(self.bar.maximum(), 0)
        self.assertEqual(self.label.text(), "")

    def test_exit_before_the_total(self):
        self.run_to_end("early-exit")
        self.assertEqual((self.bar.value(), self.bar.maximum()), (0, 1), "animation should stop")
        self.assertEqual(self.window.status_label.text(), "Error")

    def test_empty_playlist(self):
        self.run_to_end("empty")
        self.assertEqual(self.label.text(), "0 / 0 tracks · 100%")
        self.assertEqual(self.bar.value(), self.bar.maximum())
        self.assertNotIn("failed:", self.window.logs.toPlainText())

    def test_event_split_across_reads(self):
        self.run_to_end("split")
        self.assertTrue(self.label.text().startswith("10 / 10"), self.label.text())


if __name__ == "__main__":
    unittest.main()
