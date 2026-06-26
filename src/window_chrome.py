"""Окно: изменение размера, минимальные габариты, растягивание списков."""

from __future__ import annotations

from typing import Any

MIN_WIDTH = 960
MIN_HEIGHT = 640
DEFAULT_WIDTH = 1150
DEFAULT_HEIGHT = 800


def apply_resizable_window(window: Any, module: Any) -> None:
    """Без title bar, но с рамкой изменения размера (Windows)."""
    Qt = module.Qt
    geo = window.geometry()

    flags = (
        Qt.WindowType.Window
        | Qt.WindowType.CustomizeWindowHint
        | Qt.WindowType.WindowMinimizeButtonHint
    )
    window.setWindowFlags(flags)
    window.setGeometry(geo)

    window.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
    window.setMaximumSize(16_777_215, 16_777_215)
    if window.width() < MIN_WIDTH or window.height() < MIN_HEIGHT:
        window.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)


def apply_resizable_layout(window: Any, module: Any) -> None:
    """После init_ui: снять фикс. размер и растянуть вкладки."""
    from PyQt6.QtWidgets import QSizeGrip, QSizePolicy

    window.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
    window.setMaximumSize(16_777_215, 16_777_215)
    w = max(window.width(), DEFAULT_WIDTH)
    h = max(window.height(), DEFAULT_HEIGHT)
    window.resize(w, h)

    policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    tabs = getattr(window, "tabs", None)
    if tabs is not None:
        tabs.setSizePolicy(policy)

    for name in ("p_scroll", "l_scroll", "c_scroll", "d_scroll"):
        scroll = getattr(window, name, None)
        if scroll is not None:
            scroll.setSizePolicy(policy)
            scroll.setMinimumHeight(200)

    cont = window.findChild(module.QFrame, "MainContainer")
    if cont is not None:
        cont.setSizePolicy(policy)
        lay = cont.layout()
        if lay is not None and not getattr(window, "_size_grip_added", False):
            grip = QSizeGrip(cont)
            grip.setFixedSize(18, 18)
            grip.setStyleSheet("background: transparent;")
            lay.addWidget(
                grip,
                0,
                module.Qt.AlignmentFlag.AlignBottom | module.Qt.AlignmentFlag.AlignRight,
            )
            window._size_grip_added = True
