"""Какие аргументы Chrome ломают загрузку."""
import os, sys, json, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from browser_launcher import _CHROME_ARGS, parse_playwright_proxy

PROXY = parse_playwright_proxy("proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0")


def try_launch(label, args, extra=None):
    from playwright.sync_api import sync_playwright
    prof = os.path.join(ROOT, "profiles", f"_args_{label}")
    extra = extra or {}
    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=prof,
                channel="chrome",
                headless=False,
                args=args,
                proxy=PROXY,
                ignore_https_errors=True,
                **extra,
            )
        except Exception as ex:
            return {"label": label, "launch_error": str(ex)[:200]}
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        t0 = time.time()
        try:
            page.goto("https://web.max.ru", wait_until="domcontentloaded", timeout=45000)
            ok = True
            err = ""
        except Exception as ex:
            ok = False
            err = str(ex)[:300]
        body = ""
        try:
            body = page.evaluate("document.body?.innerText?.length || 0")
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass
        return {"label": label, "ok": ok, "sec": round(time.time()-t0,1), "body_len": body, "error": err}


print(json.dumps(try_launch("full", list(_CHROME_ARGS) + ["--window-size=900,700"], {"ignore_default_args": ["--enable-automation"]}), ensure_ascii=False))
print(json.dumps(try_launch("minimal", ["--window-size=900,700"], {"ignore_default_args": ["--enable-automation"]}), ensure_ascii=False))
print(json.dumps(try_launch("antidetect", [
    "--disable-blink-features=AutomationControlled",
    "--window-size=900,700",
], {"ignore_default_args": ["--enable-automation"]}), ensure_ascii=False))
