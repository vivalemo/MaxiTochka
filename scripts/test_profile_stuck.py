import os, sys, json, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
SESSION = "+79273295162.txt"
PROXY = "proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0"

from browser_launcher import launch_session, close_session, shutdown_playwright

with open(os.path.join(ROOT, "sessions", SESSION), encoding="utf-8") as f:
    js = f.read()

driver = launch_session(
    profiles_dir=os.path.join(ROOT, "profiles"),
    session_name=SESSION,
    proxy_raw=PROXY,
    js=js,
    cdp_port=19296,
)
page = driver._mx_playwright_session.page
for i in range(12):
    time.sleep(5)
    snap = page.evaluate("""() => ({
      body: (document.body?.innerText || '').slice(0,120),
      body_len: (document.body?.innerText || '').length,
      updating: (document.body?.innerText || '').includes('Обновление'),
    })""")
    print(i*5+5, json.dumps(snap, ensure_ascii=False))
page.screenshot(path=os.path.join(ROOT, "scripts", "profile_stuck.png"))
close_session(driver._mx_playwright_session)
shutdown_playwright()
