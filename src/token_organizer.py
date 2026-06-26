"""Раскладка сессий по папкам после проверки."""

from __future__ import annotations

import os
import shutil
from typing import Any

from settings_store import subdirs_for_organize


def organize_sessions(window: Any, move: bool) -> tuple[int, int, int]:
    """Разложить .txt из session_dir по подпапкам по token_results."""
    session_dir = getattr(window, "session_dir", "")
    results: dict = getattr(window, "token_results", {})
    if not session_dir or not os.path.isdir(session_dir):
        raise FileNotFoundError("Папка сессий не найдена")

    folders = subdirs_for_organize(session_dir)
    for p in folders.values():
        os.makedirs(p, exist_ok=True)

    counts = {"alive": 0, "dead": 0, "error": 0}
    op = shutil.move if move else shutil.copy2

    for name in os.listdir(session_dir):
        if not name.endswith(".txt"):
            continue
        src = os.path.join(session_dir, name)
        if not os.path.isfile(src):
            continue
        entry = results.get(name, {})
        if isinstance(entry, str):
            status = entry
        elif isinstance(entry, dict):
            status = entry.get("status") or entry.get("type") or entry.get("state")
        else:
            continue
        if status not in folders:
            continue
        dst = os.path.join(folders[status], name)
        if os.path.abspath(src) == os.path.abspath(dst):
            continue
        if os.path.exists(dst):
            os.remove(dst)
        op(src, dst)
        counts[status] += 1

    if hasattr(window, "render_sessions"):
        window.render_sessions()
    if hasattr(window, "render_checker"):
        window.render_checker()
    return counts["alive"], counts["dead"], counts["error"]
