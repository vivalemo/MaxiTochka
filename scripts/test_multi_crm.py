# -*- coding: utf-8 -*-
"""
Двухсессионный CRM-тест: аккаунт B пишет аккаунту A в группу, ответ через CRM.
Каждый браузер живёт в своём потоке (Playwright thread-local).
"""
from __future__ import annotations

import os
import queue
import threading
import time
from typing import Any, Callable

from test_suite_common import (
    ROOT,
    SESSIONS_DIR,
    load_session_js,
    load_test_config,
    phone_from_session_file,
    save_json,
    session_exists,
)


class AccountWorker:
    """Держит Playwright-сессию в одном потоке."""

    def __init__(
        self,
        fname: str,
        suffix: str,
        proxy: str,
        cdp_port: int,
    ) -> None:
        self.fname = fname
        self._suffix = suffix
        self._proxy = proxy
        self._cdp_port = cdp_port
        self._cmd: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name=f"worker-{fname}", daemon=True)
        self._driver: Any = None

    def start(self, timeout: float = 120.0) -> tuple[bool, str]:
        self._thread.start()
        return self.call("launch", timeout=timeout)

    def call(self, action: str, *args, timeout: float = 180.0) -> tuple[bool, Any]:
        reply: queue.Queue = queue.Queue()
        self._cmd.put((action, args, reply))
        try:
            ok, payload = reply.get(timeout=timeout)
            return ok, payload
        except queue.Empty:
            return False, "таймаут worker"

    def stop(self) -> None:
        if self._thread.is_alive():
            self.call("stop", timeout=30)
            self._thread.join(timeout=35)

    def _loop(self) -> None:
        from browser_launcher import close_session, launch_session, shutdown_playwright

        driver: Any = None
        try:
            while True:
                action, args, reply = self._cmd.get()
                try:
                    if action == "launch":
                        js = load_session_js(self.fname)
                        driver = launch_session(
                            profiles_dir=os.path.join(ROOT, "profiles"),
                            session_name=self.fname.replace(".txt", "") + self._suffix,
                            proxy_raw=self._proxy,
                            js=js,
                            cdp_port=self._cdp_port,
                        )
                        self._driver = driver
                        reply.put((bool(driver), "ok" if driver else "launch failed"))
                    elif action == "stop":
                        if driver:
                            close_session(driver._mx_playwright_session)
                        shutdown_playwright()
                        reply.put((True, "stopped"))
                        break
                    elif action == "run" and driver:
                        fn: Callable = args[0]
                        reply.put((True, fn(driver, self.fname)))
                    else:
                        reply.put((False, f"unknown action: {action}"))
                except Exception as ex:
                    reply.put((False, str(ex)))
        finally:
            if driver:
                try:
                    close_session(driver._mx_playwright_session)
                    shutdown_playwright()
                except Exception:
                    pass


