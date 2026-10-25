import json
import os
import re
import sys
import time
from functools import partial
from pathlib import Path
from string import Template

from PySide6.QtCore import (
    Qt, QPointF, QProcess, QProcessEnvironment, QRectF, QSize, QTemporaryDir, QTimer, QVariantAnimation
)
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QLayout, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QLineEdit,
    QSpinBox, QComboBox, QPlainTextEdit, QFileDialog, QMessageBox, QFormLayout,
    QSplitter, QGroupBox, QStatusBar, QInputDialog, QProgressBar
)

from config_manager import DEFAULT_BITRATE, DEFAULT_FORMAT, load_config, save_config, config_path
from process_control import ProcessTree, is_file_in_use
from version import __version__
from worker import BITRATES, FORMATS, LOSSLESS_FORMATS, PROGRESS_PREFIX


APP_NAME = "Spotify Playlist Downloader"
MIN_WINDOW_WIDTH = 850
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

# Colors of each theme; the stylesheet below is shared. The choice is saved
# in config.json under settings.theme.
DEFAULT_THEME = "dark"
THEMES = {
    "dark": {
        "window": "#15171c", "text": "#e7eaf0", "title": "#ffffff", "muted": "#9ba5b5",
        "menu": "#1c2028", "menu_selected": "#303746",
        "pill": "#263a32", "pill_text": "#7fe0a5",
        "border": "#343a46", "group_title": "#bfc8d8",
        "field": "#0f1116", "selection": "#4361ee", "selection_text": "#ffffff",
        "item_selected": "#29344c", "item_selected_text": "#ffffff",
        "button": "#2b303b", "button_border": "#414958", "button_hover": "#373f4e",
        "disabled": "#20232a", "disabled_border": "#2b303b", "disabled_text": "#666e7b",
        "primary": "#4f6bed", "primary_hover": "#6079f5", "primary_pressed": "#354bb8",
        "stop": "#7c3038", "stop_border": "#93404a", "stop_hover": "#99404a", "stop_pressed": "#60232a",
        "splitter": "#262b35",
        "scroll_handle": "#3a4150", "scroll_handle_hover": "#4d5668", "arrow": "#bfc8d8",
    },
    "light": {
        "window": "#f4f5f8", "text": "#1d2330", "title": "#11151d", "muted": "#5d6677",
        "menu": "#ffffff", "menu_selected": "#e3e7f0",
        "pill": "#d9f2e3", "pill_text": "#1b6e3f",
        "border": "#cdd3de", "group_title": "#3b4455",
        "field": "#ffffff", "selection": "#4f6bed", "selection_text": "#ffffff",
        "item_selected": "#dde4fb", "item_selected_text": "#11151d",
        "button": "#ffffff", "button_border": "#c3cad6", "button_hover": "#eceff5",
        "disabled": "#eceef2", "disabled_border": "#d8dce4", "disabled_text": "#8f97a6",
        "primary": "#4f6bed", "primary_hover": "#3f5ae0", "primary_pressed": "#3047b8",
        "stop": "#c0394a", "stop_border": "#a93242", "stop_hover": "#d04556", "stop_pressed": "#962b38",
        "splitter": "#d5dae3",
        "scroll_handle": "#c4cad6", "scroll_handle_hover": "#a8b0bf", "arrow": "#4a5365",
    },
}
STYLESHEET = Template("""
    QMainWindow, QWidget { background: $window; color: $text; font-size: 10pt; }
    QMenuBar, QMenu { background: $menu; color: $text; }
    QMenuBar::item:selected, QMenu::item:selected { background: $menu_selected; }
    QLabel#appTitle { font-size: 22pt; font-weight: 700; color: $title; }
    QLabel#hint { color: $muted; }
    QLabel#statusPill { background: $pill; color: $pill_text; padding: 7px 12px; border-radius: 10px; font-weight: 600; }
    QGroupBox { border: 1px solid $border; border-radius: 10px; margin-top: 12px; padding: 12px; font-weight: 600; }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: $group_title; }
    QLineEdit, QSpinBox, QComboBox, QListWidget, QPlainTextEdit { background: $field; border: 1px solid $border; border-radius: 6px; padding: 8px; selection-background-color: $selection; selection-color: $selection_text; }
    QComboBox QAbstractItemView { background: $field; border: 1px solid $border; selection-background-color: $item_selected; selection-color: $item_selected_text; }
    QListWidget::item { padding: 10px; border-radius: 5px; }
    QListWidget::item:selected { background: $item_selected; color: $item_selected_text; }
    QPushButton { background: $button; border: 1px solid $button_border; border-radius: 6px; padding: 9px 12px; }
    QPushButton:hover { background: $button_hover; }
    QPushButton:disabled { color: $disabled_text; background: $disabled; }
    QPushButton#primaryButton { background: $primary; border-color: $primary; color: white; font-weight: 700; }
    QPushButton#primaryButton:hover { background: $primary_hover; }
    QPushButton#primaryButton:pressed { background: $primary_pressed; border-style: inset; }
    QPushButton#stopButton { background: $stop; border-color: $stop_border; color: white; font-weight: 600; }
    QPushButton#stopButton:hover { background: $stop_hover; }
    QPushButton#stopButton:pressed { background: $stop_pressed; border-style: inset; }
    QPushButton#primaryButton:disabled, QPushButton#stopButton:disabled { background: $disabled; border-color: $disabled_border; color: $disabled_text; font-weight: 600; }
    QComboBox { padding-right: 34px; }
    QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: center right; width: 32px; border: none; }
    QComboBox::down-arrow { image: url("$arrow_down"); width: 12px; height: 12px; }
    QComboBox::down-arrow:on { image: url("$arrow_up"); }
    QSpinBox { padding-right: 30px; }
    QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 26px; border: none; border-left: 1px solid $border; background: transparent; }
    QSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 6px; border-bottom: 1px solid $border; }
    QSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 6px; }
    QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: $button_hover; }
    QSpinBox::up-arrow { image: url("$arrow_up"); width: 10px; height: 10px; }
    QSpinBox::down-arrow { image: url("$arrow_down"); width: 10px; height: 10px; }
    QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off, QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off { image: none; }
    QScrollBar:vertical { background: $field; width: 14px; margin: 0; }
    QScrollBar:horizontal { background: $field; height: 14px; margin: 0; }
    QScrollBar::handle:vertical { background: $scroll_handle; border-radius: 4px; min-height: 32px; margin: 2px 3px; }
    QScrollBar::handle:horizontal { background: $scroll_handle; border-radius: 4px; min-width: 32px; margin: 3px 2px; }
    QAbstractScrollArea::corner { background: $field; }
    QScrollBar::handle:hover { background: $scroll_handle_hover; }
    QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: none; }
    QScrollBar::add-page, QScrollBar::sub-page { background: none; }
    QProgressBar { background: $field; border: 1px solid $border; border-radius: 5px; }
    QProgressBar::chunk { background: $primary; border-radius: 4px; }
    QStatusBar { color: $muted; }
    QSplitter::handle { background: $splitter; width: 2px; }
""")


