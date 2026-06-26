"""Консоль и WebSocket после запуска."""
import os, sys, json, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

SESSION = "+79273295162.txt"
PROXY = "proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0"


def main():
    from browser_launcher import launch_session, close_session, shutdown_playwright

    logs = []

    with open(os.path.join(ROOT, "sessions", SESSION), encoding="utf-8") as f:
        js = f.read()

    driver = launch_session(
        profiles_dir=os.path.join(ROOT, "profiles"),
        session_name=SESSION + "_ws_test",
        proxy_raw=PROXY,
        js=js,
        cdp_port=19297,
    )
    if not driver:
        print("launch failed")
        return

    page = driver._mx_playwright_session.page
    page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))
    page.on("pageerror", lambda err: logs.append(f"[pageerror] {err}"))

    for sec in (5, 15, 30):
        time.sleep(5 if sec == 5 else 10)
        snap = {
            "sec": sec,
            "body_len": page.evaluate("document.body?.innerText?.length || 0"),
            "html_len": page.evaluate("document.documentElement?.innerHTML?.length || 0"),
            "app_children": page.evaluate("document.querySelector('#app')?.children?.length || 0"),
            "has_auth": page.evaluate("!!localStorage.getItem('__oneme_auth')"),
        }
        print(json.dumps(snap, ensure_ascii=False))

    print("--- console (last 30) ---")
    for line in logs[-30:]:
        print(line)

    page.screenshot(path=os.path.join(ROOT, "scripts", "ws_debug.png"), full_page=True)
    close_session(driver._mx_playwright_session)
    shutdown_playwright()


if __name__ == "__main__":
    main()
