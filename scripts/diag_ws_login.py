# -*- coding: utf-8 -*-
"""Инструментируем WebSocket web.max.ru и ловим причину отказа логина по токену.

Патчим WebSocket до загрузки клиента: логируем все cmd/opcode/payload,
особенно opcode 6 (init), 19 (login), 3 (error), 20 (logout).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ.setdefault("MAXITOCHKA_APP_ROOT", ROOT)

from test_suite_common import resolve_default_proxy, save_json  # noqa: E402

WS_TAP_JS = r"""
(() => {
  if (window.__wsTapInstalled) return;
  window.__wsTapInstalled = true;
  window.__wslog = [];
  const Native = window.WebSocket;
  function Tap(url, protocols) {
    const ws = protocols === undefined ? new Native(url) : new Native(url, protocols);
    try { window.__wslog.push({t: Date.now(), dir: 'open', url: String(url)}); } catch (e) {}
    const origSend = ws.send.bind(ws);
    ws.send = function(data) {
      try {
        let obj = null;
        if (typeof data === 'string') { try { obj = JSON.parse(data); } catch (e) {} }
        window.__wslog.push({t: Date.now(), dir: 'send', cmd: obj && obj.cmd, opcode: obj && obj.opcode, seq: obj && obj.seq, payload: obj && obj.payload});
      } catch (e) {}
      return origSend(data);
    };
    ws.addEventListener('message', (ev) => {
      try {
        let obj = null;
        if (typeof ev.data === 'string') { try { obj = JSON.parse(ev.data); } catch (e) {} }
        window.__wslog.push({t: Date.now(), dir: 'recv', cmd: obj && obj.cmd, opcode: obj && obj.opcode, seq: obj && obj.seq, payload: obj && obj.payload});
      } catch (e) {}
    });
    ws.addEventListener('close', (ev) => {
      try { window.__wslog.push({t: Date.now(), dir: 'close', code: ev.code, reason: ev.reason}); } catch (e) {}
    });
    return ws;
  }
  Tap.prototype = Native.prototype;
  Tap.CONNECTING = Native.CONNECTING; Tap.OPEN = Native.OPEN;
  Tap.CLOSING = Native.CLOSING; Tap.CLOSED = Native.CLOSED;
  window.WebSocket = Tap;
})();
"""


def _truncate(obj, depth=0):
    """Укорачиваем длинные токены/строки в payload для читаемости."""
    if isinstance(obj, str):
        return obj if len(obj) <= 60 else obj[:30] + "…(" + str(len(obj)) + ")"
    if isinstance(obj, dict):
        return {k: _truncate(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate(v, depth + 1) for v in obj[:8]]
    return obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", help="имя .txt сессии (в tokenbase/ или tokenbase/alive/)")
    ap.add_argument("--port", type=int, default=19340)
    ap.add_argument("--wait", type=float, default=10.0)
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--viewer", type=int, default=None, help="принудительный viewerId в __oneme_auth")
    args = ap.parse_args()

    cand = [
        os.path.join(ROOT, "tokenbase", args.session),
        os.path.join(ROOT, "tokenbase", "alive", args.session),
        os.path.join(ROOT, "sessions", args.session),
        os.path.join(ROOT, "checktoken", "alive", args.session),
    ]
    path = next((p for p in cand if os.path.isfile(p)), None)
    if not path:
        print("session not found:", args.session)
        return 1

    raw = open(path, encoding="utf-8").read()
    from session_token_parse import extract_device_id, extract_session_token, normalize_for_launch

    tok, vid = extract_session_token(raw)
    dev = extract_device_id(raw)
    if args.viewer is not None:
        parts = []
        if dev:
            parts.append(f"localStorage.setItem('__oneme_device_id', {json.dumps(dev)});")
        payload = {"viewerId": args.viewer, "token": tok}
        parts.append(
            "localStorage.setItem('__oneme_auth', JSON.stringify("
            + json.dumps(payload, ensure_ascii=False)
            + "));"
        )
        launch_js = "".join(parts)
    else:
        launch_js = normalize_for_launch(raw)
    proxy = "" if args.no_proxy else resolve_default_proxy()

    print(f"session={args.session}")
    print(f"token_len={len(tok or '')} viewer_id={vid} device_id={dev}")
    print(f"proxy={(proxy.split(':')[0]+':***') if proxy else 'нет'}")

    from browser_launcher import close_session, launch_session, shutdown_playwright

    driver = None
    try:
        driver = launch_session(
            profiles_dir=os.path.join(ROOT, "profiles"),
            session_name=args.session[:40] + "_wsdiag",
            proxy_raw=proxy,
            js=launch_js,
            cdp_port=args.port,
            init_scripts=[WS_TAP_JS],
            require_ready=False,
        )
        if not driver:
            print("launch_session returned None")
            return 1
        page = driver._mx_playwright_session.page
        time.sleep(args.wait)
        log = page.evaluate("() => window.__wslog || []")
        ui = page.evaluate(
            "() => { const b=(document.body&&document.body.innerText)||''; "
            "const a=localStorage.getItem('__oneme_auth'); "
            "return {bodyLen:b.length, preview:b.slice(0,140).replace(/\\n/g,' '), auth:a}; }"
        )
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

    print("\n=== UI ===")
    print(json.dumps(ui, ensure_ascii=False, indent=2))
    print(f"\n=== WS log ({len(log)} событий) ===")
    for e in log:
        d = dict(e)
        if "payload" in d:
            d["payload"] = _truncate(d.get("payload"))
        print(json.dumps(d, ensure_ascii=False))

    save_json("ws_login_diag.json", {"session": args.session, "ui": ui, "log": log})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
