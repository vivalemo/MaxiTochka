"""Запуск автоматизации на активных Playwright-сессиях."""

from __future__ import annotations

import threading
import time
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from app_logger import get_logger
from automation_config import load_automation_config, load_contact_records
from automation_engine import AutomationEngine
from campaign_coordinator import (
    CampaignAssignment,
    assignments_for_session,
    limit_plan_per_session,
    plan_round_robin,
    summarize_plan,
    validate_plan_unique,
)
from lead_registry import reset_claims
from browser_launcher import resolve_driver

_log = get_logger("automation_runner")

_ENGINES: dict[str, AutomationEngine] = {}
_LOCK = threading.Lock()
_ACTIVE_RUNS = 0
_BATCH_RUNNING = False
_BATCH_WORKERS_PENDING = 0


class _RunnerBridge(QObject):
    log_line = pyqtSignal(str)
    finished = pyqtSignal(str, bool, str)


def _notify(window: Any, text: str, color: str) -> None:
    if hasattr(window, "signals"):
        try:
            window.signals.notify.emit(text, color)
        except Exception:
            pass
    bridge = getattr(window, "_automation_bridge", None)
    if bridge is not None:
        try:
            bridge.log_line.emit(text)
        except Exception:
            pass


def _automation_enter(window: Any) -> None:
    global _ACTIVE_RUNS
    with _LOCK:
        _ACTIVE_RUNS += 1
        window._automation_running = True
    try:
        from crm_service import stop_poller

        stop_poller()
    except Exception:
        pass


def _automation_leave(window: Any) -> None:
    global _ACTIVE_RUNS
    with _LOCK:
        _ACTIVE_RUNS = max(0, _ACTIVE_RUNS - 1)
        if _ACTIVE_RUNS == 0:
            window._automation_running = False
    try:
        from crm_panel import restart_poller_if_visible

        restart_poller_if_visible(window)
    except Exception:
        pass


def _worker(
    window: Any,
    fname: str,
    assignments: list[CampaignAssignment] | None = None,
) -> None:
    drivers = getattr(window, "active_drivers", {}) or {}
    driver = drivers.get(fname)
    bridge = getattr(window, "_automation_bridge", None)
    ok = False
    detail = ""
    try:
        if driver is None:
            detail = "сессия не запущена — сначала нажмите Запуск"
            _notify(window, f"{fname}: {detail}", "#f43f5e")
            return

        _notify(window, f"[{fname}] подключение к браузеру…", "#6366f1")
        driver = resolve_driver(driver)
        if driver is None:
            detail = "не удалось подключиться к браузеру (перезапустите токен)"
            _notify(window, f"{fname}: {detail}", "#f43f5e")
            return

        notify = lambda t, c: _notify(window, t, c)
        sd = getattr(window, "session_dir", "") or ""
        engine = AutomationEngine(
            driver,
            fname,
            notify=notify,
            session_dir=sd,
            assignments=assignments,
        )
        with _LOCK:
            _ENGINES[fname] = engine
        state = engine.run_script()
        ok = not state.error and not state.stopped
        detail = state.error or "готово"
        color = "#22c55e" if ok else "#f43f5e"
        _notify(
            window,
            f"{fname}: {detail}\nгрупп={state.groups_created} контактов={state.contacts_added}",
            color,
        )
    except Exception as ex:
        detail = str(ex)
        _log.exception("automation failed: %s", fname)
        _notify(window, f"{fname}: {detail}", "#f43f5e")
    finally:
        with _LOCK:
            _ENGINES.pop(fname, None)
        if bridge is not None:
            try:
                bridge.finished.emit(fname, ok, detail)
            except Exception:
                pass


def _batch_worker_done(window: Any) -> None:
    global _BATCH_RUNNING, _BATCH_WORKERS_PENDING
    with _LOCK:
        _BATCH_WORKERS_PENDING = max(0, _BATCH_WORKERS_PENDING - 1)
        if _BATCH_WORKERS_PENDING == 0:
            _BATCH_RUNNING = False


def _worker_gated(
    window: Any,
    fname: str,
    assignments: list[CampaignAssignment] | None,
    sem: threading.Semaphore,
    stagger_sec: float,
) -> None:
    try:
        if stagger_sec > 0:
            time.sleep(stagger_sec)
        sem.acquire()
        _automation_enter(window)
        _worker(window, fname, assignments)
    finally:
        _automation_leave(window)
        sem.release()
        _batch_worker_done(window)


def _ensure_bridge(window: Any) -> None:
    if getattr(window, "_automation_bridge", None):
        return
    window._automation_bridge = _RunnerBridge(window)
    window._automation_bridge.log_line.connect(
        lambda line: _append_automation_log(window, line)
    )


