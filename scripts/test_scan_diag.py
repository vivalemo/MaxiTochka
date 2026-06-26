# -*- coding: utf-8 -*-
"""Диагностика сканирования списка чатов MAX."""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from test_suite_common import DEFAULT_PROXY, load_session_js, save_json

SESSION = "+79148173538__КОММЕНТАРИЙ(1м)_стал.txt"


def main() -> int:
    from browser_launcher import close_session, launch_session, shutdown_playwright
    from max_ui_actions import MaxUIActions

    js = load_session_js(SESSION)
    driver = launch_session(
        profiles_dir=os.path.join(ROOT, "profiles"),
        session_name=SESSION + "_scan_diag",
        proxy_raw=DEFAULT_PROXY,
        js=js,
        cdp_port=19292,
    )
    if not driver:
        print("launch failed")
        return 1

    page = driver._mx_playwright_session.page
    ui = MaxUIActions(page, SESSION)
    try:
        ready = ui.wait_app_ready()
        ui.go_to_chats()
        time.sleep(2.5)

        diag = page.evaluate(
            """() => {
              const info = { url: location.href, title: document.title };
              const selCounts = {};
              for (const s of [
                '[class*="chat-list"]', '[class*="dialogs"]', '[class*="ChatList"]',
                '[class*="ChatItem"]', '[role="listitem"]', '[class*="sidebar"]'
              ]) {
                selCounts[s] = document.querySelectorAll(s).length;
              }
              info.selCounts = selCounts;
              info.buttons_sample = [...document.querySelectorAll('button,[role=button]')]
                .slice(0, 40)
                .map(b => (b.innerText || '').trim().split('\\n')[0].slice(0, 60));
              const sidebar = document.querySelector('[class*="sidebar"]');
              info.sidebar_text = sidebar ? (sidebar.innerText || '').slice(0, 1200) : '';
              return info;
            }"""
        )

        raw_nodes = page.evaluate(
            """() => {
              const nodes = document.querySelectorAll(
                '[class*="chat-list"] button, [class*="dialogs"] button, '
                + '[class*="ChatList"] button, [class*="ChatItem"], '
                + '[class*="dialog"] button, [role="listitem"] button, '
                + '[class*="sidebar"] [role="button"]'
              );
              return [...nodes].slice(0, 20).map(n => (n.innerText || '').trim().slice(0, 100));
            }"""
        )

        titles = ui.list_chat_titles(limit=40)
        report = {
            "session": SESSION,
            "ready": ready,
            "titles_count": len(titles),
            "titles": titles[:20],
            "raw_nodes": raw_nodes,
            "diag": diag,
        }
        save_json("scan_diag_report.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        close_session(driver._mx_playwright_session)
        shutdown_playwright()


if __name__ == "__main__":
    raise SystemExit(main())
