import os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from browser_launcher import launch_session, close_session, shutdown_playwright

SESSION = "+79273295162.txt"
js = open(os.path.join(ROOT, "sessions", SESSION), encoding="utf-8").read()
d = launch_session(
    profiles_dir=os.path.join(ROOT, "profiles"),
    session_name=SESSION + "_v2",
    proxy_raw="proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0",
    js=js,
    cdp_port=19295,
)
if not d:
    open(os.path.join(ROOT, "scripts", "result.json"), "w", encoding="utf-8").write('{"ok":false}')
    raise SystemExit(1)
p = d._mx_playwright_session.page
r = {
    "ok": True,
    "body_len": p.evaluate("document.body.innerText.length"),
    "has_auth": p.evaluate(
        "(() => { try { const o = JSON.parse(localStorage.getItem('__oneme_auth')); return !!(o && o.token); } catch(e){ return false; } })()"
    ),
}
open(os.path.join(ROOT, "scripts", "result.json"), "w", encoding="utf-8").write(
    json.dumps(r, ensure_ascii=False)
)
p.screenshot(path=os.path.join(ROOT, "scripts", "result.png"))
close_session(d._mx_playwright_session)
shutdown_playwright()
