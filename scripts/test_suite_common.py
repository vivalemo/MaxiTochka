# -*- coding: utf-8 -*-
"""Общие утилиты для тестов."""
from __future__ import annotations

import json
import os
import re
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
OUT_DIR = os.path.join(ROOT, "scripts", "test_results")
_FALLBACK_PROXY = "proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0"

if SRC not in __import__("sys").path:
    __import__("sys").path.insert(0, SRC)

from tokenbase import default_dir as _default_tokenbase_dir

TOKENBASE_DIR = _default_tokenbase_dir(ROOT)
_legacy_sessions = os.path.join(ROOT, "sessions")
SESSIONS_DIR = (
    _legacy_sessions
    if os.path.isdir(_legacy_sessions) and not os.path.isdir(TOKENBASE_DIR)
    else TOKENBASE_DIR
)


def resolve_default_proxy() -> str:
    try:
        from token_checker import load_proxies_file, read_proxy_lines

        lines = read_proxy_lines(load_proxies_file(ROOT))
        if lines:
            return lines[0]
    except Exception:
        pass
    path = os.path.join(ROOT, "scripts", "test_accounts.json")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            proxy = str((data or {}).get("proxy") or "").strip()
            if proxy:
                return proxy
        except Exception:
            pass
    return _FALLBACK_PROXY


DEFAULT_PROXY = resolve_default_proxy()


def ensure_out() -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    return OUT_DIR


def save_json(name: str, data: dict[str, Any]) -> str:
    ensure_out()
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_test_config() -> dict[str, Any]:
    path = os.path.join(ROOT, "scripts", "test_accounts.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    return {
        "proxy": DEFAULT_PROXY,
        "primary_session": "79002673484.txt",
        "secondary_session": "my_accounts_1_20260611_1558.txt",
        "existing_contact": "КОЗЛОВА ТАТЬЯНА ЮРЬЕВНА 17.07.1966",
    }


def phone_from_session_file(fname: str) -> str:
    base = os.path.basename(fname).replace(".txt", "")
    m = re.search(r"(\+?7\d{10})", base)
    if m:
        return m.group(1).lstrip("+")
    m = re.search(r"(7\d{10})", base)
    return m.group(1) if m else ""


def load_session_js(fname: str) -> str:
    path = os.path.join(SESSIONS_DIR, fname)
    raw = open(path, encoding="utf-8").read()
    from session_token_parse import extract_session_token, normalize_for_launch

    if "localStorage.setItem" in raw or extract_session_token(raw)[0]:
        return normalize_for_launch(raw)
    return raw


def session_exists(fname: str) -> bool:
    return os.path.isfile(os.path.join(SESSIONS_DIR, fname))
