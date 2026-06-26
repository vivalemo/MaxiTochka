# -*- coding: utf-8 -*-
"""Консольная проверка токенов из папки tokenbase."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
os.environ.setdefault("MAXITOCHKA_APP_ROOT", ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Проверка токенов MAX из папки tokenbase (как чекер в программе). "
            "Читает .txt в корне и во всех подпапках."
        )
    )
    parser.add_argument(
        "-d",
        "--dir",
        default="",
        help="Папка с .txt токенами (по умолчанию: tokenbase в корне проекта)",
    )
    parser.add_argument(
        "-p",
        "--proxies",
        default="",
        help="Файл прокси (по умолчанию — из настроек Maxitochka)",
    )
    parser.add_argument(
        "--flat",
        action="store_true",
        help="только файлы в корне папки, без подпапок",
    )
    parser.add_argument(
        "-j",
        "--parallel",
        type=int,
        default=5,
        metavar="N",
        help="сколько токенов проверять одновременно (по умолчанию 5, 1 = последовательно)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="пауза между запуском проверок, сек (по умолчанию 1.5)",
    )
    args = parser.parse_args()

    from token_checker import default_checktoken_dir, run_checktoken_folder

    folder = args.dir or default_checktoken_dir(ROOT)
    stats = run_checktoken_folder(
        folder,
        root=ROOT,
        proxies_path=args.proxies or None,
        delay_sec=max(0.0, args.delay),
        recursive=not args.flat,
        parallel=max(1, args.parallel),
    )
    if stats["total"] == 0:
        return 1
    if stats["error"] and not stats["alive"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
