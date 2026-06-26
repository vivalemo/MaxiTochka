"""Вкладка «Запуск»: drag&drop, комментарии, дата добавления, мониторинг сессий."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from PyQt6.QtCore import (
    QEvent,
    QFileSystemWatcher,
    QObject,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import analytics
import browser_prefs
import sessions_meta as meta
from tokenbase import list_gui_files, token_path
from session_registry import (
    allocate_debug_port,
    get_or_create_session_id,
    is_browser_window_alive,
    last_profile_dir,
    patch_chrome_options_debug_port,
    register_session,
    restore_chrome_options_debug_port,
    unregister_session,
)
from app_logger import get_logger
from settings_store import load_settings, save_settings
from theme import ACCENT, DANGER, SUCCESS, SUCCESS_BRIGHT, TEXT, TEXT_DIM, WARNING
from table_ui import (
    TABLE_TEXT,
    TABLE_TEXT_MUTED,
    checker_table_extra_stylesheet,
    setup_resizable_columns,
    table_stylesheet,
)

_log = get_logger("launch")

_ROW_H_DEFAULT = 76
_ROW_H_COMPACT = 52
_BTN_W = (72, 88, 50, 88, 88)
_BTN_SP = 8
_BTN_BOX_W = sum(_BTN_W) + _BTN_SP * (len(_BTN_W) - 1)
_MONITOR_GRACE_SEC = 120
_RENDER_DEBOUNCE_MS = 250
_MONITOR_INTERVAL_SEC = 2.5
_TABLE_BATCH_SIZE = 120
_TABLE_BATCH_THRESHOLD = 200

# Иконки действий в таблице «Запуск» (подсказка — tooltip)
_LAUNCH_ICO_STOP = "⏹"
_LAUNCH_ICO_RUN = "▶"
_LAUNCH_ICO_RAW = "📄"
_LAUNCH_ICO_SHOW = "👁"
_LAUNCH_ICO_DEL = "🗑"
_LAUNCH_TOGGLE_W = 72
_LAUNCH_ACTION_WIDTHS = (_LAUNCH_TOGGLE_W, 50, 88, 88)
_LAUNCH_COL_COUNT = 6 + len(_LAUNCH_ACTION_WIDTHS)
_LAUNCH_COL_WIDTHS = (42, 160, 100, 200, 92, 130, *_LAUNCH_ACTION_WIDTHS)
_COL_CB = 0
_COL_FILE = 1
_COL_STATUS = 2
_COL_COMMENT = 3
_COL_ADDED = 4
_COL_LASTRUN = 5
_COL_ACT_TOGGLE = 6
_COL_ACT_RAW = 7
_COL_ACT_SHOW = 8
_COL_ACT_DEL = 9


class _MonitorBridge(QObject):
    """Передача из фонового потока (selenium) обратно в UI."""

    stop_requested = pyqtSignal(str, str)
    reconnect_finished = pyqtSignal(int)
    import_finished = pyqtSignal(int, int)


class _DropFilter(QObject):
    """Event-filter для drag&drop .txt на вкладку «Запуск»."""

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


def install_launch_panel(window: Any, module: Any) -> None:
    DotLauncher = module.DotLauncher
    window._mx_qt_module = module
    window._launch_drop_filters: list[_DropFilter] = []
    window._session_watch_state: dict[str, dict] = {}
    window._browser_prefs_applied: set[str] = set()

    _patch_render_sessions(DotLauncher, module)
    _patch_import_sessions(DotLauncher)
    _patch_add_manual(DotLauncher)
    _patch_confirm_delete(DotLauncher)
    _patch_runtime_tracking(DotLauncher)
    _patch_antidetect_connection(DotLauncher)
    _attach_launch_drop(window, module)
    _attach_session_watcher(window)
    _attach_runtime_timer(window, module)
    _attach_session_monitor(window)
    _schedule_session_reconnect(window, module)
    _add_drop_hint(window, module)
    _add_compact_toggle(window, module)
    _patch_launch_manual(DotLauncher)

    def _place_manual_btn() -> None:
        _add_manual_launch_btn(window, module)
        _add_automation_launch_btn(window, module)

    QTimer.singleShot(0, _place_manual_btn)


def _schedule_session_reconnect(window: Any, module: Any) -> None:
    """После старта — несколько попыток подцепить Chrome от прошлого запуска."""
    delays_ms = (1500, 4000, 9000)
    attempt = {"n": 0}

    def _run() -> None:
        def worker() -> None:
            n = 0
            try:
                from session_reconnect import reconnect_orphan_browsers

                n = reconnect_orphan_browsers(window, module)
                if n:
                    _log.info("reconnected %s browser session(s)", n)
            except Exception:
                _log.exception("session reconnect failed")
            bridge = getattr(window, "_monitor_bridge", None)
            if bridge is not None:
                try:
                    bridge.reconnect_finished.emit(n)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    timer = QTimer(window)
    timer.setSingleShot(True)
    timer.timeout.connect(_run)
    timer.start(delays_ms[0])

    def _on_reconnect_finished(n: int) -> None:
        if n:
            try:
                window.render_sessions()
            except Exception:
                pass
            try:
                if hasattr(window, "render_checker"):
                    window.render_checker()
            except Exception:
                pass
            if hasattr(window, "signals"):
                window.signals.notify.emit(
                    f"Подключено окон после перезапуска: {n}",
                    "#22c55e",
                )
            return
        if int(getattr(window, "_reconnect_live_candidates", 0) or 0) <= 0:
            # Все Chrome от прошлого запуска закрыты — повторять скан бессмысленно.
            return
        attempt["n"] += 1
        if attempt["n"] < len(delays_ms):
            t = QTimer(window)
            t.setSingleShot(True)
            t.timeout.connect(_run)
            t.start(delays_ms[attempt["n"]])

    bridge = getattr(window, "_monitor_bridge", None)
    if bridge is not None:
        try:
            bridge.reconnect_finished.connect(_on_reconnect_finished)
        except Exception:
            pass


def _tab_page(window: Any, index: int):
    tabs = getattr(window, "tabs", None)
    if tabs is not None and index < tabs.count():
        return tabs.widget(index)
    return None


def _launch_tab_page(window: Any) -> QWidget | None:
    """Страница «Запуск» — надёжнее, чем tabs.widget(1) после добавления дашборда."""
    page = getattr(window, "l_page", None)
    if page is not None:
        return page
    scroll = getattr(window, "l_scroll", None)
    if scroll is not None:
        page = scroll.parentWidget()
        if page is not None:
            return page
    return _tab_page(window, 1)


def _launch_btns_layout(page: QWidget) -> QHBoxLayout | None:
    """Нижняя строка: ОБНОВИТЬ / ИМПОРТ / ДОБАВИТЬ ВРУЧНУЮ (оригинальный l_btns)."""
    vlay = page.layout()
    if not isinstance(vlay, QVBoxLayout):
        return None
    for i in range(vlay.count()):
        item = vlay.itemAt(i)
        if item is None:
            continue
        sub = item.layout()
        if not isinstance(sub, QHBoxLayout):
            continue
        for j in range(sub.count()):
            witem = sub.itemAt(j)
            w = witem.widget() if witem else None
            if w is None or not isinstance(w, QPushButton):
                continue
            t = (w.text() or "").upper()
            if "ИМПОРТ" in t or ("ДОБАВИТЬ" in t and "ВРУЧНУЮ" in t):
                return sub
    return None


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


def _import_files(window: Any, paths: list[str]) -> None:
    session_dir = window.session_dir
    clean_paths = [p for p in paths if p.lower().endswith(".txt") and os.path.isfile(p)]
    if not clean_paths:
        return
    if hasattr(window, "signals"):
        window.signals.notify.emit(f"Импорт токенов: {len(clean_paths)} файлов…", ACCENT)

    def worker() -> None:
        os.makedirs(session_dir, exist_ok=True)
        ok = err = 0
        for p in clean_paths:
            name = os.path.basename(p)
            dst = os.path.join(session_dir, name)
            try:
                content = ""
                for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
                    try:
                        with open(p, encoding=enc) as src:
                            content = src.read().strip()
                        if content:
                            break
                    except Exception:
                        content = ""
                if not content:
                    err += 1
                    continue
                with open(dst, "w", encoding="utf-8") as out:
                    out.write(content)
                meta.touch_new(session_dir, name)
                analytics.record_new_token(session_dir, name)
                ok += 1
            except Exception:
                err += 1

        bridge = getattr(window, "_monitor_bridge", None)
        if bridge is not None:
            try:
                bridge.import_finished.emit(ok, err)
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()


def _attach_launch_drop(window: Any, module: Any) -> None:
    def on_drop(event) -> None:
        paths = _collect_txt_paths(event)
        if paths:
            _import_files(window, paths)

    filt_cls = _DropFilter
    targets = (
        _launch_tab_page(window),
        getattr(window, "l_scroll", None),
        getattr(window, "l_scroll_content", None),
    )
    for w in targets:
        if w is None:
            continue
        w.setAcceptDrops(True)
        f = filt_cls(on_drop, w)
        w.installEventFilter(f)
        window._launch_drop_filters.append(f)


def _txt_signature(session_dir: str) -> tuple:
    """Снимок .txt в папке — имя+mtime, для отличия от изменения meta.json."""
    if not session_dir or not os.path.isdir(session_dir):
        return ()
    out: list[tuple[str, float]] = []
    try:
        for name in list_gui_files(session_dir):
            try:
                out.append((name, os.path.getmtime(token_path(session_dir, name))))
            except OSError:
                pass
    except OSError:
        return ()
    return tuple(sorted(out))


def _schedule_render(window: Any) -> None:
    """Coalesce подряд идущие render_sessions в один."""
    if not hasattr(window, "render_sessions"):
        return
    timer = getattr(window, "_render_debounce_timer", None)
    if timer is None:
        timer = QTimer(window)
        timer.setSingleShot(True)
        timer.setInterval(_RENDER_DEBOUNCE_MS)

        def _fire():
            try:
                window.render_sessions()
            except Exception:
                pass

        timer.timeout.connect(_fire)
        window._render_debounce_timer = timer
    timer.start()


def _attach_session_watcher(window: Any) -> None:
    watcher = QFileSystemWatcher(window)
    window._launch_watcher = watcher
    window._last_txt_signature = _txt_signature(
        getattr(window, "session_dir", "")
    )

    def on_change(*_args):
        sd = getattr(window, "session_dir", "")
        if not sd:
            return
        sig = _txt_signature(sd)
        if sig == getattr(window, "_last_txt_signature", ()):
            return
        window._last_txt_signature = sig
        meta.sync_from_disk(sd)
        _schedule_render(window)

    watcher.directoryChanged.connect(on_change)
    sd = getattr(window, "session_dir", "")
    if sd and os.path.isdir(sd):
        watcher.addPath(sd)


def _row_height() -> int:
    return _ROW_H_COMPACT if load_settings().get("compact_table") else _ROW_H_DEFAULT


def _connection_label_text(session_dir: str, fname: str) -> str:
    base = meta.get_connection_display(session_dir, fname)
    path = meta.get_ip_history_display(session_dir, fname)
    if path and path != "—" and path not in base:
        return f"{base}\n↳ {path}"
    return base


def _add_compact_toggle(window: Any, module: Any) -> None:
    page = _launch_tab_page(window)
    if page is None or page.findChild(QPushButton, "LaunchCompactBtn"):
        return
    lay = page.layout()
    if not lay:
        return
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 6)
    btn = module.QPushButton("Компактная таблица")
    btn.setObjectName("LaunchCompactBtn")
    btn.setCheckable(True)
    btn.setChecked(bool(load_settings().get("compact_table")))
    btn.setCursor(module.Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"color: {ACCENT}; border-color: {ACCENT}; font-size: 11px; font-weight: 600;"
    )

    def toggle(checked: bool) -> None:
        s = load_settings()
        s["compact_table"] = checked
        save_settings(s)
        _schedule_render(window)

    btn.toggled.connect(toggle)
    row.addWidget(btn)

    from browser_engine import ENGINE_PLAYWRIGHT, ENGINE_SELENIUM, get_browser_engine

    eng = get_browser_engine()
    btn_sel = module.QPushButton("Selenium")
    btn_sel.setObjectName("LaunchEngineSelenium")
    btn_sel.setCheckable(True)
    btn_sel.setChecked(eng == ENGINE_SELENIUM)
    btn_sel.setCursor(module.Qt.CursorShape.PointingHandCursor)
    btn_sel.setStyleSheet(
        f"color: {ACCENT}; border-color: {ACCENT}; font-size: 11px; font-weight: 600;"
    )
    btn_pw = module.QPushButton("Playwright")
    btn_pw.setObjectName("LaunchEnginePlaywright")
    btn_pw.setCheckable(True)
    btn_pw.setChecked(eng == ENGINE_PLAYWRIGHT)
    btn_pw.setCursor(module.Qt.CursorShape.PointingHandCursor)
    btn_pw.setStyleSheet(
        f"color: {ACCENT}; border-color: {ACCENT}; font-size: 11px; font-weight: 600;"
    )
    eng_group = QButtonGroup(page)
    eng_group.setExclusive(True)
    eng_group.addButton(btn_sel)
    eng_group.addButton(btn_pw)

    def _on_engine(btn) -> None:
        chosen = ENGINE_PLAYWRIGHT if btn is btn_pw else ENGINE_SELENIUM
        save_settings({"browser_engine": chosen})
        label = "Playwright" if chosen == ENGINE_PLAYWRIGHT else "Selenium"
        if hasattr(window, "signals"):
            window.signals.notify.emit(
                f"Движок браузера: {label}\nПерезапустите открытые токены",
                ACCENT,
            )

    btn_sel.clicked.connect(lambda: _on_engine(btn_sel))
    btn_pw.clicked.connect(lambda: _on_engine(btn_pw))
    row.addWidget(btn_sel)
    row.addWidget(btn_pw)

    autosave_lbl = QLabel(
        "Автосохранение комментариев: "
        + ("вкл" if load_settings().get("autosave_comments", True) else "выкл")
    )
    autosave_lbl.setObjectName("LaunchAutosaveHint")
    autosave_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; border: none;")
    row.addWidget(autosave_lbl, 1)
    lay.insertLayout(2, row)


_MANUAL_PREFIX = "MANUAL-"
_MAX_URL = "https://web.max.ru/"
# Пустая строка ломает чтение в оригинальном antidetect_browser — безопасная заглушка
_MANUAL_JS = "// maxitochka: ручной запуск без токена\n"


def _is_manual_session(fname: str) -> bool:
    return (fname or "").upper().startswith(_MANUAL_PREFIX)


def _pick_launch_proxy(window: Any) -> tuple[str, bool]:
    """Прокси как при обычном запуске: случайный живой из кэша."""
    import random

    cache = getattr(window, "proxy_cache", {}) or {}
    alive = [
        p
        for p, inf in cache.items()
        if isinstance(inf, dict) and inf.get("st") == "OK" and str(p).strip()
    ]
    if alive:
        return random.choice(alive), True
    keys = [str(p).strip() for p in cache if str(p).strip()]
    if keys:
        return random.choice(keys), False
    return "", False


def _add_manual_launch_btn(window: Any, module: Any) -> None:
    page = _launch_tab_page(window)
    if page is None or page.findChild(QPushButton, "LaunchManualBtn"):
        return
    btn = module.QPushButton("Запустить вручную")
    btn.setObjectName("LaunchManualBtn")
    btn.setCursor(module.Qt.CursorShape.PointingHandCursor)
    btn.setMinimumHeight(36)
    btn.setStyleSheet(
        f"color: {ACCENT}; border: 1px solid {ACCENT}; border-radius: 10px; "
        "font-size: 12px; font-weight: 600; padding: 0 14px; background: transparent;"
    )
    btn.setToolTip(
        "Новое окно Chrome через прокси на web.max.ru без файла токена.\n"
        "Сессию можно остановить кнопкой СТОП в строке «MANUAL-…»."
    )
    btn.clicked.connect(lambda: window.launch_manual())
    window._btn_launch_manual = btn

    toolbar = _launch_btns_layout(page)
    if toolbar is not None:
        toolbar.addWidget(btn)
        _log.info("Кнопка «Запустить вручную» добавлена в панель запуска")
        return

    lay = page.layout()
    if isinstance(lay, QVBoxLayout):
        lay.addLayout(_manual_btn_fallback_row(module, btn))
        _log.warning(
            "Панель кнопок запуска не найдена — «Запустить вручную» внизу вкладки"
        )


def _manual_btn_fallback_row(module: Any, btn: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 8, 0, 0)
    row.addWidget(btn)
    row.addStretch(1)
    return row


def _add_automation_launch_btn(window: Any, module: Any) -> None:
    page = _launch_tab_page(window)
    if page is None or page.findChild(QPushButton, "LaunchAutoBtn"):
        return
    btn = module.QPushButton("Автоматизация")
    btn.setObjectName("LaunchAutoBtn")
    btn.setCursor(module.Qt.CursorShape.PointingHandCursor)
    btn.setMinimumHeight(36)
    btn.setStyleSheet(
        f"color: {SUCCESS_BRIGHT}; border: 1px solid {SUCCESS_BRIGHT}; border-radius: 10px; "
        "font-size: 12px; font-weight: 600; padding: 0 14px; background: transparent;"
    )
    btn.setToolTip(
        "Запустить сценарий на всех активных сессиях.\n"
        "Настройки — вкладка «Авто»."
    )

    def _run() -> None:
        if hasattr(window, "start_automation"):
            window.start_automation()
        else:
            from automation_runner import start_automation

            start_automation(window)

    btn.clicked.connect(_run)
    window._btn_launch_auto = btn

    toolbar = _launch_btns_layout(page)
    if toolbar is not None:
        toolbar.addWidget(btn)
        _log.info("Кнопка «Автоматизация» добавлена в панель запуска")
        return

    lay = page.layout()
    if isinstance(lay, QVBoxLayout):
        row = _manual_btn_fallback_row(module, btn)
        lay.addLayout(row)


def _add_drop_hint(window: Any, module: Any) -> None:
    page = _launch_tab_page(window)
    if page is None or page.findChild(QLabel, "LaunchDropHint"):
        return
    lay = page.layout()
    if not lay:
        return
    hint = QLabel("Перетащите .txt сюда — сессии появятся в списке")
    hint.setObjectName("LaunchDropHint")
    hint.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; border: none;")
    lay.insertWidget(1, hint)


def _clear_layout(lay) -> None:
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()


_ACTION_DISABLED = TABLE_TEXT_MUTED


def _launch_item(
    text: str,
    *,
    color: str | None = None,
    align: Qt.AlignmentFlag | None = None,
    editable: bool = False,
    userdata: str | None = None,
    bold: bool = False,
) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setToolTip(text)
    if editable:
        it.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )
    else:
        flags = it.flags()
        flags &= ~Qt.ItemFlag.ItemIsEditable
        it.setFlags(flags)
    if userdata:
        it.setData(Qt.ItemDataRole.UserRole, userdata)
    if color:
        brush = QColor(color)
        it.setForeground(brush)
        it.setData(Qt.ItemDataRole.ForegroundRole, brush)
    else:
        brush = QColor(TABLE_TEXT)
        it.setForeground(brush)
        it.setData(Qt.ItemDataRole.ForegroundRole, brush)
    if bold:
        from PyQt6.QtGui import QFont

        fnt = it.font()
        fnt.setBold(True)
        it.setFont(fnt)
    if len(text) <= 2:
        from PyQt6.QtGui import QFont

        fnt = it.font()
        fnt.setPointSize(14)
        it.setFont(fnt)
    if align is not None:
        it.setTextAlignment(align)
    return it


def _ensure_launch_table(window: Any, module: Any) -> QTableWidget | None:
    table = getattr(window, "_launch_table", None)
    if isinstance(table, QTableWidget):
        if table.columnCount() != _LAUNCH_COL_COUNT:
            table.deleteLater()
            window._launch_table = None
            window._checker_table = None
            return _ensure_launch_table(window, module)
        setup_resizable_columns(
            table.horizontalHeader(),
            _LAUNCH_COL_WIDTHS,
            stretch_col=_COL_COMMENT,
        )
        for col, tip in (
            (_COL_ACT_TOGGLE, "Запуск · остановка"),
            (_COL_ACT_RAW, "Показать RAW"),
            (_COL_ACT_SHOW, "Показать окно браузера"),
            (_COL_ACT_DEL, "Удалить"),
        ):
            item = table.horizontalHeaderItem(col)
            if item:
                item.setToolTip(tip)
        return table

    page = _launch_tab_page(window)
    if page is None:
        return None

    table = QTableWidget()
    table.setObjectName("LaunchTable")
    table.setColumnCount(_LAUNCH_COL_COUNT)
    table.setHorizontalHeaderLabels(
        (
            "",
            "Файл",
            "Статус",
            "Комментарий",
            "Добавлен",
            "Последний запуск",
            "▶⏹",
            _LAUNCH_ICO_RAW,
            _LAUNCH_ICO_SHOW,
            _LAUNCH_ICO_DEL,
        )
    )
    table.verticalHeader().setVisible(False)
    table.setShowGrid(True)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setWordWrap(False)
    table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    table.setStyleSheet(
        table_stylesheet("LaunchTable")
        + checker_table_extra_stylesheet()
    )

    setup_resizable_columns(
        table.horizontalHeader(),
        _LAUNCH_COL_WIDTHS,
        stretch_col=_COL_COMMENT,
    )
    for col, tip in (
        (_COL_ACT_TOGGLE, "Запуск · остановка"),
        (_COL_ACT_RAW, "Показать RAW"),
        (_COL_ACT_SHOW, "Показать окно браузера"),
        (_COL_ACT_DEL, "Удалить"),
    ):
        item = table.horizontalHeaderItem(col)
        if item:
            item.setToolTip(tip)

    old_scroll = getattr(window, "l_scroll", None)
    if old_scroll is not None:
        old_scroll.setVisible(False)
        parent = old_scroll.parentWidget()
        lay = parent.layout() if parent is not None else None
        if isinstance(lay, QVBoxLayout):
            idx = lay.indexOf(old_scroll)
            lay.insertWidget(max(0, idx + 1), table, 1)
        elif isinstance(page.layout(), QVBoxLayout):
            page.layout().addWidget(table, 1)
    elif isinstance(page.layout(), QVBoxLayout):
        page.layout().addWidget(table, 1)

    table.itemChanged.connect(lambda it, w=window: _on_launch_item_changed(w, it))
    table.cellClicked.connect(lambda r, c, w=window: _on_launch_cell_clicked(w, r, c))

    window._launch_table = table
    window._checker_table = table
    return table


def _on_launch_item_changed(window: Any, item: QTableWidgetItem) -> None:
    if getattr(window, "_launch_table_loading", False):
        return
    col = item.column()
    fname = item.data(Qt.ItemDataRole.UserRole)
    if not fname:
        table = getattr(window, "_launch_table", None)
        if table is not None:
            file_item = table.item(item.row(), _COL_FILE)
            if file_item:
                fname = file_item.data(Qt.ItemDataRole.UserRole)
    if not fname:
        return

    if col == _COL_CB:
        picked = set(getattr(window, "_checker_checked", None) or ())
        if item.checkState() == Qt.CheckState.Checked:
            picked.add(fname)
        else:
            picked.discard(fname)
        window._checker_checked = picked
        try:
            from checker_panel import _update_select_all_btn_text

            _update_select_all_btn_text(window)
        except Exception:
            pass
        return

    if col != _COL_COMMENT:
        return
    if _is_manual_session(fname):
        return
    sd = getattr(window, "session_dir", "") or ""
    if not sd:
        return
    try:
        meta.set_comment(sd, fname, item.text().strip())
    except Exception:
        _log.exception("save comment failed for %s", fname)


def _handle_launch_delete(window: Any, fname: str) -> None:
    pending = getattr(window, "_launch_delete_pending", None)
    if pending != fname:
        window._launch_delete_pending = fname
        QTimer.singleShot(3000, lambda: setattr(window, "_launch_delete_pending", None))
        if hasattr(window, "signals"):
            window.signals.notify.emit(
                f"Нажмите УД ещё раз для удаления: {fname}",
                WARNING,
            )
        return
    window._launch_delete_pending = None
    sd = getattr(window, "session_dir", "") or ""
    from tokenbase import token_path

    path = token_path(sd, fname) if sd else ""
    existed = os.path.isfile(path)
    try:
        if existed:
            os.remove(path)
    except OSError:
        _log.exception("delete %s failed", fname)
        if hasattr(window, "signals"):
            window.signals.notify.emit(f"Не удалось удалить: {fname}", DANGER)
        return
    if existed and sd:
        meta.remove(sd, fname)
    state = getattr(window, "_session_watch_state", None)
    if isinstance(state, dict):
        state.pop(fname, None)
    tr = getattr(window, "token_results", None)
    if isinstance(tr, dict):
        tr.pop(fname, None)
    try:
        window.render_sessions()
    except Exception:
        pass
    if hasattr(window, "signals"):
        window.signals.notify.emit(f"Удалено: {fname}", DANGER)


def _on_launch_cell_clicked(window: Any, row: int, col: int) -> None:
    table = getattr(window, "_launch_table", None)
    if table is None:
        return
    file_item = table.item(row, _COL_FILE)
    fname = file_item.data(Qt.ItemDataRole.UserRole) if file_item else None
    if not fname:
        return
    is_active = fname in getattr(window, "active_drivers", {})
    is_manual = _is_manual_session(fname)

    if col == _COL_CB:
        cb_item = table.item(row, _COL_CB)
        if cb_item is not None:
            new_state = (
                Qt.CheckState.Unchecked
                if cb_item.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
            cb_item.setCheckState(new_state)
        return
    if col == _COL_ACT_TOGGLE:
        if is_active:
            window.stop_session(fname)
        elif not is_manual:
            window.launch(fname)
    elif col == _COL_ACT_RAW and not is_manual:
        window.show_raw_content(fname)
    elif col == _COL_ACT_SHOW and is_active:
        window.focus_browser_window(fname)
    elif col == _COL_ACT_DEL and not is_active and not is_manual:
        _handle_launch_delete(window, fname)


def _toggle_action_item(*, is_active: bool, is_manual: bool) -> QTableWidgetItem:
    if is_manual and not is_active:
        return _action_item("", enabled=False, color="", tooltip="")
    if is_active:
        return _action_item(
            _LAUNCH_ICO_STOP,
            enabled=True,
            color="",
            tooltip="Остановить сессию",
        )
    return _action_item(
        _LAUNCH_ICO_RUN,
        enabled=True,
        color="",
        tooltip="Запустить",
    )


def _action_item(
    text: str,
    *,
    enabled: bool,
    color: str,
    tooltip: str = "",
) -> QTableWidgetItem:
    c = TABLE_TEXT if enabled else TABLE_TEXT_MUTED
    it = _launch_item(
        text,
        color=c,
        align=Qt.AlignmentFlag.AlignCenter,
        bold=enabled,
    )
    if tooltip:
        it.setToolTip(tooltip)
    return it


def _token_status_label(status: str | None) -> tuple[str, str, bool]:
    s = (status or "new").strip()
    if s == "OK":
        return "Живой", TABLE_TEXT, True
    if s == "dead":
        return "Мёртвый", TABLE_TEXT, True
    if s == "checking":
        return "Проверка…", TABLE_TEXT, False
    if s == "error":
        return "Ошибка", TABLE_TEXT, True
    if s == "new":
        return "Не проверен", TABLE_TEXT, False
    return s, TABLE_TEXT, True


def _fill_launch_row(
    window: Any,
    table: QTableWidget,
    row: int,
    fname: str,
    *,
    session_dir: str,
    active: set[str],
) -> None:
    is_active = fname in active
    is_manual = _is_manual_session(fname)
    checked = set(getattr(window, "_checker_checked", None) or ())
    results = getattr(window, "token_results", {}) or {}

    if not is_manual:
        cb_item = QTableWidgetItem()
        cb_item.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
        )
        cb_item.setCheckState(
            Qt.CheckState.Checked if fname in checked else Qt.CheckState.Unchecked
        )
        cb_item.setData(Qt.ItemDataRole.UserRole, fname)
        table.setItem(row, _COL_CB, cb_item)
    else:
        table.setItem(row, _COL_CB, _launch_item(""))

    status_text, status_color, status_bold = _token_status_label(results.get(fname))
    table.setItem(
        row,
        _COL_STATUS,
        _launch_item(
            status_text,
            color=status_color,
            align=Qt.AlignmentFlag.AlignCenter,
            bold=status_bold,
        ),
    )

    if is_manual:
        display = f"[РУЧНОЙ] {fname.replace('.txt', '')}"
    elif is_active:
        display = f"▶ {fname.upper()}"
    else:
        display = fname.upper()

    file_item = _launch_item(
        display,
        userdata=fname,
        bold=is_active,
    )
    table.setItem(row, _COL_FILE, file_item)

    if is_manual:
        comment_item = _launch_item(
            "web.max.ru · без токена",
            userdata=fname,
        )
    else:
        comment_item = _launch_item(
            meta.get_comment(session_dir, fname),
            editable=True,
            userdata=fname,
        )
    table.setItem(row, _COL_COMMENT, comment_item)

    added = "—" if is_manual else meta.get_added_display(session_dir, fname)
    table.setItem(
        row,
        _COL_ADDED,
        _launch_item(added, align=Qt.AlignmentFlag.AlignCenter),
    )

    lastrun_txt = "—" if is_manual else meta.get_last_launch_display(session_dir, fname)
    lastrun_item = _launch_item(
        lastrun_txt,
        align=Qt.AlignmentFlag.AlignCenter,
        bold=is_active,
    )
    table.setItem(row, _COL_LASTRUN, lastrun_item)

    table.setItem(
        row,
        _COL_ACT_TOGGLE,
        _toggle_action_item(is_active=is_active, is_manual=is_manual),
    )
    table.setItem(
        row,
        _COL_ACT_RAW,
        _action_item(
            _LAUNCH_ICO_RAW,
            enabled=not is_manual,
            color="",
            tooltip="Показать RAW",
        ),
    )
    table.setItem(
        row,
        _COL_ACT_SHOW,
        _action_item(
            _LAUNCH_ICO_SHOW,
            enabled=is_active,
            color="",
            tooltip="Показать окно браузера",
        ),
    )
    table.setItem(
        row,
        _COL_ACT_DEL,
        _action_item(
            _LAUNCH_ICO_DEL,
            enabled=not is_active and not is_manual,
            color="",
            tooltip="Удалить",
        ),
    )
    table.setRowHeight(row, 38)
    window._session_label_cache[fname] = {}


def _finish_launch_table_render(window: Any, table: QTableWidget) -> None:
    table.setUpdatesEnabled(True)
    window._launch_table_loading = False
    table.viewport().update()
    try:
        from checker_panel import _update_select_all_btn_text

        _update_select_all_btn_text(window)
    except Exception:
        pass


def _recent_sort_value(
    fname: str, data: dict, active: set[str], session_dir: str
) -> float:
    """Сортировка списка: активные сверху, затем по дате последнего запуска/добавления."""
    if fname in active:
        return float("inf")
    from datetime import datetime

    entry = data.get(fname, {}) if isinstance(data, dict) else {}
    if isinstance(entry, dict):
        for key in ("last_launch_at", "added_at"):
            value = entry.get(key)
            if value:
                try:
                    return datetime.fromisoformat(str(value)).timestamp()
                except Exception:
                    pass
    try:
        return os.path.getmtime(token_path(session_dir, fname))
    except OSError:
        return 0.0


def _render_launch_table(window: Any, module: Any) -> None:
    table = _ensure_launch_table(window, module)
    if table is None:
        return

    session_dir = getattr(window, "session_dir", "") or ""
    if not session_dir or not os.path.isdir(session_dir):
        table.setRowCount(0)
        window._session_label_cache = {}
        return

    meta.sync_from_disk(session_dir)
    active = set(getattr(window, "active_drivers", {}).keys())
    meta.sync_run_state(session_dir, active)
    # Запоминаем, какой набор активных сейчас нарисован — монитор сравнивает с ним,
    # чтобы перерисовать таблицу, когда браузер открылся/закрылся асинхронно.
    window._last_rendered_active = set(active)

    files = list_gui_files(session_dir)
    manual_extra = sorted(
        f for f in active if _is_manual_session(f) and f not in files
    )
    all_files = files + manual_extra

    data = meta.load(session_dir)
    all_files.sort(
        key=lambda fn: _recent_sort_value(fn, data, active, session_dir),
        reverse=True,
    )

    window._launch_table_loading = True
    table.setUpdatesEnabled(False)
    table.setSortingEnabled(False)
    table.clearContents()
    table.setRowCount(len(all_files))
    window._session_label_cache = {}

    if len(all_files) <= _TABLE_BATCH_THRESHOLD:
        for row, fname in enumerate(all_files):
            _fill_launch_row(
                window, table, row, fname, session_dir=session_dir, active=active
            )
        _finish_launch_table_render(window, table)
        return

    cursor = {"i": 0}

    def _batch() -> None:
        start = cursor["i"]
        end = min(start + _TABLE_BATCH_SIZE, len(all_files))
        for row in range(start, end):
            _fill_launch_row(
                window,
                table,
                row,
                all_files[row],
                session_dir=session_dir,
                active=active,
            )
        cursor["i"] = end
        if end < len(all_files):
            QTimer.singleShot(0, _batch)
        else:
            _finish_launch_table_render(window, table)

    _batch()


def render_sessions_extended(self, module: Any) -> None:
    _render_launch_table(self, module)


def _border_color(is_active: bool, profile_exists: bool) -> str:
    if is_active:
        return SUCCESS
    if profile_exists:
        return ACCENT
    return TEXT


def _btn_box_style(active: bool, color: str) -> str:
    if active:
        return (
            f"color: {color}; border-color: {color}; "
            "font-size: 11px; font-weight: 600; background: transparent;"
        )
    return (
        "color: rgba(241,245,249,0); border-color: rgba(255,255,255,0.06); "
        "font-size: 11px; font-weight: 600; background: transparent;"
    )


def _cache_session_labels(window: Any, fname: str, **labels: QLabel) -> None:
    cache = getattr(window, "_session_label_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        window._session_label_cache = cache
    cache[fname] = labels


def _build_session_row(window: Any, module: Any, fname: str) -> QFrame:
    session_dir = window.session_dir
    is_active = fname in window.active_drivers
    profile_name = fname.replace(".txt", "")
    profile_exists = os.path.isdir(os.path.join(window.profiles_dir, profile_name))

    card = module.QFrame()
    card.setObjectName("SessionItem")
    card.setFixedHeight(_row_height())
    border = _border_color(is_active, profile_exists)
    card.setStyleSheet(
        "QFrame#SessionItem { background: rgba(255,255,255,0.05); "
        f"border: 1px solid {border}; border-radius: 10px; }}"
    )

    row = module.QHBoxLayout(card)
    row.setContentsMargins(20, 8, 12, 8)
    row.setSpacing(10)

    display = f"[ACTIVE] {fname.upper()}" if is_active else fname.upper()
    name_lbl = module.QLabel(display)
    name_lbl.setFixedWidth(150)
    name_lbl.setStyleSheet(
        f"font-size: 12px; font-weight: 600; color: {SUCCESS if is_active else TEXT}; "
        "border: none;"
    )
    row.addWidget(name_lbl)

    comment = module.QLineEdit()
    comment.setPlaceholderText("Заметка менеджера…")
    comment.setText(meta.get_comment(session_dir, fname))
    comment.setStyleSheet(
        f"color: {TEXT}; background: rgba(255,255,255,0.06); "
        "border: 1px solid rgba(255,255,255,0.12); border-radius: 8px; padding: 6px 10px;"
    )

    def _save_comment(_checked=False, fn=fname, field=comment):
        try:
            meta.set_comment(session_dir, fn, field.text().strip())
        except (RuntimeError, Exception):
            pass

    if load_settings().get("autosave_comments", True):
        debounce = QTimer(comment)
        debounce.setSingleShot(True)
        debounce.setInterval(700)

        def _debounced_save(_text="", t=debounce):
            try:
                t.start()
            except (RuntimeError, Exception):
                pass

        def _do_save(fn=fname, field=comment):
            try:
                meta.set_comment(session_dir, fn, field.text().strip())
            except (RuntimeError, Exception):
                pass

        debounce.timeout.connect(_do_save)
        comment.textChanged.connect(_debounced_save)
    else:
        comment.editingFinished.connect(_save_comment)
    row.addWidget(comment, 1)

    date_lbl = module.QLabel(meta.get_added_display(session_dir, fname))
    date_lbl.setFixedWidth(108)
    date_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; border: none;")
    row.addWidget(date_lbl)

    runtime_lbl = module.QLabel(meta.get_runtime_display(session_dir, fname, is_active))
    runtime_lbl.setObjectName("SessionRuntimeLabel")
    runtime_lbl.setProperty("session_file", fname)
    runtime_lbl.setFixedWidth(88)
    runtime_lbl.setStyleSheet(
        f"color: {SUCCESS if is_active else TEXT_DIM}; font-size: 11px; "
        "font-weight: 600; border: none;"
    )
    row.addWidget(runtime_lbl)

    stopped_lbl = module.QLabel(
        meta.get_stopped_display(session_dir, fname, is_active)
    )
    stopped_lbl.setObjectName("SessionStoppedLabel")
    stopped_lbl.setProperty("session_file", fname)
    stopped_lbl.setFixedWidth(108)
    stopped_lbl.setStyleSheet(
        f"color: {TEXT_DIM}; font-size: 11px; border: none;"
    )
    row.addWidget(stopped_lbl)

    conn_lbl = module.QLabel(_connection_label_text(session_dir, fname))
    conn_lbl.setObjectName("SessionConnectionLabel")
    conn_lbl.setProperty("session_file", fname)
    conn_lbl.setFixedWidth(140)
    conn_lbl.setWordWrap(True)
    conn_lbl.setStyleSheet(
        f"color: {TEXT_DIM}; font-size: 10px; border: none; line-height: 1.2;"
    )
    row.addWidget(conn_lbl)

    btn_stop = _mk_btn(module, "СТОП", DANGER, _BTN_W[0], 30)
    btn_stop.setEnabled(is_active)
    btn_stop.setStyleSheet(_btn_box_style(is_active, DANGER))
    if is_active:
        btn_stop.clicked.connect(lambda _=False, n=fname: window.stop_session(n))

    btn_show = _mk_btn(module, "ПОКАЗАТЬ", ACCENT, _BTN_W[1], 30)
    btn_show.clicked.connect(lambda _=False, n=fname: window.focus_browser_window(n))

    btn_raw = _mk_btn(module, "RAW", ACCENT, _BTN_W[2], 30)
    btn_raw.clicked.connect(lambda _=False, n=fname: window.show_raw_content(n))

    btn_run = _mk_btn(module, "ЗАПУСК", TEXT, _BTN_W[3], 30)
    btn_run.setEnabled(not is_active)
    btn_run.clicked.connect(lambda _=False, n=fname: window.launch(n))

    btn_del = _mk_btn(module, "УДАЛИТЬ", DANGER, _BTN_W[4], 30)
    btn_del.setEnabled(not is_active)
    btn_del.clicked.connect(lambda _=False, b=btn_del, n=fname: window.confirm_delete(b, n))

    btn_box = QWidget()
    btn_box.setFixedWidth(_BTN_BOX_W)
    btn_lay = QHBoxLayout(btn_box)
    btn_lay.setContentsMargins(0, 0, 0, 0)
    btn_lay.setSpacing(_BTN_SP)
    for b in (btn_stop, btn_show, btn_raw, btn_run, btn_del):
        btn_lay.addWidget(b)
    row.addWidget(btn_box)

    _cache_session_labels(
        window,
        fname,
        runtime=runtime_lbl,
        stopped=stopped_lbl,
        connection=conn_lbl,
    )

    return card


def _build_manual_session_row(window: Any, module: Any, fname: str) -> QFrame:
    """Строка для ручного окна (без .txt на диске)."""
    session_dir = window.session_dir
    is_active = fname in window.active_drivers

    card = module.QFrame()
    card.setObjectName("SessionItem")
    card.setFixedHeight(_row_height())
    border = SUCCESS if is_active else ACCENT
    card.setStyleSheet(
        "QFrame#SessionItem { background: rgba(255,255,255,0.05); "
        f"border: 1px solid {border}; border-radius: 10px; }}"
    )

    row = module.QHBoxLayout(card)
    row.setContentsMargins(20, 8, 12, 8)
    row.setSpacing(10)

    name_lbl = module.QLabel(f"[РУЧНОЙ] {fname.replace('.txt', '')}")
    name_lbl.setFixedWidth(150)
    name_lbl.setStyleSheet(
        f"font-size: 12px; font-weight: 600; color: {SUCCESS if is_active else ACCENT}; "
        "border: none;"
    )
    row.addWidget(name_lbl)

    hint = module.QLabel("web.max.ru · без токена")
    hint.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; border: none;")
    row.addWidget(hint, 1)

    date_lbl = module.QLabel("—")
    date_lbl.setFixedWidth(108)
    date_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; border: none;")
    row.addWidget(date_lbl)

    runtime_lbl = module.QLabel(
        meta.get_runtime_display(session_dir, fname, is_active)
    )
    runtime_lbl.setObjectName("SessionRuntimeLabel")
    runtime_lbl.setProperty("session_file", fname)
    runtime_lbl.setFixedWidth(88)
    runtime_lbl.setStyleSheet(
        f"color: {SUCCESS if is_active else TEXT_DIM}; font-size: 11px; "
        "font-weight: 600; border: none;"
    )
    row.addWidget(runtime_lbl)

    stopped_lbl = module.QLabel(
        meta.get_stopped_display(session_dir, fname, is_active)
    )
    stopped_lbl.setObjectName("SessionStoppedLabel")
    stopped_lbl.setProperty("session_file", fname)
    stopped_lbl.setFixedWidth(108)
    stopped_lbl.setStyleSheet(
        f"color: {TEXT_DIM}; font-size: 11px; border: none;"
    )
    row.addWidget(stopped_lbl)

    conn_lbl = module.QLabel(_connection_label_text(session_dir, fname))
    conn_lbl.setObjectName("SessionConnectionLabel")
    conn_lbl.setProperty("session_file", fname)
    conn_lbl.setFixedWidth(140)
    conn_lbl.setWordWrap(True)
    conn_lbl.setStyleSheet(
        f"color: {TEXT_DIM}; font-size: 10px; border: none; line-height: 1.2;"
    )
    row.addWidget(conn_lbl)

    btn_stop = _mk_btn(module, "СТОП", DANGER, _BTN_W[0], 30)
    btn_stop.setEnabled(is_active)
    btn_stop.setStyleSheet(_btn_box_style(is_active, DANGER))
    if is_active:
        btn_stop.clicked.connect(lambda _=False, n=fname: window.stop_session(n))

    btn_show = _mk_btn(module, "ПОКАЗАТЬ", ACCENT, _BTN_W[1], 30)
    btn_show.setEnabled(is_active)
    btn_show.setStyleSheet(_btn_box_style(is_active, ACCENT))
    if is_active:
        btn_show.clicked.connect(lambda _=False, n=fname: window.focus_browser_window(n))

    btn_raw = _mk_btn(module, "RAW", ACCENT, _BTN_W[2], 30)
    btn_raw.setEnabled(False)
    btn_raw.setStyleSheet(_btn_box_style(False, ACCENT))

    btn_run = _mk_btn(module, "ЗАПУСК", TEXT, _BTN_W[3], 30)
    btn_run.setEnabled(False)

    btn_del = _mk_btn(module, "УДАЛИТЬ", DANGER, _BTN_W[4], 30)
    btn_del.setEnabled(False)

    btn_box = QWidget()
    btn_box.setFixedWidth(_BTN_BOX_W)
    btn_lay = QHBoxLayout(btn_box)
    btn_lay.setContentsMargins(0, 0, 0, 0)
    btn_lay.setSpacing(_BTN_SP)
    for b in (btn_stop, btn_show, btn_raw, btn_run, btn_del):
        btn_lay.addWidget(b)
    row.addWidget(btn_box)

    _cache_session_labels(
        window,
        fname,
        runtime=runtime_lbl,
        stopped=stopped_lbl,
        connection=conn_lbl,
    )

    return card


def _mk_btn(module: Any, text: str, color: str, w: int, h: int) -> QPushButton:
    btn = module.QPushButton(text)
    btn.setObjectName("GhostBtn")
    btn.setFixedSize(w, h)
    btn.setCursor(module.Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"color: {color}; border-color: {color}; "
        "font-size: 11px; font-weight: 600; background: transparent;"
    )
    return btn


def _patch_render_sessions(DotLauncher: type, module: Any) -> None:
    def render_sessions(self):
        try:
            render_sessions_extended(self, module)
        except Exception:
            _log.exception("render_sessions_extended failed")
            return
        try:
            _tick_runtime_labels(self)
        except Exception:
            _log.exception("_tick_runtime_labels failed")
        _ensure_runtime_timer(self)

    DotLauncher.render_sessions = render_sessions


def _patch_import_sessions(DotLauncher: type) -> None:
    orig = DotLauncher.import_sessions

    def import_sessions(self):
        before = set()
        sd = getattr(self, "session_dir", "")
        if os.path.isdir(sd):
            before = set(list_gui_files(sd))
        orig(self)
        if os.path.isdir(sd):
            after = set(list_gui_files(sd))
            for f in after - before:
                meta.touch_new(sd, f)
                analytics.record_new_token(sd, f)

    DotLauncher.import_sessions = import_sessions


def _patch_add_manual(DotLauncher: type) -> None:
    orig = DotLauncher.add_manual_session

    def add_manual_session(self):
        orig(self)
        sd = getattr(self, "session_dir", "")
        if os.path.isdir(sd):
            meta.sync_from_disk(sd)

    DotLauncher.add_manual_session = add_manual_session


def _patch_confirm_delete(DotLauncher: type) -> None:
    orig = DotLauncher.confirm_delete

    def confirm_delete(self, btn, fname):
        sd = getattr(self, "session_dir", "")
        path = os.path.join(sd, fname) if sd else ""
        existed = os.path.isfile(path)
        orig(self, btn, fname)
        if existed and sd and not os.path.isfile(path):
            meta.remove(sd, fname)
        state = getattr(self, "_session_watch_state", None)
        if isinstance(state, dict):
            state.pop(fname, None)

    DotLauncher.confirm_delete = confirm_delete


def _active_names(window: Any) -> set[str]:
    return set(getattr(window, "active_drivers", {}).keys())


def _tick_runtime_labels(window: Any) -> None:
    sd = getattr(window, "session_dir", "")
    if not sd:
        return
    active = _active_names(window)
    if not active:
        timer = getattr(window, "_runtime_timer", None)
        if timer and timer.isActive():
            timer.stop()
    try:
        data = meta.load(sd)
    except Exception:
        data = {}

    cache = getattr(window, "_session_label_cache", None)
    if isinstance(cache, dict) and cache:
        items = []
        for fname, labels in list(cache.items()):
            if not isinstance(labels, dict):
                continue
            items.append((fname, "SessionRuntimeLabel", labels.get("runtime")))
            items.append((fname, "SessionStoppedLabel", labels.get("stopped")))
    else:
        try:
            items = [
                (lbl.property("session_file"), lbl.objectName(), lbl)
                for lbl in window.findChildren(QLabel)
            ]
        except (RuntimeError, Exception):
            return

    for fname, name, lbl in items:
        try:
            if lbl is None:
                continue
            if name not in (
                "SessionRuntimeLabel",
                "SessionStoppedLabel",
            ):
                continue
            if not fname:
                continue
            entry = data.get(fname, {})
            is_active = fname in active
            is_table_item = isinstance(lbl, QTableWidgetItem)
            if name == "SessionRuntimeLabel":
                total = meta._total_run_seconds(entry)
                if is_active:
                    txt = meta.format_seconds(total) + " ▶"
                elif total > 0:
                    txt = meta.format_seconds(total)
                else:
                    txt = "—"
                lbl.setText(txt)
                if is_table_item:
                    brush = QColor(TABLE_TEXT)
                    lbl.setForeground(brush)
                    lbl.setData(Qt.ItemDataRole.ForegroundRole, brush)
                    from PyQt6.QtGui import QFont

                    fnt = lbl.font()
                    fnt.setBold(is_active)
                    lbl.setFont(fnt)
                else:
                    active_prop = "1" if is_active else "0"
                    if lbl.property("active_state") != active_prop:
                        lbl.setProperty("active_state", active_prop)
                        lbl.setStyleSheet(
                            f"color: {SUCCESS if is_active else TEXT_DIM}; font-size: 11px; "
                            "font-weight: 600; border: none;"
                        )
            elif name == "SessionStoppedLabel":
                lbl.setText(meta.get_stopped_display(sd, fname, is_active))
        except (RuntimeError, Exception):
            continue


def _connection_text_from_entry(entry: dict) -> str:
    ip = str(entry.get("connection_ip") or "").strip()
    country = str(entry.get("connection_country") or "").strip()
    if ip and country and country != "—":
        return f"{ip} · {country}"
    if ip:
        return ip
    proxy = str(entry.get("connection_proxy") or "").strip()
    if proxy:
        host = meta._parse_proxy_host(proxy)
        return host or "…"
    return "—"


def _ip_history_text_from_entry(entry: dict) -> str:
    hist = entry.get("ip_history") or []
    parts: list[str] = []
    for h in hist[-5:]:
        if isinstance(h, dict):
            parts.append(str(h.get("ip", "?")))
    cur = str(entry.get("connection_ip") or "").strip()
    if cur and (not parts or parts[-1] != cur):
        parts.append(cur)
    return " → ".join(parts) if parts else "—"


def _attach_runtime_timer(window: Any, module: Any) -> None:
    timer = QTimer(window)
    timer.setInterval(1000)
    timer.timeout.connect(lambda: _tick_runtime_labels(window))
    window._runtime_timer = timer


def _ensure_runtime_timer(window: Any) -> None:
    timer = getattr(window, "_runtime_timer", None)
    if not timer:
        return
    if _active_names(window):
        if not timer.isActive():
            timer.start()
    else:
        timer.stop()


def _begin_session_watch(window: Any, fname: str, proxy_raw: str | None) -> None:
    if not hasattr(window, "_session_watch_state"):
        window._session_watch_state = {}
    window._session_watch_state[fname] = {
        "grace_until": time.time() + _MONITOR_GRACE_SEC,
        "had_auth": False,
        "proxy": proxy_raw or "",
    }
    sd = getattr(window, "session_dir", "")
    if sd:
        if (proxy_raw or "").strip():
            meta.set_connection_proxy(sd, fname, proxy_raw)
        meta.start_run(sd, fname)
        cache = getattr(window, "proxy_cache", {})
        had_proxy = bool((proxy_raw or "").strip()) and cache.get(
            (proxy_raw or "").strip(), {}
        ).get("st") == "OK"
        analytics.record_launch(sd, fname, had_proxy=had_proxy)


def _end_session_watch(window: Any, fname: str) -> None:
    state = getattr(window, "_session_watch_state", None)
    if isinstance(state, dict):
        state.pop(fname, None)


def _cdp_port_for_driver(driver, fname: str = "", window: Any | None = None) -> int:
    sess = getattr(driver, "_mx_playwright_session", None)
    if sess is not None:
        port = int(getattr(sess, "cdp_port", 0) or 0)
        if port:
            return port
    if window is not None and fname:
        ports = getattr(window, "_mx_debug_ports", None) or {}
        port = int(ports.get(fname) or 0)
        if port:
            return port
    return 0


def _driver_alive(driver, fname: str = "", window: Any | None = None) -> bool:
    try:
        port = _cdp_port_for_driver(driver, fname, window)
        if port:
            return is_browser_window_alive(port)

        from browser_session import is_session_alive

        sess = getattr(driver, "_mx_playwright_session", None)
        if sess is not None:
            return is_session_alive(sess)
        handles = driver.window_handles
        return bool(handles)
    except Exception:
        return False


def _stop_session_tracked(window: Any, fname: str, reason: str) -> None:
    active = getattr(window, "active_drivers", {}) or {}
    if fname not in active:
        state = getattr(window, "_session_watch_state", None)
        if isinstance(state, dict):
            state.pop(fname, None)
        return

    sd = getattr(window, "session_dir", "")
    delta = 0.0
    if sd:
        entry = meta.load(sd).get(fname, {})
        started = entry.get("run_started_at")
        if started:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(str(started))
                delta = (datetime.now().astimezone() - dt).total_seconds()
            except Exception:
                pass
    if sd:
        meta.stop_run(sd, fname)
        if delta > 0:
            analytics.record_run_seconds(sd, delta)

    active = getattr(window, "active_drivers", {})
    driver = active.pop(fname, None)
    if driver:
        try:
            browser_prefs.capture_window_size_from_driver(driver)
        except Exception:
            pass
        try:
            driver.quit()
        except Exception:
            pass
    unregister_session(fname)

    applied = getattr(window, "_browser_prefs_applied", set())
    if isinstance(applied, set):
        applied.discard(fname)
    window._browser_prefs_applied = applied

    _end_session_watch(window, fname)

    _schedule_render(window)

    msgs = {
        "closed": "окно закрыто",
        "logout": "сессия сброшена",
        "landing": "выход на web.max.ru",
    }
    if reason in msgs:
        window.signals.notify.emit(f"{fname}: {msgs[reason]}", "#f59e0b")


def _apply_browser_prefs_for_active(window: Any) -> None:
    """Когда драйвер появился в active_drivers — размер и заголовок вкладки."""
    applied: set[str] = getattr(window, "_browser_prefs_applied", set())
    active = getattr(window, "active_drivers", {}) or {}
    sd = getattr(window, "session_dir", "")
    for fname, driver in list(active.items()):
        if not driver or fname in applied:
            continue
        try:
            browser_prefs.apply_browser_prefs(driver, sd, fname)
            applied.add(fname)
        except Exception:
            _log.exception("apply_browser_prefs failed: %s", fname)
    window._browser_prefs_applied = applied


def _ui_tick_monitor(window: Any) -> None:
    """Лёгкая часть монитора — обновление подписей. Без selenium."""
    active = _active_names(window)
    # Набор активных изменился (браузер открылся/закрылся в фоне) — перерисовать
    # таблицу, иначе значок ▶/⏹ не переключится.
    if active != getattr(window, "_last_rendered_active", set()):
        _schedule_render(window)
    # Нет активных окон — нечего пересчитывать, не трогаем диск каждые 2.5с.
    if not active and not getattr(window, "_session_watch_state", None):
        _ensure_runtime_timer(window)
        return

    sd = getattr(window, "session_dir", "")
    if sd:
        try:
            meta.sync_run_state(sd, active)
        except Exception:
            pass
    _apply_browser_prefs_for_active(window)
    _tick_runtime_labels(window)
    _ensure_runtime_timer(window)


def _monitor_worker(window: Any, stop_event: threading.Event) -> None:
    """Фоновый поток: дергает selenium и шлёт сигналы в UI."""
    bridge: _MonitorBridge = window._monitor_bridge
    while not stop_event.is_set():
        try:
            active = dict(getattr(window, "active_drivers", {}) or {})
            watch_state = getattr(window, "_session_watch_state", {}) or {}
            sd = getattr(window, "session_dir", "")
            for fname, driver in list(active.items()):
                if stop_event.is_set():
                    return
                if driver is None:
                    continue
                try:
                    browser_prefs.refresh_tab_title(driver, sd, fname)
                except Exception:
                    pass
                try:
                    reason = _check_session_should_stop_bg(
                        watch_state.get(fname, {}), fname, driver, window
                    )
                except Exception:
                    _log.exception("session check failed: %s", fname)
                    reason = None
                if reason and not stop_event.is_set():
                    try:
                        bridge.stop_requested.emit(fname, reason)
                    except (RuntimeError, Exception):
                        return
        except Exception:
            _log.exception("monitor loop error")
        stop_event.wait(_MONITOR_INTERVAL_SEC)


def _check_session_should_stop_bg(
    state: dict, fname: str, driver, window: Any | None = None
) -> str | None:
    """Версия для фонового потока — пишет в state-снимок без UI-влияния."""
    if not _driver_alive(driver, fname, window):
        return "closed"

    grace_until = float(state.get("grace_until") or 0)
    had_auth = bool(state.get("had_auth"))

    if time.time() < grace_until:
        return None

    logged_out = meta.is_max_logged_out(driver)
    if logged_out is False:
        state["had_auth"] = True
        return None

    if logged_out is True and had_auth:
        return "logout"

    try:
        url = driver.current_url or ""
    except Exception:
        return "closed"

    if had_auth and meta.is_max_landing_url(url):
        return "landing"

    return None


def _attach_session_monitor(window: Any) -> None:
    bridge = _MonitorBridge(window)
    bridge.stop_requested.connect(
        lambda fname, reason: _stop_session_tracked(window, fname, reason)
    )
    bridge.import_finished.connect(lambda ok, err: _on_import_finished(window, ok, err))
    window._monitor_bridge = bridge

    stop_event = threading.Event()
    window._monitor_stop_event = stop_event

    thread = threading.Thread(
        target=_monitor_worker, args=(window, stop_event), daemon=True
    )
    thread.start()
    window._monitor_thread = thread

    timer = QTimer(window)
    timer.setInterval(2500)
    timer.timeout.connect(lambda: _ui_tick_monitor(window))
    timer.start()
    window._session_monitor_timer = timer

    def _shutdown(*_args):
        stop_event.set()

    if hasattr(window, "destroyed"):
        try:
            window.destroyed.connect(_shutdown)
        except Exception:
            pass


def _on_import_finished(window: Any, ok: int, err: int) -> None:
    try:
        sd = getattr(window, "session_dir", "")
        if sd:
            meta.sync_from_disk(sd)
        _schedule_render(window)
        if hasattr(window, "render_checker"):
            window.render_checker()
        color = ACCENT if ok else DANGER
        window.signals.notify.emit(f"Добавлено: {ok} | Ошибок: {err}", color)
    except Exception:
        _log.exception("import_finished ui update failed")


def _seleniumwire_port_of(driver: Any) -> int:
    """Совместимость — см. browser_launcher.seleniumwire_port_of."""
    from browser_launcher import seleniumwire_port_of

    return seleniumwire_port_of(driver)


def _install_seleniumwire_port_capture() -> None:
    from browser_launcher import _install_seleniumwire_port_capture as _install

    _install()


def _patch_antidetect_connection(DotLauncher: type) -> None:
    orig = DotLauncher.antidetect_browser

    def antidetect_browser(self, proxy_raw, js, session_name, *args, **kwargs):
        try:
            _begin_session_watch(self, session_name, proxy_raw)
        except Exception:
            _log.exception("begin_session_watch failed: %s", session_name)
        try:
            driver = orig(self, proxy_raw, js, session_name, *args, **kwargs)
        except Exception:
            _log.exception("antidetect_browser failed: %s", session_name)
            _end_session_watch(self, session_name)
            sd = getattr(self, "session_dir", "")
            if sd:
                try:
                    meta.stop_run(sd, session_name)
                except Exception:
                    pass
            return None
        if driver:
            sd = getattr(self, "session_dir", "")
            sid = get_or_create_session_id(sd, session_name)
            port = (getattr(self, "_mx_debug_ports", {}) or {}).get(session_name, 0)
            from browser_engine import use_playwright
            from browser_launcher import seleniumwire_port_of

            if use_playwright():
                sess = getattr(driver, "_mx_playwright_session", None)
                proxy_port = int(getattr(sess, "relay_port", 0) or 0)
            else:
                proxy_port = seleniumwire_port_of(driver)
            _log.info(
                "session start: %s engine=%s cdp=%s proxy_port=%s proxy=%s",
                session_name,
                "playwright" if use_playwright() else "selenium",
                port,
                proxy_port,
                str(proxy_raw or "")[:80],
            )
            register_session(
                session_name,
                port=port,
                session_id=sid,
                profile_dir=last_profile_dir(),
                proxy_raw=str(proxy_raw or ""),
                proxy_port=proxy_port,
            )
            try:
                browser_prefs.apply_browser_prefs(driver, sd, session_name)
            except Exception:
                pass
            try:
                from browser_session import install_browser_close_handler

                bridge = getattr(self, "_monitor_bridge", None)
                if bridge is not None:

                    def _on_browser_closed(
                        name: str = session_name,
                        br: _MonitorBridge = bridge,
                    ) -> None:
                        br.stop_requested.emit(name, "closed")

                    install_browser_close_handler(driver, _on_browser_closed)
            except Exception:
                _log.exception("install_browser_close_handler failed: %s", session_name)
        return driver

    DotLauncher.antidetect_browser = antidetect_browser


def _patch_runtime_tracking(DotLauncher: type) -> None:
    orig_launch = DotLauncher.launch
    orig_stop = DotLauncher.stop_session
    orig_status = DotLauncher.handle_browser_status

    def launch(self, fname):
        for need_dir in ("session_dir", "profiles_dir"):
            p = getattr(self, need_dir, "")
            if p:
                try:
                    os.makedirs(p, exist_ok=True)
                except Exception:
                    _log.exception("Cannot mkdir %s=%s", need_dir, p)
        try:
            orig_launch(self, fname)
        except FileNotFoundError as ex:
            _log.exception("FileNotFoundError в launch(%s): %s", fname, ex)
            if hasattr(self, "signals"):
                self.signals.notify.emit(
                    f"Файл не найден: {ex.filename or ex}", "#f43f5e"
                )
        except Exception as ex:
            _log.exception("Ошибка в launch(%s): %s", fname, ex)
            if hasattr(self, "signals"):
                self.signals.notify.emit(
                    f"Ошибка запуска: {type(ex).__name__}", "#f43f5e"
                )
        _ensure_runtime_timer(self)

    def stop_session(self, fname):
        sd = getattr(self, "session_dir", "")
        delta = 0.0
        if sd:
            entry = meta.load(sd).get(fname, {})
            started = entry.get("run_started_at")
            if started:
                try:
                    from datetime import datetime

                    dt = datetime.fromisoformat(str(started))
                    delta = (
                        datetime.now().astimezone() - dt
                    ).total_seconds()
                except Exception:
                    pass
        driver = getattr(self, "active_drivers", {}).get(fname)
        if driver:
            try:
                browser_prefs.capture_window_size_from_driver(driver)
            except Exception:
                pass
        orig_stop(self, fname)
        unregister_session(fname)
        if sd:
            meta.stop_run(sd, fname)
            if delta > 0:
                analytics.record_run_seconds(sd, delta)
        applied = getattr(self, "_browser_prefs_applied", set())
        if isinstance(applied, set):
            applied.discard(fname)
        self._browser_prefs_applied = applied
        _end_session_watch(self, fname)
        if sd:
            meta.sync_run_state(sd, _active_names(self))
        _schedule_render(self)
        _ensure_runtime_timer(self)

    def handle_browser_status(self):
        sd = getattr(self, "session_dir", "")
        if sd:
            try:
                meta.sync_run_state(sd, _active_names(self))
            except Exception:
                pass
        try:
            orig_status(self)
        except Exception:
            pass
        # active_drivers мог измениться (браузер открылся/закрылся) — обновляем
        # таблицу, чтобы значок ▶/⏹ переключился сразу.
        if _active_names(self) != getattr(self, "_last_rendered_active", set()):
            _schedule_render(self)
        _tick_runtime_labels(self)
        _ensure_runtime_timer(self)

    DotLauncher.launch = launch
    DotLauncher.stop_session = stop_session
    DotLauncher.handle_browser_status = handle_browser_status


def _patch_launch_manual(DotLauncher: type) -> None:
    def launch_manual(self):
        for need_dir in ("session_dir", "profiles_dir"):
            p = getattr(self, need_dir, "")
            if p:
                try:
                    os.makedirs(p, exist_ok=True)
                except Exception:
                    _log.exception("Cannot mkdir %s=%s", need_dir, p)

        from datetime import datetime

        fname = f"{_MANUAL_PREFIX}{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        proxy, proxy_ok = _pick_launch_proxy(self)

        if hasattr(self, "signals"):
            if proxy:
                note = "рабочий" if proxy_ok else "не проверен"
                self.signals.notify.emit(
                    f"Ручной запуск {_MAX_URL}\nПрокси ({note}): {proxy[:80]}",
                    "#6366f1",
                )
            else:
                self.signals.notify.emit(
                    f"Ручной запуск {_MAX_URL}\nПрокси не задан — без прокси",
                    "#f59e0b",
                )

        def worker() -> None:
            try:
                driver = self.antidetect_browser(proxy, _MANUAL_JS, fname)
                if driver:
                    try:
                        driver.get(_MAX_URL)
                    except Exception:
                        _log.exception("navigate manual %s failed", fname)
                    _schedule_render(self)
                    _ensure_runtime_timer(self)
                else:
                    sd = getattr(self, "session_dir", "")
                    if sd:
                        meta.stop_run(sd, fname)
                    _end_session_watch(self, fname)
                    _schedule_render(self)
            except Exception:
                _log.exception("launch_manual failed: %s", fname)
                _end_session_watch(self, fname)
                sd = getattr(self, "session_dir", "")
                if sd:
                    meta.stop_run(sd, fname)
                if hasattr(self, "signals"):
                    self.signals.notify.emit(
                        "Не удалось открыть ручное окно — см. лог",
                        "#f43f5e",
                    )

        threading.Thread(target=worker, daemon=True).start()

    DotLauncher.launch_manual = launch_manual

