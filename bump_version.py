#!/usr/bin/env python3
"""Увеличить версию в version.json перед сборкой или после правок.

Примеры:
  python bump_version.py          # 1.2.0 -> 1.2.1 (patch)
  python bump_version.py minor    # 1.2.0 -> 1.3.0
  python bump_version.py major    # 1.2.0 -> 2.0.0
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / "version.json"


def _parse_version(text: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    if not m:
        raise ValueError(f"bad version: {text!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _format_version(parts: tuple[int, int, int]) -> str:
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def main() -> int:
    kind = (sys.argv[1] if len(sys.argv) > 1 else "patch").strip().lower()
    if kind not in {"patch", "minor", "major"}:
        print("Usage: bump_version.py [patch|minor|major]", file=sys.stderr)
        return 1

    if not VERSION_FILE.is_file():
        print(f"Missing {VERSION_FILE}", file=sys.stderr)
        return 1

    data = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    major, minor, patch = _parse_version(str(data.get("version", "1.0.0")))
    old = _format_version((major, minor, patch))

    if kind == "major":
        major += 1
        minor = 0
        patch = 0
    elif kind == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1

    new = _format_version((major, minor, patch))
    data["version"] = new
    data["build"] = date.today().isoformat()
    url = str(data.get("url") or "")
    if "/releases/download/v" in url:
        base = url.split("/releases/download/v", 1)[0]
        data["url"] = f"{base}/releases/download/v{new}/Maxitochka.zip"
    VERSION_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{old} -> {new}")
    print(f"Updated {VERSION_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
