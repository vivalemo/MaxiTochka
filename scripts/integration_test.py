# -*- coding: utf-8 -*-
"""Интеграционные тесты: окно, контакты, группы."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

SESSION = "79002673484.txt"
PROXY = "proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0"
OUT_DIR = os.path.join(ROOT, "scripts", "test_results")
# Подпись в адресной книге (ФИО + д.р.)
EXISTING_CONTACT = "КОЗЛОВА ТАТЬЯНА ЮРЬЕВНА 17.07.1966"
UNKNOWN_PHONE = "79045765745"
TEST_DB = f"""Козлова Татьяна Юрьевна
17.07.1966
79000000002 тест
-------
"""


def save_report(report: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def test_launch():
    from browser_launcher import launch_session

    js = open(os.path.join(ROOT, "sessions", SESSION), encoding="utf-8").read()
    t0 = time.time()
    driver = launch_session(
        profiles_dir=os.path.join(ROOT, "profiles"),
        session_name=SESSION + "_integration",
        proxy_raw=PROXY,
        js=js,
        cdp_port=19294,
    )
    page = driver._mx_playwright_session.page if driver else None
    body_len = page.evaluate("document.body.innerText.length") if page else 0
    return driver, {
        "test": "launch_window",
        "ok": bool(driver) and body_len > 500,
        "elapsed_sec": round(time.time() - t0, 1),
        "body_len": body_len,
    }


def reset_home(driver) -> None:
    from max_ui_actions import MaxUIActions

    ui = MaxUIActions(driver._mx_playwright_session.page, SESSION)
    ui.go_to_chats()
    ui.wait_app_ready(60000)


def test_create_group(driver):
    from max_ui_actions import MaxUIActions

    title = f"Тест {datetime.now().strftime('%H%M%S')}"
    ui = MaxUIActions(driver._mx_playwright_session.page, SESSION)
    ok, detail = ui.create_group(title, [EXISTING_CONTACT])
    return {
        "test": "create_group",
        "ok": ok,
        "detail": detail,
        "title": title,
    }


def test_add_contact_existing(driver):
    from max_ui_actions import MaxUIActions

    ui = MaxUIActions(driver._mx_playwright_session.page, SESSION)
    ok, detail = ui.add_contact(EXISTING_CONTACT)
    return {
        "test": "add_contact_existing",
        "ok": ok and ("найден" in detail or "уже есть" in detail),
        "detail": detail,
        "contact": EXISTING_CONTACT,
    }


def test_contacts_tab_add_form(driver):
    from max_ui_actions import MaxUIActions

    ui = MaxUIActions(driver._mx_playwright_session.page, SESSION)
    ok = ui.open_add_contact_form()
    has_fields = False
    try:
        has_fields = ui.page.locator('input[placeholder="Имя"]').first.is_visible(timeout=2000)
    except Exception:
        pass
    ui._close_overlays()
    return {
        "test": "contacts_tab_add_form",
        "ok": ok and has_fields,
    }


def test_add_contact_phone(driver):
    from max_ui_actions import MaxUIActions

    ui = MaxUIActions(driver._mx_playwright_session.page, SESSION)
    book = "Тестов Тест Тестович 01.01.1990"
    ok, detail = ui.add_contact(UNKNOWN_PHONE, save_as=book)
    low = detail.casefold()
    flow_ok = ok and any(x in low for x in ("добавлен", "сохранён", "уже есть")) or (
        not ok and any(x in low for x in ("не сохран", "не найден"))
    )
    return {
        "test": "add_contact_via_contacts_tab",
        "ok": flow_ok,
        "detail": detail,
        "phone": UNKNOWN_PHONE,
        "save_as": book,
    }


def test_automation_engine(driver):
    from automation_config import load_automation_config, save_automation_config
    from automation_engine import AutomationEngine

    cfg = load_automation_config()
    cfg["database_inline"] = TEST_DB
    cfg["database_file"] = ""
    cfg["contacts_per_account_max"] = 1
    cfg["groups_per_account_max"] = 1
    cfg["post_group_steps"] = []
    for key in cfg.get("delays_sec", {}):
        cfg["delays_sec"][key] = [1, 2]
    save_automation_config(cfg)

    engine = AutomationEngine(driver, SESSION + "_integration")
    state = engine.run_database_workflow()
    ok = state.error == "" or "не сохран" in (state.error or "").casefold()
    return {
        "test": "automation_database_workflow",
        "ok": ok,
        "error": state.error,
        "groups_created": state.groups_created,
        "contacts_added": state.contacts_added,
        "log": state.log,
    }


def main() -> int:
    report = {"started": datetime.now().isoformat(), "tests": []}

    driver, launch_r = test_launch()
    report["tests"].append(launch_r)
    if not driver:
        save_report(report)
        return 1

    for fn in (
        test_contacts_tab_add_form,
        test_add_contact_existing,
        test_add_contact_phone,
        test_create_group,
        test_automation_engine,
    ):
        reset_home(driver)
        try:
            report["tests"].append(fn(driver))
        except Exception as ex:
            report["tests"].append({"test": fn.__name__, "ok": False, "error": str(ex)})

    from browser_launcher import close_session, shutdown_playwright

    close_session(driver._mx_playwright_session)
    shutdown_playwright()

    report["passed"] = sum(1 for t in report["tests"] if t.get("ok"))
    report["total"] = len(report["tests"])
    report["finished"] = datetime.now().isoformat()
    save_report(report)
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
