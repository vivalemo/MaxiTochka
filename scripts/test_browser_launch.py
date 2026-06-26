"""Диагностика запуска web.max.ru через Playwright."""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

PROXY = "proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0"
SESSION = "+79273295162.txt"
PROFILE_TEST = os.path.join(ROOT, "profiles", "_test_launch_diag")


def load_session_js() -> str:
    path = os.path.join(ROOT, "sessions", SESSION)
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    from sessions_meta import sanitize_session_js

    return sanitize_session_js(raw)


def check_proxy_requests() -> dict:
    import requests

    host, port, user, pwd = PROXY.split(":", 3)
    proxies = {"http": f"http://{user}:{pwd}@{host}:{port}", "https": f"http://{user}:{pwd}@{host}:{port}"}
    out = {}
    for url in ("https://api.ipify.org?format=json", "https://web.max.ru/"):
        try:
            r = requests.get(url, proxies=proxies, timeout=30, verify=False)
            out[url] = {"status": r.status_code, "len": len(r.content), "snippet": r.text[:120]}
        except Exception as ex:
            out[url] = {"error": str(ex)}
    return out


def test_playwright(*, use_proxy: bool, inject_token: bool) -> dict:
    from browser_launcher import parse_playwright_proxy, _CHROME_ARGS
    from playwright.sync_api import sync_playwright

    os.makedirs(PROFILE_TEST, exist_ok=True)
    js = load_session_js() if inject_token else ""
    result: dict = {"use_proxy": use_proxy, "inject_token": inject_token}

    with sync_playwright() as pw:
        kwargs = {
            "user_data_dir": PROFILE_TEST + ("_proxy" if use_proxy else "_direct"),
            "channel": "chrome",
            "headless": False,
            "args": list(_CHROME_ARGS) + ["--window-size=900,700"],
            "ignore_default_args": ["--enable-automation"],
            "ignore_https_errors": True,
            "locale": "ru-RU",
        }
        if use_proxy:
            kwargs["proxy"] = parse_playwright_proxy(PROXY)

        t0 = time.time()
        try:
            ctx = pw.chromium.launch_persistent_context(**kwargs)
        except Exception as ex:
            result["launch_error"] = str(ex)
            return result

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        result["launch_sec"] = round(time.time() - t0, 2)

        nav_errors = []
        for wait in ("commit", "domcontentloaded", "load"):
            t1 = time.time()
            try:
                page.goto("https://web.max.ru", wait_until=wait, timeout=60000)
                result[f"goto_{wait}"] = {"ok": True, "sec": round(time.time() - t1, 2), "url": page.url}
                break
            except Exception as ex:
                nav_errors.append(f"{wait}: {ex}")
        if nav_errors and not any(k.startswith("goto_") for k in result):
            result["goto_errors"] = nav_errors

        if inject_token and js.strip():
            try:
                page.evaluate(js)
                page.reload(wait_until="domcontentloaded", timeout=60000)
                result["token_injected"] = True
            except Exception as ex:
                result["token_error"] = str(ex)

        time.sleep(5)
        try:
            result["final_url"] = page.url
            result["title"] = page.title()
            result["ready"] = page.evaluate("document.readyState")
            result["body_len"] = page.evaluate(
                "document.body ? document.body.innerText.length : -1"
            )
            result["has_auth"] = page.evaluate(
                """() => {
                  try {
                    const r = localStorage.getItem('__oneme_auth');
                    if (!r) return false;
                    const o = JSON.parse(r);
                    return !!(o && o.token);
                  } catch(e) { return false; }
                }"""
            )
            shot = os.path.join(ROOT, "scripts", f"shot_{'proxy' if use_proxy else 'direct'}.png")
            page.screenshot(path=shot, full_page=True)
            result["screenshot"] = shot
        except Exception as ex:
            result["inspect_error"] = str(ex)

        try:
            ctx.close()
        except Exception:
            pass

    return result


def main() -> None:
    print("=== requests через прокси ===")
    print(json.dumps(check_proxy_requests(), ensure_ascii=False, indent=2))

    for use_proxy in (False, True):
        for inject in (False, True):
            label = f"proxy={use_proxy} token={inject}"
            print(f"\n=== Playwright {label} ===")
            try:
                r = test_playwright(use_proxy=use_proxy, inject_token=inject)
                print(json.dumps(r, ensure_ascii=False, indent=2))
            except Exception as ex:
                print(f"FAIL {label}: {ex}")
            if not use_proxy and not inject:
                break  # direct без токена достаточно для базовой проверки
        if not use_proxy:
            break


if __name__ == "__main__":
    main()
