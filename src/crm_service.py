"""Сервис CRM: синхронизация всех диалогов, отправка, опрос."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Callable

ProgressFn = Callable[[str, int, int, str], None]

from app_logger import get_logger
from campaign_store import (
    STATUS_AWAITING,
    STATUS_REPLIED,
    DialogRecord,
    delete_dialog,
    dialog_stats,
    get_dialog,
    list_dialogs,
    mark_read,
)
from browser_launcher import resolve_driver
from browser_session import is_session_alive
from crm_filter import dialog_matches_keyword, get_crm_keyword, title_matches_keyword
from max_ui_actions import MaxUIActions, is_ui_chrome_title
from chat_bridge import delete_group_in_max
from chat_bridge import send_message as bridge_send
from chat_bridge import sync_dialog as bridge_sync

_log = get_logger("crm_service")

_poll_stop = threading.Event()
_poll_thread: threading.Thread | None = None
_SYNC_CURSORS: dict[str, int] = {}
_SMART_BATCH_SIZE = 4
_POLL_INTERVAL_SEC = 18.0
_UI_REFRESH_MIN_SEC = 3.0
_last_ui_refresh: float = 0.0

# Сериализация доступа к браузеру: Playwright-страницу нельзя дёргать
# из нескольких потоков одновременно (поллер + таймер + ручная синхронизация).
_browser_lock = threading.Lock()


def get_active_drivers(window: Any) -> dict[str, Any]:
    return dict(getattr(window, "active_drivers", {}) or {})


def list_visible_dialogs(window: Any, **kwargs: Any) -> list[DialogRecord]:
    """Диалоги только запущенных токенов и только по ключевому слову CRM."""
    sd = getattr(window, "session_dir", "") or ""
    active = set(get_active_drivers(window).keys())
    keyword = get_crm_keyword()
    return [
        d
        for d in list_dialogs(sd, **kwargs)
        if d.session_name in active and dialog_matches_keyword(d, keyword)
    ]


def _remove_dialog(window: Any, dialog_id: str, reason: str) -> None:
    sd = getattr(window, "session_dir", "") or ""
    if delete_dialog(sd, dialog_id):
        _log.info("crm removed dialog %s: %s", dialog_id, reason)


def _known_titles_index(session_dir: str, session_name: str) -> set[str]:
    low: set[str] = set()
    for d in list_dialogs(session_dir, session_name=session_name):
        gt = (d.group_title or "").strip().casefold()
        if gt:
            low.add(gt)
        alias = (d.lead_alias or "").strip().casefold()
        if alias:
            low.add(alias)
    return low


def pick_dialogs_for_smart_sync(
    session_dir: str,
    active_sessions: set[str] | None = None,
    *,
    batch_size: int = _SMART_BATCH_SIZE,
) -> list[DialogRecord]:
    """Очередь sync: непрочитанные ответы → ответили → ждём → остальное по кругу."""
    keyword = get_crm_keyword()
    dialogs = [
        d
        for d in list_dialogs(session_dir, operator_order=True)
        if dialog_matches_keyword(d, keyword)
    ]
    if active_sessions is not None:
        dialogs = [d for d in dialogs if d.session_name in active_sessions]
    if not dialogs:
        return []

    unread = [
        d
        for d in dialogs
        if d.status == STATUS_REPLIED and int(d.unread or 0) > 0
    ]
    if unread:
        return unread[:batch_size]

    replied = [d for d in dialogs if d.status == STATUS_REPLIED]
    awaiting = [d for d in dialogs if d.status == STATUS_AWAITING]
    rest = [
        d
        for d in dialogs
        if d.status not in (STATUS_REPLIED, STATUS_AWAITING)
    ]

    pool: list[DialogRecord] = []
    for bucket in (replied, awaiting, rest):
        for d in bucket:
            if d not in pool:
                pool.append(d)
    if not pool:
        return []

    cursor = _SYNC_CURSORS.get(session_dir, 0) % len(pool)
    picked: list[DialogRecord] = []
    for i in range(min(batch_size, len(pool))):
        picked.append(pool[(cursor + i) % len(pool)])
    _SYNC_CURSORS[session_dir] = (cursor + len(picked)) % len(pool)
    return picked


def _emit_progress(
    fn: ProgressFn | None,
    phase: str,
    current: int,
    total: int,
    detail: str,
) -> None:
    if fn is None:
        return
    try:
        fn(phase, current, total, detail)
    except Exception:
        pass


def sync_dialogs(
    window: Any,
    dialogs: list[DialogRecord],
    *,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    if getattr(window, "_automation_running", False):
        return {"added": 0, "errors": [], "stats": {}}
    if not dialogs:
        return {"added": 0, "errors": [], "stats": {}, "synced": 0}

    sd = getattr(window, "session_dir", "") or ""
    drivers = get_active_drivers(window)

    by_session: dict[str, list[DialogRecord]] = defaultdict(list)
    for dialog in dialogs:
        by_session[dialog.session_name].append(dialog)

    sessions = sorted(by_session.items(), key=lambda x: x[0])
    with _browser_lock:
        return _sync_sessions_locked(
            window, sd, drivers, sessions, on_progress, dialogs
        )


def _sync_sessions_locked(
    window: Any,
    sd: str,
    drivers: dict[str, Any],
    sessions: list[tuple[str, list[DialogRecord]]],
    on_progress: ProgressFn | None,
    dialogs: list[DialogRecord],
) -> dict[str, Any]:
    total_added = 0
    errors: list[str] = []
    for si, (sess_name, sess_dialogs) in enumerate(sessions, start=1):
        _emit_progress(
            on_progress,
            "sync_session",
            si,
            len(sessions),
            sess_name,
        )
        driver = resolve_driver(drivers.get(sess_name))
        if driver is None:
            errors.append(f"{sess_name}: нет драйвера")
            continue
        try:
            sess = driver._mx_playwright_session
            if not is_session_alive(sess):
                errors.append(f"{sess_name}: сессия закрыта")
                continue
            ui = MaxUIActions(sess.page, sess_name)
            _emit_progress(
                on_progress, "sync_list", 1, 1, f"{sess_name}: список чатов…"
            )
            titles = ui.list_chat_titles(limit=80)
            valid = [
                d
                for d in sess_dialogs
                if not is_ui_chrome_title(d.group_title)
                and dialog_matches_keyword(d)
            ]
            for di, dialog in enumerate(valid, start=1):
                _emit_progress(
                    on_progress,
                    "sync_chat",
                    di,
                    len(valid) or 1,
                    dialog.group_title or dialog.display_name(),
                )
                try:
                    added, info, exists = bridge_sync(
                        sd, driver, dialog, chat_titles=titles
                    )
                    if not exists:
                        errors.append(f"{dialog.display_name}: {info}")
                        continue
                    total_added += added
                except Exception as ex:
                    _log.exception("sync %s", dialog.id)
                    errors.append(f"{dialog.display_name}: {ex}")
        except Exception as ex:
            _log.exception("sync session %s", sess_name)
            errors.append(f"{sess_name}: {ex}")

    return {
        "added": total_added,
        "errors": errors,
        "stats": dialog_stats(sd),
        "synced": len(dialogs),
    }


def sync_smart(
    window: Any,
    *,
    batch_size: int = _SMART_BATCH_SIZE,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Синхронизировать только приоритетную пачку диалогов."""
    sd = getattr(window, "session_dir", "") or ""
    active = set(get_active_drivers(window).keys())
    picked = pick_dialogs_for_smart_sync(sd, active, batch_size=batch_size)
    if not picked:
        return {"added": 0, "errors": [], "stats": dialog_stats(sd), "synced": 0}
    result = sync_dialogs(window, picked, on_progress=on_progress)
    result["synced"] = len(picked)
    return result


