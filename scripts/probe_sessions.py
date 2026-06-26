# -*- coding: utf-8 -*-
"""Быстрая проверка: какие токены поднимают MAX."""
from __future__ import annotations

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_suite_common import DEFAULT_PROXY, load_session_js, phone_from_session_file


def probe(fname: str, port: int) -> dict:
    from browser_launcher import close_session, launch_session, shutdown_playwright
    from max_ui_actions import MaxUIActions
    from session_token_parse import extract_session_token

    path = os.path.join(ROOT, "sessions", fname)
    if not os.path.isfile(path):
        return {"file": fname, "ok": False, "error": "missing"}

    raw = open(path, encoding="utf-8").read()
    tok, vid = extract_session_token(raw)
    js = load_session_js(fname)
    has_ls = "localStorage.setItem" in js

    driver = launch_session(
        profiles_dir=os.path.join(ROOT, "profiles"),
        session_name=f"probe_{fname.replace('.txt','')[:40]}",
        proxy_raw=DEFAULT_PROXY,
        js=js,
        cdp_port=port,
    )
    if not driver:
        return {
            "file": fname,
            "ok": False,
            "token": bool(tok),
            "viewer": vid,
            "js_localStorage": has_ls,
            "error": "launch_failed",
        }

    ui = MaxUIActions(driver._mx_playwright_session.page, fname)
    ready = ui.wait_app_ready(90000)
    body = 0
    if ready:
        try:
            body = int(
                driver._mx_playwright_session.page.evaluate(
                    "document.body?.innerText?.length || 0"
                )
            )
        except Exception:
            pass

    close_session(driver._mx_playwright_session)
    shutdown_playwright()
    return {
        "file": fname,
        "ok": ready and body > 500,
        "ready": ready,
        "body_len": body,
        "phone": phone_from_session_file(fname),
        "token": bool(tok),
        "viewer": vid,
        "js_localStorage": has_ls,
    }


def main() -> int:
    candidates = sorted(
        set(
            ["79002673484.txt"]
            + [os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "sessions", "my_accounts*.txt"))]
        )
    )
    results = []
    port = 19300
    for fname in candidates:
        print(f"probe {fname}...", flush=True)
        results.append(probe(fname, port))
        port += 1

    ok = [r for r in results if r.get("ok")]
    print("\n=== READY ===")
    for r in ok:
        print(f"  {r['file']} phone={r.get('phone') or '?'} body={r.get('body_len')}")
    print("\n=== FAILED ===")
    for r in results:
        if not r.get("ok"):
            print(f"  {r['file']}: ready={r.get('ready')} err={r.get('error','')}")

    import json
    from test_suite_common import save_json

    save_json("probe_sessions.json", {"results": results, "ready": [r["file"] for r in ok]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
