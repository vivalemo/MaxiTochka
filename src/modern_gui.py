"""Лёгкая оболочка GUI Maxitochka.

Цель: не трогать бизнес-логику DotLauncher, а заново собрать только виджеты,
которые эта логика ожидает (`p_input`, `l_list_lay`, `c_list_lay` и т.п.).
Так интерфейс меньше подвисает при большом количестве токенов: меньше вложенных
контейнеров, меньше лишних стилей и никаких пост-рендер проходов по всему окну.
"""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from manager_guide import APP_NAME
from app_version import version_display, window_title
from theme import ACCENT, BG_CARD, BG_DEEP, BORDER, DANGER, MUTED, TEXT, TEXT_DIM


def _toggle_window_maximize(window: QWidget) -> None:
    """Развернуть/свернуть окно (без системной рамки — вручную по экрану)."""
    if getattr(window, "_mx_maximized", False):
        geo = getattr(window, "_mx_normal_geo", None)
        if geo is not None:
            window.setGeometry(geo)
        window._mx_maximized = False
        return
    window._mx_normal_geo = window.geometry()
    screen = window.screen()
    if screen is not None:
        window.setGeometry(screen.availableGeometry())
    window._mx_maximized = True


def build_modern_ui(window: Any, module: Any) -> None:
    """Собрать GUI с нуля, сохранив имена атрибутов оригинального интерфейса."""
    window.setWindowTitle(window_title(APP_NAME))
    window.setMinimumSize(1040, 680)
    window.resize(max(window.width(), 1180), max(window.height(), 760))
    window.setStyleSheet(_stylesheet())

    root = QWidget()
    root.setObjectName("Root")
    root_lay = QVBoxLayout(root)
    root_lay.setContentsMargins(12, 12, 12, 12)
    root_lay.setSpacing(0)
    window.setCentralWidget(root)

    window.cont = QFrame()
    window.cont.setObjectName("MainContainer")
    cont_lay = QVBoxLayout(window.cont)
    cont_lay.setContentsMargins(16, 14, 16, 14)
    cont_lay.setSpacing(12)
    root_lay.addWidget(window.cont)

    _build_header(window, cont_lay)

    window.tabs = QStackedWidget()
    window.tabs.setObjectName("MainTabs")
    window.tabs.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
    )
    cont_lay.addWidget(window.tabs, 1)

    window.p_page = _build_proxy_page(window)
    window.l_page = _build_tokens_page(window)
    window.c_page = window.l_page  # обратная совместимость
    window.tabs.addWidget(window.p_page)
    window.tabs.addWidget(window.l_page)

    window.switch_tab = _make_switch_tab(window)
    window.btn_p.clicked.connect(lambda: window.switch_tab(0))
    window.btn_l.clicked.connect(lambda: window.switch_tab(1))
    window.switch_tab(0)

def _build_header(window: Any, parent_lay: QVBoxLayout) -> None:
    header = QWidget()
    header_lay = QHBoxLayout(header)
    header_lay.setContentsMargins(0, 0, 0, 0)
    header_lay.setSpacing(10)

    title_box = QWidget()
    title_lay = QVBoxLayout(title_box)
    title_lay.setContentsMargins(0, 0, 0, 0)
    title_lay.setSpacing(0)
    title = QLabel(APP_NAME)
    title.setObjectName("Header")
    ver = QLabel(version_display())
    ver.setObjectName("AppVersion")
    ver.setStyleSheet(
        f"color: {TEXT_DIM}; font-size: 11px; font-weight: 600; border: none; "
        "padding: 4px 0 0 6px;"
    )
    title_row = QHBoxLayout()
    title_row.setContentsMargins(0, 0, 0, 0)
    title_row.setSpacing(0)
    title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignBottom)
    title_row.addWidget(ver, 0, Qt.AlignmentFlag.AlignBottom)
    subtitle = QLabel("прокси · токены · авто · CRM")
    subtitle.setObjectName("SubHeader")
    title_lay.addLayout(title_row)
    title_lay.addWidget(subtitle)
    header_lay.addWidget(title_box)

    header_lay.addStretch(1)

    nav = QWidget()
    nav.setObjectName("NavBar")
    nav_lay = QHBoxLayout(nav)
    nav_lay.setContentsMargins(4, 4, 4, 4)
    nav_lay.setSpacing(4)
    window.btn_p = _nav_btn("Прокси")
    window.btn_l = _nav_btn("Токены")
    window.btn_a = _nav_btn("Авто")
    window.btn_crm = _nav_btn("CRM")
    for b in (window.btn_p, window.btn_l, window.btn_a, window.btn_crm):
        nav_lay.addWidget(b)
    header_lay.addWidget(nav, 0)

    btn_min = QPushButton("—")
    btn_min.setObjectName("WindowBtn")
    btn_min.clicked.connect(window.showMinimized)
    btn_max = QPushButton("□")
    btn_max.setObjectName("WindowBtn")
    btn_max.clicked.connect(lambda: _toggle_window_maximize(window))
    btn_close = QPushButton("✕")
    btn_close.setObjectName("WindowCloseBtn")
    btn_close.clicked.connect(window.close)
    header_lay.addWidget(btn_min)
    header_lay.addWidget(btn_max)
    header_lay.addWidget(btn_close)

    parent_lay.addWidget(header)


