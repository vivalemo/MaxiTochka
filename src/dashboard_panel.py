"""Вкладка «Дашборд»: KPI на главной панели + подробный экран по клику."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import analytics
from theme import ACCENT, BG_CARD, SUCCESS, TEXT, TEXT_DIM, WARNING

_DASH_INDEX = 2

_NAV_KPI = (
    ("total_tokens", "Ток.", ACCENT),
    ("active_count", "Акт.", SUCCESS),
    ("time_today", "Сег.", ACCENT),
    ("launches_today", "Зап.", WARNING),
    ("checker_alive", "Жив.", SUCCESS),
    ("proxy", "Прок.", SUCCESS),
)


class _StatsNavPanel(QFrame):
    """Панель статистики в шапке (не QPushButton — иначе текст сжимается)."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardNavPanel")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("checked", "0")
        self.setMinimumWidth(200)
        self.setMaximumHeight(46)
        self.setMinimumHeight(40)
        self.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def set_nav_checked(self, active: bool) -> None:
        self.setProperty("checked", "1" if active else "0")
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()


def install_dashboard(window: Any, module: Any) -> None:
    if getattr(window, "_dashboard_installed", False):
        return
    window._dashboard_installed = True

    window.btn_d = _build_nav_stats_panel(window)
    window.btn_d.clicked.connect(lambda: window.switch_tab(_DASH_INDEX))

    parent = window.btn_l.parentWidget()
    if parent and parent.layout():
        lay = parent.layout()
        idx = lay.indexOf(window.btn_l)
        if isinstance(lay, QHBoxLayout):
            lay.insertWidget(idx + 1, window.btn_d, 1)
        else:
            lay.insertWidget(idx + 1, window.btn_d)

    page = _build_page(window, module)
    window.tabs.addWidget(page)
    window._dashboard_scroll = page.findChild(QScrollArea, "DashboardScroll")
    window._dashboard_body = page.findChild(QWidget, "DashboardBody")

    orig_switch = window.switch_tab

    def switch_tab(i: int) -> None:
        try:
            if i == _DASH_INDEX:
                window.tabs.setCurrentIndex(_DASH_INDEX)
                for attr in ("btn_p", "btn_l", "btn_a", "btn_crm"):
                    b = getattr(window, attr, None)
                    if b is not None:
                        b.setChecked(False)
                window.btn_d.set_nav_checked(True)
                _refresh_full_dashboard(window)
                return
            window.btn_d.set_nav_checked(False)
            orig_switch(i)
        except Exception:
            pass

    window.switch_tab = switch_tab

    timer = QTimer(window)
    timer.setInterval(3000)
    timer.timeout.connect(lambda: _dashboard_tick(window))
    timer.start()
    window._dashboard_timer = timer

    _dashboard_tick(window)


def _nav_panel_stylesheet() -> str:
    return f"""
        QFrame#DashboardNavPanel {{
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 10px;
        }}
        QFrame#DashboardNavPanel:hover {{
            background: rgba(99, 102, 241, 0.12);
            border-color: rgba(99, 102, 241, 0.4);
        }}
        QFrame#DashboardNavPanel[checked="1"] {{
            background: rgba(99, 102, 241, 0.22);
            border: 1px solid rgba(99, 102, 241, 0.5);
        }}
        QLabel#DashNavTitle {{
            color: {TEXT};
            font-size: 11px;
            font-weight: 700;
            border: none;
            background: transparent;
        }}
        QLabel#DashNavKpiLabel {{
            color: {TEXT_DIM};
            font-size: 10px;
            font-weight: 600;
            border: none;
            background: transparent;
        }}
        QLabel#DashNavKpiValue {{
            font-size: 12px;
            font-weight: 800;
            border: none;
            background: transparent;
        }}
        """


