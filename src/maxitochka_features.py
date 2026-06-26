"""Дополнительные функции Maxitochka (папки, drag&drop, автообновление списка)."""

from __future__ import annotations

import os
import shutil
import threading
from typing import Any

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from app_logger import get_logger, log_path, open_log_folder
from app_version import version_display
from settings_store import (
    app_data_root,
    default_proxies_file,
    default_tokenbase_dir,
    load_settings,
    save_settings,
)
from tokenbase import migrate_legacy_dirs

_log = get_logger("features")


def install(window: Any, module: Any) -> None:
    settings = load_settings()
    _migrate_crm_keyword(settings)
    _apply_paths(window, settings)
    _schedule_profile_cleanup(window, module)
    _enable_drag_drop(window, module)
    _show_version_footer(window, module)
    _schedule_auto_update_check(window)


def _schedule_auto_update_check(window: Any) -> None:
    try:
        from update_checker import schedule_auto_check

        schedule_auto_check(window)
    except Exception:
        _log.debug("schedule_auto_update_check failed", exc_info=True)


def _migrate_crm_keyword(settings: dict) -> None:
    """Обновить ключевые слова CRM на «ЖКХ, ключ», если стоит старое/пустое значение."""
    from crm_filter import DEFAULT_CRM_KEYWORD

    current = str(settings.get("crm_chat_keyword") or "").strip()
    if current.casefold() in ("", "жкх"):
        if current.casefold() != DEFAULT_CRM_KEYWORD.casefold():
            save_settings({"crm_chat_keyword": DEFAULT_CRM_KEYWORD})
            settings["crm_chat_keyword"] = DEFAULT_CRM_KEYWORD
            _log.info("CRM keyword мигрирован на «%s»", DEFAULT_CRM_KEYWORD)


def _schedule_profile_cleanup(window: Any, module: Any) -> None:
    profiles_dir = getattr(window, "profiles_dir", "") or ""
    session_dir = getattr(window, "session_dir", "") or ""
    if not profiles_dir or not os.path.isdir(profiles_dir):
        return

    def worker() -> None:
        try:
            from profile_cleanup import cleanup_orphan_profiles

            stats = cleanup_orphan_profiles(profiles_dir, session_dir)
        except Exception:
            _log.exception("profile cleanup failed")
            return
        deleted = int(stats.get("deleted") or 0)
        if deleted <= 0:
            return
        freed_mb = float(stats.get("bytes_freed") or 0) / (1024 * 1024)
        _log.info(
            "Очистка profiles: удалено %s, оставлено %s, пропущено (запущены) %s, ~%.1f МБ",
            deleted,
            stats.get("kept"),
            stats.get("skipped_running"),
            freed_mb,
        )

        def notify() -> None:
            if not hasattr(window, "signals"):
                return
            try:
                window.signals.notify.emit(
                    f"Очистка профилей: удалено {deleted} папок (~{freed_mb:.0f} МБ)",
                    "#6366f1",
                )
            except Exception:
                pass

        QTimer.singleShot(0, notify)

    threading.Thread(target=worker, daemon=True).start()


def _apply_paths(window: Any, settings: dict) -> None:
    root = app_data_root()
    tokenbase = (
        str(settings.get("tokenbase_dir") or settings.get("sessions_dir") or "").strip()
        or default_tokenbase_dir()
    )
    os.makedirs(tokenbase, exist_ok=True)
    try:
        migrated = migrate_legacy_dirs(root, tokenbase)
        if migrated:
            _log.info("Миграция токенов в tokenbase: %s файлов", migrated)
    except Exception:
        _log.exception("migrate_legacy_dirs failed")
    window.session_dir = tokenbase
    if not str(settings.get("tokenbase_dir") or "").strip():
        save_settings({"tokenbase_dir": tokenbase, "sessions_dir": tokenbase})
    window.profiles_dir = os.path.join(root, "profiles")
    os.makedirs(window.profiles_dir, exist_ok=True)

    proxies = settings.get("proxies_file") or default_proxies_file()
    if os.path.isfile(proxies):
        try:
            with open(proxies, encoding="utf-8") as f:
                text = f.read().strip()
            if hasattr(window, "p_input") and text:
                window.p_input.setPlainText(text)
        except Exception:
            pass

    for sub in ("рабочие", "мёртвые", "ошибки", "alive"):
        os.makedirs(os.path.join(tokenbase, sub), exist_ok=True)


def _sync_proxies_ui(window: Any) -> None:
    if hasattr(window, "last_txt"):
        window.last_txt = ""
    if hasattr(window, "live_sync"):
        window.live_sync()
    elif hasattr(window, "render_proxies"):
        window.render_proxies()


def _save_proxies_file(window: Any, path: str) -> None:
    settings = load_settings()
    settings["proxies_file"] = path
    save_settings(settings)
    if os.path.isfile(path) and hasattr(window, "p_input"):
        with open(path, encoding="utf-8") as f:
            window.p_input.setPlainText(f.read().strip())
        _sync_proxies_ui(window)
    window.signals.notify.emit(f"Прокси из файла:\n{os.path.basename(path)}", "#6366f1")


