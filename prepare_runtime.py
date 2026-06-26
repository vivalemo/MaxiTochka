#!/usr/bin/env python3
"""Копирует минимальный runtime рядом с .exe (без profiles и пользовательских сессий)."""
from __future__ import annotations

import json
import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_RT = os.path.join(ROOT, "DotLauncher.exe_extracted")
OUT_RT = os.path.join(ROOT, "build", "runtime", "DotLauncher.exe_extracted")

COPY_FILES = (
    "main.pyc",
    "chromedriver.exe",
    "storage.json",
    "history.json",
    "proxy_stats.json",
)

COPY_DIRS = ("pydivert",)


def _default_json(name: str, fallback: object) -> None:
    path = os.path.join(OUT_RT, name)
    if os.path.isfile(path):
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fallback, f, ensure_ascii=False, indent=2)


def main() -> None:
    if not os.path.isfile(os.path.join(SRC_RT, "main.pyc")):
        raise SystemExit(f"Missing {SRC_RT}\\main.pyc — extract DotLauncher first.")

    if os.path.isdir(OUT_RT):
        shutil.rmtree(OUT_RT)
    os.makedirs(OUT_RT, exist_ok=True)

    for name in COPY_FILES:
        src = os.path.join(SRC_RT, name)
        if not os.path.isfile(src):
            raise SystemExit(f"Missing runtime file: {src}")
        shutil.copy2(src, os.path.join(OUT_RT, name))

    for dirname in COPY_DIRS:
        src = os.path.join(SRC_RT, dirname)
        if not os.path.isdir(src):
            raise SystemExit(f"Missing runtime dir: {src}")
        shutil.copytree(src, os.path.join(OUT_RT, dirname))

    os.makedirs(os.path.join(OUT_RT, "sessions"), exist_ok=True)
    os.makedirs(os.path.join(OUT_RT, "profiles"), exist_ok=True)

    _default_json("storage.json", {})
    _default_json("history.json", [])
    _default_json("proxy_stats.json", {})

    print(f"Runtime prepared: {OUT_RT}")


if __name__ == "__main__":
    main()