def preflight(window: Any) -> tuple[bool, str]:
    """Проверки перед стартом — сразу понятная причина отказа."""
    active = list((getattr(window, "active_drivers", {}) or {}).keys())
    if not active:
        return False, (
            "Нет активных сессий.\n"
            "1. Вкладка «Запуск» → выберите токены → Запуск\n"
            "2. Подождите 10–15 сек (пока откроется MAX)\n"
            "3. Снова «Запустить автоматизацию»"
        )

    records = load_contact_records()
    if not records:
        return False, (
            "База контактов пуста.\n"
            "Вкладка «Авто» → укажите файл базы или вставьте текст с разделителями -------"
        )

    with _LOCK:
        if _BATCH_RUNNING:
            return False, "Автоматизация уже выполняется — дождитесь окончания"
        running = [f for f in active if f in _ENGINES]
    if running:
        return False, f"Уже выполняется: {', '.join(running[:3])}"

    cfg = load_automation_config()
    start = int(cfg.get("database_start_index") or 0)
    plan = plan_round_robin(sorted(active), records, start)
    summary = summarize_plan(plan)
    rounds = summary.get("rounds") or 0
    max_parallel = max(1, int(cfg.get("automation_max_parallel") or 3))
    return (
        True,
        f"Сессий: {len(active)}, записей: {len(records)}, "
        f"кругов: {rounds} (1 лид на сессию за круг), "
        f"параллельно до {max_parallel}",
    )


def _build_session_assignments(
    session_names: list[str],
) -> tuple[dict[str, list[CampaignAssignment]], list[CampaignAssignment]]:
    cfg = load_automation_config()
    records = load_contact_records(cfg)
    start = int(cfg.get("database_start_index") or 0)
    ordered = sorted(dict.fromkeys(s for s in session_names if s))
    plan = plan_round_robin(ordered, records, start)
    max_per = int(cfg.get("contacts_per_account_max") or 0)
    max_rounds = int(cfg.get("automation_rounds_per_run") or 0)
    plan = limit_plan_per_session(
        plan,
        max_per_session=max_per,
        max_rounds=max_rounds,
    )
    dup_errors = validate_plan_unique(plan)
    if dup_errors:
        _log.error("plan duplicate leads: %s", "; ".join(dup_errors[:5]))
    by_session = {name: assignments_for_session(plan, name) for name in ordered}
    return by_session, plan


def start_automation(window: Any, fnames: list[str] | None = None) -> int:
    """Запустить сценарий на активных сессиях. Возвращает число потоков."""
    global _BATCH_RUNNING, _BATCH_WORKERS_PENDING

    _ensure_bridge(window)

    ok, msg = preflight(window)
    if not ok:
        _notify(window, msg, "#f59e0b")
        _append_automation_log(window, f"⚠ {msg.replace(chr(10), ' | ')}")
        return 0

    active = list((getattr(window, "active_drivers", {}) or {}).keys())
    targets = list(
        dict.fromkeys(f for f in (fnames or active) if f in active)
    )
    if not targets:
        _notify(window, "Нет сессий для автоматизации", "#f59e0b")
        return 0

    by_session, plan = _build_session_assignments(targets)
    dup_errors = validate_plan_unique(plan)
    if dup_errors:
        err = dup_errors[0]
        _notify(window, f"Ошибка плана лидов: {err}", "#f43f5e")
        _append_automation_log(window, f"⚠ {err}")
        return 0

    with _LOCK:
        _BATCH_RUNNING = True
        _BATCH_WORKERS_PENDING = len(targets)

    reset_claims()
    window._automation_plan_by_session = by_session
    window._automation_batch_plan = plan

    _append_automation_log(window, f"─── Старт: {msg} ───")
    seen_phones: set[str] = set()
    for t in sorted(targets):
        items = by_session.get(t) or []
        if not items:
            _append_automation_log(window, f"  → {t}: нет лидов в очереди")
            continue
        first = items[0]
        ph = first.record.primary_phone
        dup_mark = ""
        if ph:
            from contact_database import normalize_phone

            key = normalize_phone(ph)
            if key in seen_phones:
                dup_mark = " [ДУБЛЬ!]"
            seen_phones.add(key)
        first_label = first.record.display_label()
        extra = f", ещё {len(items) - 1}" if len(items) > 1 else ""
        _append_automation_log(
            window,
            f"  → {t}: #{first.record_index + 1} {first_label}{extra}{dup_mark}",
        )
    cfg = load_automation_config()
    max_parallel = max(1, int(cfg.get("automation_max_parallel") or 3))
    stagger = max(0.0, float(cfg.get("automation_stagger_sec") or 2))
    sem = threading.Semaphore(max_parallel)

    _notify(
        window,
        f"Автоматизация: {len(targets)} сессий (до {max_parallel} одновременно)…",
        "#6366f1",
    )

    for i, fname in enumerate(targets):
        assignments = by_session.get(fname) or []
        threading.Thread(
            target=_worker_gated,
            args=(window, fname, assignments, sem, i * stagger),
            name=f"auto-{fname}",
            daemon=True,
        ).start()
    return len(targets)


def stop_automation(window: Any, fname: str | None = None) -> None:
    with _LOCK:
        if fname:
            eng = _ENGINES.get(fname)
            if eng:
                eng.stop()
        else:
            for eng in list(_ENGINES.values()):
                eng.stop()
    _notify(window, "Остановка автоматизации…", "#f59e0b")
    _append_automation_log(window, "■ Остановка запрошена")


def _append_automation_log(window: Any, line: str) -> None:
    log_w = getattr(window, "_auto_run_log", None)
    if log_w is None:
        return
    try:
        log_w.append(line)
        # прокрутка вниз
        bar = log_w.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())
    except Exception:
        pass


def install_automation_handlers(window: Any, module: Any) -> None:
    window.start_automation = lambda fnames=None: start_automation(window, fnames)
    window.stop_automation = lambda fname=None: stop_automation(window, fname)