def _build_nav_stats_panel(window: Any) -> _StatsNavPanel:
    panel = _StatsNavPanel()
    panel.setStyleSheet(_nav_panel_stylesheet())

    outer = QHBoxLayout(panel)
    outer.setContentsMargins(10, 4, 10, 4)
    outer.setSpacing(10)

    title = QLabel("Статистика")
    title.setObjectName("DashNavTitle")
    title.setToolTip("Нажмите — подробный дашборд")
    outer.addWidget(title)

    sep_font = QFont("Segoe UI", 10)
    font_label = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
    font_value = QFont("Segoe UI", 12, QFont.Weight.Bold)

    window._nav_kpi_values: dict[str, QLabel] = {}
    for i, (key, label, color) in enumerate(_NAV_KPI):
        if i > 0:
            dot = QLabel("·")
            dot.setFont(sep_font)
            dot.setStyleSheet(f"color: {TEXT_DIM}; border: none;")
            outer.addWidget(dot)

        cell = QWidget()
        cell.setStyleSheet("background: transparent; border: none;")
        h = QHBoxLayout(cell)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(3)

        t = QLabel(label)
        t.setObjectName("DashNavKpiLabel")
        t.setFont(font_label)
        v = QLabel("—")
        v.setObjectName("DashNavKpiValue")
        v.setFont(font_value)
        v.setStyleSheet(f"color: {color};")
        window._nav_kpi_values[key] = v
        h.addWidget(t)
        h.addWidget(v)
        outer.addWidget(cell)

    outer.addStretch(1)
    return panel


def _fetch_dashboard_data(window: Any) -> dict | None:
    sd = getattr(window, "session_dir", "")
    if not sd:
        return None
    proxy_cache = getattr(window, "proxy_cache", {}) or {}
    active = getattr(window, "active_drivers", {}) or {}
    token_results = getattr(window, "token_results", {}) or {}
    checker = None
    if token_results:
        alive = sum(1 for v in token_results.values() if v == "OK")
        dead = sum(1 for v in token_results.values() if v and v != "OK")
        checker = {"alive": alive, "dead": dead}
    try:
        return analytics.build_dashboard(
            sd, proxy_cache, active, checker_results=checker
        )
    except Exception:
        return None


def _fetch_nav_kpi(window: Any) -> dict | None:
    sd = getattr(window, "session_dir", "")
    if not sd:
        return None
    proxy_cache = getattr(window, "proxy_cache", {}) or {}
    active = getattr(window, "active_drivers", {}) or {}
    token_results = getattr(window, "token_results", {}) or {}
    checker = None
    if token_results:
        alive = sum(1 for v in token_results.values() if v == "OK")
        dead = sum(1 for v in token_results.values() if v and v != "OK")
        checker = {"alive": alive, "dead": dead}
    try:
        return analytics.build_nav_kpi(
            sd, proxy_cache, active, checker_results=checker
        )
    except Exception:
        return None


def refresh_nav_stats(window: Any) -> None:
    """Обновить цифры на кнопке статистики (главная панель) — лёгкий расчёт."""
    labels = getattr(window, "_nav_kpi_values", None)
    if not labels:
        return
    kpi = _fetch_nav_kpi(window)
    if not kpi:
        return
    mapping = {
        "total_tokens": str(kpi.get("total_tokens", 0)),
        "active_count": str(kpi.get("active_count", 0)),
        "time_today": kpi.get("time_today", "—"),
        "launches_today": str(kpi.get("launches_today", 0)),
        "checker_alive": str(kpi.get("checker_alive", 0)),
        "proxy": f"{kpi.get('proxy_ok', 0)}/{kpi.get('proxy_total', 0)}",
    }
    for key, lbl in labels.items():
        text = mapping.get(key, "—")
        lbl.setText(text)
        lbl.setToolTip(text)


