"""Мост CRM ↔ Playwright: открытие чата, синхронизация, отправка."""

from __future__ import annotations

from typing import Any

from app_logger import get_logger
from browser_session import PlaywrightDriverAdapter, is_session_alive
from campaign_store import (
    STATUS_AWAITING,
    STATUS_REPLIED,
    ChatMessage,
    DialogRecord,
    append_messages,
    get_dialog,
    list_messages,
    update_dialog,
)
from max_ui_actions import MaxUIActions, is_ui_chrome_title

_log = get_logger("chat_bridge")


def _ui(driver: PlaywrightDriverAdapter) -> MaxUIActions:
    sess = driver._mx_playwright_session
    return MaxUIActions(sess.page, sess.session_name)


def resolve_chat_title(
    ui: MaxUIActions,
    group_title: str,
    *,
    chat_titles: list[str] | None = None,
) -> str:
    """Сопоставить сохранённое имя группы с заголовком в списке MAX."""
    title = (group_title or "").strip()
    if not title:
        return title
    needle = title.casefold()
    titles = chat_titles
    if titles is None:
        try:
            titles = ui.list_chat_titles(limit=120)
        except Exception:
            titles = []
    best = ""
    for item in titles or []:
        low = item.casefold()
        if low == needle:
            return item
        if needle in low or low in needle:
            if len(item) > len(best):
                best = item
    return best or title


def sync_dialog(
    session_dir: str,
    driver: PlaywrightDriverAdapter,
    dialog: DialogRecord,
    *,
    chat_titles: list[str] | None = None,
) -> tuple[int, str, bool]:
    """Синхронизировать сообщения. Третье значение: чат существует в MAX."""
    if is_ui_chrome_title(dialog.group_title):
        return 0, "служебная вкладка MAX, не чат", False
    if not is_session_alive(driver._mx_playwright_session):
        return 0, "сессия закрыта", True

    ui = _ui(driver)
    resolved = resolve_chat_title(
        ui, dialog.group_title, chat_titles=chat_titles
    )
    if not ui.open_group_chat(resolved):
        return 0, f"не открыт чат «{dialog.group_title}»", False

    if resolved != dialog.group_title:
        update_dialog(session_dir, dialog.id, group_title=resolved)
        dialog = get_dialog(session_dir, dialog.id) or dialog

    raw = ui.read_chat_messages()
    known = {(m.direction, m.text) for m in list_messages(session_dir, dialog.id)}
    new_items: list[ChatMessage] = []
    last_in = ""
    has_incoming = False

    for item in raw:
        direction = "out" if item.get("direction") == "out" else "in"
        text = str(item.get("text") or "").strip()
        if not text or (direction, text) in known:
            continue
        new_items.append(ChatMessage.create(dialog.id, direction, text))
        known.add((direction, text))
        if direction == "in":
            has_incoming = True
            last_in = text

    added = append_messages(session_dir, dialog.id, new_items)
    fields: dict[str, Any] = {}
    if new_items:
        last = new_items[-1]
        fields["last_message_text"] = last.text[:500]
        fields["last_message_dir"] = last.direction
    if has_incoming:
        fields["status"] = STATUS_REPLIED
        fields["unread"] = int(dialog.unread or 0) + sum(
            1 for m in new_items if m.direction == "in"
        )
    elif dialog.status == "sent":
        fields["status"] = STATUS_AWAITING

    if fields:
        update_dialog(session_dir, dialog.id, **fields)

    return added, last_in or f"+{added} сообщ.", True


def delete_group_in_max(
    driver: PlaywrightDriverAdapter,
    dialog: DialogRecord,
) -> tuple[bool, str]:
    if not is_session_alive(driver._mx_playwright_session):
        return False, "сессия закрыта"
    return _ui(driver).delete_group(dialog.group_title)


def send_message(
    session_dir: str,
    driver: PlaywrightDriverAdapter,
    dialog: DialogRecord,
    text: str,
) -> tuple[bool, str]:
    if not is_session_alive(driver._mx_playwright_session):
        return False, "сессия закрыта"

    ui = _ui(driver)
    resolved = resolve_chat_title(ui, dialog.group_title)
    ok, detail = ui.send_message(text, group_title=resolved)
    if not ok:
        return False, detail

    msg = ChatMessage.create(dialog.id, "out", text)
    append_messages(session_dir, dialog.id, [msg])
    update_dialog(
        session_dir,
        dialog.id,
        last_message_text=text[:500],
        last_message_dir="out",
        status=STATUS_AWAITING,
        unread=0,
    )
    return True, detail
