"""Локальный mitmproxy-бэкенд seleniumwire — поднять/остановить на нужном порту.

Используется при перезапуске Maxitochka: чтобы ранее открытые окна Chrome
снова получили интернет через тот же `127.0.0.1:<port>`, что и до закрытия.
"""

from __future__ import annotations

import socket
import threading
from typing import Any

from app_logger import get_logger

_log = get_logger("proxy_backend")

_BACKENDS: dict[int, Any] = {}
_LOCK = threading.Lock()


def _port_externally_busy(port: int) -> bool:
    """Порт занят чем-то посторонним (не нашим процессом)?"""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def has_backend(port: int) -> bool:
    with _LOCK:
        return int(port) in _BACKENDS


def start_backend(port: int, proxy_raw: str) -> Any | None:
    """Поднять mitmproxy на 127.0.0.1:port с указанным upstream прокси.

    - Если уже работает в нашем процессе — вернёт существующий экземпляр.
    - Если порт занят чем-то ещё — вернёт None (старая сессия не восстановится).
    """
    port = int(port or 0)
    if not port:
        return None

    with _LOCK:
        existing = _BACKENDS.get(port)
        if existing is not None:
            return existing

    if _port_externally_busy(port):
        _log.warning("port %s занят посторонним процессом — пропуск", port)
        return None

    try:
        from seleniumwire.server import MitmProxy
    except Exception:
        _log.exception("seleniumwire не импортируется — backend не поднять")
        return None

    options: dict = {}
    p = (proxy_raw or "").strip()
    if p:
        # seleniumwire получает upstream через options['proxy']: scheme://[user:pass@]host:port
        # Нормализуем формат, если пользователь дал host:port или host:port:user:pass
        upstream = _normalize_upstream(p)
        if upstream:
            options["proxy"] = {"http": upstream, "https": upstream}

    try:
        backend = MitmProxy("127.0.0.1", port, options)
    except Exception:
        _log.exception("MitmProxy старт на порту %s — ошибка", port)
        return None

    t = threading.Thread(
        name=f"SW-Backend-{port}",
        target=backend.serve_forever,
        daemon=True,
    )
    t.start()

    with _LOCK:
        _BACKENDS[port] = backend
    _log.info(
        "selenium-wire backend up on 127.0.0.1:%s upstream=%s",
        port,
        (p[:60] + "…") if len(p) > 60 else (p or "(direct)"),
    )
    return backend


def _normalize_upstream(raw: str) -> str:
    """`host:port`, `host:port:user:pass`, `user:pass@host:port`, `http://...`, `socks5://...`
    → upstream URL для MitmProxy.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    if "://" in s:
        return s
    parts = s.split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        return f"http://{user}:{pwd}@{host}:{port}"
    if "@" in s:
        return f"http://{s}"
    return f"http://{s}"


def allocate_relay_port() -> int:
    """Свободный локальный порт для HTTP-реле."""
    import random

    for _ in range(40):
        port = random.randint(20000, 29999)
        if not _port_externally_busy(port):
            return port
    return 0


def stop_all() -> None:
    """Завершить все локальные mitmproxy-бэкенды (вызывать на закрытии Maxitochka)."""
    with _LOCK:
        backends = list(_BACKENDS.values())
        _BACKENDS.clear()
    for b in backends:
        try:
            b.shutdown()
        except Exception:
            _log.debug("backend shutdown error", exc_info=True)


def stop_backend(port: int) -> None:
    with _LOCK:
        b = _BACKENDS.pop(int(port), None)
    if b is None:
        return
    try:
        b.shutdown()
    except Exception:
        _log.debug("backend %s shutdown error", port, exc_info=True)
