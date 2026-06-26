"""Всплывающие уведомления снизу окна."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt, QPoint
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QLabel, QVBoxLayout

from theme import BG_CARD, TEXT

_TOAST_W = 400
_TOAST_MIN_H = 44
_TOAST_MARGIN = 18
_TOAST_GAP = 8
_TOAST_DURATION_MS = 3700
_ANIM_MS = 260


def _border_color(color: str) -> str:
    m = {
        "#40E0D0": "#6366f1",
        "#FF7F50": "#f43f5e",
        "#ADFF2F": "#22c55e",
        "#FFD700": "#f59e0b",
        "#FFFFFF": "#f1f5f9",
    }
    c = (color or "#6366f1").strip()
    return m.get(c, c)


class _BottomToast(QFrame):
    def __init__(self, parent, text: str, border_color: str) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setFixedWidth(_TOAST_W)
        bc = _border_color(border_color)
        self.setStyleSheet(
            f"""
            QFrame#Toast {{
                background: {BG_CARD};
                border: 1px solid {bc};
                border-radius: 12px;
            }}
            QLabel {{
                color: {TEXT};
                font-size: 12px;
                font-weight: 600;
                border: none;
                background: transparent;
            }}
            """
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lbl = QLabel(str(text).replace("\n", " · "))
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        self.adjustSize()
        self.setMinimumHeight(max(_TOAST_MIN_H, self.height()))

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(0.0)

    def animate_in(self, x: int, y: int) -> None:
        start_y = self.parentWidget().height() + 20
        self.move(x, start_y)
        self.show()
        self.raise_()

        slide = QPropertyAnimation(self, b"pos")
        slide.setDuration(_ANIM_MS)
        slide.setStartValue(QPoint(x, start_y))
        slide.setEndValue(QPoint(x, y))
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        slide.start()
        self._slide = slide

        fade = QPropertyAnimation(self._opacity, b"opacity")
        fade.setDuration(_ANIM_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.start()
        self._fade = fade

    def animate_out(self, on_done) -> None:
        fade = QPropertyAnimation(self._opacity, b"opacity")
        fade.setDuration(180)
        fade.setStartValue(self._opacity.opacity())
        fade.setEndValue(0.0)
        fade.finished.connect(on_done)
        fade.start()
        self._fade_out = fade


def _toast_host(window: Any):
    host = getattr(window, "_mx_toast_host", None)
    if host is not None:
        return host
    host = window.centralWidget() or window
    window._mx_toast_host = host
    return host


def _relayout(window: Any) -> None:
    host = _toast_host(window)
    stack: list = getattr(window, "_mx_toast_stack", [])
    y = host.height() - _TOAST_MARGIN
    for toast in reversed(stack):
        h = toast.height()
        y -= h
        toast.move(_TOAST_MARGIN, y)
        y -= _TOAST_GAP


def show_toast(window: Any, text: str, color: str) -> None:
    host = _toast_host(window)
    if not hasattr(window, "_mx_toast_stack"):
        window._mx_toast_stack = []

    stack: list = window._mx_toast_stack
    stack[:] = [t for t in stack if t is not None]

    toast = _BottomToast(host, text, color)
    stack.append(toast)
    _relayout(window)

    idx = stack.index(toast)
    y = host.height() - _TOAST_MARGIN
    for t in reversed(stack[idx:]):
        y -= t.height()
        if t is toast:
            toast.animate_in(_TOAST_MARGIN, y)
        else:
            t.move(_TOAST_MARGIN, y)
        y -= _TOAST_GAP

    def _remove() -> None:
        if toast not in stack:
            return

        def _done() -> None:
            if toast in stack:
                stack.remove(toast)
            toast.deleteLater()
            _relayout(window)

        toast.animate_out(_done)

    QTimer.singleShot(_TOAST_DURATION_MS, _remove)


def install_toast(module: Any) -> None:
    def show_toast_patched(self, text, color):
        try:
            from ui_patches import _log_toast_message

            _log_toast_message(text, color)
        except Exception:
            pass
        show_toast(self, text, color)

    module.DotLauncher.show_toast = show_toast_patched
