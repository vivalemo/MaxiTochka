"""Форматирование списка CRM и подписи токенов."""

from __future__ import annotations

import os
import re

from campaign_store import STATUS_AWAITING, STATUS_REPLIED, DialogRecord

_PHONE_IN_NAME = re.compile(r"(\+?7\d{10})")


def phone_from_session_file(fname: str) -> str:
    base = os.path.basename(fname or "").replace(".txt", "")
    m = _PHONE_IN_NAME.search(base)
    if not m:
        return ""
    digits = re.sub(r"\D", "", m.group(1))
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def format_token_label(session_name: str) -> str:
    phone = phone_from_session_file(session_name)
    if phone:
        return f"+{phone}"
    base = os.path.basename(session_name or "").replace(".txt", "")
    if len(base) > 22:
        return base[:19] + "…"
    return base or "?"


def contact_label(dialog: DialogRecord) -> str:
    if dialog.lead_alias:
        return dialog.lead_alias.strip()
    if dialog.lead_fio:
        return dialog.lead_fio.strip()
    if dialog.lead_phone:
        return dialog.lead_phone.strip()
    return dialog.group_title or "?"


def format_chat_row(dialog: DialogRecord) -> str:
    """Строка чата под сессией (без токена)."""
    contact = contact_label(dialog)
    if dialog.status == STATUS_REPLIED:
        badge = "● Ответил"
        if int(dialog.unread or 0) > 0:
            badge += f" ({dialog.unread})"
        return f"{badge} — {contact}"
    if dialog.status == STATUS_AWAITING:
        return f"○ Ждём — {contact}"
    return contact


def format_session_row(session_name: str, chat_count: int) -> str:
    token = format_token_label(session_name)
    short = os.path.basename(session_name or "").replace(".txt", "")
    if len(short) > 28:
        short = short[:25] + "…"
    if token != short and short:
        return f"{token}  ·  {short}  ({chat_count})"
    return f"{token}  ({chat_count})"


def group_dialogs_by_session(
    dialogs: list[DialogRecord],
) -> list[tuple[str, list[DialogRecord]]]:
    buckets: dict[str, list[DialogRecord]] = {}
    for d in dialogs:
        buckets.setdefault(d.session_name, []).append(d)
    for chats in buckets.values():
        chats.sort(
            key=lambda x: (
                crm_tier(x),
                x.updated_at or x.created_at or "",
            )
        )
        chats.reverse()
    return sorted(
        buckets.items(),
        key=lambda item: format_token_label(item[0]),
    )


def format_dialog_row(dialog: DialogRecord) -> str:
    """Строка списка: токен · контакт [метка ответа]."""
    token = format_token_label(dialog.session_name)
    contact = contact_label(dialog)
    if dialog.status == STATUS_REPLIED:
        badge = "● Ответил"
        if int(dialog.unread or 0) > 0:
            badge += f" ({dialog.unread})"
        return f"{badge}  {token}  ·  {contact}"
    if dialog.status == STATUS_AWAITING:
        return f"○ Ждём  {token}  ·  {contact}"
    return f"{token}  ·  {contact}"


def crm_tier(dialog: DialogRecord) -> int:
    """Меньше = выше в списке оператора."""
    unread = int(dialog.unread or 0)
    if dialog.status == STATUS_REPLIED and unread > 0:
        return 0
    if dialog.status == STATUS_REPLIED:
        return 1
    if dialog.status == STATUS_AWAITING:
        return 2
    return 3
