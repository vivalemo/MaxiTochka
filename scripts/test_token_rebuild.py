# -*- coding: utf-8 -*-
"""Тест пересборки сессии: extract token → normalize_for_launch → опционально браузер."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ.setdefault("MAXITOCHKA_APP_ROOT", ROOT)

SAMPLE = """
sessionStorage.clear();
localStorage.clear();
localStorage.setItem('__oneme_device_id', 'ff768993-29fe-4fe1-90af-23347b68dd8c');
localStorage.setItem('__oneme_auth', JSON.stringify({"token":"An_Sx6HQ9HDiBi2lLq3ixX6-F3QFbjV9ufKhmymLSkzbTtf5BLGvvYyz5HBNPgJSuFzPomKsU0C9imL_cLgMsfuPtpz9q8BnjDhht-Ms8ZzuFnuJWTbI1oc5MGtSHKmp1sc7MyF7PjsmY9ECzLw2yhgcaeCB0B9w2c46qY3kC8mV5tgLlIsxhtdgoUIWW0JoqCp6iB93Cweigu4Y2d79c1o3NQmI0TP8u5Om6jy55NFHA-NRXraB5KPnPJT_CXMMv0fU3SDlv3QHMGctYX6c6shRkGt4FZYFIzfN-j6O6kRbfQctcfS_7yajubl9OgPga9wroYtrQ0fDu6oD8Q-tbBvUBPeydineBBi0HHWoNy6OklInG2Zro-k-jjgL5eGHIZ0mQvTZTQzq4aJRL0qACFKuRt8aWUBUY0RKMCI2H74GolsaWIVC94zgn7rjZK6-_lhy2Ci_LZW47ZZRUuLVrRQcqUAJxI1MB6ykimleWiFXCwmSOJkMcOjW3lsI9YEV6Jx-3XCq7I5Zk_Ji5DvZsPIlLNZrwa_OFkhifQ98lruLlCQvAC_aGB9f4kKKgnPzCDc6yGHzA2FPqJmcuR5qC6HKHbVOz9rPYKG4_ROK1Nbb7OqJCiHl0Fp_wIsJBPSnqzkdF6oYeMKvBB3DblJK2B0fsm9U2Ww0pDCflDUI4X-_Y6R018wWhwQIFaXY90ccdSmrXMI"}));
window.location.reload();
"""


def test_parse_rebuild() -> dict:
    from session_token_parse import (
        extract_device_id,
        extract_session_token,
        normalize_for_checker,
        normalize_for_launch,
    )

    tok, vid = extract_session_token(SAMPLE)
    dev = extract_device_id(SAMPLE)
    launch_js = normalize_for_launch(SAMPLE)
    checker_js = normalize_for_checker(SAMPLE)

    ok = tok is not None and len(tok or "") > 100
    ok = ok and dev == "ff768993-29fe-4fe1-90af-23347b68dd8c"
    ok = ok and "ff768993" in launch_js
    ok = ok and "JSON.stringify" in launch_js
    ok = ok and ".clear()" not in launch_js
    ok = ok and "reload" not in launch_js.casefold()
    ok = ok and tok in launch_js

    return {
        "test": "parse_rebuild",
        "ok": ok,
        "token_len": len(tok or ""),
        "viewer_id": vid,
        "device_id": dev,
        "launch_js": launch_js,
        "checker_js_len": len(checker_js),
    }


def test_browser_launch() -> dict:
    from test_suite_common import DEFAULT_PROXY, save_json

    from session_token_parse import normalize_for_launch

    venv_py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if not os.path.isfile(venv_py):
        return {"test": "browser_launch", "ok": False, "skip": "no venv"}

    launch_js = normalize_for_launch(SAMPLE)
    session_name = "_token_rebuild_test"
    cdp_port = 19294

    try:
        from browser_launcher import close_session, launch_session, shutdown_playwright

        driver = launch_session(
            profiles_dir=os.path.join(ROOT, "profiles"),
            session_name=session_name,
            proxy_raw=DEFAULT_PROXY,
            js=launch_js,
            cdp_port=cdp_port,
        )
        if not driver:
            return {"test": "browser_launch", "ok": False, "error": "launch_session None"}

        page = driver._mx_playwright_session.page
        import time

        time.sleep(3)
        state = page.evaluate(
            """() => {
              try {
                const raw = localStorage.getItem('__oneme_auth');
                const dev = localStorage.getItem('__oneme_device_id');
                const body = (document.body && document.body.innerText) || '';
                let hasToken = false;
                if (raw && raw !== 'null') {
                  const o = JSON.parse(raw);
                  hasToken = !!(o && o.token);
                }
                return {
                  url: location.href,
                  hasToken,
                  deviceId: dev || '',
                  bodyLen: body.length,
                  preview: body.slice(0, 200),
                  qr: body.includes('QR') || body.includes('код'),
                };
              } catch (e) { return { error: String(e) }; }
            }"""
        )
        ok = isinstance(state, dict) and state.get("hasToken") and int(state.get("bodyLen") or 0) > 80
        ok = ok and not state.get("qr")
        result = {
            "test": "browser_launch",
            "ok": ok,
            "state": state,
        }
        close_session(driver._mx_playwright_session)
        shutdown_playwright()
        return result
    except Exception as ex:
        try:
            from browser_launcher import shutdown_playwright

            shutdown_playwright()
        except Exception:
            pass
        return {"test": "browser_launch", "ok": False, "error": str(ex)}


def main() -> int:
    from test_suite_common import save_json

    tests = [test_parse_rebuild()]
    print("=== parse / rebuild ===")
    print(json.dumps({k: v for k, v in tests[0].items() if k != "launch_js"}, ensure_ascii=False, indent=2))
    if tests[0].get("launch_js"):
        print("\n--- launch JS ---")
        print(tests[0]["launch_js"])

    print("\n=== browser launch (venv) ===")
    bl = test_browser_launch()
    tests.append(bl)
    print(json.dumps(bl, ensure_ascii=False, indent=2))

    report = {
        "suite": "token_rebuild",
        "passed": sum(1 for t in tests if t.get("ok")),
        "total": len(tests),
        "tests": [{k: v for k, v in t.items() if k != "launch_js"} for t in tests],
        "launch_js": tests[0].get("launch_js", ""),
    }
    save_json("token_rebuild_report.json", report)

    for t in tests:
        mark = "OK" if t.get("ok") else ("SKIP" if t.get("skip") else "FAIL")
        print(f"\n{mark}: {t.get('test')} {t.get('error') or t.get('skip') or ''}")
    return 0 if all(t.get("ok") or t.get("skip") for t in tests) else 1


if __name__ == "__main__":
    raise SystemExit(main())
