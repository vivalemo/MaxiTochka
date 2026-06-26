"""Движок автоматизации: база контактов, группы, общение."""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app_logger import get_logger
from automation_config import (
    get_active_script,
    group_name_for_record,
    load_automation_config,
    load_contact_records,
    pick_delay,
    post_group_steps_for_record,
)
from browser_session import PlaywrightDriverAdapter, is_session_alive
from campaign_coordinator import CampaignAssignment
from contact_database import ContactRecord
from lead_registry import release_claim, try_claim
from max_ui_actions import MaxUIActions

_log = get_logger("automation")


class StepKind(str, enum.Enum):
    SEND = "send"
    WAIT_REPLY = "wait_reply"
    DELAY = "delay"
    ADD_CONTACT = "add_contact"
    CREATE_GROUP = "create_group"


@dataclass
class StepResult:
    ok: bool
    detail: str = ""
    reply_text: str = ""


@dataclass
class RunState:
    session_name: str
    script_id: str
    step_index: int = 0
    record_index: int = 0
    last_incoming: str = ""
    groups_created: int = 0
    contacts_added: int = 0
    stopped: bool = False
    error: str = ""
    log: list[str] = field(default_factory=list)


NotifyFn = Callable[[str, str], None]


class AutomationEngine:
    def __init__(
        self,
        driver: PlaywrightDriverAdapter,
        session_name: str,
        *,
        notify: NotifyFn | None = None,
        session_dir: str = "",
        assignments: list[CampaignAssignment] | None = None,
    ) -> None:
        self._driver = driver
        self._session = driver._mx_playwright_session
        self._session_name = session_name
        self._session_dir = session_dir or ""
        self._notify = notify or (lambda _t, _c: None)
        self._cfg = load_automation_config()
        self._ui = MaxUIActions(self._session.page, session_name)
        self._state = RunState(
            session_name=session_name,
            script_id=str(self._cfg.get("active_script_id") or "database"),
        )
        self._stop = threading.Event()
        self._last_seen_messages: set[str] = set()
        self._sent_messages: set[str] = set()
        self._records = load_contact_records(self._cfg)
        self._record_cursor = int(self._cfg.get("database_start_index") or 0)
        self._assignments = assignments
        self._current_record: ContactRecord | None = None
        self._current_group_title: str = ""

    @property
    def state(self) -> RunState:
        return self._state

    def stop(self) -> None:
        self._stop.set()
        self._state.stopped = True

    def _log(self, msg: str) -> None:
        self._state.log.append(msg)
        _log.info("[%s] %s", self._session_name, msg)
        self._notify(f"[{self._session_name}] {msg}", "#6366f1")

    def _sleep(self, seconds: float) -> bool:
        end = time.time() + max(0.0, seconds)
        while time.time() < end:
            if self._stop.is_set():
                return False
            time.sleep(min(0.25, end - time.time()))
        return True

    def _limit_ok(self, kind: str) -> bool:
        if kind == "contact":
            mx = int(self._cfg.get("contacts_per_account_max") or 0)
            return mx <= 0 or self._state.contacts_added < mx
        if kind == "group":
            mx = int(self._cfg.get("groups_per_account_max") or 0)
            return mx <= 0 or self._state.groups_created < mx
        return True

    def _read_incoming_messages(self) -> list[str]:
        return self._ui.read_incoming_messages()

    @staticmethod
    def _is_real_reply(text: str, *, sent: set[str], ignore_own: bool) -> bool:
        msg = (text or "").strip()
        if not msg or len(msg) < 2:
            return False
        low = msg.casefold()
        for noise in (
            "вы создали чат",
            "чат готов",
            "обновление",
            "вступил в чат",
            "покинул чат",
        ):
            if noise in low:
                return False
        if ignore_own:
            for own in sent:
                if own and (own in msg or msg in own):
                    return False
        return True

    def _wait_for_reply(self, step: dict) -> StepResult:
        cfg = self._cfg.get("reply_wait") or {}
        poll = float(cfg.get("poll_interval_sec") or 5)
        timeout = float(step.get("timeout_sec") or cfg.get("default_timeout_sec") or 3600)
        match_mode = str(step.get("match") or "any").lower()
        keywords = [str(k).lower() for k in (step.get("keywords") or []) if str(k).strip()]
        deadline = time.time() + timeout

        ignore_own = bool(cfg.get("ignore_own_messages", True))
        self._log(f"Ожидание ответа до {int(timeout)} сек…")
        while time.time() < deadline:
            if self._stop.is_set():
                return StepResult(False, "остановлено")
            if not is_session_alive(self._session):
                return StepResult(False, "сессия закрыта")

            incoming = self._read_incoming_messages()
            fresh = [m for m in incoming if m not in self._last_seen_messages]
            for msg in fresh:
                self._last_seen_messages.add(msg)
                if not self._is_real_reply(
                    msg, sent=self._sent_messages, ignore_own=ignore_own
                ):
                    continue
                low = msg.lower()
                if match_mode == "any" or not keywords:
                    self._state.last_incoming = msg
                    self._crm_record_incoming(msg)
                    return StepResult(True, "ответ получен", reply_text=msg)
                if any(k in low for k in keywords):
                    self._state.last_incoming = msg
                    self._crm_record_incoming(msg)
                    return StepResult(True, "ответ по ключевым словам", reply_text=msg)
            if not self._sleep(poll):
                return StepResult(False, "остановлено")

        if bool(cfg.get("stop_on_timeout", True)):
            self.stop()
        return StepResult(False, "таймаут ожидания ответа")

    def _ui_send_message(self, text: str) -> StepResult:
        self._log(f"Отправка: {text[:80]}")
        if not self._sleep(pick_delay("before_message", self._cfg)):
            return StepResult(False, "остановлено")
        ok, detail = self._ui.send_message(text)
        if ok and text.strip():
            self._sent_messages.add(text.strip())
        return StepResult(ok, detail)

    def _ui_add_contact(
        self, phone: str, save_as: str = "", label: str = ""
    ) -> StepResult:
        if not self._limit_ok("contact"):
            return StepResult(False, "лимит контактов на аккаунт")
        display = save_as or label or phone
        self._log(f"Добавление в контакты: {display} (номер {phone})")
        if not self._sleep(pick_delay("before_contact", self._cfg)):
            return StepResult(False, "остановлено")
        ok, detail = self._ui.add_contact(phone, save_as=save_as or None)
        if ok:
            self._state.contacts_added += 1
            self._sleep(pick_delay("after_contact_added", self._cfg))
        return StepResult(ok, detail)

    def _ui_create_group(self, title: str, members: list[str]) -> StepResult:
        if not self._limit_ok("group"):
            return StepResult(False, "лимит групп на аккаунт")
        max_m = max(1, int(self._cfg.get("members_per_group_max") or 1))
        members = [m for m in members if m][:max_m]

        self._log(f"Группа «{title}» → участник: {', '.join(members)}")
        if not self._sleep(pick_delay("before_group_create", self._cfg)):
            return StepResult(False, "остановлено")
        ok, detail = self._ui.create_group(title, members)
        if ok:
            self._state.groups_created += 1
            self._sleep(pick_delay("after_group_create", self._cfg))
        return StepResult(ok, detail)

    def _run_step(self, step: dict) -> StepResult:
        kind = str(step.get("type") or "").lower()
        if kind == StepKind.SEND.value:
            return self._ui_send_message(str(step.get("text") or ""))
        if kind == StepKind.WAIT_REPLY.value:
            return self._wait_for_reply(step)
        if kind == StepKind.DELAY.value:
            sec = float(step.get("seconds") or pick_delay("before_message", self._cfg))
            ok = self._sleep(sec)
            return StepResult(ok, f"пауза {sec:.0f}с")
        return StepResult(False, f"неизвестный шаг: {kind}")

    def _process_one_record(self, record: ContactRecord, idx: int) -> StepResult:
        phone = record.primary_phone
        if not phone:
            return StepResult(False, f"нет телефона: {record.fio or '?'}")

        self._current_record = record
        self._state.record_index = idx
        self._log(f"── Запись {idx + 1}: {record.display_label()}")

        book_name = record.contact_book_name()
        if not book_name:
            return StepResult(False, f"нет имени для контакта: {record.fio or '?'}")

        r = self._ui_add_contact(phone, book_name, record.display_label())
        if not r.ok:
            return r

        for attempt in range(6):
            if self._stop.is_set():
                return StepResult(False, "остановлено")
            if self._ui._contact_visible_in_list(book_name):
                break
            self._log(
                f"Ожидание появления контакта в списке ({attempt + 1}/6)…"
            )
            if not self._sleep(3):
                return StepResult(False, "остановлено")

        title, self._cfg = group_name_for_record(
            record, idx, self._session_name, self._cfg
        )
        self._current_group_title = title
        self._log(f"В группу по имени: «{book_name}»")
        r = self._ui_create_group(title, [book_name])
        if not r.ok:
            return r

        try:
            from chat_bridge import resolve_chat_title

            resolved = resolve_chat_title(self._ui, title)
            if resolved:
                title = resolved
        except Exception:
            pass
        self._current_group_title = title
        self._register_crm_dialog(record, title)

        steps = post_group_steps_for_record(
            record, idx, self._session_name, self._cfg
        )
        if steps and steps[0].get("type") == "send":
            self._log(f"Первое сообщение: {str(steps[0].get('text') or '')[:80]}")
        for step in steps:
            if self._stop.is_set():
                return StepResult(False, "остановлено")
            if not isinstance(step, dict):
                continue
            r = self._run_step(step)
            if not r.ok:
                return r

        if not self._sleep(pick_delay("between_records", self._cfg)):
            return StepResult(False, "остановлено")
        return StepResult(True, "запись обработана")

    def _crm_record_incoming(self, text: str) -> None:
        if not self._session_dir or not self._current_group_title:
            return
        try:
            from campaign_store import (
                STATUS_REPLIED,
                ChatMessage,
                append_messages,
                find_dialog,
                update_dialog,
            )

            dialog = find_dialog(
                self._session_dir,
                session_name=self._session_name,
                group_title=self._current_group_title,
            )
            if not dialog:
                return
            msg = ChatMessage.create(dialog.id, "in", text)
            append_messages(self._session_dir, dialog.id, [msg])
            update_dialog(
                self._session_dir,
                dialog.id,
                status=STATUS_REPLIED,
                unread=int(dialog.unread or 0) + 1,
                last_message_text=text[:500],
                last_message_dir="in",
            )
        except Exception:
            _log.debug("crm incoming failed", exc_info=True)

    def _register_crm_dialog(self, record: ContactRecord, group_title: str) -> None:
        if not self._session_dir:
            return
        try:
            from campaign_store import STATUS_AWAITING, DialogRecord, add_dialog

            add_dialog(
                self._session_dir,
                DialogRecord.create(
                    session_name=self._session_name,
                    group_title=group_title,
                    lead_fio=record.fio,
                    lead_phone=record.primary_phone,
                    lead_alias=record.contact_book_name()
                    or record.primary_alias
                    or record.short_name,
                ),
            )
            from campaign_store import update_dialog, list_dialogs

            for d in list_dialogs(self._session_dir, session_name=self._session_name):
                if d.group_title == group_title:
                    update_dialog(self._session_dir, d.id, status=STATUS_AWAITING)
                    break
        except Exception:
            _log.debug("crm register failed", exc_info=True)

    def _records_to_process(self) -> list[tuple[ContactRecord, int]]:
        if self._assignments is not None:
            return [(a.record, a.record_index) for a in self._assignments]
        if not self._records:
            return []
        from campaign_coordinator import assignments_for_session, plan_round_robin

        plan = plan_round_robin(
            [self._session_name],
            self._records,
            self._record_cursor,
        )
        mine = assignments_for_session(plan, self._session_name)
        if mine:
            return [(a.record, a.record_index) for a in mine]
        return []

    def run_database_workflow(self) -> RunState:
        queue = self._records_to_process()
        if not queue:
            self._state.error = "база пуста — укажите файл или вставьте текст"
            self._notify(self._state.error, "#f43f5e")
            return self._state

        if self._assignments is not None:
            self._log(
                f"Очередь сессии: {len(queue)} лид(ов), "
                f"всего в базе {len(self._records)}"
            )
        else:
            self._log(f"Режим базы: {len(self._records)} записей, 1 группа = 1 контакт")
        if not self._ui.wait_app_ready():
            self._state.error = "MAX не загрузился"
            return self._state

        for n, (record, idx) in enumerate(queue, start=1):
            if self._stop.is_set():
                break
            if not self._limit_ok("group") or not self._limit_ok("contact"):
                self._log("Достигнут лимит на аккаунт")
                break
            if self._assignments is not None:
                self._log(f"Лид {n}/{len(queue)} (запись #{idx + 1})")

            phone = record.primary_phone
            claimed, owner = try_claim(phone, self._session_name)
            if not claimed:
                self._log(
                    f"Пропуск: лид уже у другой сессии ({owner}): "
                    f"{record.display_label()}"
                )
                continue

            result = self._process_one_record(record, idx)
            if not result.ok:
                release_claim(phone, self._session_name)

            if not result.ok:
                self._state.error = result.detail
                self._notify(f"{self._session_name}: {result.detail}", "#f43f5e")
                break
        else:
            self._log("Очередь сессии обработана")

        return self._state

    def run_script(self) -> RunState:
        mode = str(self._cfg.get("automation_mode") or "database").lower()
        if mode == "database" or bool(self._cfg.get("one_group_per_contact")):
            return self.run_database_workflow()

        script = get_active_script(self._cfg)
        steps = script.get("steps") or []
        self._log(f"Сценарий «{script.get('name', script.get('id'))}»")
        if not self._ui.wait_app_ready():
            self._state.error = "MAX не загрузился"
            return self._state

        for idx, step in enumerate(steps):
            if self._stop.is_set():
                break
            if not isinstance(step, dict):
                continue
            self._state.step_index = idx
            result = self._run_step(step)
            if not result.ok:
                self._state.error = result.detail
                self._notify(f"{self._session_name}: {result.detail}", "#f43f5e")
                break
        else:
            self._log("Сценарий завершён")
        return self._state


def run_for_session(
    driver: PlaywrightDriverAdapter,
    session_name: str,
    *,
    notify: NotifyFn | None = None,
) -> None:
    engine = AutomationEngine(driver, session_name, notify=notify)
    engine.run_script()
