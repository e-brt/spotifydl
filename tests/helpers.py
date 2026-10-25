"""Shared setup for the GUI tests.

The real MainWindow runs with a fake worker (fake_worker.py), an in-memory
configuration and a temporary destination folder: the user's config.json and
Spotify cache are never read or written, and nothing is downloaded.
"""

import ctypes
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import downloads  # noqa: E402
import main_window  # noqa: E402
import profiles  # noqa: E402
from PySide6.QtCore import QProcess  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

FAKE_WORKER = Path(__file__).with_name("fake_worker.py")


def qt_app():
    return QApplication.instance() or QApplication([])


def process_alive(pid):
    """True if the Windows process is still running."""
    kernel32 = ctypes.WinDLL("kernel32")
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


class AppTestCase(unittest.TestCase):
    """Base class: builds windows that run fake_worker.py instead of spotDL."""

    def setUp(self):
        self.qt = qt_app()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.out = Path(self._tmp.name)
        self.config = {
            "version": 1,
            "settings": {},
            "profiles": [{
                "id": "test", "name": "Test", "url": "https://open.spotify.com/playlist/x",
                "destination": str(self.out), "threads": 1,
            }],
        }
        self.saved_configs = []
        self.mode = "chatty"
        self.windows = []

        test = self

        self.started_args = []
        self.retried_urls = None

        class FakeWorkerProcess(QProcess):
            def start(self, program, args):
                # Keep what the real worker would have received.
                test.started_args = list(args)
                if "--only-tracks" in args:
                    retry_file = args[args.index("--only-tracks") + 1]
                    test.retried_urls = json.loads(Path(retry_file).read_text(encoding="utf-8"))
                super().start(sys.executable, [str(FAKE_WORKER), test.mode])

        for target, attribute, value in [
            (main_window, "load_config", lambda: self.config),
            (profiles, "save_config", lambda config: self.saved_configs.append(config)),
            (downloads, "QProcess", FakeWorkerProcess),
            (QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)),
        ]:
            patcher = mock.patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        for window in self.windows:
            if window.process is not None:
                window._kill_worker()
                window.process.waitForFinished(5000)
            window._release_process_tree()
        self.wait(lambda: False, 0.3)
        # Destroy the windows now, with their pending events handled, rather
        # than whenever Python collects them: Qt could otherwise deliver an
        # event to a window already destroyed, and crash the next test.
        for window in self.windows:
            window.hide()
            window.deleteLater()
        self.windows.clear()
        self.wait(lambda: False, 0.2)
        self._tmp.cleanup()

    def make_window(self):
        window = main_window.MainWindow()
        self.windows.append(window)
        return window

    def start(self, window, mode):
        self.mode = mode
        window.logs.clear()
        window._start_download()
        return window.process

    def wait(self, condition, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            self.qt.processEvents()
            if condition():
                return True
            time.sleep(0.02)
        return False

    def wait_finished(self, window, timeout=10.0):
        self.assertTrue(self.wait(lambda: window.process is None, timeout), "worker did not finish")

    @staticmethod
    def child_pids(window):
        """CHILD and GRANDCHILD pids printed by the newest fake worker."""
        found = re.findall(r"CHILD (\d+)", window.logs.toPlainText())
        return [int(pid) for pid in found[-2:]]