def _nav_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("NavBtn")
    btn.setCheckable(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def _section(title: str, hint: str = "") -> tuple[QWidget, QVBoxLayout]:
    box = QFrame()
    box.setObjectName("Panel")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(10)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    lbl = QLabel(title)
    lbl.setObjectName("SectionTitle")
    row.addWidget(lbl)
    if hint:
        h = QLabel(hint)
        h.setObjectName("Hint")
        row.addWidget(h, 1)
    else:
        row.addStretch(1)
    lay.addLayout(row)
    return box, lay


def _scroll_area(object_name: str) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setObjectName(object_name)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    content = QWidget()
    content.setObjectName(object_name + "Content")
    lay = QVBoxLayout(content)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lay.setAlignment(Qt.AlignmentFlag.AlignTop)
    scroll.setWidget(content)
    return scroll, content, lay


def _build_proxy_page(window: Any) -> QWidget:
    page = QWidget()
    page.setObjectName("ProxyPage")
    lay = QHBoxLayout(page)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(12)

    left, left_lay = _section("Прокси", "вставьте список, затем проверьте")
    window.p_input = QTextEdit()
    window.p_input.setObjectName("ProxyInput")
    window.p_input.setPlaceholderText("host:port:user:pass или user:pass@host:port")
    left_lay.addWidget(window.p_input, 1)
    row = QHBoxLayout()
    row.addWidget(_action_btn("Проверить", window.start_check, primary=True))
    row.addWidget(_action_btn("Сохранить список", window.save_list))
    row.addWidget(_action_btn("Удалить мёртвые", window.purge_dead, danger=True))
    left_lay.addLayout(row)

    right, right_lay = _section("Результаты", "статус, пинг и история IP")
    window.p_scroll, window.p_scroll_content, window.p_list_lay = _scroll_area(
        "ProxyScroll"
    )
    right_lay.addWidget(window.p_scroll, 1)

    lay.addWidget(left, 1)
    lay.addWidget(right, 2)
    return page


def _build_tokens_page(window: Any) -> QWidget:
    """Запуск + чекер в одной вкладке."""
    page = QWidget()
    page.setObjectName("LaunchPage")
    lay = QVBoxLayout(page)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)

    actions = QHBoxLayout()
    actions.setContentsMargins(0, 0, 0, 0)
    actions.addWidget(_action_btn("Обновить", window.manual_refresh))
    actions.addWidget(_action_btn("Импорт", window.import_sessions))
    actions.addWidget(_action_btn("Вручную", window.add_manual_session, primary=True))
    actions.addWidget(_action_btn("Проверить", window.start_check_tokens, primary=True))
    btn_all = _action_btn("Выбрать все", lambda: None)
    btn_all.setObjectName("CheckerSelectAllBtn")
    window.checker_select_all_btn = btn_all
    actions.addWidget(btn_all)
    actions.addWidget(_action_btn("Мёртвые", window.select_dead_tokens))
    actions.addWidget(_action_btn("Удалить", window.delete_selected_tokens, danger=True))
    actions.addWidget(_action_btn("Авто", lambda: getattr(window, "start_automation", lambda: None)()))
    actions.addStretch(1)
    lay.addLayout(actions)

    panel, panel_lay = _section(
        "Токены",
        "отметьте → проверьте → запустите; комментарии и IP в строке",
    )
    window.l_scroll, window.l_scroll_content, window.l_list_lay = _scroll_area(
        "LaunchScroll"
    )
    window.c_scroll = window.l_scroll
    window.c_scroll_content = window.l_scroll_content
    window.c_list_lay = window.l_list_lay
    panel_lay.addWidget(window.l_scroll, 1)
    lay.addWidget(panel, 1)

    window.c_log = QTextEdit()
    window.c_log.setObjectName("CheckerLog")
    window.c_log.setReadOnly(True)
    window.c_log.setFixedHeight(92)
    lay.addWidget(window.c_log)

    window.c_checkboxes = {}
    return page


