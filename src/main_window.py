"""The main window: layout, menus, theme, About and closing."""

import time

from PySide6.QtCore import Qt, QProcess, QTemporaryDir
from PySide6.QtGui import QAction, QActionGroup, QFont
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from config_manager import config_path, load_config
from downloads import PARTIAL_DELETE_ATTEMPTS, PARTIAL_DELETE_RETRY_MS, STOP_TIMEOUT_MS, DownloadsMixin
from profiles import ProfilesMixin
from theme import DEFAULT_THEME, STYLESHEET, THEMES, make_arrow_images
from version import __version__
from widgets import ThemeSwitch
from worker import BITRATES, FORMATS

APP_NAME = "Spotify Playlist Downloader"
MIN_WINDOW_WIDTH = 850


class MainWindow(ProfilesMixin, DownloadsMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1100, 820)

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
        # Processed tracks: up to date, downloaded or failed.
        self._progress = {"total": None, "done": 0, "failed": 0}
        self._failed_tracks = []
        # Arrow images used by the stylesheet, deleted when the window closes.
        self._arrow_dir = QTemporaryDir()

        self._build_ui()
        settings = self.config.get("settings")
        saved_theme = settings.get("theme") if isinstance(settings, dict) else None
        # Applied before the window is shown; an unknown value falls back to dark.
        self._set_theme(saved_theme, save=False)
        self._refresh_profiles()
        self.statusBar().showMessage(f"Configuration: {config_path()}")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)
        # The window can never be smaller than this layout needs, so no field
        # is ever squeezed. Qt keeps it up to date once the stylesheet applies.
        outer.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        header = QHBoxLayout()
        title_box = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        title_box.addWidget(title)
        version_label = QLabel(f"v{__version__}")
        version_label.setObjectName("hint")
        title_box.addWidget(version_label, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addLayout(title_box)
        header.addStretch()
        self.theme_switch = ThemeSwitch()
        self.theme_switch.toggled.connect(
            lambda light: self._set_theme("light" if light else "dark")
        )
        header.addWidget(self.theme_switch, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addSpacing(8)
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("statusPill")
        header.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        # Below this width the form gets cramped.
        splitter.setMinimumWidth(MIN_WINDOW_WIDTH - 2 * 18)
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
        # The row sits in its own widget: without this, the default layout
        # margins make it taller than the other fields, and it is the one
        # squeezed when the window is at its default size.
        dest_row.setContentsMargins(0, 0, 0, 0)
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

        def add_row(text, field):
            # QFormLayout places labels at the top of their row; giving each
            # label its field's height centers the text on the field.
            label = QLabel(text)
            label.setMinimumHeight(field.sizeHint().height())
            form.addRow(label, field)

        add_row("Profile name", self.name_edit)
        add_row("Spotify playlist URL", self.url_edit)
        add_row("Destination folder", dest_widget)
        add_row("Audio format", self.format_combo)
        add_row("Bitrate", self.bitrate_combo)
        add_row("Download threads", self.threads_spin)
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

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("hint")
        self.progress_label.setToolTip(
            "Processed tracks: already up to date, downloaded, or failed."
        )
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_label)
        logs_layout.addLayout(progress_row)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.logs.setFont(QFont("Consolas", 9))
        # The logs scroll, so they can shrink more than the form when the
        # window is small.
        self.logs.setMinimumHeight(60)
        self.logs.document().setMaximumBlockCount(5000)
        logs_layout.addWidget(self.logs)
        outer.addWidget(logs_group, 2)

        file_menu = self.menuBar().addMenu("File")
        open_config_action = QAction("Show configuration location", self)
        open_config_action.triggered.connect(self._show_config_location)
        file_menu.addAction(open_config_action)

        view_menu = self.menuBar().addMenu("View")
        theme_menu = view_menu.addMenu("Theme")
        # Exclusive group: exactly one theme is checked.
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        self.theme_actions = {}
        for name, label in (("light", "Light"), ("dark", "Dark")):
            action = QAction(label, self)
            action.setCheckable(True)
            # triggered is only emitted by the user, not by setChecked().
            action.triggered.connect(lambda checked=False, theme=name: self._set_theme(theme))
            theme_group.addAction(action)
            theme_menu.addAction(action)
            self.theme_actions[name] = action

        help_menu = self.menuBar().addMenu("Help")
        about_action = QAction(f"About {APP_NAME}", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _set_theme(self, name, save=True):
        """Apply a theme to the whole window, and save it as the user's choice."""
        if name not in THEMES:
            name = DEFAULT_THEME
        self.theme = name
        arrows = make_arrow_images(self._arrow_dir.path(), THEMES[name]["arrow"])
        self.setStyleSheet(STYLESHEET.substitute(THEMES[name], **arrows))
        # Keep both toggles in sync without triggering them again; the switch
        # only animates when the user changes the theme.
        self.theme_switch.set_colors(THEMES[name])
        self.theme_switch.set_light(name == "light", animate=save)
        self.theme_switch.setToolTip("Switch to the light theme" if name == "dark" else "Switch to the dark theme")
        self.theme_actions[name].setChecked(True)
        if save:
            if not isinstance(self.config.get("settings"), dict):
                self.config["settings"] = {}
            self.config["settings"]["theme"] = name
            self._persist()

    def _clear_logs(self):
        self.logs.clear()

    def _show_config_location(self):
        QMessageBox.information(self, "Configuration file", f"Your profiles are stored here:\n{config_path()}")

    def _show_about(self):
        QMessageBox.about(self, f"About {APP_NAME}", about_text())

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


def about_text():
    """Rich text for Help → About: versions, license and where to find more."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        spotdl_version = version("spotdl")
    except PackageNotFoundError:
        spotdl_version = "unknown"
    return (
        f"<h3>{APP_NAME}</h3>"
        f"<p>Version {__version__}<br>spotDL {spotdl_version}</p>"
        "<p>Released under the MIT License.</p>"
        "<p>Bundled software (spotDL, yt-dlp, Qt for Python, FFmpeg, Deno) keeps its own "
        "license: see docs\\THIRD_PARTY_NOTICES.md next to the executable.</p>"
    )