def sync_all(
    window: Any,
    *,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    if getattr(window, "_automation_running", False):
        return {"added": 0, "errors": [], "stats": {}}
    sd = getattr(window, "session_dir", "") or ""
    active = set(get_active_drivers(window).keys())
    keyword = get_crm_keyword()
    dialogs = [
        d
        for d in list_dialogs(sd)
        if d.session_name in active and dialog_matches_keyword(d, keyword)
    ]
    result = sync_dialogs(window, dialogs, on_progress=on_progress)
    result["synced"] = len(dialogs)
    return result


def sync_one(window: Any, dialog_id: str) -> tuple[int, str]:
    sd = getattr(window, "session_dir", "") or ""
    dialog = get_dialog(sd, dialog_id)
    if not dialog:
        return 0, "диалог не найден"
    if not dialog_matches_keyword(dialog):
        return 0, "чат вне фильтра CRM"
    driver = resolve_driver(get_active_drivers(window).get(dialog.session_name))
    if not driver:
        return 0, "сессия не запущена"
    # Не блокируем UI-поток: если браузер сейчас занят другой синхронизацией — пропускаем.
    if not _browser_lock.acquire(blocking=False):
        return 0, "идёт синхронизация"
    try:
        added, info, exists = bridge_sync(sd, driver, dialog)
    finally:
        _browser_lock.release()
    if not exists:
        return 0, info
    return added, info


def import_chats_from_max(
    window: Any,
    *,
    per_session_limit: int = 60,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Добавить в CRM группы из списка чатов MAX (без открытия каждого чата)."""
    from campaign_store import DialogRecord, add_dialog

    sd = getattr(window, "session_dir", "") or ""
    added = 0
    found_total = 0
    matched_total = 0
    errors: list[str] = []
    keyword = get_crm_keyword()

    drivers_list = list(get_active_drivers(window).items())
    with _browser_lock:
        for si, (sess_name, raw_driver) in enumerate(drivers_list, start=1):
            _emit_progress(on_progress, "import", si, len(drivers_list), sess_name)
            driver = resolve_driver(raw_driver)
            if driver is None:
                continue
            try:
                sess = driver._mx_playwright_session
                if not is_session_alive(sess):
                    errors.append(f"{sess_name}: сессия закрыта")
                    continue
                ui = MaxUIActions(sess.page, sess_name)
                known = _known_titles_index(sd, sess_name)
                titles = ui.list_chat_titles(limit=per_session_limit)
                found_total += len(titles)
                matched = 0
                skipped_keyword: list[str] = []
                for title in titles:
                    if is_ui_chrome_title(title):
                        continue
                    if not title_matches_keyword(title, keyword):
                        if len(skipped_keyword) < 15:
                            skipped_keyword.append(title)
                        continue
                    matched += 1
                    matched_total += 1
                    low = title.casefold()
                    if low in known:
                        continue
                    add_dialog(
                        sd,
                        DialogRecord.create(
                            session_name=sess_name,
                            group_title=title,
                            lead_alias=title,
                        ),
                    )
                    known.add(low)
                    added += 1
                _log.info(
                    "import %s: найдено %s, по слову «%s» подходит %s, добавлено %s; "
                    "не прошли фильтр (примеры): %s",
                    sess_name,
                    len(titles),
                    keyword or "(без фильтра)",
                    matched,
                    added,
                    skipped_keyword,
                )
            except Exception as ex:
                _log.exception("import chats %s", sess_name)
                errors.append(f"{sess_name}: {ex}")

    return {
        "added": added,
        "found": found_total,
        "matched": matched_total,
        "keyword": keyword,
        "errors": errors,
        "stats": dialog_stats(sd),
    }


def reconcile_offline(window: Any) -> dict[str, Any]:
    """Убрать из CRM только чаты незапущенных токенов."""
    sd = getattr(window, "session_dir", "") or ""
    active = set(get_active_drivers(window).keys())
    removed = 0
    for dialog in list_dialogs(sd):
        if dialog.session_name not in active:
            if delete_dialog(sd, dialog.id):
                removed += 1
    return {"removed": removed, "stats": dialog_stats(sd)}


def reconcile_crm(
    window: Any,
    *,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Полная очистка: офлайн-токены + группы, которых нет в MAX."""
    sd = getattr(window, "session_dir", "") or ""
    active = get_active_drivers(window)
    _emit_progress(on_progress, "reconcile", 1, 3, "офлайн-токены…")
    off = reconcile_offline(window)
    removed_offline = int(off.get("removed") or 0)
    removed_missing = 0
    details: list[str] = []

    to_check = [
        d for d in list_dialogs(sd) if d.session_name in active
    ]
    with _browser_lock:
        for i, dialog in enumerate(to_check, start=1):
            _emit_progress(
                on_progress,
                "reconcile",
                i,
                max(len(to_check), 1),
                dialog.group_title or dialog.display_name(),
            )
            if dialog.session_name not in active:
                continue
            driver = resolve_driver(active.get(dialog.session_name))
            if driver is None:
                continue
            try:
                sess = driver._mx_playwright_session
                if not is_session_alive(sess):
                    continue
                ui = MaxUIActions(sess.page, dialog.session_name)
                if not ui.chat_exists(dialog.group_title):
                    if delete_dialog(sd, dialog.id):
                        removed_missing += 1
                        details.append(f"нет в MAX: {dialog.group_title}")
            except Exception as ex:
                _log.debug("reconcile %s: %s", dialog.id, ex)

    return {
        "removed_offline": removed_offline,
        "removed_missing": removed_missing,
        "removed": removed_offline + removed_missing,
        "details": details[:20],
        "stats": dialog_stats(sd),
    }


def delete_dialog_crm(
    window: Any,
    dialog_id: str,
    *,
    delete_in_max: bool = False,
) -> tuple[bool, str]:
    sd = getattr(window, "session_dir", "") or ""
    dialog = get_dialog(sd, dialog_id)
    if not dialog:
        return False, "диалог не найден"

    max_detail = ""
    if delete_in_max:
        driver = resolve_driver(get_active_drivers(window).get(dialog.session_name))
        if not driver:
            return False, "сессия не запущена — группу в MAX не удалить"
        ok, max_detail = delete_group_in_max(driver, dialog)
        if not ok:
            return False, max_detail

    if not delete_dialog(sd, dialog_id):
        return False, "не удалось удалить из CRM"
    if delete_in_max:
        return True, max_detail or "удалено из CRM и MAX"
    return True, "удалено из CRM"


def send_from_crm(window: Any, dialog_id: str, text: str) -> tuple[bool, str]:
    sd = getattr(window, "session_dir", "") or ""
    dialog = get_dialog(sd, dialog_id)
    if not dialog:
        return False, "диалог не найден"
    driver = resolve_driver(get_active_drivers(window).get(dialog.session_name))
    if not driver:
        return False, "сессия не запущена"
    return bridge_send(sd, driver, dialog, text)


def open_dialog_read(window: Any, dialog_id: str) -> None:
    sd = getattr(window, "session_dir", "") or ""
    mark_read(sd, dialog_id)


def request_crm_ui_refresh(window: Any, *, force: bool = False) -> None:
    """Обновить список CRM в главном потоке Qt (не чаще раз в N сек)."""
    global _last_ui_refresh
    now = time.time()
    if not force and now - _last_ui_refresh < _UI_REFRESH_MIN_SEC:
        return
    _last_ui_refresh = now
    bridge = getattr(window, "_crm_bridge", None)
    if bridge is not None:
        try:
            bridge.refresh_requested.emit()
            return
        except Exception:
            pass
    refresh = getattr(window, "_crm_refresh_ui", None)
    if callable(refresh):
        try:
            refresh()
        except Exception:
            _log.exception("crm ui refresh")


def purge_ui_chrome_dialogs(window: Any) -> int:
    """Убрать из CRM служебные вкладки и чаты без ключевого слова (ЖКХ)."""
    sd = getattr(window, "session_dir", "") or ""
    keyword = get_crm_keyword()
    removed = 0
    for dialog in list_dialogs(sd):
        is_chrome = is_ui_chrome_title(dialog.group_title) or is_ui_chrome_title(
            dialog.lead_alias
        )
        if is_chrome or not dialog_matches_keyword(dialog, keyword):
            if delete_dialog(sd, dialog.id):
                removed += 1
    return removed


def run_manual_sync(
    window: Any,
    *,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Полная ручная синхронизация: мусор → импорт → sync."""
    _emit_progress(on_progress, "purge", 1, 1, "мусор UI…")
    purge_ui_chrome_dialogs(window)
    imported = import_chats_from_max(window, on_progress=on_progress)
    synced = sync_all(window, on_progress=on_progress)
    return {
        "imported": imported.get("added", 0),
        "found": imported.get("found", 0),
        "matched": imported.get("matched", 0),
        "keyword": imported.get("keyword", ""),
        "added": synced.get("added", 0),
        "synced": synced.get("synced", 0),
        "errors": (imported.get("errors") or []) + (synced.get("errors") or []),
        "stats": synced.get("stats") or {},
    }


def crm_bootstrap(
    window: Any,
    *,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """При открытии CRM: подтянуть чаты из MAX, убрать офлайн, синхронизировать."""
    _emit_progress(on_progress, "reconcile", 1, 4, "офлайн-токены…")
    reconcile_offline(window)
    _emit_progress(on_progress, "purge", 2, 4, "мусор UI…")
    removed_chrome = purge_ui_chrome_dialogs(window)
    imported = import_chats_from_max(window, on_progress=on_progress)
    synced = sync_all(window, on_progress=on_progress)
    request_crm_ui_refresh(window, force=True)
    return {
        "imported": imported.get("added", 0),
        "found": imported.get("found", 0),
        "matched": imported.get("matched", 0),
        "keyword": imported.get("keyword", ""),
        "removed_chrome": removed_chrome,
        "synced": synced.get("synced", 0),
        "added_messages": synced.get("added", 0),
        "errors": (imported.get("errors") or []) + (synced.get("errors") or []),
    }


def start_poller(window: Any, interval_sec: float = _POLL_INTERVAL_SEC) -> None:
    global _poll_thread
    stop_poller()
    _poll_stop.clear()
    window._crm_poll_bootstrapped = True

    def _loop() -> None:
        while not _poll_stop.is_set():
            try:
                if getattr(window, "_automation_running", False):
                    pass
                elif getattr(window, "_crm_job_running", False):
                    # Идёт ручная синхронизация/импорт — не мешаем браузеру.
                    pass
                elif list_visible_dialogs(window):
                    result = sync_smart(window)
                    if result.get("added"):
                        request_crm_ui_refresh(window)
            except Exception:
                _log.exception("crm poll")
            _poll_stop.wait(max(5.0, float(interval_sec)))

    _poll_thread = threading.Thread(target=_loop, name="crm-poll", daemon=True)
    _poll_thread.start()


def stop_poller() -> None:
    _poll_stop.set()
