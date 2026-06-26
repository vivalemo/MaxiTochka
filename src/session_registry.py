"""Реестр открытых браузеров: порт CDP, id сессии — для переподключения после перезапуска."""

from __future__ import annotations

import json
import os
import socket
import uuid
from typing import Any

from settings_store import load_settings, save_settings

_REGISTRY_KEY = "browser_sessions"
_TITLE_PREFIX = "MX"
_PORT_MIN = 19222
_PORT_MAX = 19999
_last_profile_dir = ""


def _registry() -> dict:
    data = load_settings()
    reg = data.get(_REGISTRY_KEY)
    if not isinstance(reg, dict):
        reg = {}
        data[_REGISTRY_KEY] = reg
    return data, reg


def _save_registry(data: dict) -> None:
    save_settings(data)


def get_or_create_session_id(session_dir: str, fname: str) -> str:
    """Стабильный короткий id для токена (в заголовке вкладки)."""
    if not session_dir or not fname:
        return uuid.uuid4().hex[:8]
    try:
        import sessions_meta as meta

        data = meta.load(session_dir)
        entry = data.get(fname) if isinstance(data.get(fname), dict) else {}
        sid = (entry.get("mx_session_id") or "").strip()
        if not sid:
            sid = uuid.uuid4().hex[:8]
            entry["mx_session_id"] = sid
            data[fname] = entry
            meta.save(session_dir, data)
        return sid
    except Exception:
        return uuid.uuid4().hex[:8]


def format_tab_title(session_id: str, display: str) -> str:
    """Уникальный заголовок: MX·id·имя (id не повторяется между токенами)."""
    sid = (session_id or "").strip() or "?"
    name = (display or "").strip() or "?"
    return f"{_TITLE_PREFIX}·{sid}·{name}"


def parse_tab_title(title: str) -> tuple[str | None, str | None]:
    """
    Разбор заголовка вкладки.
    Возвращает (session_id, display_name) или (None, None).
    """
    t = (title or "").strip()
    if not t.startswith(_TITLE_PREFIX):
        return None, None
    parts = t.split("·", 2)
    if len(parts) < 3:
        parts = t.split("|", 2)
    if len(parts) < 3:
        return None, None
    return parts[1].strip() or None, parts[2].strip() or None


def find_fname_by_session_id(session_dir: str, session_id: str) -> str | None:
    if not session_dir or not session_id:
        return None
    try:
        import sessions_meta as meta

        for fname, entry in meta.load(session_dir).items():
            if not fname.endswith(".txt") or not isinstance(entry, dict):
                continue
            if entry.get("mx_session_id") == session_id:
                return fname
    except Exception:
        pass
    return None


def allocate_debug_port() -> int:
    for port in range(_PORT_MIN, _PORT_MAX):
        if _port_free(port):
            return port
    return _PORT_MIN


def _port_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def is_debug_port_alive(port: int) -> bool:
    if not port:
        return False
    try:
        import urllib.request

        with urllib.request.urlopen(
            f"http://127.0.0.1:{int(port)}/json/version", timeout=1.5
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def is_browser_window_alive(port: int) -> bool:
    """CDP: браузер отвечает и есть хотя бы одна страница (не пустой процесс)."""
    if not is_debug_port_alive(port):
        return False
    try:
        import json
        import urllib.request

        with urllib.request.urlopen(
            f"http://127.0.0.1:{int(port)}/json/list", timeout=1.5
        ) as resp:
            targets = json.loads(resp.read().decode())
        if not isinstance(targets, list):
            return False
        for target in targets:
            if not isinstance(target, dict) or target.get("type") != "page":
                continue
            url = (target.get("url") or "").lower()
            if url.startswith("chrome://"):
                continue
            return True
        return False
    except Exception:
        return False


def register_session(
    fname: str,
    *,
    port: int,
    session_id: str,
    profile_dir: str = "",
    proxy_raw: str = "",
    proxy_port: int = 0,
) -> None:
    data, reg = _registry()
    prev = reg.get(fname) if isinstance(reg.get(fname), dict) else {}
    entry = {
        "port": int(port),
        "session_id": session_id,
        "profile_dir": profile_dir,
        "proxy_raw": str(proxy_raw or prev.get("proxy_raw") or ""),
        "proxy_port": int(proxy_port or prev.get("proxy_port") or 0),
    }
    reg[fname] = entry
    _save_registry(data)


def update_session_proxy(fname: str, proxy_raw: str, proxy_port: int) -> None:
    """Сохранить актуальный upstream-прокси и порт mitmproxy для сессии."""
    data, reg = _registry()
    entry = reg.get(fname)
    if not isinstance(entry, dict):
        return
    entry["proxy_raw"] = str(proxy_raw or "")
    entry["proxy_port"] = int(proxy_port or 0)
    _save_registry(data)


def unregister_session(fname: str) -> None:
    data, reg = _registry()
    if fname in reg:
        reg.pop(fname, None)
        _save_registry(data)


def list_registered() -> dict[str, dict]:
    _, reg = _registry()
    return dict(reg)


def patch_chrome_options_debug_port(port: int) -> Any:
    """Добавить --remote-debugging-port при сборке ChromeOptions."""
    import undetected_chromedriver as uc

    global _last_profile_dir
    _last_profile_dir = ""
    orig = uc.ChromeOptions.add_argument
    injected = [False]

    def add_argument(self, arg: str, *args, **kwargs):
        global _last_profile_dir
        if isinstance(arg, str) and arg.startswith("--user-data-dir="):
            _last_profile_dir = arg.split("=", 1)[1].strip().strip('"')
        result = orig(self, arg, *args, **kwargs)
        if not injected[0]:
            orig(self, f"--remote-debugging-port={int(port)}")
            injected[0] = True
        return result

    uc.ChromeOptions.add_argument = add_argument
    return orig


def restore_chrome_options_debug_port(orig_add_argument: Any) -> None:
    import undetected_chromedriver as uc

    uc.ChromeOptions.add_argument = orig_add_argument


def last_profile_dir() -> str:
    return _last_profile_dir


def read_profile_debug_port(profiles_dir: str, profile_name: str) -> int | None:
    """Порт из DevToolsActivePort в папке профиля Chrome."""
    return read_debug_port_file(
        os.path.join(profiles_dir, profile_name, "DevToolsActivePort")
    )


def read_debug_port_file(path: str) -> int | None:
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            first = (f.readline() or "").strip()
        return int(first) if first.isdigit() else None
    except Exception:
        return None


def port_for_registered(rec: dict) -> int | None:
    """Порт из реестра или из DevToolsActivePort в profile_dir."""
    port = int(rec.get("port") or 0) or None
    prof = str(rec.get("profile_dir") or "").strip()
    if prof:
        live = read_debug_port_file(os.path.join(prof, "DevToolsActivePort"))
        if live:
            return live
    return port


def profile_looks_running(profiles_dir: str, profile_name: str) -> bool:
    base = os.path.join(profiles_dir, profile_name)
    if not os.path.isdir(base):
        return False
    lock = os.path.join(base, "SingletonLock")
    port_file = os.path.join(base, "DevToolsActivePort")
    return os.path.exists(lock) or os.path.isfile(port_file)
