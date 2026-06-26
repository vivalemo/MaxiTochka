"""Вкладка «Чекер»: проверка только отмеченных сессий."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import sessions_meta as meta
from app_logger import get_logger
from session_token_parse import extract_session_token, normalize_session_token
from tokenbase import list_gui_files, token_path
from theme import ACCENT, BORDER, DANGER, TEXT, TEXT_DIM, WARNING
from table_ui import (
    TABLE_TEXT,
    TABLE_TEXT_MUTED,
    checker_table_extra_stylesheet,
    setup_resizable_columns,
    table_stylesheet,
)

_log = get_logger("checker")

_CHECK_BTN_MARKERS = ("ПРОВЕРИТЬ ВСЕ", "ПРОВЕРИТЬ ВСЁ", "CHECK ALL")
_CHECK_DELAY_SEC = 1.0
_CHECK_MAX_WORKERS = 5
_CHECKER_TAB_INDEX = 1
_TABLE_BATCH_SIZE = 120
_TABLE_BATCH_THRESHOLD = 200


def _websockets_checker_ok() -> str | None:
    try:
        from websockets.asyncio.client import connect  # noqa: F401

        return None
    except ImportError as ex:
        return str(ex)


def patch_checker_class(DotLauncher: type) -> None:
    """Патч класса до создания окна (на случай ранних вызовов)."""
    if getattr(DotLauncher, "_maxitochka_checker_class_patched", False):
        return
    _patch_start_check_tokens(DotLauncher)
    _patch_check_token_worker(DotLauncher)
    _patch_render_checker(DotLauncher)
    _patch_select_dead_tokens(DotLauncher)
    _patch_delete_selected_tokens(DotLauncher)
    _patch_checker_stats(DotLauncher)
    DotLauncher._maxitochka_checker_class_patched = True  # noqa: SLF001


def install_checker_panel(window: Any, module: Any) -> None:
    DotLauncher = module.DotLauncher
    patch_checker_class(DotLauncher)
    window._checker_checked = set(getattr(window, "_checker_checked", None) or ())
    _rewire_checker_buttons(window, module)
    _rename_check_button(window, module)
    _wire_select_all_btn(window, module)
    miss = _websockets_checker_ok()
    if miss:
        _log.warning("Чекер: websockets не готов (%s)", miss)


def _checker_tab_page(window: Any) -> Any | None:
    page = getattr(window, "l_page", None)
    if page is not None:
        return page
    tabs = getattr(window, "tabs", None)
    if tabs is None or tabs.count() <= _CHECKER_TAB_INDEX:
        return None
    return tabs.widget(_CHECKER_TAB_INDEX)


def _table_checked_files(window: Any) -> set[str] | None:
    """Отмеченные строки из единой таблицы токенов."""
    table = getattr(window, "_launch_table", None) or getattr(
        window, "_checker_table", None
    )
    if not isinstance(table, QTableWidget):
        return None
    picked: set[str] = set()
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is None:
            continue
        if item.checkState() == Qt.CheckState.Checked:
            fname = item.data(Qt.ItemDataRole.UserRole)
            if fname:
                picked.add(fname)
    return picked


def _selected_checker_files(window: Any) -> list[str]:
    """Только отмеченные галочками строки на вкладке чекера."""
    from_table = _table_checked_files(window)
    if from_table is not None:
        window._checker_checked = from_table
        return sorted(from_table)
    return sorted(set(getattr(window, "_checker_checked", None) or ()))


def _sync_checker_checked_from_ui(window: Any) -> None:
    from_table = _table_checked_files(window)
    if from_table is not None:
        window._checker_checked = from_table


def _checker_btns_layout(page: QWidget) -> QHBoxLayout | None:
    """Нижняя строка кнопок чекера (Проверить / Выбрать мёртвые / …)."""
    vlay = page.layout()
    if not isinstance(vlay, QVBoxLayout):
        return None
    markers = ("ПРОВЕР", "МЁРТВ", "МЕРТВ", "УДАЛИТЬ", "ВЫБРАТЬ")
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
            if any(m in t for m in markers):
                return sub
    return None


def _update_select_all_btn_text(window: Any) -> None:
    page = _checker_tab_page(window)
    if page is None:
        return
    btn = page.findChild(QPushButton, "CheckerSelectAllBtn")
    if btn is None:
        return
    table = getattr(window, "_launch_table", None) or getattr(
        window, "_checker_table", None
    )
    if not isinstance(table, QTableWidget):
        btn.setText("Выбрать все")
        return
    total = table.rowCount()
    checked = len(_table_checked_files(window) or set())
    if total > 0 and checked >= total:
        btn.setText("Снять все")
        btn.setToolTip("Снять выбор со всех сессий")
    else:
        btn.setText("Выбрать все")
        btn.setToolTip("Отметить все сессии в списке")


def _select_all_checker(window: Any) -> None:
    """Выбрать все / снять все — переключатель."""
    table = getattr(window, "_launch_table", None) or getattr(
        window, "_checker_table", None
    )
    if not isinstance(table, QTableWidget) or table.rowCount() == 0:
        if hasattr(window, "signals"):
            window.signals.notify.emit("Список сессий пуст", WARNING)
        return

    total = table.rowCount()
    already = _table_checked_files(window) or set()
    target = Qt.CheckState.Unchecked if len(already) >= total else Qt.CheckState.Checked

    window._launch_table_loading = True
    picked: set[str] = set()
    for row in range(total):
        item = table.item(row, 0)
        if item is None:
            continue
        item.setCheckState(target)
        if target == Qt.CheckState.Checked:
            fname = item.data(Qt.ItemDataRole.UserRole)
            if fname:
                picked.add(fname)
    window._launch_table_loading = False
    window._checker_checked = picked
    _update_select_all_btn_text(window)
    if hasattr(window, "signals"):
        if target == Qt.CheckState.Checked:
            window.signals.notify.emit(f"Выбрано: {len(picked)}", ACCENT)
        else:
            window.signals.notify.emit("Выбор снят", ACCENT)


def _wire_select_all_btn(window: Any, module: Any) -> None:
    page = _checker_tab_page(window)
    if page is None:
        return
    btn = getattr(window, "checker_select_all_btn", None)
    if btn is None:
        btn = page.findChild(QPushButton, "CheckerSelectAllBtn")
    if btn is None:
        btn = QPushButton("Выбрать все")
        btn.setObjectName("GhostBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        toolbar = _checker_btns_layout(page)
        if toolbar is not None:
            toolbar.insertWidget(1, btn)
        elif isinstance(page.layout(), QVBoxLayout):
            row = QHBoxLayout()
            row.addWidget(btn)
            row.addStretch(1)
            page.layout().addLayout(row)
        window.checker_select_all_btn = btn
    try:
        btn.clicked.disconnect()
    except (TypeError, RuntimeError):
        pass
    btn.clicked.connect(lambda: _select_all_checker(window))
    _update_select_all_btn_text(window)


def _patch_render_checker(DotLauncher: type) -> None:
    def render_checker(self):
        prev = set(getattr(self, "_checker_checked", None) or ())
        _sync_checker_checked_from_ui(self)
        prev |= set(getattr(self, "_checker_checked", None) or ())
        self._checker_checked = prev

        mod = getattr(self, "_mx_qt_module", None)
        if mod is not None:
            from launch_panel import _render_launch_table

            _render_launch_table(self, mod)
        elif hasattr(self, "render_sessions"):
            self.render_sessions()

    DotLauncher.render_checker = render_checker


def _ensure_checker_table(window: Any) -> QTableWidget | None:
    mod = getattr(window, "_mx_qt_module", None)
    if mod is None:
        return getattr(window, "_launch_table", None)
    from launch_panel import _ensure_launch_table

    return _ensure_launch_table(window, mod)


def _item(
    text: str,
    *,
    color: str | None = None,
    align: Qt.AlignmentFlag | None = None,
    bold: bool = False,
) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setToolTip(text)
    flags = it.flags()
    flags &= ~Qt.ItemFlag.ItemIsEditable
    it.setFlags(flags)
    if color:
        from PyQt6.QtGui import QColor

        brush = QColor(color)
        it.setForeground(brush)
        it.setData(Qt.ItemDataRole.ForegroundRole, brush)
    else:
        from PyQt6.QtGui import QColor

        brush = QColor(TABLE_TEXT)
        it.setForeground(brush)
        it.setData(Qt.ItemDataRole.ForegroundRole, brush)
    if bold:
        from PyQt6.QtGui import QFont

        fnt = it.font()
        fnt.setBold(True)
        it.setFont(fnt)
    if align is not None:
        it.setTextAlignment(align)
    return it


def _status_text(status: str | None) -> tuple[str, str, bool]:
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
    return s, TABLE_TEXT, False


def _render_checker_table(window: Any) -> None:
    mod = getattr(window, "_mx_qt_module", None)
    if mod is not None:
        from launch_panel import _render_launch_table

        _sync_checker_checked_from_ui(window)
        _render_launch_table(window, mod)
    elif hasattr(window, "render_sessions"):
        window.render_sessions()


def _center_widget(widget: QWidget) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addStretch(1)
    lay.addWidget(widget)
    lay.addStretch(1)
    return box


def _find_session_item_card(widget: Any) -> Any | None:
    w = widget
    while w is not None:
        if getattr(w, "objectName", lambda: "")() == "SessionItem":
            return w
        w = w.parent() if hasattr(w, "parent") else None
    return None


def _inject_checker_stopped_labels(window: Any) -> None:
    """Колонка «Остановлен» в строках чекера (после orig render_checker)."""
    sd = getattr(window, "session_dir", "") or ""
    active = set(getattr(window, "active_drivers", {}) or {})
    cbs: dict = getattr(window, "c_checkboxes", None) or {}
    for fname, cb in cbs.items():
        card = _find_session_item_card(cb)
        if card is None:
            continue
        lay = card.layout()
        if lay is None:
            continue
        old = card.findChild(QLabel, "CheckerStoppedLabel")
        is_active = fname in active
        if old is None:
            lbl = QLabel()
            lbl.setObjectName("CheckerStoppedLabel")
            lbl.setFixedWidth(108)
            lbl.setStyleSheet(
                f"color: {TEXT_DIM}; font-size: 10px; border: none;"
            )
            lbl.setToolTip("Время последней остановки сессии")
            # checkbox, имя, статус, [остановлен], RAW
            idx = min(3, lay.count())
            lay.insertWidget(idx, lbl)
        else:
            lbl = old
        lbl.setText(meta.get_stopped_display(sd, fname, is_active))


def _short_name(name: str, limit: int = 46) -> str:
    if len(name) <= limit:
        return name
    keep = max(10, (limit - 1) // 2)
    return f"{name[:keep]}…{name[-keep:]}"


def _normalize_checker_rows(window: Any) -> None:
    """Зафиксировать геометрию строк чекера, чтобы длинные имена не ломали таблицу."""
    page = _checker_tab_page(window)
    content = getattr(window, "c_scroll_content", None)
    if content is not None:
        content.setMinimumWidth(920)
    scroll = getattr(window, "c_scroll", None)
    if scroll is not None:
        try:
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        except Exception:
            pass

    cbs: dict = getattr(window, "c_checkboxes", None) or {}
    cards = []
    if cbs:
        for cb in cbs.values():
            card = _find_session_item_card(cb)
            if card is not None:
                cards.append(card)
    elif page is not None:
        cards = page.findChildren(QFrame, "SessionItem")

    for card in cards:
        lay = card.layout()
        if lay is None:
            continue
        card.setMinimumWidth(900)
        card.setFixedHeight(56)
        lay.setContentsMargins(12, 4, 10, 4)
        lay.setSpacing(8)

        labels = [
            lay.itemAt(i).widget()
            for i in range(lay.count())
            if lay.itemAt(i) is not None and isinstance(lay.itemAt(i).widget(), QLabel)
        ]
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is None:
                continue
            if isinstance(w, QCheckBox):
                w.setFixedWidth(34)
                w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            elif isinstance(w, QPushButton):
                w.setFixedSize(54, 30)
                w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            elif isinstance(w, QLabel):
                w.setWordWrap(False)
                w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                if w.objectName() == "CheckerStoppedLabel":
                    w.setFixedWidth(108)
                elif labels and w is labels[0]:
                    full = w.toolTip() or w.text()
                    if full:
                        w.setToolTip(full)
                        w.setText(_short_name(full))
                    w.setFixedWidth(430)
                    w.setStyleSheet(
                        f"color: {TEXT}; font-size: 11px; font-weight: 700; border: none;"
                    )
                else:
                    w.setFixedWidth(118)
                    w.setAlignment(Qt.AlignmentFlag.AlignCenter)


def _on_row_toggled(window: Any, fname: str, checked: bool) -> None:
    picked = set(getattr(window, "_checker_checked", None) or ())
    if checked:
        picked.add(fname)
    else:
        picked.discard(fname)
    window._checker_checked = picked


def _patch_select_dead_tokens(DotLauncher: type) -> None:
    orig = DotLauncher.select_dead_tokens

    def select_dead_tokens(self):
        table = getattr(self, "_checker_table", None)
        if isinstance(table, QTableWidget):
            results = getattr(self, "token_results", {}) or {}
            self._checker_table_loading = True
            picked: set[str] = set()
            dead_count = 0
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is None:
                    continue
                fname = item.data(Qt.ItemDataRole.UserRole)
                if not fname:
                    continue
                is_dead = results.get(fname) == "dead"
                item.setCheckState(
                    Qt.CheckState.Checked if is_dead else Qt.CheckState.Unchecked
                )
                if is_dead:
                    picked.add(fname)
                    dead_count += 1
            self._checker_table_loading = False
            self._checker_checked = picked
            _update_select_all_btn_text(self)
            if hasattr(self, "signals"):
                if dead_count:
                    self.signals.notify.emit(
                        f"Выбрано мёртвых: {dead_count}", WARNING
                    )
                else:
                    self.signals.notify.emit("Мёртвых токенов нет", TEXT_DIM)
            return
        orig(self)

    DotLauncher.select_dead_tokens = select_dead_tokens


def _patch_delete_selected_tokens(DotLauncher: type) -> None:
    orig = DotLauncher.delete_selected_tokens

    def delete_selected_tokens(self):
        table = getattr(self, "_checker_table", None)
        if isinstance(table, QTableWidget):
            files = _selected_checker_files(self)
            if not files:
                if hasattr(self, "signals"):
                    self.signals.notify.emit("Ничего не выбрано", WARNING)
                return
            sd = getattr(self, "session_dir", "") or ""
            tr = getattr(self, "token_results", None)
            if tr is None:
                self.token_results = {}
                tr = self.token_results
            deleted = 0
            for fname in files:
                path = token_path(sd, fname)
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                    tr.pop(fname, None)
                    deleted += 1
                except OSError:
                    _log.exception("delete %s failed", fname)
            picked = set(getattr(self, "_checker_checked", None) or ())
            for fname in files:
                picked.discard(fname)
            self._checker_checked = picked
            try:
                self.render_checker()
            except Exception:
                _log.exception("render_checker after delete failed")
            try:
                if hasattr(self, "render_sessions"):
                    self.render_sessions()
            except Exception:
                pass
            if hasattr(self, "signals"):
                self.signals.notify.emit(f"Удалено: {deleted} токенов", DANGER)
            return
        orig(self)

    DotLauncher.delete_selected_tokens = delete_selected_tokens


def _patch_start_check_tokens(DotLauncher: type) -> None:
    orig = DotLauncher.start_check_tokens

    def start_check_tokens(self):
        sd = getattr(self, "session_dir", "")
        if not sd or not os.path.isdir(sd):
            if hasattr(self, "signals"):
                self.signals.notify.emit("Папка сессий не задана", WARNING)
            return

        _sync_checker_checked_from_ui(self)
        files = _selected_checker_files(self)
        if not files:
            if hasattr(self, "signals"):
                self.signals.notify.emit(
                    "Отметьте сессии галочками — проверятся только они",
                    WARNING,
                )
            return

        ws_err = _websockets_checker_ok()
        if ws_err:
            _log.error("websockets для чекера: %s", ws_err)
            if hasattr(self, "signals"):
                self.signals.notify.emit(
                    "Чекер не работает: нет модуля websockets.\n"
                    "Переустановите Maxitochka (полная папка dist) или start.bat.",
                    DANGER,
                )
            return

        tr = getattr(self, "token_results", None)
        if tr is None:
            self.token_results = {}
            tr = self.token_results
        for fname in files:
            tr[fname] = "checking"
        try:
            self.render_checker()
        except Exception:
            _log.exception("render_checker failed")

        if hasattr(self, "signals"):
            self.signals.notify.emit(f"Проверка: {len(files)} сессий…", "#f1f5f9")

        def run() -> None:
            workers = max(1, min(_CHECK_MAX_WORKERS, len(files)))

            def check_one(fname: str) -> None:
                path = token_path(sd, fname)
                try:
                    with open(path, encoding="utf-8") as fp:
                        content = fp.read()
                except Exception:
                    try:
                        self.signals.check_result.emit(fname, "error")
                    except Exception:
                        pass
                    return
                self._check_token_worker(fname, content)

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = []
                for i, fname in enumerate(files):
                    futures.append(pool.submit(check_one, fname))
                    if i < len(files) - 1:
                        time.sleep(_CHECK_DELAY_SEC)
                for fut in as_completed(futures):
                    try:
                        fut.result()
                    except Exception:
                        _log.exception("checker worker failed")

            results = getattr(self, "token_results", {}) or {}
            alive = sum(1 for f in files if results.get(f) == "OK")
            dead = sum(1 for f in files if results.get(f) == "dead")
            err = sum(
                1
                for f in files
                if results.get(f) not in ("OK", "dead", "checking", "new")
            )
            if hasattr(self, "signals"):
                self.signals.notify.emit(
                    f"Готово: {alive} живых | {dead} мёртвых | {err} ошибок",
                    ACCENT,
                )

        threading.Thread(target=run, daemon=True).start()

    DotLauncher.start_check_tokens = start_check_tokens
    DotLauncher._maxitochka_start_check_tokens_orig = orig  # noqa: SLF001


def _patch_check_token_worker(DotLauncher: type) -> None:
    orig = DotLauncher._check_token_worker

    def _check_token_worker(self, fname, content):
        prepared = normalize_session_token(content)
        if not extract_session_token(prepared)[0]:
            if hasattr(self, "signals"):
                self.signals.check_result.emit(fname, "error")
            return
        try:
            orig(self, fname, prepared)
        except ModuleNotFoundError as ex:
            if "websockets" in str(ex):
                _log.error("check %s: %s", fname, ex)
                if hasattr(self, "signals"):
                    self.signals.check_result.emit(fname, "error")
                return
            raise

    DotLauncher._check_token_worker = _check_token_worker


def _rewire_checker_buttons(window: Any, module: Any) -> None:
    """
    orig_init_ui вешает clicked на старый bound-method.
    Переподключаем кнопку на вкладке «Чекер» к актуальному start_check_tokens.
    """
    page = _checker_tab_page(window)
    if page is None:
        return
    for btn in page.findChildren(QPushButton):
        text = (btn.text() or "").strip().upper()
        if "ПРОВЕР" not in text:
            continue
        try:
            btn.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        btn.clicked.connect(window.start_check_tokens)
        _log.debug("Чекер: кнопка %r переподключена", btn.text())


def _rename_check_button(window: Any, module: Any) -> None:
    page = _checker_tab_page(window)
    if page is None:
        return
    for btn in page.findChildren(QPushButton):
        text = (btn.text() or "").strip().upper()
        if any(m in text for m in _CHECK_BTN_MARKERS) or text == "ПРОВЕРИТЬ ВСЕ":
            btn.setText("Проверить")
            btn.setToolTip(
                "Проверить только отмеченные галочками сессии в списке ниже."
            )


def _patch_checker_stats(DotLauncher: type) -> None:
    orig = DotLauncher.handle_check_result

    def handle_check_result(self, fname, status):
        orig(self, fname, status)
        sd = getattr(self, "session_dir", "")
        if not sd:
            return
        tr = getattr(self, "token_results", {})
        alive = sum(1 for v in tr.values() if v == "OK")
        dead = sum(1 for v in tr.values() if v and v != "OK")
        try:
            import analytics

            analytics.record_checker(sd, alive, dead)
        except Exception:
            pass

    DotLauncher.handle_check_result = handle_check_result
