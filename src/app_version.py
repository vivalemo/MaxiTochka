"""Версия Maxitochka — читается из version.json в корне проекта / рядом с .exe."""

from __future__ import annotations

import json
import os
import sys

_FALLBACK_VERSION = "1.2.0"
_cached: dict | None = None


def _version_json_paths() -> list[str]:
    paths: list[str] = []
    if getattr(sys, "frozen", False):
        paths.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "version.json"))
    src_dir = os.path.dirname(os.path.abspath(__file__))
    paths.append(os.path.join(os.path.dirname(src_dir), "version.json"))
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        paths.append(os.path.join(meipass, "version.json"))
    paths.append(os.path.join(os.getcwd(), "version.json"))
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        ap = os.path.abspath(p)
        if ap not in seen:
            seen.add(ap)
            out.append(ap)
    return out


def load_version_info(*, reload: bool = False) -> dict:
    """Прочитать version.json (кэш на время работы приложения)."""
    global _cached
    if _cached is not None and not reload:
        return dict(_cached)
    for path in _version_json_paths():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("version"):
                _cached = dict(data)
                _cached["_path"] = path
                return dict(_cached)
        except Exception:
            continue
    _cached = {
        "version": _FALLBACK_VERSION,
        "url": "",
        "notes": "",
    }
    return dict(_cached)


def app_version() -> str:
    return str(load_version_info().get("version") or _FALLBACK_VERSION).strip()


def version_display() -> str:
    return f"v{app_version()}"


def window_title(app_name: str) -> str:
    return f"{app_name} {version_display()}"


# Обратная совместимость: from settings_store import APP_VERSION
APP_VERSION = app_version()
