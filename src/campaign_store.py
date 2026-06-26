"""Хранилище CRM: диалоги кампании и история сообщений."""

from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

_lock = threading.RLock()
_STORE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_AWAITING = "awaiting_reply"
STATUS_REPLIED = "replied"
STATUS_CLOSED = "closed"

STORE_FILENAME = "campaign_crm.json"


@dataclass
class ChatMessage:
    id: str
    dialog_id: str
    direction: str  # in | out
    text: str
    created_at: str

    @staticmethod
    def create(dialog_id: str, direction: str, text: str) -> ChatMessage:
        return ChatMessage(
            id=uuid.uuid4().hex[:12],
            dialog_id=dialog_id,
            direction=direction,
            text=text,
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )


@dataclass
class DialogRecord:
    id: str
    session_name: str
    lead_fio: str = ""
    lead_phone: str = ""
    lead_alias: str = ""
    group_title: str = ""
    status: str = STATUS_PENDING
    created_at: str = ""
    updated_at: str = ""
    last_message_text: str = ""
    last_message_dir: str = ""
    unread: int = 0
    campaign_id: str = "default"

    @property
    def display_name(self) -> str:
        if self.lead_fio:
            return self.lead_fio
        if self.lead_alias:
            return self.lead_alias
        return self.lead_phone or self.group_title or "?"

    @staticmethod
    def create(
        *,
        session_name: str,
        group_title: str,
        lead_fio: str = "",
        lead_phone: str = "",
        lead_alias: str = "",
        campaign_id: str = "default",
    ) -> DialogRecord:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        return DialogRecord(
            id=uuid.uuid4().hex[:12],
            session_name=session_name,
            lead_fio=lead_fio,
            lead_phone=lead_phone,
            lead_alias=lead_alias,
            group_title=group_title,
            status=STATUS_SENT,
            created_at=now,
            updated_at=now,
            campaign_id=campaign_id,
        )


@dataclass
class CampaignState:
    id: str = "default"
    name: str = "Кампания"
    lead_cursor: int = 0
    phase: str = "idle"  # idle | outreach | wait_replies | followup
    created_at: str = ""
    updated_at: str = ""


def _default_store() -> dict[str, Any]:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "version": 1,
        "campaign": asdict(CampaignState(created_at=now, updated_at=now)),
        "dialogs": [],
        "messages": [],
    }


def _store_path(session_dir: str) -> str:
    return os.path.join(session_dir or ".", STORE_FILENAME)


def load_store(session_dir: str) -> dict[str, Any]:
    path = _store_path(session_dir)
    with _lock:
        try:
            mtime = os.path.getmtime(path) if os.path.isfile(path) else -1.0
        except OSError:
            mtime = -1.0
        cached = _STORE_CACHE.get(path)
        if cached and cached[0] == mtime:
            return copy.deepcopy(cached[1])
        if not os.path.isfile(path):
            data = _default_store()
            _STORE_CACHE[path] = (-1.0, copy.deepcopy(data))
            return copy.deepcopy(data)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = _default_store()
            else:
                data.setdefault("dialogs", [])
                data.setdefault("messages", [])
                data.setdefault("campaign", asdict(CampaignState()))
            _STORE_CACHE[path] = (mtime, copy.deepcopy(data))
            return copy.deepcopy(data)
        except Exception:
            return _default_store()


def invalidate_store_cache(session_dir: str = "") -> None:
    with _lock:
        if not session_dir:
            _STORE_CACHE.clear()
            return
        _STORE_CACHE.pop(_store_path(session_dir), None)


