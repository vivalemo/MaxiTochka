"""Минимальный тест Playwright + Chrome."""
import os, sys, time, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

PROXY = {"server": "http://proxy.proxyma.io:10062", "username": "mUjWhsclWb", "password": "OHVx4PCwZ0"}


def run(label, **ctx_kw):
    from playwright.sync_api import sync_playwright
    prof = os.path.join(ROOT, "profiles", f"_min_{label}")
    os.makedirs(prof, exist_ok=True)
    out = {"label": label}
    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(user_data_dir=prof, channel="chrome", headless=False, **ctx_kw)
        except Exception as ex:
            return {**out, "launch_error": str(ex)}
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            resp = page.goto("https://web.max.ru", wait_until="domcontentloaded", timeout=90000)
            out["status"] = resp.status if resp else None
            out["url"] = page.url
            time.sleep(3)
            out["title"] = page.title()
            out["body"] = page.evaluate("document.body?.innerText?.slice(0,200) || ''")
        except Exception as ex:
            out["goto_error"] = str(ex)
        try:
            ctx.close()
        except Exception:
            pass
    return out


cases = [
    ("bare", {}),
    ("proxy", {"proxy": PROXY}),
    ("ignore_https", {"ignore_https_errors": True}),
    ("proxy_https", {"proxy": PROXY, "ignore_https_errors": True}),
    ("no_automation", {"ignore_default_args": ["--enable-automation"]}),
]

for label, kw in cases:
    print(json.dumps(run(label, **kw), ensure_ascii=False))
