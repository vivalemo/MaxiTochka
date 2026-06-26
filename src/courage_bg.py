"""Animated COURAGE watermark — visible through the main panel."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QWidget

# Base sizes before 3× scale (72, 96, 56) → tripled
_ROW_CONFIGS: list[tuple[str, int, float, float, float]] = [
    # color, font_size, y_frac, start_offset, speed
    ("rgba(129, 140, 248, 0.22)", 216, 0.04, 0.0, 1.5),
    ("rgba(99, 102, 241, 0.18)", 288, 0.16, 420.0, -1.2),
    ("rgba(255, 255, 255, 0.12)", 168, 0.28, 180.0, 1.9),
    ("rgba(129, 140, 248, 0.16)", 240, 0.40, 640.0, -0.95),
    ("rgba(99, 102, 241, 0.14)", 192, 0.52, 90.0, 1.35),
    ("rgba(255, 255, 255, 0.10)", 204, 0.64, 520.0, -1.55),
    ("rgba(129, 140, 248, 0.20)", 180, 0.76, 300.0, 1.1),
    ("rgba(99, 102, 241, 0.12)", 156, 0.88, 760.0, -1.7),
]


class CourageBackground(QWidget):
    """Large COURAGE text drifting horizontally."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._offsets: list[float] = []
        self._speeds: list[float] = []
        self._y_fracs: list[float] = []
        self._font_sizes: list[int] = []
        self._labels: list[QLabel] = []

        phrase = "COURAGE   " * 14

        for color, size, y_frac, offset, speed in _ROW_CONFIGS:
            lbl = QLabel(phrase, self)
            lbl.setStyleSheet(
                f"color: {color}; background: transparent; border: none;"
            )
            spacing = max(6, size // 12)
            font = QFont("Segoe UI", size, QFont.Weight.Black)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
            lbl.setFont(font)
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._labels.append(lbl)
            self._offsets.append(offset)
            self._speeds.append(speed)
            self._y_fracs.append(y_frac)
            self._font_sizes.append(size)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

    def _row_span(self, lbl: QLabel, size: int) -> int:
        return max(lbl.width(), lbl.sizeHint().width(), size * 14, 2100)

    def _tick(self) -> None:
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        for i, lbl in enumerate(self._labels):
            self._offsets[i] += self._speeds[i]
            span = self._row_span(lbl, self._font_sizes[i])
            if self._offsets[i] > w + 80:
                self._offsets[i] = -span
            elif self._offsets[i] < -span:
                self._offsets[i] = w + 80
            y = int(h * self._y_fracs[i])
            lbl.move(int(self._offsets[i]), y)
            lbl.show()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.parent():
            self.setGeometry(0, 0, self.parent().width(), self.parent().height())
        self._tick()
