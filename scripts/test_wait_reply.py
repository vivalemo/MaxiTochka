# -*- coding: utf-8 -*-
"""
Тест wait_reply: B создаёт группу с A, A пишет пинг и ждёт ответ лида от B.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from test_multi_crm import AccountWorker
from test_suite_common import (
    load_test_config,
    phone_from_session_file,
    save_json,
    session_exists,
)


def _pick_secondary(cfg: dict, primary: str) -> str:
    for fname in cfg.get("secondary_candidates") or []:
        if (
            fname
            and fname != primary
            and session_exists(str(fname))
            and phone_from_session_file(str(fname))
        ):
            return str(fname)
    sec = str(cfg.get("secondary_session") or "")
    return sec if session_exists(sec) and phone_from_session_file(sec) else ""


def test_wait_reply_live() -> dict:
    cfg = load_test_config()
    proxy = str(cfg.get("proxy") or "")
    sess_a = str(cfg.get("primary_session") or "79002673484.txt")
    sess_b = _pick_secondary(cfg, sess_a)

    result: dict[str, Any] = {
        "test": "wait_reply_live",
        "session_a": sess_a,
        "session_b": sess_b,
        "steps": [],
    }

    phone_a = phone_from_session_file(sess_a)
    phone_b = phone_from_session_file(sess_b)
    if not phone_a or not phone_b:
        result["ok"] = False
        result["skip"] = "нужны 2 аккаунта с телефоном в имени файла"
        return result

    stamp = int(time.time()) % 100000
    group_title = f"Reply test {stamp}"
    book_a = f"Аккаунт A {phone_a}"
    ping = f"Пинг {stamp}"
    reply_text = f"Ответ лида {stamp}"

    worker_a = AccountWorker(sess_a, "_reply_a", proxy, 19280)
    worker_b = AccountWorker(sess_b, "_reply_b", proxy, 19281)

    try:
        ok_a, _ = worker_a.start()
        time.sleep(15)
        ok_b, _ = worker_b.start()
        result["steps"].append({"launch_a": ok_a, "launch_b": ok_b})
        if not ok_a or not ok_b:
            result["ok"] = False
            result["skip"] = "не удалось запустить сессии"
            return result

        def b_setup(driver, _fname):
            from max_ui_actions import MaxUIActions

            ui = MaxUIActions(driver._mx_playwright_session.page, sess_b)
            if not ui.wait_app_ready(120000):
                return {"ready": False}
            ok_add, det_add = ui.add_contact(phone_a, save_as=book_a)
            time.sleep(5)
            ok_grp, det_grp = ui.create_group(group_title, [book_a])
            time.sleep(2)
            return {
                "ready": True,
                "add": ok_add,
                "group": ok_grp,
                "details": [det_add, det_grp],
            }

        ok, b_setup_res = worker_b.call("run", b_setup, timeout=240)
        result["steps"].append({"b_setup": b_setup_res if ok else b_setup_res})
        if not ok or not isinstance(b_setup_res, dict) or not b_setup_res.get("group"):
            result["ok"] = False
            result["error"] = "B не создал группу с A"
            return result

        time.sleep(5)

        wait_holder: list = []

        def _wait_thread():
            ok_w, res = worker_a.call("run", _a_ping_and_wait, timeout=180)
            wait_holder.append((ok_w, res))

        def _a_ping_and_wait(driver, _fname):
            from automation_engine import AutomationEngine

            ui = AutomationEngine(driver, sess_a)._ui
            if not ui.wait_app_ready(120000):
                return {"ready": False}
            ui.go_to_chats()
            time.sleep(1)
            if not ui.open_group_chat(group_title):
                return {"ready": False, "error": "чат не открыт"}

            ok_send, det_send = ui.send_message(ping)
            if not ok_send:
                return {"ready": False, "send": False, "detail": det_send}

            eng = AutomationEngine(driver, sess_a)
            eng._ui.open_group_chat(group_title)
            eng._sent_messages.add(ping)
            for noise in eng._read_incoming_messages():
                eng._last_seen_messages.add(noise)

            step = {
                "type": "wait_reply",
                "timeout_sec": 120,
                "match": "keywords",
                "keywords": [f"ответ лида {stamp}"],
            }
            r = eng._wait_for_reply(step)
            return {
                "ready": True,
                "send": ok_send,
                "wait_ok": r.ok,
                "detail": r.detail,
                "reply": r.reply_text,
            }

        def b_reply(driver, _fname):
            time.sleep(12)
            from max_ui_actions import MaxUIActions

            ui = MaxUIActions(driver._mx_playwright_session.page, sess_b)
            ok_send, det = ui.send_message(reply_text)
            if not ok_send:
                ui.go_to_chats()
                time.sleep(1)
                opened = ui.open_group_chat(group_title)
                ok_send, det = ui.send_message(
                    reply_text, group_title="" if opened else group_title
                )
                return {"opened": opened, "send": ok_send, "detail": det}
            return {"opened": True, "send": ok_send, "detail": det}

        t_wait = threading.Thread(target=_wait_thread, daemon=True)
        t_wait.start()
        time.sleep(4)
        ok_r, b_res = worker_b.call("run", b_reply, timeout=120)
        result["steps"].append({"b_reply": b_res if ok_r else b_res})
        t_wait.join(timeout=180)

        wait_result = wait_holder[0][1] if wait_holder else {"wait_ok": False}
        if wait_holder:
            result["steps"].append({"a_wait": wait_result})

        got_reply = bool(wait_result.get("wait_ok")) and reply_text.casefold() in str(
            wait_result.get("reply") or ""
        ).casefold()
        result["ok"] = got_reply
        result["ping"] = ping
        result["expected_reply"] = reply_text
        result["received"] = wait_result.get("reply")

    except Exception as ex:
        result["ok"] = False
        result["error"] = str(ex)
    finally:
        worker_a.stop()
        time.sleep(2)
        worker_b.stop()

    return result


def main() -> int:
    report = {"tests": [test_wait_reply_live()]}
    t = report["tests"][0]
    report["passed"] = 1 if t.get("ok") else 0
    report["total"] = 1
    save_json("wait_reply_report.json", report)
    if t.get("skip"):
        print("SKIP:", t["skip"])
        return 0
    print("OK" if t.get("ok") else "FAIL")
    print(t)
    return 0 if t.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
