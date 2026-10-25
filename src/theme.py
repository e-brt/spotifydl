"""Color themes: one palette per theme, filled into a single stylesheet."""

from pathlib import Path
from string import Template

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

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
