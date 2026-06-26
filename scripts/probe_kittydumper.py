# -*- coding: utf-8 -*-
"""Анализ механизма логина max.kittydumper.com: какие JS-бандлы, как шлётся токен."""
from __future__ import annotations

import re
import sys

import requests

BASE = "https://max.kittydumper.com/"


def main() -> int:
    r = requests.get(BASE, timeout=30)
    html = r.text
    print("html len", len(html))

    js_urls = re.findall(r'(?:src|href)=["\']([^"\']+\.(?:js|mjs)[^"\']*)["\']', html)
    js_urls = sorted(set(js_urls))
    print("JS bundles:")
    for u in js_urls:
        print("  ", u)

    # ищем интересные ключевые слова прямо в html
    for kw in ("token", "userAgent", "deviceType", "websocket", "wss", "api"):
        if kw.lower() in html.lower():
            print("html contains:", kw)

    keywords = re.compile(
        r"userAgent|deviceType|appVersion|deviceId|wss?://|/api/|login|interactive|"
        r"osVersion|screen|locale|timezone|appName|deviceName|chatList",
        re.I,
    )

    for u in js_urls:
        full = u if u.startswith("http") else BASE.rstrip("/") + "/" + u.lstrip("/")
        try:
            jr = requests.get(full, timeout=60)
        except Exception as ex:
            print("FAIL", full, ex)
            continue
        body = jr.text
        print("\n==== JS", full, "len", len(body))
        hits = {}
        for m in keywords.finditer(body):
            w = m.group(0).lower()
            hits[w] = hits.get(w, 0) + 1
        print("  keyword hits:", hits)
        # достаём wss/api эндпоинты
        for ep in sorted(set(re.findall(r'["\'](wss?://[^"\']+|/api/[^"\']+)["\']', body)))[:30]:
            print("  endpoint:", ep)

    return 0


if __name__ == "__main__":
    sys.exit(main())