def _dashboard_tick(window: Any) -> None:
    tabs = getattr(window, "tabs", None)
    on_dashboard = tabs is not None and tabs.currentIndex() == _DASH_INDEX

    if on_dashboard:
        try:
            refresh_nav_stats(window)
        except Exception:
            pass
        try:
            _refresh_full_dashboard(window)
        except Exception:
            pass
        return

    # Дашборд закрыт — обновляем только цифры в шапке, и то не каждый тик.
    n = int(getattr(window, "_nav_kpi_skip", 0)) + 1
    if n >= 3:
        n = 0
        try:
            refresh_nav_stats(window)
        except Exception:
            pass
    window._nav_kpi_skip = n


def _refresh_full_dashboard(window: Any) -> None:
    data = _fetch_dashboard_data(window)
    if not data:
        return
    try:
        _render_kpi(window, data)
        _render_sections(window, data)
    except Exception:
        pass


def _build_page(window: Any, module: Any) -> QWidget:
    outer = QWidget()
    outer_lay = QVBoxLayout(outer)
    outer_lay.setContentsMargins(0, 0, 0, 0)

    scroll = QScrollArea()
    scroll.setObjectName("DashboardScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(module.QFrame.Shape.NoFrame)

    body = QWidget()
    body.setObjectName("DashboardBody")
    lay = QVBoxLayout(body)
    lay.setContentsMargins(16, 12, 16, 16)
    lay.setSpacing(14)

    hdr = QLabel("Подробная статистика")
    hdr.setStyleSheet(
        f"color: {TEXT}; font-size: 16px; font-weight: 800; border: none;"
    )
    lay.addWidget(hdr)

    window._dash_kpi_row = QWidget()
    window._dash_kpi_row.setLayout(QGridLayout())
    lay.addWidget(window._dash_kpi_row)

    window._dash_sections: dict[str, QLabel] = {}
    for key, title in (
        ("live", "Сейчас — активные сессии"),
        ("today", "Сегодня"),
        ("longest", "Рекорды"),
        ("top_tokens", "Топ-10 токенов по времени"),
        ("top_countries", "Топ стран"),
        ("top_proxies", "Топ прокси по времени"),
        ("proxy_geo", "Прокси и контроль"),
    ):
        lay.addWidget(_section(title, key, window))

    scroll.setWidget(body)
    outer_lay.addWidget(scroll)
    return outer


def _section(title: str, key: str, window: Any) -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(
        f"QFrame {{ background: {BG_CARD}; border-radius: 12px; "
        "border: 1px solid rgba(255,255,255,0.08); }}"
    )
    v = QVBoxLayout(frame)
    v.setContentsMargins(14, 12, 14, 12)
    hdr = QLabel(title)
    hdr.setStyleSheet(
        f"color: {TEXT_DIM}; font-size: 11px; font-weight: 700; "
        "letter-spacing: 0.5px; border: none;"
    )
    v.addWidget(hdr)
    body = QLabel("—")
    body.setWordWrap(True)
    body.setTextFormat(Qt.TextFormat.RichText)
    body.setStyleSheet(
        f"color: {TEXT}; font-size: 12px; font-weight: 500; border: none;"
    )
    body.setAlignment(Qt.AlignmentFlag.AlignTop)
    v.addWidget(body)
    window._dash_sections[key] = body
    return frame


def _kpi_card(title: str, value: str, accent: str = ACCENT) -> QFrame:
    card = QFrame()
    card.setFixedHeight(72)
    card.setStyleSheet(
        f"QFrame {{ background: rgba(255,255,255,0.08); border-radius: 10px; "
        f"border: 1px solid {accent}; }}"
    )
    v = QVBoxLayout(card)
    v.setContentsMargins(12, 8, 12, 8)
    t = QLabel(title)
    t.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px; border: none;")
    val = QLabel(value)
    val.setObjectName("KpiValue")
    val.setStyleSheet(
        f"color: {TEXT}; font-size: 18px; font-weight: 800; border: none;"
    )
    v.addWidget(t)
    v.addWidget(val)
    return card


def _render_kpi(window: Any, data: dict) -> None:
    kpi = data.get("kpi", {})
    row = window._dash_kpi_row
    lay = row.layout()
    while lay.count():
        item = lay.takeAt(0)
        if item.widget():
            item.widget().deleteLater()

    cards = [
        ("Всего токенов", str(kpi.get("total_tokens", 0)), ACCENT),
        ("Активно", str(kpi.get("active_count", 0)), SUCCESS),
        ("Время сегодня", kpi.get("time_today", "—"), ACCENT),
        ("Запусков", str(kpi.get("launches_today", 0)), WARNING),
        ("Живых (чекер)", str(kpi.get("checker_alive", 0)), SUCCESS),
        (
            "Прокси OK",
            f"{kpi.get('proxy_ok', 0)}/{kpi.get('proxy_total', 0)}",
            SUCCESS,
        ),
    ]
    for col, (title, val, color) in enumerate(cards):
        lay.addWidget(_kpi_card(title, val, color), 0, col)


def _render_sections(window: Any, data: dict) -> None:
    sec = window._dash_sections
    active = data.get("active_list") or []
    if active:
        lines = [
            f"<b>{a['name']}</b> — идёт <span style='color:#22c55e'>{a['runtime']}</span>"
            for a in active
        ]
        live_html = f"<p>Окон открыто: <b>{len(active)}</b></p>" + "<br>".join(lines)
    else:
        live_html = "<p>Нет активных сессий</p>"

    today = data.get("today", {})
    today_html = (
        f"Новых токенов: <b>{today.get('new_tokens', 0)}</b><br>"
        f"Уникальных за день: <b>{today.get('unique_tokens', 0)}</b><br>"
        f"Запусков без прокси (OK): <b>{today.get('no_proxy_launches', 0)}</b><br>"
        f"Общее время (все сессии): <b>{data.get('total_runtime', '—')}</b>"
    )

    longest = data.get("longest", {})
    longest_html = (
        f"Самая длинная сессия:<br>"
        f"<b>{longest.get('name', '—')}</b> — {longest.get('time', '—')}"
    )

    top = data.get("top_tokens") or []
    top_html = (
        "<br>".join(
            f"{i + 1}. <b>{t['name']}</b> — {t['time']}"
            for i, t in enumerate(top)
        )
        or "—"
    )

    countries = data.get("top_countries") or []
    c_html = (
        "<br>".join(
            f"{c['country']}: {c['launches']} запусков, {c['time']}"
            for c in countries[:10]
        )
        or "—"
    )

    proxies = data.get("top_proxies") or []
    p_html = (
        "<br>".join(f"<code>{p['proxy']}</code> — {p['time']}" for p in proxies[:10])
        or "—"
    )

    changes = data.get("country_changes") or []
    ch_html = (
        "<br>".join(
            f"<b>{c['name']}</b>: {c['countries']}" for c in changes[:15]
        )
        or "Нет смен стран за неделю"
    )
    no_proxy = today.get("no_proxy_launches", 0)
    geo_html = (
        f"Запуски без зелёного прокси: <b>{no_proxy}</b><br><br>"
        f"<span style='color:{WARNING}'>Смена страны (неделя):</span><br>{ch_html}"
    )

    sec["live"].setText(live_html)
    sec["today"].setText(today_html)
    sec["longest"].setText(longest_html)
    sec["top_tokens"].setText(top_html)
    sec["top_countries"].setText(c_html)
    sec["top_proxies"].setText(p_html)
    sec["proxy_geo"].setText(geo_html)


# Совместимость со старыми вызовами
def refresh_dashboard(window: Any) -> None:
    refresh_nav_stats(window)
    tabs = getattr(window, "tabs", None)
    if tabs is not None and tabs.currentIndex() == _DASH_INDEX:
        _refresh_full_dashboard(window)
