"""Running the spotDL worker: start, Stop, logs, progress and the clean-up
of a track left incomplete by Stop."""

import json
import os
import re
import sys
import time
from functools import partial
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer
from PySide6.QtWidgets import QMessageBox

from config_manager import DEFAULT_BITRATE, DEFAULT_FORMAT
from process_control import ProcessTree, is_file_in_use
from resources import resource_path
from worker import LOSSLESS_FORMATS, PROGRESS_PREFIX

# How long to wait for the worker to exit after Stop before killing it again.
STOP_TIMEOUT_MS = 5000
# Output formats spotDL can write; used to find tracks left incomplete by Stop.
AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav"}
# Killed processes can release their files with a short delay.
PARTIAL_DELETE_ATTEMPTS = 10
PARTIAL_DELETE_RETRY_MS = 300
# spotDL logs through rich, which wraps at 80 columns when its output is not a
# terminal. Use a wider console and let the log view wrap to its own width.
LOG_COLUMNS = 300
# rich pads every line with spaces up to the console width.
TRAILING_SPACES = re.compile(r"[ \t]+(?=\r?\n|\Z)")


class DownloadsMixin:
    """Download handling of MainWindow (see main_window.py)."""

    def _start_download(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            return
        self._save_current_profile()
        profile = self._current_profile()
        if not profile or not self._validate_profile(profile):
            return

        destination = Path(profile["destination"]).expanduser()
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Destination error", str(exc))
            return

        vendor = resource_path("vendor")
        missing = [str(vendor / name) for name in ("ffmpeg.exe", "ffprobe.exe", "deno.exe")
                   if not (vendor / name).is_file()]
        if missing:
            QMessageBox.warning(
                self, "Missing dependency",
                "Could not find:\n" + "\n".join(missing)
                + "\n\nRun fetch_vendor.ps1 to download the required tools.",
            )
            return

        args = [
            "--url", profile["url"],
            "--format", profile.get("format", DEFAULT_FORMAT),
            "--bitrate", profile.get("bitrate", DEFAULT_BITRATE),
            "--threads", str(profile.get("threads", 1)),
        ]

        process = QProcess(self)
        process.setWorkingDirectory(str(destination))
        # processEnvironment() is empty until one is set: start from the system
        # environment so the worker keeps SystemRoot, TEMP, APPDATA, etc.
        env = QProcessEnvironment.systemEnvironment()
        path_value = str(vendor) + os.pathsep + env.value("PATH")
        env.insert("PATH", path_value)
        # Deliver worker output as soon as it is written, in a known encoding.
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("COLUMNS", str(LOG_COLUMNS))
        process.setProcessEnvironment(env)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        # Each handler receives the process that emitted the signal, so signals
        # from an earlier worker cannot change the state of a newer download.
        process.started.connect(partial(self._process_started, process))
        process.readyReadStandardOutput.connect(partial(self._read_process_output, process))
        process.finished.connect(partial(self._process_finished, process))
        process.errorOccurred.connect(partial(self._process_error, process))
        self.process = process
        self.stop_requested = False
        self._download_destination = destination
        self._download_started_at = time.time()
        self._partial_files = []

        if getattr(sys, "frozen", False):
            program = sys.executable
            process_args = ["--spotdl-worker"] + args
        else:
            program = sys.executable
            process_args = [str(Path(__file__).resolve().with_name("main.py")), "--spotdl-worker"] + args

        self.logs.appendPlainText(f"\n> Starting profile: {profile['name']}")
        self.logs.appendPlainText(f"> Destination: {destination}")
        quality = profile.get("format", DEFAULT_FORMAT)
        if quality not in LOSSLESS_FORMATS:
            quality += f", {profile.get('bitrate', DEFAULT_BITRATE)}"
        self.logs.appendPlainText(f"> Quality: {quality}")
        self.logs.appendPlainText(f"> Download threads: {profile.get('threads', 1)}\n")
        self.log_state.setText("Starting…")
        self._reset_progress()
        self.status_label.setText("Running")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        process.start(program, process_args)

    def _process_started(self, process):
        if process is not self.process:
            return
        self.process_tree = ProcessTree()
        if not self.process_tree.attach(process.processId()) and sys.platform == "win32":
            self.logs.appendPlainText("[Application] Could not track the worker process; Stop may leave child processes running.")

    def _read_process_output(self, process, flush=False):
        data = self._output_tails.pop(process, b"") + bytes(process.readAllStandardOutput())
        if not flush:
            # Only show complete lines, so trailing padding can be stripped and
            # multi-byte characters are never split across two reads.
            end = data.rfind(b"\n") + 1
            if end < len(data):
                self._output_tails[process] = data[end:]
            data = data[:end]
        text = TRAILING_SPACES.sub("", data.decode("utf-8", errors="replace"))
        shown = []
        for line in text.splitlines(keepends=True):
            if not line.startswith(PROGRESS_PREFIX):
                shown.append(line)
            elif process is self.process:
                self._handle_progress_event(line[len(PROGRESS_PREFIX):])
        text = "".join(shown)
        if text:
            self.logs.moveCursor(self.logs.textCursor().MoveOperation.End)
            self.logs.insertPlainText(text)
            self.logs.ensureCursorVisible()

    def _process_finished(self, process, exit_code, exit_status):
        self._read_process_output(process, flush=True)
        if process is not self.process:
            process.deleteLater()
            return
        self._cancel_stop_timer()
        self._release_process_tree()
        self._end_progress()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        if self.stop_requested:
            self.log_state.setText("Download stopped")
            self.status_label.setText("Stopped")
            self.logs.appendPlainText("[Application] Download stopped by user.")
            self._remove_partial_files_later(self._partial_files)

        elif exit_status == QProcess.ExitStatus.CrashExit:
            self.log_state.setText("Process crashed")
            self.status_label.setText("Error")
            self.logs.appendPlainText("[Application] spotDL worker crashed.")

        elif exit_code == 0:
            self.log_state.setText("Download finished")
            self.status_label.setText("Completed")
            self.logs.appendPlainText("[Application] Download process finished.")

        else:
            self.log_state.setText(f"Finished with exit code {exit_code}")
            self.status_label.setText("Error")
            self.logs.appendPlainText(
                f"[Application] spotDL exited with code {exit_code}."
            )

        self.stop_requested = False
        self.process = None
        process.deleteLater()

    def _reset_progress(self):
        self._progress = {"total": None, "done": 0, "failed": 0}
        self._failed_tracks = []
        # Indeterminate until the worker reports the number of tracks.
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText("")

    def _handle_progress_event(self, payload):
        try:
            event = json.loads(payload)
            kind = event["event"]
        except (ValueError, KeyError, TypeError):
            return
        progress = self._progress
        if kind == "phase":
            phase = event.get("phase")
            if phase == "fetching":
                self.log_state.setText("Fetching playlist…")
            elif phase == "checking":
                self.log_state.setText("Checking existing tracks…")
                self.progress_label.setText(f"{event.get('total', '?')} tracks")
            elif phase == "downloading":
                self.log_state.setText("Downloading…")
        elif kind == "total":
            progress["total"] = int(event.get("total", 0))
            progress["done"] = int(event.get("done", 0))
            self._update_progress()
        elif kind == "track" and progress["total"] is not None:
            progress["done"] += 1
            if not event.get("ok", False):
                progress["failed"] += 1
                self._failed_tracks.append(str(event.get("name", "unknown track")))
            self._update_progress()

    def _update_progress(self):
        total, done, failed = (self._progress[key] for key in ("total", "done", "failed"))
        done = min(done, total)
        # An empty playlist counts as complete.
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done if total else 1)
        percent = done * 100 // total if total else 100
        text = f"{done} / {total} tracks · {percent}%"
        if failed:
            text += f" · {failed} failed"
        self.progress_label.setText(text)

    def _end_progress(self):
        # Keep the last known progress; only stop an indeterminate animation.
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
        if self._failed_tracks:
            self.logs.appendPlainText(
                f"[Application] {len(self._failed_tracks)} track(s) failed:\n  - "
                + "\n  - ".join(self._failed_tracks)
            )

    def _process_error(self, process, error):
        if process is not self.process:
            return
        if error == QProcess.ProcessError.FailedToStart:
            # finished() is not emitted when the process never started.
            self.logs.appendPlainText(f"[Application] Could not start spotDL worker: {process.errorString()}")
            self._cancel_stop_timer()
            self._release_process_tree()
            self._end_progress()
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText("Error")
            self.log_state.setText("Failed to start")
            self.stop_requested = False
            self.process = None
            process.deleteLater()
        elif not (self.stop_requested and error == QProcess.ProcessError.Crashed):
            # A crash is expected when the user stopped the worker.
            self.logs.appendPlainText(f"[Application] Worker error: {process.errorString()}")

    def _stop_download(self):
        process = self.process
        if not process or process.state() == QProcess.ProcessState.NotRunning or self.stop_requested:
            return

        self.stop_requested = True
        self.stop_button.setEnabled(False)
        self.logs.appendPlainText("[Application] Stop requested.")
        self.status_label.setText("Stopping...")
        self.log_state.setText("Stopping...")
        self._capture_partial_files()

        if sys.platform == "win32":
            # terminate() only posts WM_CLOSE, which a windowless worker never
            # receives, so there is no graceful path: end the whole tree now.
            self._kill_worker()
        else:
            process.terminate()

        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(partial(self._stop_timed_out, process))
        self._stop_timer.start(STOP_TIMEOUT_MS)

    def _stop_timed_out(self, process):
        if process is not self.process or process.state() == QProcess.ProcessState.NotRunning:
            return
        self.logs.appendPlainText("[Application] Worker did not exit in time; forcing termination.")
        self._kill_worker()

    def _kill_worker(self):
        if self.process_tree:
            self.process_tree.kill()
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def _cancel_stop_timer(self):
        if self._stop_timer is not None:
            self._stop_timer.stop()
            self._stop_timer.deleteLater()
            self._stop_timer = None

    def _release_process_tree(self):
        if self.process_tree:
            # Closing the job also ends any leftover child of the worker.
            self.process_tree.close()
            self.process_tree = None

    def _capture_partial_files(self):
        """Remember the audio files the worker is writing, before it is killed.

        A track counts as incomplete if it was created or modified since the
        download started and is still held open by the worker at Stop time.
        """
        self._partial_files = []
        if self._download_destination is None:
            return
        # Allow for coarse file-system timestamps.
        since = self._download_started_at - 2
        for path in self._download_destination.rglob("*"):
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            # st_ctime is the creation time on Windows.
            if max(stat.st_mtime, stat.st_ctime) >= since and is_file_in_use(path):
                self._partial_files.append(path)

    def _remove_partial_files(self, files):
        """Delete the given incomplete files. Returns those that are still locked."""
        remaining = []
        for path in files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                remaining.append(path)
            else:
                self.logs.appendPlainText(f"[Application] Removed incomplete file: {path.name}")
        files[:] = remaining
        return remaining

    def _remove_partial_files_later(self, files, attempts_left=PARTIAL_DELETE_ATTEMPTS):
        # Skip if a newer stop replaced the list in the meantime.
        if files is not self._partial_files or not self._remove_partial_files(files):
            return
        if attempts_left > 1:
            QTimer.singleShot(PARTIAL_DELETE_RETRY_MS,
                              partial(self._remove_partial_files_later, files, attempts_left - 1))
        else:
            for path in files:
                self.logs.appendPlainText(f"[Application] Could not remove incomplete file: {path}")
