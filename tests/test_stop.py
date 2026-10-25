"""Stop, Close and exit status (SPECIFICATION.md, section 6)."""

import os
import sys
import time
import unittest

from helpers import AppTestCase, process_alive


@unittest.skipUnless(sys.platform == "win32", "process tree handling is Windows specific")
class StopTests(AppTestCase):

    def assert_stops_cleanly(self, window, mode, delay):
        process = self.start(window, mode)
        self.assertFalse(window.start_button.isEnabled())
        self.assertTrue(window.stop_button.isEnabled())
        self.assertTrue(self.wait(lambda: len(self.child_pids(window)) == 2), "grandchild not started")
        pids = [process.processId()] + self.child_pids(window)
        self.wait(lambda: False, delay)

        window._stop_download()
        self.assertEqual(window.status_label.text(), "Stopping...")
        self.assertFalse(window.stop_button.isEnabled())
        self.wait_finished(window, 8)

        self.assertEqual(window.status_label.text(), "Stopped")
        self.assertTrue(window.start_button.isEnabled())
        self.assertFalse(window.stop_button.isEnabled())
        self.wait(lambda: False, 0.5)
        self.assertEqual([pid for pid in pids if process_alive(pid)], [], "processes left running")
        logs = window.logs.toPlainText()
        self.wait(lambda: False, 0.6)
        self.assertEqual(window.logs.toPlainText(), logs, "logs kept growing after Stop")
        self.assertNotIn("Worker error", logs)
        self.assertNotIn("crashed", logs)

    def test_stop_while_logging(self):
        self.assert_stops_cleanly(self.make_window(), "chatty", 0.5)

    def test_stop_while_silent(self):
        self.assert_stops_cleanly(self.make_window(), "silent", 0.5)

    def test_restart_right_after_stop(self):
        window = self.make_window()
        self.assert_stops_cleanly(window, "chatty", 0.3)
        self.assert_stops_cleanly(window, "chatty", 0.0)

    def test_exit_codes(self):
        window = self.make_window()
        self.start(window, "quick-ok")
        self.wait_finished(window)
        self.assertEqual(window.status_label.text(), "Completed")
        self.start(window, "quick-fail")
        self.wait_finished(window)
        self.assertEqual(window.status_label.text(), "Error")

    def test_stop_on_worker_exiting_quickly(self):
        window = self.make_window()
        self.start(window, "quick-ok")
        window._stop_download()
        self.wait_finished(window)
        self.assertIn(window.status_label.text(), ("Stopped", "Completed"))

    def test_utf8_output(self):
        window = self.make_window()
        self.start(window, "chatty")
        self.assertTrue(self.wait(lambda: "Downloaded track 1" in window.logs.toPlainText()))
        self.assertIn("é ü ✓", window.logs.toPlainText())

    def test_close_window_kills_everything(self):
        window = self.make_window()
        process = self.start(window, "chatty")
        self.assertTrue(self.wait(lambda: len(self.child_pids(window)) == 2))
        pids = [process.processId()] + self.child_pids(window)
        window.close()
        self.wait(lambda: False, 0.5)
        self.assertEqual([pid for pid in pids if process_alive(pid)], [])


@unittest.skipUnless(sys.platform == "win32", "open-file detection is Windows specific")
class PartialFileTests(AppTestCase):

    def setUp(self):
        super().setUp()
        old = self.out / "Old Song.mp3"
        old.write_bytes(b"old")
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        # The download must start clearly after "Old Song" was created.
        time.sleep(2.5)

    def test_stop_removes_only_the_file_being_written(self):
        window = self.make_window()
        self.start(window, "writer")
        self.assertTrue(self.wait(lambda: "WRITING" in window.logs.toPlainText()))
        self.wait(lambda: False, 0.5)
        window._stop_download()
        self.wait_finished(window, 8)
        self.assertTrue(self.wait(lambda: not (self.out / "Partial Song.mp3").exists(), 5))
        self.assertTrue((self.out / "Done Song.mp3").exists())
        self.assertTrue((self.out / "Old Song.mp3").exists())
        self.assertIn("Removed incomplete file: Partial Song.mp3", window.logs.toPlainText())

    def test_close_while_writing_removes_the_partial_file(self):
        window = self.make_window()
        self.start(window, "writer")
        self.assertTrue(self.wait(lambda: "WRITING" in window.logs.toPlainText()))
        window.close()
        self.assertFalse((self.out / "Partial Song.mp3").exists())
        self.assertTrue((self.out / "Done Song.mp3").exists())
        self.assertTrue((self.out / "Old Song.mp3").exists())


if __name__ == "__main__":
    unittest.main()