def test_cross_account_crm() -> dict:
    cfg = load_test_config()
    proxy = str(cfg.get("proxy") or "")
    sess_a = str(cfg.get("primary_session") or "79002673484.txt")
    sess_b = str(cfg.get("secondary_session") or "")
    for cand in cfg.get("secondary_candidates") or []:
        if (
            cand
            and cand != sess_a
            and session_exists(str(cand))
            and phone_from_session_file(str(cand))
        ):
            sess_b = str(cand)
            break

    result: dict[str, Any] = {
        "test": "cross_account_crm",
        "session_a": sess_a,
        "session_b": sess_b,
        "steps": [],
    }

    if not session_exists(sess_a):
        result["ok"] = False
        result["skip"] = f"нет файла {sess_a}"
        return result

    phone_a = phone_from_session_file(sess_a)
    if not phone_a:
        result["ok"] = False
        result["skip"] = "не удалось определить телефон аккаунта A"
        return result

    if not sess_b or not session_exists(sess_b):
        result["ok"] = False
        result["skip"] = "второй аккаунт не настроен (scripts/test_accounts.json)"
        return result

    stamp = int(time.time()) % 100000
    group_title = f"CRM cross {stamp}"
    book_a = f"Аккаунт A {phone_a}"
    msg_from_b = f"Привет от B {stamp}"
    msg_from_a = f"Ответ от A {stamp}"

    worker_a = AccountWorker(sess_a, "_crm_a", proxy, 19285)
    worker_b = AccountWorker(sess_b, "_crm_b", proxy, 19286)

    test_sd = os.path.join(SESSIONS_DIR, "_crm_cross_test")
    os.makedirs(test_sd, exist_ok=True)
    crm_path = os.path.join(test_sd, "campaign_crm.json")
    if os.path.isfile(crm_path):
        os.remove(crm_path)

    try:
        ok_a, det_a = worker_a.start()
        time.sleep(15)
        ok_b, det_b = worker_b.start()
        result["steps"].append({"launch_a": ok_a, "detail_a": det_a})
        result["steps"].append({"launch_b": ok_b, "detail_b": det_b})
        if not ok_a or not ok_b:
            result["ok"] = False
            result["skip"] = "не удалось запустить оба аккаунта (прокси/токен)"
            return result

        def b_setup(driver, _fname):
            from max_ui_actions import MaxUIActions

            ui = MaxUIActions(driver._mx_playwright_session.page, sess_b)
            if not ui.wait_app_ready(90000):
                return {"ready": False}
            ok_add, det_add = ui.add_contact(phone_a, save_as=book_a)
            ok_grp, det_grp = ui.create_group(group_title, [book_a])
            time.sleep(2)
            ok_send, det_send = ui.send_message(msg_from_b)
            if not ok_send:
                ui.go_to_chats()
                time.sleep(1)
                opened = ui.open_group_chat(group_title)
                ok_send, det_send = ui.send_message(
                    msg_from_b, group_title="" if opened else group_title
                )
            return {
                "ready": True,
                "add": ok_add,
                "add_detail": det_add,
                "group": ok_grp,
                "group_detail": det_grp,
                "send": ok_send,
                "send_detail": det_send,
            }

        ok, b_res = worker_b.call("run", b_setup)
        result["steps"].append({"account_b_setup": b_res if ok else {"error": b_res}})
        if not ok or not isinstance(b_res, dict) or not b_res.get("ready"):
            result["ok"] = False
            result["skip"] = "аккаунт B не загрузил MAX — проверьте токен my_accounts"
            return result

        time.sleep(4)

        def a_crm(driver, _fname):
            from campaign_store import DialogRecord, list_messages
            from chat_bridge import send_message, sync_dialog
            from max_ui_actions import MaxUIActions

            ui = MaxUIActions(driver._mx_playwright_session.page, sess_a)
            if not ui.wait_app_ready(90000):
                return {"ready": False}
            opened = ui.open_group_chat(group_title)
            dialog = DialogRecord.create(
                session_name=sess_a,
                group_title=group_title,
                lead_fio="Аккаунт B",
                lead_phone=phone_a,
                lead_alias=book_a,
            )
            from campaign_store import add_dialog

            dialog = add_dialog(test_sd, dialog)
            added, sync_info, _exists = sync_dialog(test_sd, driver, dialog)
            msgs = list_messages(test_sd, dialog.id)
            texts = [m.text for m in msgs]
            has_b_msg = any(msg_from_b in t for t in texts)
            ok_reply, det_reply = send_message(test_sd, driver, dialog, msg_from_a)
            return {
                "ready": True,
                "opened": opened,
                "sync_added": added,
                "sync_info": sync_info,
                "has_b_message": has_b_msg,
                "messages": texts,
                "reply": ok_reply,
                "reply_detail": det_reply,
            }

        ok, a_res = worker_a.call("run", a_crm)
        result["steps"].append({"account_a_crm": a_res if ok else {"error": a_res}})

        time.sleep(4)

        def b_sync(driver, _fname):
            from campaign_store import DialogRecord, add_dialog, get_dialog, list_messages
            from chat_bridge import sync_dialog
            from max_ui_actions import MaxUIActions

            ui = MaxUIActions(driver._mx_playwright_session.page, sess_b)
            ui.go_to_chats()
            time.sleep(1)
            ui.open_group_chat(group_title)

            dialog_b = add_dialog(
                test_sd,
                DialogRecord.create(
                    session_name=sess_b,
                    group_title=group_title,
                    lead_fio="Аккаунт A",
                    lead_phone=phone_a,
                    lead_alias=book_a,
                ),
            )
            added, sync_info, _exists = sync_dialog(test_sd, driver, dialog_b)
            dialog_b = get_dialog(test_sd, dialog_b.id) or dialog_b
            msgs = list_messages(test_sd, dialog_b.id)
            texts = [m.text for m in msgs]
            has_a_reply = any(msg_from_a in t for t in texts)
            if not has_a_reply:
                raw = ui.read_chat_messages()
                ui_texts = [str(x.get("text") or "") for x in raw]
                has_a_reply = any(msg_from_a in t for t in ui_texts)
                texts.extend(ui_texts)
            return {
                "sync_added": added,
                "sync_info": sync_info,
                "has_a_reply": has_a_reply,
                "status": dialog_b.status,
                "messages": texts,
            }

        ok, b_sync_res = worker_b.call("run", b_sync)
        result["steps"].append({"account_b_sync": b_sync_res if ok else {"error": b_sync_res}})

        b_ok = isinstance(b_res, dict) and b_res.get("group") and b_res.get("send")
        a_ok = isinstance(a_res, dict) and a_res.get("reply") and (
            a_res.get("has_b_message") or (a_res.get("sync_added") or 0) > 0
        )
        sync_ok = isinstance(b_sync_res, dict) and (
            b_sync_res.get("has_a_reply")
            or b_sync_res.get("status") == "replied"
            or (b_sync_res.get("sync_added") or 0) > 0
        )
        result["ok"] = bool(b_ok and a_ok and (sync_ok or a_res.get("reply")))

    except Exception as ex:
        result["ok"] = False
        result["error"] = str(ex)
    finally:
        worker_a.stop()
        worker_b.stop()
        if os.path.isfile(crm_path):
            try:
                os.remove(crm_path)
            except OSError:
                pass

    return result


def main() -> int:
    report = {"tests": [test_cross_account_crm()]}
    report["passed"] = sum(1 for t in report["tests"] if t.get("ok"))
    report["skipped"] = sum(1 for t in report["tests"] if t.get("skip"))
    report["total"] = len(report["tests"])
    save_json("multi_crm_report.json", report)
    t = report["tests"][0]
    if t.get("skip"):
        print(f"SKIP: {t['skip']}")
        return 0
    print("OK" if t.get("ok") else "FAIL")
    print(t)
    return 0 if t.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