def resource_path(*parts):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def make_arrow_images(directory, color):
    """Draw rounded chevrons in the given color and return their file paths.

    Stylesheets can only show arrows as images. They are drawn at run time,
    once per theme color, rather than shipped as SVG files that would depend
    on the Qt SVG plugin being bundled.
    """
    paths = {}
    for name, points in {
        "down": [(8, 12), (16, 20), (24, 12)],
        "up": [(8, 20), (16, 12), (24, 20)],
    }.items():
        path = Path(directory) / f"arrow_{name}_{color.lstrip('#')}.png"
        if not path.exists():
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(color), 3.5, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            chevron = QPainterPath(QPointF(*points[0]))
            for point in points[1:]:
                chevron.lineTo(QPointF(*point))
            painter.drawPath(chevron)
            painter.end()
            pixmap.save(str(path), "PNG")
        # Stylesheet URLs need forward slashes.
        paths[f"arrow_{name}"] = path.as_posix()
    return paths


class ThemeSwitch(QAbstractButton):
    """Dark/light toggle switch: a moon on the left, a sun on the right.

    Checked means the light theme. The knob slides to the active side and
    shows its icon; the colors follow the current theme palette.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Repaint on hover, to highlight the border. Keyboard users reach it
        # with Tab; a mouse click does not leave it highlighted.
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedSize(self.sizeHint())
        self._colors = THEMES[DEFAULT_THEME]
        # Knob position: 0 = dark (left), 1 = light (right).
        self._position = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(150)
        self._animation.valueChanged.connect(self._set_position)
        self.toggled.connect(self._animate_to)

    def sizeHint(self):
        return QSize(62, 30)

    def set_colors(self, colors):
        self._colors = colors
        self.update()

    def set_light(self, light, animate=True):
        """Change the state without emitting toggled."""
        if self.isChecked() != light:
            self.blockSignals(True)
            self.setChecked(light)
            self.blockSignals(False)
        if animate:
            self._animate_to(light)
        else:
            self._animation.stop()
            self._set_position(1.0 if light else 0.0)

    def _animate_to(self, light):
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if light else 0.0)
        self._animation.start()

    def _set_position(self, value):
        self._position = float(value)
        self.update()

    def paintEvent(self, event):
        colors = self._colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = track.height() / 2
        highlighted = self.underMouse() or self.hasFocus()
        border = colors["primary"] if highlighted else colors["button_border"]
        painter.setPen(QPen(QColor(border), 1))
        painter.setBrush(QColor(colors["field"]))
        painter.drawRoundedRect(track, radius, radius)

        margin = 3
        knob_size = track.height() - 2 * margin
        left = track.left() + margin
        right = track.right() - margin - knob_size
        center_y = track.center().y()
        icon_size = knob_size * 0.62

        # Faint icons on the track; the knob covers the active one.
        muted = QColor(colors["muted"])
        self._draw_moon(painter, QPointF(left + knob_size / 2, center_y), icon_size, muted)
        self._draw_sun(painter, QPointF(right + knob_size / 2, center_y), icon_size, muted)

        knob_x = left + (right - left) * self._position
        knob = QRectF(knob_x, center_y - knob_size / 2, knob_size, knob_size)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["primary"]))
        painter.drawEllipse(knob)
        white = QColor("#ffffff")
        if self._position >= 0.5:
            self._draw_sun(painter, knob.center(), icon_size, white)
        else:
            self._draw_moon(painter, knob.center(), icon_size, white)

    @staticmethod
    def _draw_sun(painter, center, size, color):
        painter.setPen(QPen(color, max(1.2, size * 0.1), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(color)
        core = size * 0.22
        painter.drawEllipse(center, core, core)
        for index in range(8):
            angle = index * 45
            path = QPainterPath()
            path.moveTo(center + QPointF(size * 0.36, 0))
            path.lineTo(center + QPointF(size * 0.5, 0))
            painter.save()
            painter.translate(center)
            painter.rotate(angle)
            painter.translate(-center)
            painter.drawPath(path)
            painter.restore()

    @staticmethod
    def _draw_moon(painter, center, size, color):
        # A disc with an offset disc removed from it: a crescent.
        outer = QPainterPath()
        outer.addEllipse(center, size * 0.42, size * 0.42)
        bite = QPainterPath()
        bite.addEllipse(center + QPointF(size * 0.22, -size * 0.16), size * 0.36, size * 0.36)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(outer.subtracted(bite))


def run_spotdl_worker():
    """Run spotDL in a child process so the GUI can capture logs and stop it."""
    import worker

    worker.run(sys.argv[2:])


class MainWindow(QMainWindow):
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
        "license: see THIRD_PARTY_NOTICES.md next to the executable.</p>"
    )


def config_manager_new_id():
    import uuid
    return uuid.uuid4().hex[:12]


def main():
    if "--spotdl-worker" in sys.argv:
        run_spotdl_worker()
        return
    if "--self-check" in sys.argv:
        import worker

        sys.exit(worker.self_check())

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)

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
