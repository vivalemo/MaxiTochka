"""Полный тест launch_session как в приложении."""
import os, sys, json, time, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

SESSION = "+79273295162.txt"
PROXY = "proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0"
PROFILES = os.path.join(ROOT, "profiles")
PROFILE = os.path.join(PROFILES, SESSION)


def read_js():
    with open(os.path.join(ROOT, "sessions", SESSION), encoding="utf-8") as f:
        return f.read()


def inspect(driver):
    page = driver._mx_playwright_session.page
    time.sleep(8)
    out = {}
    try:
        out["url"] = page.url
        out["title"] = page.title()
        out["ready"] = page.evaluate("document.readyState")
        out["body_len"] = page.evaluate("document.body?.innerText?.length || 0")
        out["body_preview"] = page.evaluate("document.body?.innerText?.slice(0,300) || ''")
        out["has_auth"] = driver.execute_script("""
try {
  const raw = localStorage.getItem('__oneme_auth');
  if (!raw || raw === 'null') return false;
  const o = JSON.parse(raw);
  return !!(o && o.token);
} catch (e) { return false; }
""")
        out["logged_out_check"] = driver.execute_script("""
try {
  const raw = localStorage.getItem('__oneme_auth');
  if (!raw || raw === 'null') return true;
  const o = JSON.parse(raw);
  return !o || !o.token;
} catch (e) { return true; }
""")
        shot = os.path.join(ROOT, "scripts", "full_launch_shot.png")
        page.screenshot(path=shot, full_page=True)
        out["screenshot"] = shot
    except Exception as ex:
        out["inspect_error"] = str(ex)
    return out


def main():
    from browser_launcher import launch_session, close_session, shutdown_playwright

    # свежий профиль для чистого теста
    fresh = PROFILE + "_fresh_test"
    if os.path.isdir(fresh):
        shutil.rmtree(fresh, ignore_errors=True)

    js = read_js()
    print("=== fresh profile ===")
    driver = launch_session(
        profiles_dir=PROFILES,
        session_name=SESSION + "_fresh_test",
        proxy_raw=PROXY,
        js=js,
        cdp_port=19299,
    )
    print("driver:", driver is not None)
    if driver:
        print(json.dumps(inspect(driver), ensure_ascii=False, indent=2))
        close_session(driver._mx_playwright_session)

    print("\n=== existing profile ===")
    driver2 = launch_session(
        profiles_dir=PROFILES,
        session_name=SESSION,
        proxy_raw=PROXY,
        js=js,
        cdp_port=19298,
    )
    print("driver:", driver2 is not None)
    if driver2:
        print(json.dumps(inspect(driver2), ensure_ascii=False, indent=2))
        close_session(driver2._mx_playwright_session)

    shutdown_playwright()


if __name__ == "__main__":
    main()
