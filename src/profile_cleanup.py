"""Удаление папок Chrome-профилей без соответствующего токена в tokenbase."""

from __future__ import annotations

import os
import shutil
from typing import Callable

from app_logger import get_logger
from tokenbase import list_gui_files

_log = get_logger("profile_cleanup")

_SKIP_DIR_NAMES = frozenset({".checker", ".tmp", "__pycache__"})


def _protected_profile_names(token_names: list[str]) -> set[str]:
    protected: set[str] = set()
    for fname in token_names:
        norm = fname.replace("\\", "/")
        protected.add(norm)
        protected.add(os.path.basename(norm))
        if norm.lower().endswith(".txt"):
            protected.add(norm[:-4])
        base = os.path.basename(norm)
        if base.lower().endswith(".txt"):
            protected.add(base[:-4])
    return protected


def profile_has_token(profile_name: str, protected: set[str]) -> bool:
    name = profile_name.replace("\\", "/")
    if name in protected:
        return True
    base = os.path.basename(name)
    if base in protected:
        return True
    if f"{name}.txt" in protected:
        return True
    if f"{base}.txt" in protected:
        return True
    if name.lower().endswith(".txt") and name[:-4] in protected:
        return True
    if base.lower().endswith(".txt") and base[:-4] in protected:
        return True
    return False


def _is_chrome_profile_dir(path: str) -> bool:
    return (
        os.path.isdir(os.path.join(path, "Default"))
        or os.path.isfile(os.path.join(path, "Preferences"))
        or os.path.exists(os.path.join(path, "SingletonLock"))
        or os.path.isfile(os.path.join(path, "DevToolsActivePort"))
    )


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for fname in files:
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                pass
    return total


def iter_chrome_profile_dirs(profiles_dir: str):
    """Корневые папки профилей Chrome под profiles_dir."""
    if not profiles_dir or not os.path.isdir(profiles_dir):
        return
    for dirpath, dirnames, _filenames in os.walk(profiles_dir):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _SKIP_DIR_NAMES and not d.startswith(".")
        ]
        rel = os.path.relpath(dirpath, profiles_dir)
        if rel == ".":
            continue
        if not _is_chrome_profile_dir(dirpath):
            continue
        rel_norm = rel.replace("\\", "/")
        yield rel_norm, dirpath
        dirnames[:] = []


def cleanup_orphan_profiles(
    profiles_dir: str,
    session_dir: str,
    *,
    is_running: Callable[[str], bool] | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Удалить профили, для которых нет .txt в tokenbase.
    Папки с активным Chrome (SingletonLock / DevToolsActivePort) не трогаем.
    """
    stats = {
        "scanned": 0,
        "kept": 0,
        "deleted": 0,
        "skipped_running": 0,
        "errors": 0,
        "bytes_freed": 0,
    }
    if not profiles_dir or not os.path.isdir(profiles_dir):
        return stats

    token_names = list_gui_files(session_dir or "")
    protected = _protected_profile_names(token_names)
    if is_running is None:
        from session_registry import profile_looks_running

        is_running = lambda name: profile_looks_running(profiles_dir, name)

    for rel_name, prof_path in iter_chrome_profile_dirs(profiles_dir):
        stats["scanned"] += 1
        if profile_has_token(rel_name, protected):
            stats["kept"] += 1
            continue
        if is_running(rel_name):
            stats["skipped_running"] += 1
            _log.info("profile cleanup skip (running): %s", rel_name)
            continue
        size = _dir_size(prof_path)
        if dry_run:
            stats["deleted"] += 1
            stats["bytes_freed"] += size
            _log.info("profile cleanup dry-run delete: %s", rel_name)
            continue
        try:
            shutil.rmtree(prof_path)
            stats["deleted"] += 1
            stats["bytes_freed"] += size
            _log.info("profile cleanup deleted: %s (%.1f MB)", rel_name, size / (1024 * 1024))
        except OSError:
            stats["errors"] += 1
            _log.exception("profile cleanup failed: %s", rel_name)

    return stats
