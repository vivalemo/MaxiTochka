# -*- coding: utf-8 -*-
"""Полный тест синхронизации CRM: запуск токена → import → sync_all."""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from test_suite_common import (
    DEFAULT_PROXY,
    SESSIONS_DIR,
    load_session_js,
    load_test_config,
    save_json,
    session_exists,
)


class _FakeWindow:
    """Минимальный объект окна для crm_service."""

    def __init__(self, session_dir: str, active_drivers: dict) -> None:
        self.session_dir = session_dir
        self.active_drivers = active_drivers
        self._automation_running = False


def _pick_session() -> str:
    cfg = load_test_config()
    for cand in [cfg.get("secondary_session")] + list(
        cfg.get("secondary_candidates") or []
    ) + [cfg.get("primary_session")]:
        s = str(cand or "").strip()
        if s and session_exists(s):
            return s
    return ""


def _progress_log(steps: list) -> callable:
    def _cb(phase: str, cur: int, total: int, detail: str) -> None:
        line = f"{phase} {cur}/{total}: {detail}"
        print(f"  … {line}")
        steps.append(line)

    return _cb


def test_full_manual_sync() -> dict:
    from browser_launcher import close_session, launch_session, shutdown_playwright
    from campaign_store import dialog_stats, list_dialogs
    from crm_service import run_manual_sync
    from max_ui_actions import MaxUIActions

    session = _pick_session()
    if not session:
        return {"test": "full_manual_sync", "ok": False, "skip": "no session file"}

    js = load_session_js(session)
    launch_name = session + "_full_sync_test"
    driver = launch_session(
        profiles_dir=os.path.join(ROOT, "profiles"),
        session_name=launch_name,
        proxy_raw=DEFAULT_PROXY,
        js=js,
        cdp_port=19293,
    )
    if not driver:
        return {"test": "full_manual_sync", "ok": False, "error": "launch failed"}

    test_sd = os.path.join(SESSIONS_DIR, "_full_sync_test")
    os.makedirs(test_sd, exist_ok=True)
    store_path = os.path.join(test_sd, "campaign_crm.json")
    if os.path.isfile(store_path):
        os.remove(store_path)

    steps: list[str] = []
    t0 = time.time()
    try:
        ui = MaxUIActions(driver._mx_playwright_session.page, session)
        if not ui.wait_app_ready():
            return {"test": "full_manual_sync", "ok": False, "error": "MAX not ready"}

        titles_before = ui.list_chat_titles(limit=10)
        window = _FakeWindow(test_sd, {launch_name: driver})

        print(f"[sync] токен {session}, чатов в MAX: {len(titles_before)}")
        result = run_manual_sync(window, on_progress=_progress_log(steps))

        dialogs = list_dialogs(test_sd, session_name=launch_name)
        stats = dialog_stats(test_sd)
        elapsed = round(time.time() - t0, 1)

        ok = (
            len(titles_before) >= 1
            and len(dialogs) >= 1
            and not result.get("errors")
        )
        return {
            "test": "full_manual_sync",
            "ok": ok,
            "session": session,
            "launch_name": launch_name,
            "titles_in_max": len(titles_before),
            "titles_sample": titles_before[:5],
            "imported": result.get("imported", 0),
            "synced_chats": result.get("synced", 0),
            "added_messages": result.get("added", 0),
            "dialogs_in_crm": len(dialogs),
            "stats": stats,
            "errors": result.get("errors") or [],
            "elapsed_sec": elapsed,
            "progress_steps": steps[-12:],
        }
    finally:
        close_session(driver._mx_playwright_session)
        shutdown_playwright()
        if os.path.isfile(store_path):
            os.remove(store_path)


def main() -> int:
    print("=== full CRM sync flow ===")
    try:
        report = test_full_manual_sync()
    except Exception as ex:
        report = {"test": "full_manual_sync", "ok": False, "error": str(ex)}

    save_json("full_sync_report.json", report)
    mark = "OK" if report.get("ok") else "FAIL"
    print(f"\n{mark}: {report.get('test')}")
    if report.get("error") or report.get("skip"):
        print(f"  {report.get('error') or report.get('skip')}")
    else:
        print(
            f"  импорт +{report.get('imported', 0)} · "
            f"sync {report.get('synced_chats', 0)} чатов · "
            f"+{report.get('added_messages', 0)} сообщ. · "
            f"CRM: {report.get('dialogs_in_crm', 0)} диалогов · "
            f"{report.get('elapsed_sec', '?')} сек"
        )
        if report.get("errors"):
            print(f"  ошибки: {report['errors'][:5]}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
