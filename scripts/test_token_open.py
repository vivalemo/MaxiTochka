# -*- coding: utf-8 -*-
"""Тест открытия токенов: launch_session + проверка auth в MAX."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ.setdefault("MAXITOCHKA_APP_ROOT", ROOT)

from test_suite_common import (
    DEFAULT_PROXY,
    SESSIONS_DIR,
    load_session_js,
    load_test_config,
    save_json,
    session_exists,
)

_INSPECT_JS = """() => {
  try {
    const raw = localStorage.getItem('__oneme_auth');
    const dev = localStorage.getItem('__oneme_device_id') || '';
    const body = (document.body && document.body.innerText) || '';
    let hasToken = false;
    let viewerId = null;
    if (raw && raw !== 'null') {
      const o = JSON.parse(raw);
      hasToken = !!(o && o.token);
      viewerId = o && o.viewerId != null ? o.viewerId : null;
    }
    const low = body.toLowerCase();
    return {
      url: location.href,
      hasToken,
      deviceId: dev.slice(0, 40),
      viewerId,
      bodyLen: body.length,
      qr: low.includes('qr') || body.includes('код') && body.length < 500,
      updating: body.includes('Обновление') && body.length < 120,
      preview: body.slice(0, 160).replace(/\\n/g, ' '),
    };
  } catch (e) { return { error: String(e) }; }
}
"""


def _pick_sessions(limit: int) -> list[str]:
    cfg = load_test_config()
    out: list[str] = []
    for item in cfg.get("all_ready") or []:
        if isinstance(item, dict):
            f = str(item.get("file") or "").strip()
            if f and session_exists(f) and f not in out:
                out.append(f)
    for cand in [cfg.get("primary_session"), cfg.get("secondary_session")] + list(
        cfg.get("secondary_candidates") or []
    ):
        s = str(cand or "").strip()
        if s and session_exists(s) and s not in out:
            out.append(s)
    if not out:
        try:
            for name in sorted(os.listdir(SESSIONS_DIR)):
                if name.endswith(".txt") and not name.startswith("_"):
                    out.append(name)
        except OSError:
            pass
    return out[: max(1, limit)]


def test_open_one(session_file: str, cdp_port: int, *, proxy_raw: str) -> dict:
    from session_token_parse import extract_device_id, extract_session_token, normalize_for_launch

    path = os.path.join(SESSIONS_DIR, session_file)
    raw = open(path, encoding="utf-8").read()
    tok, vid = extract_session_token(raw)
    dev = extract_device_id(raw)
    launch_js = normalize_for_launch(raw)

    result: dict = {
        "session": session_file,
        "token_len": len(tok or ""),
        "viewer_id": vid,
        "device_id": (dev or "")[:36],
        "rebuild_ok": bool(tok and launch_js),
    }

    if not tok:
        result["ok"] = False
        result["error"] = "token not parsed"
        return result

    from browser_launcher import close_session, launch_session, shutdown_playwright

    test_name = session_file.replace(".txt", "")[:50] + "_open_test"
    t0 = time.time()
    driver = None
    try:
        driver = launch_session(
            profiles_dir=os.path.join(ROOT, "profiles"),
            session_name=test_name,
            proxy_raw=proxy_raw,
            js=launch_js,
            cdp_port=cdp_port,
        )
        if not driver:
            result["ok"] = False
            result["error"] = "launch_session returned None"
            result["elapsed_sec"] = round(time.time() - t0, 1)
            return result

        page = driver._mx_playwright_session.page
        time.sleep(2.5)
        state = page.evaluate(_INSPECT_JS)
        result["state"] = state
        result["elapsed_sec"] = round(time.time() - t0, 1)

        if isinstance(state, dict) and not state.get("error"):
            logged_in = bool(state.get("hasToken")) and int(state.get("bodyLen") or 0) > 100
            logged_in = logged_in and not state.get("qr") and not state.get("updating")
            result["ok"] = logged_in
            if not logged_in:
                result["error"] = (
                    "no auth in UI"
                    if not state.get("hasToken")
                    else "QR/updating/empty UI"
                )
        else:
            result["ok"] = False
            result["error"] = str(state.get("error") if isinstance(state, dict) else state)
        return result
    except Exception as ex:
        result["ok"] = False
        result["error"] = str(ex)
        result["elapsed_sec"] = round(time.time() - t0, 1)
        return result
    finally:
        if driver is not None:
            try:
                close_session(driver._mx_playwright_session)
            except Exception:
                pass
        try:
            shutdown_playwright()
        except Exception:
            pass
        time.sleep(1.5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--limit", type=int, default=3, help="сколько токенов проверить")
    parser.add_argument("--port", type=int, default=19295, help="базовый CDP порт")
    parser.add_argument("--proxy", default="", help="host:port:user:pass (по умолчанию из proxies.txt)")
    parser.add_argument("--no-proxy", action="store_true", help="без прокси")
    args = parser.parse_args()

    proxy = "" if args.no_proxy else (args.proxy.strip() or DEFAULT_PROXY)

    sessions = _pick_sessions(args.limit)
    if not sessions:
        print("Нет .txt сессий для теста")
        return 1

    print(f"=== Тест открытия токенов ({len(sessions)}) ===")
    print(f"Прокси: {(proxy.split(':')[0] + ':***') if proxy else 'нет'}")
    tests = []
    for i, sess in enumerate(sessions):
        port = args.port + i
        print(f"\n[{i + 1}/{len(sessions)}] {sess} (cdp {port})…")
        try:
            r = test_open_one(sess, port, proxy_raw=proxy)
        except Exception as ex:
            r = {"session": sess, "ok": False, "error": str(ex)}
        tests.append(r)
        mark = "OK" if r.get("ok") else "FAIL"
        print(f"  {mark}: {r.get('error') or r.get('state', {}).get('preview', '')[:80]}")

    passed = sum(1 for t in tests if t.get("ok"))
    report = {
        "suite": "token_open",
        "passed": passed,
        "total": len(tests),
        "proxy": (proxy.split(":")[0] + ":***") if proxy else "",
        "tests": tests,
    }
    path = save_json("token_open_report.json", report)
    print(f"\nИтого: {passed}/{len(tests)} открылись")
    print(f"Отчёт: {path}")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    raise SystemExit(main())
