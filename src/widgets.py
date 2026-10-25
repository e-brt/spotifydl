"""Custom widgets."""

from PySide6.QtCore import Qt, QPointF, QRectF, QSize, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QPlainTextEdit

from theme import DEFAULT_THEME, THEMES


class LogView(QPlainTextEdit):
    """Read-only log view that also writes what it shows to a file, while one
    is attached. Everything shown goes through appendPlainText or
    insertPlainText, so the file gets exactly the displayed text, written
    as it arrives; the view itself only keeps its last lines."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self._file = None
        self._at_line_start = True

    def attach_file(self, path):
        """Write from now on to path (appended, UTF-8), instead of any earlier file."""
        self.detach_file()
        try:
            self._file = open(path, "a", encoding="utf-8")
        except OSError:
            self._file = None
        self._at_line_start = True
        return self._file is not None

    def detach_file(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None

    def appendPlainText(self, text):
        super().appendPlainText(text)
        # appendPlainText always starts a new paragraph.
        self._write(("" if self._at_line_start else "\n") + text + "\n")

    def insertPlainText(self, text):
        super().insertPlainText(text)
        self._write(text)

    def _write(self, text):
        if self._file is None or not text:
            return
        try:
            self._file.write(text)
            # Flushed at once, so the log survives a crash of the application.
            self._file.flush()
            self._at_line_start = text.endswith("\n")
        except OSError:
            # A full or removed disk must not break the application.
            self.detach_file()


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
