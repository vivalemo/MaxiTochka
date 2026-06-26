"""Настройки Maxitochka (папки, пути, версия)."""

from __future__ import annotations

import copy
import json
import os
import threading

from app_version import APP_VERSION, load_version_info

_info = load_version_info()
UPDATE_URL = _info.get("update_url") or "https://raw.githubusercontent.com/vivalemo/MaxiTochka/main/version.json"

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()

_DEFAULT = {
    "tokenbase_dir": "",
    "sessions_dir": "",
    "proxies_file": "",
    "organize_move": False,
    "last_version_check": "",
    "compact_table": False,
    "autosave_comments": True,
    "crm_chat_keyword": "ЖКХ, ключ",
    "browser_width": 800,
    "browser_height": 600,
    "browser_engine": "selenium",
    "auto_check_updates": True,
    "last_version_check": "",
    "browser_sessions": {},
}


def _settings_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "Maxitochka")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "settings.json")


def _read_from_disk(path: str) -> dict:
    if not os.path.isfile(path):
        out = dict(_DEFAULT)
        return out
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return dict(_DEFAULT)
    out = dict(_DEFAULT)
    out.update({k: data.get(k, v) for k, v in _DEFAULT.items()})
    if isinstance(data, dict):
        for k, v in data.items():
            if k not in _DEFAULT:
                out[k] = v
    reg = out.get("browser_sessions")
    if not isinstance(reg, dict):
        out["browser_sessions"] = {}
    return out


def load_settings() -> dict:
    """Кэш по mtime: настройки читаются с диска только при изменении файла."""
    path = _settings_path()
    try:
        mtime = os.path.getmtime(path) if os.path.isfile(path) else 0.0
    except OSError:
        mtime = 0.0
    with _cache_lock:
        cached = _cache.get(path)
        if cached and cached[0] == mtime:
            return copy.deepcopy(cached[1])
        data = _read_from_disk(path)
        _cache[path] = (mtime, copy.deepcopy(data))
        return copy.deepcopy(data)


def save_settings(data: dict) -> None:
    path = _settings_path()
    merged = load_settings() if os.path.isfile(path) else dict(_DEFAULT)
    merged.update(data)
    for k, v in _DEFAULT.items():
        if k in data:
            merged[k] = data[k]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    try:
        new_mtime = os.path.getmtime(path)
    except OSError:
        new_mtime = 0.0
    with _cache_lock:
        _cache[path] = (new_mtime, copy.deepcopy(merged))


def app_data_root(cwd: str | None = None) -> str:
    """Папка данных пользователя — не DotLauncher.exe_extracted."""
    env = (os.environ.get("MAXITOCHKA_APP_ROOT") or "").strip()
    if env:
        return os.path.abspath(env)
    cwd = os.path.abspath(cwd or os.getcwd())
    norm = os.path.normcase(cwd)
    if norm.endswith(os.path.normcase("DotLauncher.exe_extracted")):
        parent = os.path.dirname(cwd)
        if parent:
            return parent
    return cwd


def default_tokenbase_dir(cwd: str | None = None) -> str:
    return os.path.join(app_data_root(cwd), "tokenbase")


def default_sessions_dir(cwd: str | None = None) -> str:
    """Обратная совместимость — то же, что tokenbase."""
    return default_tokenbase_dir(cwd)


def resolve_tokenbase_dir(
    settings: dict | None = None, cwd: str | None = None
) -> str:
    data = settings if settings is not None else load_settings()
    for key in ("tokenbase_dir", "sessions_dir"):
        path = str(data.get(key) or "").strip()
        if path:
            return os.path.abspath(path)
    return default_tokenbase_dir(cwd)


def default_proxies_file(cwd: str | None = None) -> str:
    return os.path.join(app_data_root(cwd), "proxies.txt")


def subdirs_for_organize(sessions_dir: str) -> dict[str, str]:
    return {
        "alive": os.path.join(sessions_dir, "рабочие"),
        "dead": os.path.join(sessions_dir, "мёртвые"),
        "error": os.path.join(sessions_dir, "ошибки"),
    }
