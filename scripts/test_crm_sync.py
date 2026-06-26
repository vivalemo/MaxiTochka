# -*- coding: utf-8 -*-
"""Тест синхронизации CRM: импорт чатов, sync, list_chat_titles."""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
OUT = os.path.join(ROOT, "scripts", "test_results")
os.makedirs(OUT, exist_ok=True)

from test_suite_common import (
    DEFAULT_PROXY,
    SESSIONS_DIR,
    load_session_js,
    load_test_config,
    save_json,
    session_exists,
)


def _pick_session() -> str:
    cfg = load_test_config()
    for cand in [cfg.get("primary_session"), cfg.get("secondary_session")] + list(
        cfg.get("secondary_candidates") or []
    ):
        s = str(cand or "").strip()
        if s and session_exists(s):
            return s
    return ""


def test_list_chats() -> dict:
    from browser_launcher import close_session, launch_session, shutdown_playwright
    from max_ui_actions import MaxUIActions

    session = _pick_session()
    if not session:
        return {"test": "list_chats", "ok": False, "skip": "no session file"}

    js = load_session_js(session)
    driver = launch_session(
        profiles_dir=os.path.join(ROOT, "profiles"),
        session_name=session + "_crm_sync_test",
        proxy_raw=DEFAULT_PROXY,
        js=js,
        cdp_port=19290,
    )
    if not driver:
        return {"test": "list_chats", "ok": False, "error": "launch failed"}

    try:
        ui = MaxUIActions(driver._mx_playwright_session.page, session)
        ready = ui.wait_app_ready()
        titles = ui.list_chat_titles(limit=40) if ready else []
        return {
            "test": "list_chats",
            "ok": ready and len(titles) >= 1,
            "session": session,
            "ready": ready,
            "titles_count": len(titles),
            "titles_sample": titles[:8],
        }
    finally:
        close_session(driver._mx_playwright_session)
        shutdown_playwright()


def test_sync_roundtrip() -> dict:
    from browser_launcher import close_session, launch_session, shutdown_playwright
    from campaign_store import DialogRecord, add_dialog, get_dialog, list_messages
    from chat_bridge import resolve_chat_title, send_message, sync_dialog
    from max_ui_actions import MaxUIActions

    session = _pick_session()
    if not session:
        return {"test": "sync_roundtrip", "ok": False, "skip": "no session"}

    contact = str(load_test_config().get("existing_contact") or "")
    if not contact:
        return {"test": "sync_roundtrip", "ok": False, "skip": "no existing_contact"}

    js = load_session_js(session)
    test_name = session + "_crm_sync_rt"
    driver = launch_session(
        profiles_dir=os.path.join(ROOT, "profiles"),
        session_name=test_name,
        proxy_raw=DEFAULT_PROXY,
        js=js,
        cdp_port=19291,
    )
    if not driver:
        return {"test": "sync_roundtrip", "ok": False, "error": "launch failed"}

    test_sd = os.path.join(SESSIONS_DIR, "_crm_sync_test")
    os.makedirs(test_sd, exist_ok=True)
    store_path = os.path.join(test_sd, "campaign_crm.json")
    if os.path.isfile(store_path):
        os.remove(store_path)

    try:
        ui = MaxUIActions(driver._mx_playwright_session.page, session)
        if not ui.wait_app_ready():
            return {"test": "sync_roundtrip", "ok": False, "error": "MAX not ready"}

        group_title = ""
        g_ok = False
        g_detail = ""
        titles = ui.list_chat_titles(limit=30)
        for candidate in titles:
            if ui.open_group_chat(candidate):
                group_title = candidate
                g_ok = True
                ui.go_to_chats()
                break
        if not g_ok:
            group_title = f"CRM sync {int(time.time()) % 100000}"
            g_ok, g_detail = ui.create_group(group_title, [contact])
        if not g_ok or not group_title:
            return {
                "test": "sync_roundtrip",
                "ok": False,
                "error": g_detail or "no openable chat",
                "session": session,
                "titles": titles[:10],
            }

        resolved = resolve_chat_title(ui, group_title)
        dialog = add_dialog(
            test_sd,
            DialogRecord.create(
                session_name=test_name,
                group_title=group_title,
                lead_alias=contact or group_title,
            ),
        )

        msg = f"sync_test_{int(time.time()) % 100000}"
        s_ok, s_detail = send_message(test_sd, driver, dialog, msg)
        time.sleep(1.5)
        added, sync_info, exists = sync_dialog(test_sd, driver, dialog)
        msgs = [m.text for m in list_messages(test_sd, dialog.id)]
        dialog = get_dialog(test_sd, dialog.id) or dialog

        ok = exists and s_ok and msg in msgs
        return {
            "test": "sync_roundtrip",
            "ok": ok,
            "session": session,
            "group": group_title,
            "resolved": resolved,
            "create_group": g_ok,
            "send": s_ok,
            "send_detail": s_detail,
            "sync_added": added,
            "sync_info": sync_info,
            "exists": exists,
            "messages": msgs[-5:],
            "status": dialog.status,
        }
    finally:
        close_session(driver._mx_playwright_session)
        shutdown_playwright()
        if os.path.isfile(store_path):
            os.remove(store_path)


def main() -> int:
    tests = []
    for fn in (test_list_chats, test_sync_roundtrip):
        try:
            tests.append(fn())
        except Exception as ex:
            tests.append({"test": fn.__name__, "ok": False, "error": str(ex)})

    report = {
        "suite": "crm_sync",
        "passed": sum(1 for t in tests if t.get("ok")),
        "total": len(tests),
        "tests": tests,
    }
    save_json("crm_sync_report.json", report)
    for t in tests:
        mark = "OK" if t.get("ok") else "FAIL"
        print(f"{mark}: {t.get('test')} {t.get('error') or t.get('skip') or ''}")
    print(f"\n{report['passed']}/{report['total']} passed")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
