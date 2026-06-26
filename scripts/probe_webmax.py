# -*- coding: utf-8 -*-
"""Разбор хранилища web.max.ru: классы bte/xte (Zr/Qr), getItem/setItem, формат __oneme_auth."""
from __future__ import annotations

import io
import os
import re
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
requests.packages.urllib3.disable_warnings()  # type: ignore
OUT = io.StringIO()


def w(*a):
    OUT.write(" ".join(str(x) for x in a) + "\n")


def proxies():
    p = open(os.path.join(ROOT, "DotLauncher.exe_extracted", "proxies.txt"), encoding="utf-8").read().strip().splitlines()[0]
    h, port, u, pw = p.split(":", 3)
    url = f"http://{u}:{pw}@{h}:{port}"
    return {"http": url, "https": url}


def main() -> int:
    px = proxies()
    url = "https://web.max.ru/_app/immutable/chunks/BqUXhCtM.js"
    body = requests.get(url, proxies=px, timeout=90, verify=False).text
    w("len", len(body))

    # классы хранилища и инициализация Zr/Qr
    for kw in ("class bte", "class xte", "bte=", "xte=", "Zr=new", "Qr=new", "Qr.init",
               "Qr.setItem", "Qr.getItem", "$r=`__oneme_auth`", "init(", "getItem(e", "setItem(e"):
        idxs = [m.start() for m in re.finditer(re.escape(kw), body)]
        if not idxs:
            continue
        w(f"\n== {kw}: {len(idxs)} hits ==")
        for j in idxs[:3]:
            w(body[max(0, j - 120): j + 360].replace("\n", " "))

    # найдём определение классов перед 'Zr=new bte'
    m = re.search(r"Zr=new\s+(\w+),\s*Qr=new\s+(\w+)", body)
    if m:
        bcls, xcls = m.group(1), m.group(2)
        w(f"\nstorage classes: Zr=new {bcls}, Qr=new {xcls}")
        for cls in (bcls, xcls):
            ci = body.find(f"{cls}=class")
            if ci < 0:
                ci = body.find(f"class {cls}")
            if ci >= 0:
                w(f"\n#### class {cls} @ {ci}")
                w(body[ci: ci + 900].replace("\n", " "))

    path = os.path.join(ROOT, "scripts", "test_results", "webmax_storage.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(OUT.getvalue())
    print("saved", path, len(OUT.getvalue()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
