"""Вкладка «Прокси»: пинг, скорость (TCP), путь IP."""

from __future__ import annotations

import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from settings_store import default_proxies_file, load_settings, save_settings
from table_ui import TABLE_TEXT
from theme import ACCENT, SUCCESS, TEXT_DIM, WARNING

_PING_CACHE: dict[str, dict] = {}
_IP_PATH: dict[str, list[str]] = {}
_PING_SEM = threading.Semaphore(8)
_PING_LOCK = threading.Lock()
_PING_MAX_WORKERS = 8


def parse_proxy_endpoint(raw: str) -> tuple[str, int] | None:
    s = (raw or "").strip()
    if not s:
        return None
    if "://" in s:
        try:
            u = urlparse(s)
            host = (u.hostname or "").strip()
            if not host:
                return None
            port = u.port
            if port is None:
                port = 1080 if "socks" in (u.scheme or "").lower() else 8080
            return host, int(port)
        except Exception:
            return None
    parts = s.split(":")
    if len(parts) >= 2:
        host = parts[0].strip()
        try:
            port = int(parts[1].strip())
        except ValueError:
            return None
        if host:
            return host, port
    return None


def ping_proxy_ms(raw: str, timeout: float = 3.0) -> int | None:
    ep = parse_proxy_endpoint(raw)
    if not ep:
        return None
    host, port = ep
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return int((time.perf_counter() - t0) * 1000)
    except Exception:
        return None


def resolve_proxy_ip(raw: str) -> str:
    host = ""
    ep = parse_proxy_endpoint(raw)
    if ep:
        host = ep[0]
    if not host:
        return ""
    try:
        import requests

        r = requests.get(
            f"http://ip-api.com/json/{host}",
            params={"fields": "status,query"},
            timeout=6,
        )
        if r.ok:
            data = r.json()
            if data.get("status") == "success":
                return str(data.get("query") or host)
    except Exception:
        pass
    return host


def _append_ip_path(line: str, ip: str) -> None:
    if not ip:
        return
    hist = _IP_PATH.setdefault(line, [])
    if not hist or hist[-1] != ip:
        hist.append(ip)
        _IP_PATH[line] = hist[-12:]


def get_ip_path_display(line: str) -> str:
    hist = _IP_PATH.get(line) or []
    if not hist:
        return ""
    return " → ".join(hist[-6:])


def install_proxy_panel(window: Any, module: Any) -> None:
    DotLauncher = module.DotLauncher
    window._proxy_ping_cache = _PING_CACHE
    window._proxy_ip_path = _IP_PATH

    _add_proxy_toolbar(window, module)
    _patch_render_proxies(DotLauncher, module)
    _autosave_proxy_list(window, module)


def _autosave_proxy_list(window: Any, module: Any) -> None:
    if not hasattr(window, "p_input"):
        return
    timer = QTimer(window)
    timer.setSingleShot(True)
    timer.setInterval(1500)

    def _save() -> None:
        try:
            settings = load_settings()
            path = settings.get("proxies_file") or default_proxies_file()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(window.p_input.toPlainText())
            os.replace(tmp, path)
            settings["proxies_file"] = path
            save_settings(settings)
        except Exception:
            pass

    window.p_input.textChanged.connect(lambda: timer.start())
    timer.timeout.connect(_save)


def _add_proxy_toolbar(window: Any, module: Any) -> None:
    page = window.tabs.widget(0) if hasattr(window, "tabs") else None
    if page is None:
        return
    lay = page.layout()
    if lay is None or page.findChild(QPushButton, "ProxyPingAllBtn"):
        return

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 8)
    btn = QPushButton("Пинг всех")
    btn.setObjectName("ProxyPingAllBtn")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"color: {ACCENT}; border-color: {ACCENT}; font-size: 11px; font-weight: 600;"
    )
    btn.clicked.connect(lambda: _ping_all(window))
    row.addWidget(btn)
    hint = QLabel("TCP до хоста прокси · путь IP при смене")
    hint.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; border: none;")
    row.addWidget(hint, 1)
    lay.insertLayout(1, row)