def _import_files(window: Any, paths: list[str]) -> None:
    session_dir = getattr(window, "session_dir", default_tokenbase_dir())
    os.makedirs(session_dir, exist_ok=True)
    ok = err = 0
    for p in paths:
        if not p.lower().endswith(".txt") or not os.path.isfile(p):
            continue
        name = os.path.basename(p)
        dst = os.path.join(session_dir, name)
        try:
            shutil.copy2(p, dst)
            ok += 1
        except Exception:
            err += 1
    try:
        from launch_panel import _schedule_render

        _schedule_render(window)
    except Exception:
        if hasattr(window, "render_sessions"):
            window.render_sessions()
    if hasattr(window, "render_checker"):
        try:
            window.render_checker()
        except Exception:
            pass
    window.signals.notify.emit(f"Добавлено: {ok}\nОшибок: {err}", "#6366f1")


def _show_version_footer(window: Any, module: Any) -> None:
    cont = window.findChild(module.QFrame, "MainContainer")
    if not cont or not cont.layout():
        return
    if cont.findChild(QWidget, "MxFooter"):
        return

    footer = QWidget()
    footer.setObjectName("MxFooter")
    lay = QHBoxLayout(footer)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.setSpacing(8)

    lbl = QLabel(f"Maxitochka {version_display()}")
    lbl.setObjectName("MxVersion")
    lbl.setStyleSheet(
        "color: rgba(255,255,255,0.35); font-size: 10px; border: none;"
    )
    lay.addWidget(lbl)
    lay.addStretch()

    from tutorial import add_tutorial_footer_button, install_tutorial

    install_tutorial(window)
    add_tutorial_footer_button(window, lay)

    btn_upd = QPushButton("Обновление")
    btn_upd.setObjectName("MxUpdateBtn")
    btn_upd.setToolTip("Проверить новую версию Maxitochka")
    btn_upd.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_upd.setStyleSheet(
        "QPushButton#MxUpdateBtn { "
        "color: rgba(241,245,249,0.7); background: rgba(255,255,255,0.05); "
        "border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; "
        "padding: 3px 10px; font-size: 10px; font-weight: 600; }"
        "QPushButton#MxUpdateBtn:hover { background: rgba(99,102,241,0.18); }"
    )

    def _check_updates() -> None:
        try:
            from update_checker import check_updates

            check_updates(window, silent=False)
        except Exception:
            _log.exception("manual update check failed")
            if hasattr(window, "signals"):
                window.signals.notify.emit(
                    "Не удалось проверить обновления", "#f43f5e"
                )

    btn_upd.clicked.connect(_check_updates)
    lay.addWidget(btn_upd)

    btn = QPushButton("Открыть лог")
    btn.setObjectName("MxOpenLogBtn")
    btn.setToolTip(f"Файл: {log_path()}")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        "QPushButton#MxOpenLogBtn { "
        "color: rgba(241,245,249,0.7); background: rgba(255,255,255,0.05); "
        "border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; "
        "padding: 3px 10px; font-size: 10px; font-weight: 600; }"
        "QPushButton#MxOpenLogBtn:hover { background: rgba(99,102,241,0.18); }"
    )

    def _open() -> None:
        ok = open_log_folder()
        if not ok and hasattr(window, "signals"):
            window.signals.notify.emit(
                f"Не удалось открыть папку лога.\n{log_path()}", "#f59e0b"
            )

    btn.clicked.connect(_open)
    lay.addWidget(btn)

    cont.layout().addWidget(footer)


class _FileDropFilter(QObject):
    """Надёжный drag-and-drop через eventFilter (работает на всех вкладках)."""

    def __init__(self, on_drop, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._on_drop = on_drop

    def eventFilter(self, obj, event) -> bool:
        t = event.type()
        if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if event.mimeData() and event.mimeData().hasUrls():
                event.acceptProposedAction()
                return True
            return False
        if t == QEvent.Type.Drop:
            self._on_drop(event)
            event.acceptProposedAction()
            return True
        return False


def _collect_txt_paths(event) -> list[str]:
    paths: list[str] = []
    for url in event.mimeData().urls():
        p = url.toLocalFile()
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    if f.lower().endswith(".txt"):
                        paths.append(os.path.join(root, f))
        elif p.lower().endswith(".txt"):
            paths.append(p)
    return paths


def _install_drop_target(window: Any, widget, handler) -> None:
    if widget is None:
        return
    widget.setAcceptDrops(True)
    filt = _FileDropFilter(handler, widget)
    widget.installEventFilter(filt)
    window._mx_drop_filters.append(filt)


def _tab_page(window: Any, index: int):
    tabs = getattr(window, "tabs", None)
    if tabs is not None and index < tabs.count():
        return tabs.widget(index)
    return None


def _enable_drag_drop(window: Any, module: Any) -> None:
    window._mx_drop_filters = []

    def drop_sessions(event) -> None:
        paths = _collect_txt_paths(event)
        if paths:
            _import_files(window, paths)

    def drop_proxy(event) -> None:
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isfile(p):
                _save_proxies_file(window, p)
                return

    # В main.pyc страницы лежат только в QStackedWidget: 0=Прокси, 1=Запуск, 2=Чекер
    p_page = _tab_page(window, 0)
    l_page = _tab_page(window, 1)
    c_page = _tab_page(window, 2)

    session_targets = (
        l_page,
        getattr(window, "c_scroll", None),
        getattr(window, "c_scroll_content", None),
    )
    proxy_targets = (
        p_page,
        getattr(window, "p_input", None),
        getattr(window, "p_scroll", None),
        getattr(window, "p_scroll_content", None),
    )

    for w in session_targets:
        _install_drop_target(window, w, drop_sessions)
    for w in proxy_targets:
        _install_drop_target(window, w, drop_proxy)
