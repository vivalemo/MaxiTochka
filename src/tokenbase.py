"""Единая папка токенов tokenbase/ — запуск, чекер, checktoken.bat."""

from __future__ import annotations

import os
import shutil

DIR_NAME = "tokenbase"
ALIVE_SUBDIR = "alive"
_LEGACY_DIRS = ("sessions", "checktoken")


def default_dir(root: str | None = None) -> str:
    from settings_store import app_data_root

    return os.path.join(app_data_root(root), DIR_NAME)


def alive_dir(tokenbase: str) -> str:
    return os.path.join(tokenbase, ALIVE_SUBDIR)


def resolve_dir(settings: dict | None = None, root: str | None = None) -> str:
    from settings_store import load_settings

    data = settings if settings is not None else load_settings()
    for key in ("tokenbase_dir", "sessions_dir"):
        path = str(data.get(key) or "").strip()
        if path:
            return os.path.abspath(path)
    return default_dir(root)


def list_txt_files(
    folder: str,
    *,
    recursive: bool = True,
    skip_subdirs: tuple[str, ...] = (ALIVE_SUBDIR,),
) -> list[str]:
    """Список .txt относительно folder (кроме skip_subdirs)."""
    if not folder or not os.path.isdir(folder):
        return []
    skip = {s.casefold() for s in skip_subdirs}
    found: list[str] = []

    if not recursive:
        for fname in os.listdir(folder):
            if fname.lower().endswith(".txt") and os.path.isfile(
                os.path.join(folder, fname)
            ):
                found.append(fname)
        return sorted(found, key=lambda p: p.casefold())

    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d.casefold() not in skip]
        rel_dir = os.path.relpath(dirpath, folder)
        if rel_dir != ".":
            parts = rel_dir.split(os.sep)
            if any(p.casefold() in skip for p in parts):
                continue
        for fname in filenames:
            if not fname.lower().endswith(".txt"):
                continue
            full = os.path.join(dirpath, fname)
            if not os.path.isfile(full):
                continue
            if rel_dir in (".", ""):
                found.append(fname)
            else:
                found.append(os.path.join(rel_dir, fname))
    return sorted(found, key=lambda p: p.casefold())


def list_gui_files(tokenbase: str) -> list[str]:
    """Токены для вкладок Запуск и Чекер: корень tokenbase + alive/."""
    if not tokenbase or not os.path.isdir(tokenbase):
        return []
    out: list[str] = []
    for fname in os.listdir(tokenbase):
        if fname.lower().endswith(".txt") and os.path.isfile(
            os.path.join(tokenbase, fname)
        ):
            out.append(fname)
    ad = alive_dir(tokenbase)
    if os.path.isdir(ad):
        for fname in os.listdir(ad):
            if fname.lower().endswith(".txt") and os.path.isfile(os.path.join(ad, fname)):
                out.append(os.path.join(ALIVE_SUBDIR, fname))
    return sorted(out, key=lambda p: p.casefold())


def token_path(tokenbase: str, rel_name: str) -> str:
    return os.path.join(tokenbase, rel_name.replace("/", os.sep))


def migrate_legacy_dirs(root: str | None = None, tokenbase: str | None = None) -> int:
    """Перенести .txt из sessions/ и checktoken/ в tokenbase/ (один раз)."""
    from settings_store import app_data_root

    root = os.path.abspath(root or app_data_root())
    dest = os.path.abspath(tokenbase or default_dir(root))
    os.makedirs(dest, exist_ok=True)
    os.makedirs(alive_dir(dest), exist_ok=True)

    moved = 0

    legacy_alive = os.path.join(root, "checktoken", ALIVE_SUBDIR)
    if os.path.isdir(legacy_alive):
        for fname in os.listdir(legacy_alive):
            if not fname.lower().endswith(".txt"):
                continue
            src = os.path.join(legacy_alive, fname)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(alive_dir(dest), fname)
            if os.path.exists(dst):
                continue
            shutil.move(src, dst)
            moved += 1

    for legacy_name in _LEGACY_DIRS:
        legacy = os.path.join(root, legacy_name)
        if not os.path.isdir(legacy):
            continue
        for dirpath, dirnames, filenames in os.walk(legacy):
            if ALIVE_SUBDIR in dirnames:
                dirnames.remove(ALIVE_SUBDIR)
            rel = os.path.relpath(dirpath, legacy)
            if rel != "." and rel.split(os.sep)[0].casefold() == ALIVE_SUBDIR:
                continue
            for fname in filenames:
                if not fname.lower().endswith(".txt"):
                    continue
                src = os.path.join(dirpath, fname)
                if rel in (".", ""):
                    dst = os.path.join(dest, fname)
                else:
                    dst = os.path.join(dest, rel, fname)
                if os.path.abspath(src) == os.path.abspath(dst):
                    continue
                if os.path.exists(dst):
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                moved += 1

    return moved
