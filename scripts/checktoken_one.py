# -*- coding: utf-8 -*-
"""Проверка одного токена в отдельном процессе (Qt только в main этого процесса)."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
os.environ.setdefault("MAXITOCHKA_APP_ROOT", ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка одного .txt токена")
    parser.add_argument("--path", required=True, help="полный путь к .txt")
    parser.add_argument("--fname", required=True, help="отображаемое имя (для логов чекера)")
    parser.add_argument("--root", default=ROOT, help="корень Maxitochka")
    parser.add_argument("-p", "--proxies", default="", help="файл прокси")
    args = parser.parse_args()

    from token_checker import (
        build_proxy_cache,
        check_token_via_launcher,
        load_proxies_file,
        read_proxy_lines,
    )

    path = os.path.abspath(args.path)
    if not os.path.isfile(path):
        print("error", flush=True)
        return 2

    root = os.path.abspath(args.root)
    proxy_file = args.proxies or load_proxies_file(root)
    proxy_lines = read_proxy_lines(proxy_file)
    proxy_cache = build_proxy_cache(proxy_lines, log=lambda _m: None)

    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        print("error", flush=True)
        return 2

    def _log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    result = check_token_via_launcher(
        content,
        args.fname,
        proxy_cache=proxy_cache,
        root=root,
        log=_log,
    )
    print(result, flush=True)
    return 0 if result == "alive" else 1 if result == "dead" else 2


if __name__ == "__main__":
    raise SystemExit(main())
