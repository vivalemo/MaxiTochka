# -*- coding: utf-8 -*-
"""Тесты CRM: store, bridge, send/sync через Playwright."""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
OUT = os.path.join(ROOT, "scripts", "test_results")
os.makedirs(OUT, exist_ok=True)

from test_suite_common import (
    DEFAULT_PROXY as PROXY,
    SESSIONS_DIR,
    load_session_js,
    load_test_config,
)

_cfg = load_test_config()
SESSION = str(_cfg.get("primary_session") or "79002673484.txt")
EXISTING_CONTACT = str(_cfg.get("existing_contact") or "КОЗЛОВА ТАТЬЯНА ЮРЬЕВНА 17.07.1966")


def test_store_roundtrip() -> dict:
    from campaign_store import (
        DialogRecord,
        ChatMessage,
        add_dialog,
        append_messages,
        list_dialogs,
        list_messages,
        load_store,
        _store_path,
    )

    test_sd = os.path.join(ROOT, "sessions", "_crm_unit_test")
    os.makedirs(test_sd, exist_ok=True)
    p = _store_path(test_sd)
    if os.path.isfile(p):
        os.remove(p)

    try:
        d = add_dialog(
            test_sd,
            DialogRecord.create(
                session_name=SESSION,
                group_title="CRM Test Group",
                lead_fio="Тест CRM",
                lead_phone="79000000000",
                lead_alias="Тест",
            ),
        )
        append_messages(
            test_sd,
            d.id,
            [ChatMessage.create(d.id, "out", "Привет из теста")],
        )
        dialogs = list_dialogs(test_sd, session_name=SESSION)
        msgs = list_messages(test_sd, d.id)
        ok = len(dialogs) >= 1 and len(msgs) == 1
        return {"test": "store", "ok": ok, "dialogs": len(dialogs), "messages": len(msgs)}
    finally:
        if os.path.isfile(p):
            os.remove(p)


def test_playwright_crm() -> dict:
    from browser_launcher import launch_session, close_session, shutdown_playwright
    from campaign_store import DialogRecord, add_dialog, list_messages, get_dialog
    from chat_bridge import send_message, sync_dialog
    from max_ui_actions import MaxUIActions

    js = load_session_js(SESSION)
    group_title = f"CRM тест {int(time.time()) % 100000}"

    driver = launch_session(
        profiles_dir=os.path.join(ROOT, "profiles"),
        session_name=SESSION + "_crm_test",
        proxy_raw=PROXY,
        js=js,
        cdp_port=19288,
    )
    if not driver:
        return {"test": "playwright_crm", "ok": False, "error": "launch failed"}

    result: dict = {"test": "playwright_crm", "steps": []}
    ui = MaxUIActions(driver._mx_playwright_session.page, SESSION)

    g_ok, g_detail = ui.create_group(group_title, [EXISTING_CONTACT])
    result["steps"].append({"create_group": g_ok, "detail": g_detail})

    dialog = add_dialog(
        SESSIONS_DIR,
        DialogRecord.create(
            session_name=SESSION + "_crm_test",
            group_title=group_title,
            lead_fio="CRM Тест",
            lead_phone="79000000001",
            lead_alias=EXISTING_CONTACT,
        ),
    )

    msg_text = f"CRM ping {int(time.time()) % 10000}"
    s_ok, s_detail = send_message(SESSIONS_DIR, driver, dialog, msg_text)
    result["steps"].append({"send": s_ok, "detail": s_detail})

    time.sleep(2)
    added, sync_info, _exists = sync_dialog(SESSIONS_DIR, driver, dialog)
    result["steps"].append({"sync": added, "info": sync_info})

    dialog = get_dialog(SESSIONS_DIR, dialog.id) or dialog
    msgs = list_messages(SESSIONS_DIR, dialog.id)
    out_texts = [m.text for m in msgs]
    result["messages"] = out_texts
    result["ok"] = g_ok and s_ok and msg_text in out_texts

    close_session(driver._mx_playwright_session)
    shutdown_playwright()
    return result


def test_coordinator() -> dict:
    from campaign_coordinator import plan_round_robin, summarize_plan
    from contact_database import ContactRecord

    sessions = [f"s{i}.txt" for i in range(10)]
    records = [ContactRecord(fio=f"Lead {i}", phones=[(f"790000000{i:02d}", "")]) for i in range(30)]
    plan = plan_round_robin(sessions, records)
    summary = summarize_plan(plan)
    ok = summary["total_assignments"] == 30 and summary["rounds"] == 3
    per = summary["per_session"]
    ok = ok and all(per.get(s) == 3 for s in sessions)
    return {"test": "coordinator", "ok": ok, "summary": summary}


def main() -> int:
    report = {"tests": []}
    for fn in (test_store_roundtrip, test_coordinator, test_playwright_crm):
        try:
            report["tests"].append(fn())
        except Exception as ex:
            report["tests"].append({"test": fn.__name__, "ok": False, "error": str(ex)})

    report["passed"] = sum(1 for t in report["tests"] if t.get("ok"))
    report["total"] = len(report["tests"])
    path = os.path.join(OUT, "crm_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
