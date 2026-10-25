import os
import re
import sys
import time
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QTimer
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QLineEdit,
    QSpinBox, QComboBox, QPlainTextEdit, QFileDialog, QMessageBox, QFormLayout,
    QSplitter, QGroupBox, QStatusBar, QInputDialog
)

from config_manager import DEFAULT_BITRATE, DEFAULT_FORMAT, load_config, save_config, config_path
from process_control import ProcessTree, is_file_in_use
from worker import BITRATES, FORMATS, LOSSLESS_FORMATS


APP_NAME = "Spotify Playlist Downloader"
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


def resource_path(*parts):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def run_spotdl_worker():
    """Run spotDL in a child process so the GUI can capture logs and stop it."""
    import worker

    worker.run(sys.argv[2:])


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 760)
        self.setMinimumSize(850, 600)

        self.config = load_config()
        self.process = None
        self.process_tree = None
        self.current_profile_id = None
        self._loading_profile = False
        self.stop_requested = False
        self._stop_timer = None
        self._download_destination = None
        self._download_started_at = None
        self._partial_files = []
        # Incomplete last line of output, per worker process.
        self._output_tails = {}

        self._build_ui()
        self._apply_theme()
        self._refresh_profiles()
        self.statusBar().showMessage(f"Configuration: {config_path()}")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        subtitle = QLabel("Manage playlist profiles and monitor spotDL downloads")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("statusPill")
        header.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 3)

        # Left pane: saved profiles
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.addWidget(QLabel("PLAYLIST PROFILES"))
        self.profile_list = QListWidget()
        self.profile_list.currentItemChanged.connect(self._profile_selected)
        left_layout.addWidget(self.profile_list, 1)

        profile_buttons = QHBoxLayout()
        self.add_button = QPushButton("+ New")
        self.duplicate_button = QPushButton("Duplicate")
        self.delete_button = QPushButton("Delete")
        self.add_button.clicked.connect(self._new_profile)
        self.duplicate_button.clicked.connect(self._duplicate_profile)
        self.delete_button.clicked.connect(self._delete_profile)
        profile_buttons.addWidget(self.add_button)
        profile_buttons.addWidget(self.duplicate_button)
        profile_buttons.addWidget(self.delete_button)
        left_layout.addLayout(profile_buttons)
        splitter.addWidget(left)

        # Right pane: profile settings
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        settings_group = QGroupBox("Profile settings")
        form = QFormLayout(settings_group)
        form.setSpacing(12)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Workout playlist")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://open.spotify.com/playlist/...")
        self.destination_edit = QLineEdit()
        self.destination_edit.setPlaceholderText("Choose where downloaded tracks are saved")
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self._browse_destination)
        dest_row = QHBoxLayout()
        dest_row.addWidget(self.destination_edit, 1)
        dest_row.addWidget(self.browse_button)
        dest_widget = QWidget()
        dest_widget.setLayout(dest_row)

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 16)
        self.threads_spin.setValue(1)
        self.threads_spin.setToolTip(
            "Number of tracks downloaded at the same time. Lower values can help reduce "
            "rate limiting from audio providers. Checking existing files always uses more threads."
        )

        self.format_combo = QComboBox()
        self.format_combo.addItems(FORMATS)
        self.format_combo.setToolTip("Audio format of the downloaded files.")
        self.format_combo.currentTextChanged.connect(self._format_changed)
        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(BITRATES)
        self.bitrate_combo.setToolTip(
            "auto keeps the bitrate of the YouTube source (usually 128k to 160k).\n"
            "Higher values make larger files but cannot add quality the source does not have.\n"
            "Existing files below the selected bitrate are downloaded again."
        )

        form.addRow("Profile name", self.name_edit)
        form.addRow("Spotify playlist URL", self.url_edit)
        form.addRow("Destination folder", dest_widget)
        form.addRow("Audio format", self.format_combo)
        form.addRow("Bitrate", self.bitrate_combo)
        form.addRow("Download threads", self.threads_spin)
        right_layout.addWidget(settings_group)

        info = QLabel("Profiles are saved locally. Keep the same destination folder to help spotDL skip existing tracks.")
        info.setObjectName("hint")
        info.setWordWrap(True)
        right_layout.addWidget(info)

        action_row = QHBoxLayout()
        self.save_button = QPushButton("Save profile")
        self.start_button = QPushButton("▶  Start download")
        self.stop_button = QPushButton("■  Stop")
        self.stop_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_current_profile)
        self.start_button.clicked.connect(self._start_download)
        self.stop_button.clicked.connect(self._stop_download)
        self.start_button.setObjectName("primaryButton")
        self.stop_button.setObjectName("stopButton")
        action_row.addWidget(self.save_button)
        action_row.addStretch()
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        right_layout.addLayout(action_row)
        right_layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([300, 760])

        logs_group = QGroupBox("Live spotDL output")
        logs_layout = QVBoxLayout(logs_group)
        log_toolbar = QHBoxLayout()
        self.log_state = QLabel("Waiting for a download")
        self.clear_logs_button = QPushButton("Clear logs")
        self.clear_logs_button.clicked.connect(self._clear_logs)
        log_toolbar.addWidget(self.log_state)
        log_toolbar.addStretch()
        log_toolbar.addWidget(self.clear_logs_button)
        logs_layout.addLayout(log_toolbar)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.logs.setFont(QFont("Consolas", 9))
        self.logs.document().setMaximumBlockCount(5000)
        logs_layout.addWidget(self.logs)
        outer.addWidget(logs_group, 2)

        file_menu = self.menuBar().addMenu("File")
        open_config_action = QAction("Show configuration location", self)
        open_config_action.triggered.connect(self._show_config_location)
        file_menu.addAction(open_config_action)

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #15171c; color: #e7eaf0; font-size: 10pt; }
            QMenuBar, QMenu { background: #1c2028; color: #e7eaf0; }
            QMenuBar::item:selected, QMenu::item:selected { background: #303746; }
            QLabel#appTitle { font-size: 22pt; font-weight: 700; color: #ffffff; }
            QLabel#subtitle, QLabel#hint { color: #9ba5b5; }
            QLabel#statusPill { background: #263a32; color: #7fe0a5; padding: 7px 12px; border-radius: 10px; font-weight: 600; }
            QGroupBox { border: 1px solid #343a46; border-radius: 10px; margin-top: 12px; padding: 12px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #bfc8d8; }
            QLineEdit, QSpinBox, QComboBox, QListWidget, QPlainTextEdit { background: #0f1116; border: 1px solid #343a46; border-radius: 6px; padding: 8px; selection-background-color: #4361ee; }
            QListWidget::item { padding: 10px; border-radius: 5px; }
            QListWidget::item:selected { background: #29344c; color: #ffffff; }
            QPushButton { background: #2b303b; border: 1px solid #414958; border-radius: 6px; padding: 9px 12px; }
            QPushButton:hover { background: #373f4e; }
            QPushButton:disabled { color: #666e7b; background: #20232a; }
            QPushButton#primaryButton { background: #4f6bed; border-color: #4f6bed; color: white; font-weight: 700; }
            QPushButton#primaryButton:hover { background: #6079f5; }
            QPushButton#primaryButton:pressed { background: #354bb8; border-style: inset; }
            QPushButton#stopButton { background: #7c3038; border-color: #93404a; color: white; font-weight: 600; }
            QPushButton#stopButton:hover { background: #99404a; }
            QPushButton#stopButton:pressed { background: #60232a; border-style: inset; }
            QPushButton#primaryButton:disabled, QPushButton#stopButton:disabled { background: #20232a; border-color: #2b303b; color: #666e7b; font-weight: 600; }
            QStatusBar { color: #9ba5b5; }
            QSplitter::handle { background: #262b35; width: 2px; }
        """)

    def _refresh_profiles(self, select_id=None):
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        selected_row = -1
        for index, profile in enumerate(self.config.get("profiles", [])):
            item = QListWidgetItem(profile.get("name", "Unnamed profile"))
            item.setData(Qt.ItemDataRole.UserRole, profile["id"])
            self.profile_list.addItem(item)
            if profile["id"] == select_id:
                selected_row = index
        self.profile_list.blockSignals(False)
        if self.profile_list.count():
            self.profile_list.setCurrentRow(selected_row if selected_row >= 0 else 0)
        else:
            self.current_profile_id = None
            self._clear_form()

    def _current_profile(self):
        for profile in self.config.get("profiles", []):
            if profile["id"] == self.current_profile_id:
                return profile
        return None

    def _profile_selected(self, current, previous=None):
        if current is None:
            return
        self.current_profile_id = current.data(Qt.ItemDataRole.UserRole)
        profile = self._current_profile()
        if not profile:
            return
        self._loading_profile = True
        self.name_edit.setText(profile.get("name", ""))
        self.url_edit.setText(profile.get("url", ""))
        self.destination_edit.setText(profile.get("destination", ""))
        self.threads_spin.setValue(int(profile.get("threads", 1)))
        self._set_combo(self.format_combo, profile.get("format"), DEFAULT_FORMAT)
        self._set_combo(self.bitrate_combo, profile.get("bitrate"), DEFAULT_BITRATE)
        self._loading_profile = False

    def _clear_form(self):
        self._loading_profile = True
        self.name_edit.clear()
        self.url_edit.clear()
        self.destination_edit.clear()
        self.threads_spin.setValue(1)
        self._set_combo(self.format_combo, DEFAULT_FORMAT, DEFAULT_FORMAT)
        self._set_combo(self.bitrate_combo, DEFAULT_BITRATE, DEFAULT_BITRATE)
        self._loading_profile = False

    @staticmethod
    def _set_combo(combo, value, default):
        index = combo.findText(str(value))
        combo.setCurrentIndex(index if index >= 0 else combo.findText(default))

    def _format_changed(self, audio_format):
        # Lossless formats have no bitrate to choose.
        self.bitrate_combo.setEnabled(audio_format not in LOSSLESS_FORMATS)

    def _new_profile(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "Download running", "Stop the current download before changing profiles.")
            return
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if not ok:
            return
        name = name.strip() or "New profile"
        profile = {
            "id": config_manager_new_id(),
            "name": name,
            "url": "",
            "destination": str(Path.home() / "Music" / name),
            "threads": 1,
            "format": DEFAULT_FORMAT,
            "bitrate": DEFAULT_BITRATE,
        }
        self.config.setdefault("profiles", []).append(profile)
        self._persist()
        self._refresh_profiles(profile["id"])

    def _duplicate_profile(self):
        profile = self._current_profile()
        if not profile:
            return
        clone = dict(profile)
        clone["id"] = config_manager_new_id()
        clone["name"] = profile.get("name", "Profile") + " (copy)"
        self.config["profiles"].append(clone)
        self._persist()
        self._refresh_profiles(clone["id"])

    def _delete_profile(self):
        profile = self._current_profile()
        if not profile:
            return
        answer = QMessageBox.question(
            self, "Delete profile",
            f"Delete the profile '{profile.get('name', 'Unnamed profile')}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.config["profiles"] = [p for p in self.config["profiles"] if p["id"] != profile["id"]]
        self._persist()
        self._refresh_profiles()

    def _browse_destination(self):
        current = self.destination_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Select destination folder", current)
        if path:
            self.destination_edit.setText(path)

    def _save_current_profile(self):
        profile = self._current_profile()
        if not profile:
            QMessageBox.information(self, "No profile", "Create a profile before saving settings.")
            return
        profile["name"] = self.name_edit.text().strip() or "Unnamed profile"
        profile["url"] = self.url_edit.text().strip()
        profile["destination"] = self.destination_edit.text().strip()
        profile["threads"] = self.threads_spin.value()
        profile["format"] = self.format_combo.currentText()
        profile["bitrate"] = self.bitrate_combo.currentText()
        self._persist()
        self._refresh_profiles(profile["id"])
        self.statusBar().showMessage("Profile saved.", 4000)

    def _persist(self):
        try:
            save_config(self.config)
        except OSError as exc:
            QMessageBox.critical(self, "Configuration error", f"Could not save configuration:\n{exc}")

    def _validate_profile(self, profile):
        url = profile.get("url", "").strip()
        if not url.startswith("https://open.spotify.com/playlist/") and not url.startswith("https://spotify.link/"):
            QMessageBox.warning(self, "Invalid playlist URL", "Enter a valid Spotify playlist URL in the selected profile.")
            return False
        if not profile.get("destination", "").strip():
            QMessageBox.warning(self, "Missing destination", "Choose a destination folder first.")
            return False
        return True

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
        ffmpeg = vendor / "ffmpeg.exe"
        deno = vendor / "deno.exe"
        ffprobe = vendor / "ffprobe.exe"
        if not ffmpeg.is_file():
            QMessageBox.warning(self, "Missing dependency", f"Could not find:\n{ffmpeg}\n\nDownload the required tools and place them in the vendor folder.")
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
            process_args = [str(Path(__file__).resolve()), "--spotdl-worker"] + args

        self.logs.appendPlainText(f"\n> Starting profile: {profile['name']}")
        self.logs.appendPlainText(f"> Destination: {destination}")
        quality = profile.get("format", DEFAULT_FORMAT)
        if quality not in LOSSLESS_FORMATS:
            quality += f", {profile.get('bitrate', DEFAULT_BITRATE)}"
        self.logs.appendPlainText(f"> Quality: {quality}")
        self.logs.appendPlainText(f"> Download threads: {profile.get('threads', 1)}\n")
        self.log_state.setText("Downloading…")
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

    def _process_error(self, process, error):
        if process is not self.process:
            return
        if error == QProcess.ProcessError.FailedToStart:
            # finished() is not emitted when the process never started.
            self.logs.appendPlainText(f"[Application] Could not start spotDL worker: {process.errorString()}")
            self._cancel_stop_timer()
            self._release_process_tree()
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

    def _clear_logs(self):
        self.logs.clear()

    def _show_config_location(self):
        QMessageBox.information(self, "Configuration file", f"Your profiles are stored here:\n{config_path()}")

    def closeEvent(self, event):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            answer = QMessageBox.question(
                self, "Download in progress",
                "A download is still running. Stop it and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.stop_requested = True
            self._capture_partial_files()
            files = self._partial_files
            self._kill_worker()
            self.process.waitForFinished(STOP_TIMEOUT_MS)
            # The event loop is ending, so retry synchronously.
            for _ in range(PARTIAL_DELETE_ATTEMPTS):
                if not self._remove_partial_files(files):
                    break
                time.sleep(PARTIAL_DELETE_RETRY_MS / 1000)
        self._release_process_tree()
        event.accept()


def config_manager_new_id():
    import uuid
    return uuid.uuid4().hex[:12]


def main():
    if "--spotdl-worker" in sys.argv:
        run_spotdl_worker()
        return

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    icon_path = resource_path("assets", "spotifydownloader.ico")
    icon = QIcon(str(icon_path))

    if icon.isNull():
        print(f"ERROR: Icon could not be loaded: {icon_path}")
    else:
        app.setWindowIcon(icon)

    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
