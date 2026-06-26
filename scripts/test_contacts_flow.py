# -*- coding: utf-8 -*-
"""Тесты: контакты через вкладку «Контакты» → «Добавить контакт»."""
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
# Уже есть в адресной книге этого аккаунта
EXISTING_BOOK = "КОЗЛОВА ТАТЬЯНА ЮРЬЕВНА 17.07.1966"
UNKNOWN_PHONE = "79045765745"
TEST_DB = f"""Козлова Татьяна Юрьевна
17.07.1966
79000000001 тест
-------
"""


def save_report(report: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "contacts_flow_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def launch():
    from browser_launcher import launch_session

    js = open(os.path.join(ROOT, "sessions", SESSION), encoding="utf-8").read()
    t0 = time.time()
    driver = launch_session(
        profiles_dir=os.path.join(ROOT, "profiles"),
        session_name=SESSION + "_contacts_test",
        proxy_raw=PROXY,
        js=js,
        cdp_port=19297,
    )
    return driver, round(time.time() - t0, 1)


def ui(driver):
    from max_ui_actions import MaxUIActions

    return MaxUIActions(driver._mx_playwright_session.page, SESSION)


def test_contacts_tab(driver) -> dict:
    u = ui(driver)
    page = driver._mx_playwright_session.page
    ok = u.go_to_contacts()
    body = ""
    try:
        body = page.inner_text("body")[:200]
    except Exception:
        pass
    return {
        "test": "contacts_tab",
        "ok": ok and "Контакты" in body,
        "body_head": body,
    }


def test_open_add_form(driver) -> dict:
    u = ui(driver)
    page = driver._mx_playwright_session.page
    ok = u.open_add_contact_form()
    has_name = False
    try:
        has_name = page.locator('input[placeholder="Имя"]').first.is_visible(timeout=2000)
    except Exception:
        pass
    u._close_overlays()
    return {"test": "open_add_contact_form", "ok": ok and has_name}


def test_existing_contact(driver) -> dict:
    u = ui(driver)
    ok, detail = u.add_contact(EXISTING_BOOK)
    return {
        "test": "existing_contact_in_list",
        "ok": ok and ("найден" in detail or "уже есть" in detail),
        "detail": detail,
    }


def test_unknown_phone(driver) -> dict:
    u = ui(driver)
    book = "Тестов Тест Тестович 01.01.1990"
    ok, detail = u.add_contact(UNKNOWN_PHONE, save_as=book)
    low = detail.casefold()
    flow_ok = ok and any(x in low for x in ("добавлен", "сохранён", "уже есть")) or (
        not ok and any(x in low for x in ("не сохран", "не найден"))
    )
    return {
        "test": "unknown_phone_add",
        "ok": flow_ok,
        "detail": detail,
    }


def test_create_group_book_name(driver) -> dict:
    u = ui(driver)
    title = f"ТестКонт {datetime.now().strftime('%H%M%S')}"
    ok, detail = u.create_group(title, [EXISTING_BOOK])
    return {
        "test": "create_group_by_book_name",
        "ok": ok,
        "detail": detail,
        "title": title,
    }


def test_automation_engine(driver) -> dict:
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

    engine = AutomationEngine(driver, SESSION + "_contacts_test")
    state = engine.run_database_workflow()
    # номер тестовый — допускаем отказ на сохранении, но движок должен отработать без падения
    ok = state.error == "" or "не сохран" in (state.error or "").casefold()
    return {
        "test": "automation_contacts_workflow",
        "ok": ok,
        "error": state.error,
        "groups_created": state.groups_created,
        "contacts_added": state.contacts_added,
        "log": state.log,
    }


def main() -> int:
    report: dict = {"started": datetime.now().isoformat(), "session": SESSION, "tests": []}
    driver, launch_sec = launch()
    report["launch_sec"] = launch_sec
    if not driver:
        report["tests"].append({"test": "launch", "ok": False})
        save_report(report)
        return 1

    from max_ui_actions import MaxUIActions

    if not MaxUIActions(driver._mx_playwright_session.page, SESSION).wait_app_ready(120000):
        report["tests"].append({"test": "app_ready", "ok": False})
        save_report(report)
        return 1

    for fn in (
        test_contacts_tab,
        test_open_add_form,
        test_existing_contact,
        test_unknown_phone,
        test_create_group_book_name,
        test_automation_engine,
    ):
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
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