def save_store(session_dir: str, data: dict[str, Any]) -> None:
    if not session_dir:
        return
    path = _store_path(session_dir)
    os.makedirs(session_dir, exist_ok=True)
    payload = copy.deepcopy(data)
    camp = payload.get("campaign") or {}
    if isinstance(camp, dict):
        camp["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        payload["campaign"] = camp
    with _lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        try:
            _STORE_CACHE[path] = (os.path.getmtime(path), copy.deepcopy(payload))
        except OSError:
            _STORE_CACHE.pop(path, None)


def _dialog_from_dict(raw: dict) -> DialogRecord:
    return DialogRecord(
        id=str(raw.get("id") or ""),
        session_name=str(raw.get("session_name") or ""),
        lead_fio=str(raw.get("lead_fio") or ""),
        lead_phone=str(raw.get("lead_phone") or ""),
        lead_alias=str(raw.get("lead_alias") or ""),
        group_title=str(raw.get("group_title") or ""),
        status=str(raw.get("status") or STATUS_PENDING),
        created_at=str(raw.get("created_at") or ""),
        updated_at=str(raw.get("updated_at") or ""),
        last_message_text=str(raw.get("last_message_text") or ""),
        last_message_dir=str(raw.get("last_message_dir") or ""),
        unread=int(raw.get("unread") or 0),
        campaign_id=str(raw.get("campaign_id") or "default"),
    )


def _message_from_dict(raw: dict) -> ChatMessage:
    return ChatMessage(
        id=str(raw.get("id") or ""),
        dialog_id=str(raw.get("dialog_id") or ""),
        direction=str(raw.get("direction") or "in"),
        text=str(raw.get("text") or ""),
        created_at=str(raw.get("created_at") or ""),
    )


def list_dialogs(
    session_dir: str,
    *,
    session_name: str | None = None,
    status: str | None = None,
    operator_order: bool = False,
) -> list[DialogRecord]:
    data = load_store(session_dir)
    out: list[DialogRecord] = []
    for raw in data.get("dialogs") or []:
        if not isinstance(raw, dict):
            continue
        rec = _dialog_from_dict(raw)
        if session_name and rec.session_name != session_name:
            continue
        if status and rec.status != status:
            continue
        out.append(rec)
    if operator_order:
        from crm_helpers import crm_tier

        out.sort(key=lambda d: d.updated_at or d.created_at or "", reverse=True)
        out.sort(key=crm_tier)
    else:
        out.sort(key=lambda d: d.updated_at or d.created_at, reverse=True)
    return out


def find_dialog(
    session_dir: str,
    *,
    session_name: str,
    group_title: str,
) -> DialogRecord | None:
    for d in list_dialogs(session_dir, session_name=session_name):
        if d.group_title == group_title:
            return d
    return None


def get_dialog(session_dir: str, dialog_id: str) -> DialogRecord | None:
    for rec in list_dialogs(session_dir):
        if rec.id == dialog_id:
            return rec
    return None


def add_dialog(session_dir: str, dialog: DialogRecord) -> DialogRecord:
    data = load_store(session_dir)
    dialogs = data.setdefault("dialogs", [])
    for raw in dialogs:
        if (
            isinstance(raw, dict)
            and raw.get("session_name") == dialog.session_name
            and raw.get("group_title") == dialog.group_title
        ):
            return _dialog_from_dict(raw)
    dialogs.append(asdict(dialog))
    save_store(session_dir, data)
    return dialog


def update_dialog(session_dir: str, dialog_id: str, **fields: Any) -> DialogRecord | None:
    data = load_store(session_dir)
    dialogs = data.get("dialogs") or []
    updated = None
    for raw in dialogs:
        if not isinstance(raw, dict) or raw.get("id") != dialog_id:
            continue
        raw.update(fields)
        raw["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        updated = _dialog_from_dict(raw)
        break
    if updated:
        save_store(session_dir, data)
    return updated


def list_messages(session_dir: str, dialog_id: str) -> list[ChatMessage]:
    data = load_store(session_dir)
    out: list[ChatMessage] = []
    for raw in data.get("messages") or []:
        if not isinstance(raw, dict) or raw.get("dialog_id") != dialog_id:
            continue
        out.append(_message_from_dict(raw))
    out.sort(key=lambda m: m.created_at)
    return out


def append_messages(
    session_dir: str,
    dialog_id: str,
    items: list[ChatMessage],
) -> int:
    if not items:
        return 0
    data = load_store(session_dir)
    messages = data.setdefault("messages", [])
    existing = {
        (m.get("dialog_id"), m.get("direction"), m.get("text"))
        for m in messages
        if isinstance(m, dict)
    }
    added = 0
    for msg in items:
        key = (msg.dialog_id, msg.direction, msg.text)
        if key in existing:
            continue
        messages.append(asdict(msg))
        existing.add(key)
        added += 1
    if added:
        save_store(session_dir, data)
    return added


def mark_read(session_dir: str, dialog_id: str) -> None:
    update_dialog(session_dir, dialog_id, unread=0)


def delete_dialog(session_dir: str, dialog_id: str) -> bool:
    """Удалить диалог и все его сообщения из CRM."""
    if not dialog_id:
        return False
    data = load_store(session_dir)
    dialogs = data.get("dialogs") or []
    new_dialogs = [
        raw
        for raw in dialogs
        if not (isinstance(raw, dict) and raw.get("id") == dialog_id)
    ]
    if len(new_dialogs) == len(dialogs):
        return False
    messages = data.get("messages") or []
    data["messages"] = [
        raw
        for raw in messages
        if not (isinstance(raw, dict) and raw.get("dialog_id") == dialog_id)
    ]
    data["dialogs"] = new_dialogs
    save_store(session_dir, data)
    return True


def dialog_stats(session_dir: str) -> dict[str, int]:
    dialogs = list_dialogs(session_dir)
    return {
        "total": len(dialogs),
        "awaiting": sum(1 for d in dialogs if d.status == STATUS_AWAITING),
        "replied": sum(1 for d in dialogs if d.status == STATUS_REPLIED),
        "unread": sum(int(d.unread or 0) for d in dialogs),
    }
