import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QLineEdit,
    QSpinBox, QPlainTextEdit, QFileDialog, QMessageBox, QFormLayout,
    QSplitter, QGroupBox, QStatusBar, QInputDialog
)

from config_manager import load_config, save_config, config_path


APP_NAME = "Spotify Playlist Downloader"


def resource_path(*parts):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)



def run_spotdl_worker():
    """Run spotDL in a child process so the GUI can capture logs and stop it."""
    from pathlib import Path

    home_value = (
        os.environ.get("USERPROFILE")
        or os.environ.get("HOME")
        or str(Path(sys.executable).resolve().parent)
    )

    os.environ["HOME"] = home_value
    os.environ["USERPROFILE"] = home_value

    args = sys.argv[2:]
    sys.argv = ["spotdl"] + args

    from spotdl.console.entry_point import console_entry_point

    console_entry_point()



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 760)
        self.setMinimumSize(850, 600)

        self.config = load_config()
        self.process = None
        self.current_profile_id = None
        self._loading_profile = False
        self.stop_requested = False

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
        self.threads_spin.setToolTip("Lower values can help reduce rate limiting from audio providers.")

        form.addRow("Profile name", self.name_edit)
        form.addRow("Spotify playlist URL", self.url_edit)
        form.addRow("Destination folder", dest_widget)
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
        self.logs.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
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
            QLineEdit, QSpinBox, QListWidget, QPlainTextEdit { background: #0f1116; border: 1px solid #343a46; border-radius: 6px; padding: 8px; selection-background-color: #4361ee; }
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
        self._loading_profile = False

    def _clear_form(self):
        self._loading_profile = True
        self.name_edit.clear()
        self.url_edit.clear()
        self.destination_edit.clear()
        self.threads_spin.setValue(1)
        self._loading_profile = False

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
        #   "--log-level", "DEBUG",
            "--overwrite", "skip",
            "--scan-for-songs",
            "--threads", str(profile.get("threads", 1)),
            "download", profile["url"]
        ]

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(destination))
        env = self.process.processEnvironment()
        path_value = str(vendor) + os.pathsep + env.value("PATH")
        env.insert("PATH", path_value)
        self.process.setProcessEnvironment(env)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)

        if getattr(sys, "frozen", False):
            program = sys.executable
            process_args = ["--spotdl-worker"] + args
        else:
            program = sys.executable
            process_args = [str(Path(__file__).resolve()), "--spotdl-worker"] + args

        self.logs.appendPlainText(f"\n> Starting profile: {profile['name']}")
        self.logs.appendPlainText(f"> Destination: {destination}")
        self.logs.appendPlainText(f"> Threads: {profile.get('threads', 1)}\n")
        self.log_state.setText("Downloading…")
        self.status_label.setText("Running")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.process.start(program, process_args)

    def _read_process_output(self):
        if not self.process:
            return
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self.logs.moveCursor(self.logs.textCursor().MoveOperation.End)
            self.logs.insertPlainText(data)
            self.logs.ensureCursorVisible()

    def _process_finished(self, exit_code, exit_status):
        self._read_process_output()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        if self.stop_requested:
            self.log_state.setText("Download stopped")
            self.status_label.setText("Stopped")
            self.logs.appendPlainText("\n[Application] Download stopped by user.")

        elif exit_status == QProcess.ExitStatus.CrashExit:
            self.log_state.setText("Process crashed")
            self.status_label.setText("Error")
            self.logs.appendPlainText("\n[Application] spotDL worker crashed.")

        elif exit_code == 0:
            self.log_state.setText("Download finished")
            self.status_label.setText("Completed")
            self.logs.appendPlainText("\n[Application] Download process finished.")

        else:
            self.log_state.setText(f"Finished with exit code {exit_code}")
            self.status_label.setText("Error")
            self.logs.appendPlainText(
                f"\n[Application] spotDL exited with code {exit_code}."
            )

        self.stop_requested = False
        self.process = None

    def _process_error(self, error):
        if self.process and error == QProcess.ProcessError.FailedToStart:
            self.logs.appendPlainText("\n[Application] Could not start spotDL worker.")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText("Error")
            self.log_state.setText("Failed to start")
            self.process = None

    def _stop_download(self):
        if not self.process or self.process.state() == QProcess.ProcessState.NotRunning:
            return

        self.stop_requested = True
        self.process.terminate()

        self.logs.appendPlainText("\n[Application] Stop requested.")
        self.status_label.setText("Stopping...")
        self.log_state.setText("Stopping...")

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
            self.process.terminate()
            if not self.process.waitForFinished(2500):
                self.process.kill()
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
