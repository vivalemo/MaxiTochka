# -*- coding: utf-8 -*-
"""Точный кусок логина kittydumper: device uuid, ws-url, manual-login."""
from __future__ import annotations

import re
import sys

import requests

URL = "https://max.kittydumper.com/assets/G8BLUpHC.js"


def main() -> int:
    body = requests.get(URL, timeout=60).text

    i = body.find("window.__d9pdt")
    print("==== ws/uuid block ====")
    print(body[i - 600: i + 1500])

    for kw in ("getUuidByString", "manual-login", "lastUUID", "ws-", "new WebSocket", "WebSocket(",
               "Origin", "headers", "MULTIDEVICE", "interactive", "login"):
        idxs = [m.start() for m in re.finditer(re.escape(kw), body)]
        print(f"\n## {kw}: {len(idxs)} hits")
        for j in idxs[:2]:
            print("  ...", body[max(0, j - 150): j + 220].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
