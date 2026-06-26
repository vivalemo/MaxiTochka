"""Create release zip from dist/Maxitochka for GitHub Releases."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "Maxitochka"
VERSION_FILE = ROOT / "version.json"


def _pack(zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    print(f"Creating {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(DIST.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(DIST).as_posix())
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  OK: {zip_path} ({size_mb:.1f} MB)")


def main() -> int:
    if not (DIST / "Maxitochka.exe").is_file():
        print("Run build.bat first (dist\\Maxitochka\\Maxitochka.exe missing).")
        return 1

    version = json.loads(VERSION_FILE.read_text(encoding="utf-8"))["version"].strip()
    _pack(ROOT / "dist" / f"Maxitochka-{version}.zip")
    _pack(ROOT / "dist" / "Maxitochka.zip")

    print()
    print(f"Upload dist/Maxitochka.zip to GitHub Releases (tag v{version}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