def _ping_all(window: Any) -> None:
    text = ""
    if hasattr(window, "p_input"):
        text = window.p_input.toPlainText()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        window.signals.notify.emit("Нет прокси в списке", WARNING)
        return

    def worker() -> None:
        def check_one(ln: str) -> None:
            with _PING_SEM:
                ms = ping_proxy_ms(ln)
                with _PING_LOCK:
                    _PING_CACHE[ln] = {"ms": ms, "at": time.time()}
                ip = resolve_proxy_ip(ln)
                if ip:
                    with _PING_LOCK:
                        _append_ip_path(ln, ip)

        workers = max(1, min(_PING_MAX_WORKERS, len(lines)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(check_one, ln) for ln in lines]
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception:
                    pass

        def done() -> None:
            try:
                if hasattr(window, "render_proxies"):
                    window.render_proxies()
                window.signals.notify.emit(f"Пинг: {len(lines)} прокси", SUCCESS)
            except Exception:
                pass

        QTimer.singleShot(0, done)

    threading.Thread(target=worker, daemon=True).start()
    window.signals.notify.emit("Пинг прокси…", ACCENT)


def _patch_render_proxies(DotLauncher: type, module: Any) -> None:
    orig = DotLauncher.render_proxies

    def render_proxies(self):
        try:
            orig(self)
        except Exception:
            return
        try:
            _decorate_proxy_rows(self, module)
        except Exception:
            pass

    DotLauncher.render_proxies = render_proxies


def _decorate_proxy_rows(window: Any, module: Any) -> None:
    lay = getattr(window, "p_list_lay", None)
    if lay is None:
        return

    text = ""
    if hasattr(window, "p_input"):
        text = window.p_input.toPlainText()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    cache = getattr(window, "proxy_cache", {})

    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is None or w.objectName() != "ProxyItem":
            continue
        if i >= len(lines):
            break
        line = lines[i]
        info = cache.get(line, {})
        st = info.get("st", "WAIT")
        ping = _PING_CACHE.get(line, {})
        ms = ping.get("ms")
        ping_txt = f"{ms} мс" if ms is not None else "—"

        path = get_ip_path_display(line)
        extra = QLabel()
        extra.setObjectName("ProxyExtraInfo")
        extra.setStyleSheet(
            f"color: {TABLE_TEXT}; font-size: 10px; border: none; padding-left: 8px;"
        )
        parts = [f"пинг {ping_txt}"]
        if path:
            parts.append(f"IP {path}")
        extra.setText(" · ".join(parts))

        for child in w.findChildren(QLabel):
            on = child.objectName()
            if on in ("ProxyPingLabel", "ProxyExtraInfo"):
                continue
            child.setStyleSheet(
                f"color: {TABLE_TEXT}; font-size: 11px; border: none;"
            )

        ping_lbl = w.findChild(QLabel, "ProxyPingLabel")
        if ping_lbl is None:
            ping_lbl = module.QLabel(f" {ping_txt} ")
            ping_lbl.setObjectName("ProxyPingLabel")
            ping_lbl.setStyleSheet(
                f"color: {TABLE_TEXT}; font-size: 11px; font-weight: 700; border: none;"
            )
            hlay = w.layout()
            if hlay is not None:
                hlay.insertWidget(1, ping_lbl)
        else:
            ping_lbl.setText(f" {ping_txt} ")
            ping_lbl.setStyleSheet(
                f"color: {TABLE_TEXT}; font-size: 11px; font-weight: 700; border: none;"
            )

        old_extra = w.findChild(QLabel, "ProxyExtraInfo")
        if old_extra:
            old_extra.deleteLater()
        hlay = w.layout()
        if hlay is not None:
            hlay.addWidget(extra)

        # Автопинг отключён — пользуйтесь кнопкой «Пинг всех»,
        # чтобы не создавать фоновую нагрузку.