def _build_launch_page(window: Any) -> QWidget:
    return _build_tokens_page(window)


def _action_btn(
    text: str,
    callback: Callable,
    *,
    primary: bool = False,
    danger: bool = False,
) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("CyanBtn" if primary else "DangerBtn" if danger else "GhostBtn")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.clicked.connect(callback)
    return btn


def _make_switch_tab(window: Any) -> Callable[[int], None]:
    def switch_tab(i: int) -> None:
        window.tabs.setCurrentIndex(i)
        for idx, btn in enumerate((window.btn_p, window.btn_l)):
            btn.setChecked(idx == i)
        auto = getattr(window, "btn_a", None)
        if auto is not None:
            auto.setChecked(False)

    return switch_tab


def _stylesheet() -> str:
    return f"""
    QMainWindow, QWidget#Root {{
        background: {BG_DEEP};
        color: {TEXT};
        font-family: "Segoe UI", "Inter", sans-serif;
    }}
    QFrame#MainContainer {{
        background: {BG_CARD};
        border: 1px solid {BORDER};
        border-radius: 18px;
    }}
    QLabel#Header {{
        color: {TEXT};
        font-size: 23px;
        font-weight: 800;
        border: none;
    }}
    QLabel#SubHeader, QLabel#Hint {{
        color: {TEXT_DIM};
        font-size: 11px;
        border: none;
    }}
    QWidget#NavBar {{
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
    }}
    QPushButton#NavBtn {{
        min-height: 34px;
        padding: 0 16px;
        border: none;
        border-radius: 9px;
        color: {MUTED};
        font-size: 13px;
        font-weight: 700;
    }}
    QPushButton#NavBtn:checked {{
        color: {TEXT};
        background: rgba(99,102,241,0.28);
    }}
    QPushButton#WindowBtn, QPushButton#WindowCloseBtn {{
        min-width: 36px;
        min-height: 32px;
        border: none;
        border-radius: 9px;
        color: {TEXT_DIM};
        font-size: 16px;
        font-weight: 800;
    }}
    QPushButton#WindowCloseBtn:hover {{
        background: {DANGER};
        color: white;
    }}
    QFrame#Panel {{
        background: rgba(255,255,255,0.045);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
    }}
    QLabel#SectionTitle {{
        color: {TEXT};
        font-size: 14px;
        font-weight: 800;
        border: none;
    }}
    QTextEdit, QLineEdit {{
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 10px;
        color: {TEXT};
        padding: 8px;
        selection-background-color: {ACCENT};
    }}
    QTextEdit#CheckerLog {{
        font-family: "Cascadia Code", "Consolas", monospace;
        font-size: 11px;
        color: {TEXT_DIM};
    }}
    QPushButton#GhostBtn, QPushButton#CyanBtn, QPushButton#DangerBtn {{
        min-height: 38px;
        padding: 0 14px;
        border-radius: 10px;
        font-size: 12px;
        font-weight: 700;
    }}
    QPushButton#GhostBtn {{
        color: {TEXT};
        background: rgba(255,255,255,0.055);
        border: 1px solid rgba(255,255,255,0.10);
    }}
    QPushButton#CyanBtn {{
        color: {TEXT};
        background: rgba(99,102,241,0.28);
        border: 1px solid rgba(99,102,241,0.48);
    }}
    QPushButton#DangerBtn {{
        color: {DANGER};
        background: rgba(244,63,94,0.08);
        border: 1px solid rgba(244,63,94,0.35);
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255,255,255,0.18);
        border-radius: 4px;
        min-height: 24px;
    }}
    QFrame#ProxyItem, QFrame#SessionItem {{
        background: #1b1e27;
        border: 1px solid rgba(255,255,255,0.14);
        border-radius: 10px;
    }}
    QFrame#ProxyItem:hover, QFrame#SessionItem:hover {{
        background: #22262f;
        border: 1px solid rgba(99,102,241,0.45);
    }}
    QCheckBox {{
        color: {TEXT};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 17px;
        height: 17px;
        border-radius: 4px;
        border: 1px solid rgba(255,255,255,0.35);
        background: rgba(255,255,255,0.04);
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border: 1px solid {ACCENT};
    }}
    """
