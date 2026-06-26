# -*- coding: utf-8 -*-
"""Разведка UI вкладки «Контакты» в web.max.ru."""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OUT = os.path.join(ROOT, "scripts", "test_results")
SESSION = "+79273295162.txt"
PROXY = "proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0"
PHONE = "79045765745"
BOOK = "Тестов Тест Тестович 01.01.1990"


def dump_page(page, tag: str) -> str:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"probe_{tag}.png")
    page.screenshot(path=path, full_page=True)
    text_path = os.path.join(OUT, f"probe_{tag}.txt")
    try:
        body = page.inner_text("body")[:8000]
    except Exception as ex:
        body = str(ex)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(body)
    # buttons / links
    info = page.evaluate(
        """() => {
          const res = [];
          for (const el of document.querySelectorAll('button, a, [role="button"], [aria-label]')) {
            const t = (el.innerText || el.getAttribute('aria-label') || '').trim();
            if (!t || t.length > 80) continue;
            if (!res.includes(t)) res.push(t);
          }
          return res.slice(0, 80);
        }"""
    )
    with open(os.path.join(OUT, f"probe_{tag}_buttons.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(info))
    return path


def main() -> int:
    from browser_launcher import close_session, launch_session, shutdown_playwright

    js = open(os.path.join(ROOT, "sessions", SESSION), encoding="utf-8").read()
    d = launch_session(
        profiles_dir=os.path.join(ROOT, "profiles"),
        session_name=SESSION + "_probe",
        proxy_raw=PROXY,
        js=js,
        cdp_port=19295,
    )
    if not d:
        print("launch failed")
        return 1
    from max_ui_actions import MaxUIActions

    page = d._mx_playwright_session.page
    ui = MaxUIActions(page, SESSION + "_probe")
    if not ui.wait_app_ready(90000):
        dump_page(page, "not_ready")
        print("MAX not ready")
        close_session(d._mx_playwright_session)
        shutdown_playwright()
        return 1

    # bottom nav Контакты
    for sel in (
        '[aria-label="Контакты"]',
        'button:has-text("Контакты")',
        'nav button:has-text("Контакты")',
    ):
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=2000):
                loc.click()
                print("clicked", sel)
                break
        except Exception as ex:
            print("miss", sel, ex)
    time.sleep(2)
    dump_page(page, "contacts_tab")

    # try + in contacts
    for sel in (
        '[aria-label="Добавить"]',
        '[aria-label="Добавить контакт"]',
        'button:has-text("Добавить")',
        '[aria-label="Начать общение"]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1500):
                loc.click()
                print("plus", sel)
                time.sleep(1.5)
                dump_page(page, f"after_{sel.replace('[','').replace(']','')[:30]}")
                break
        except Exception as ex:
            print("plus miss", sel, ex)

    # inputs visible
    inputs = page.evaluate(
        """() => [...document.querySelectorAll('input')].filter(i => i.offsetParent).map(i => ({
          ph: i.placeholder, type: i.type, name: i.name
        }))"""
    )
    print("inputs", inputs)

    close_session(d._mx_playwright_session)
    shutdown_playwright()
    print("done, see", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
