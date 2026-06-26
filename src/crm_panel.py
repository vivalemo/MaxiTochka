"""Вкладка CRM: диалоги по сессиям (дерево) и переписка."""

from __future__ import annotations

import json
import threading
from typing import Any

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from campaign_store import (
    STATUS_AWAITING,
    STATUS_REPLIED,
    list_messages,
)
from crm_helpers import (
    contact_label,
    format_chat_row,
    format_session_row,
    format_token_label,
    group_dialogs_by_session,
)
from crm_service import (
    crm_bootstrap,
    delete_dialog_crm,
    import_chats_from_max,
    list_visible_dialogs,
    open_dialog_read,
    purge_ui_chrome_dialogs,
    reconcile_crm,
    request_crm_ui_refresh,
    run_manual_sync,
    send_from_crm,
    start_poller,
    stop_poller,
    sync_all,
    sync_one,
)
from theme import SUCCESS, TEXT, TEXT_DIM, WARNING

_CRM_INDEX = 4
_ROLE_DIALOG_ID = Qt.ItemDataRole.UserRole
_ROLE_IS_SESSION = Qt.ItemDataRole.UserRole + 1


class _CrmUiBridge(QObject):
    refresh_requested = pyqtSignal()


class _CrmProgressBridge(QObject):
    progress = pyqtSignal(str, int, int, str)
    job_finished = pyqtSignal(str, object)
    job_failed = pyqtSignal(str, str)


_PHASE_LABELS = {
    "purge": "Очистка",
    "import": "Импорт",
    "sync_session": "Сессия",
    "sync_list": "Список чатов",
    "sync_chat": "Чат",
    "reconcile": "Проверка",
}


def restart_poller_if_visible(window: Any) -> None:
    if getattr(window, "tabs", None) and window.tabs.currentIndex() == _CRM_INDEX:
        start_poller(window, interval_sec=18.0)


def install_crm_panel(window: Any, module: Any) -> None:
    if getattr(window, "_crm_installed", False):
        return
    window._crm_installed = True

    if not getattr(window, "btn_crm", None):
        window.btn_crm = _nav_btn("CRM")

    page = _build_page(window)
    window.tabs.addWidget(page)
    window._crm_selected_id: str | None = None

    def _refresh() -> None:
        _refresh_dialog_tree(window, force=True)
        if window._crm_selected_id:
            _load_messages(window, window._crm_selected_id)

    window._crm_refresh_ui = _refresh
    window._crm_bridge = _CrmUiBridge(window)
    window._crm_bridge.refresh_requested.connect(_refresh)
    window._crm_progress_bridge = _CrmProgressBridge(window)
    window._crm_progress_bridge.progress.connect(
        lambda phase, cur, total, detail: _on_crm_progress(window, phase, cur, total, detail)
    )
    window._crm_progress_bridge.job_finished.connect(
        lambda job, result: _on_crm_job_finished(window, job, result)
    )
    window._crm_progress_bridge.job_failed.connect(
        lambda job, err: _on_crm_job_failed(window, job, err)
    )
    window._crm_job_running = False

    orig_switch = window.switch_tab

    def switch_tab(i: int) -> None:
        if i == _CRM_INDEX:
            window.tabs.setCurrentIndex(_CRM_INDEX)
            for attr in ("btn_p", "btn_l", "btn_a"):
                b = getattr(window, attr, None)
                if b is not None:
                    b.setChecked(False)
            window.btn_crm.setChecked(True)
            dash = getattr(window, "btn_d", None)
            if dash is not None and hasattr(dash, "set_nav_checked"):
                dash.set_nav_checked(False)
            _refresh()
            start_poller(window, interval_sec=18.0)
            _bootstrap_async(window)
            return
        window.btn_crm.setChecked(False)
        stop_poller()
        orig_switch(i)

    window.switch_tab = switch_tab
    window.btn_crm.clicked.connect(lambda: window.switch_tab(_CRM_INDEX))

    timer = QTimer(window)
    timer.setInterval(8000)
    timer.timeout.connect(lambda: _refresh_if_visible(window))
    timer.start()


def _nav_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("NavBtn")
    btn.setCheckable(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def _build_page(window: Any) -> QWidget:
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(4, 4, 4, 4)
    lay.setSpacing(8)

    top = QHBoxLayout()
    window._crm_stats = QLabel("")
    window._crm_stats.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
    top.addWidget(window._crm_stats, 1)

    btn_sync = QPushButton("Синхронизировать")
    btn_sync.setObjectName("CyanBtn")
    btn_sync.clicked.connect(lambda: _on_sync(window))
    top.addWidget(btn_sync)
    window._crm_btn_sync = btn_sync

    btn_import = QPushButton("Подтянуть из MAX")
    btn_import.clicked.connect(lambda: _on_import(window))
    top.addWidget(btn_import)
    window._crm_btn_import = btn_import

    btn_clean = QPushButton("Очистить")
    btn_clean.clicked.connect(lambda: _on_reconcile(window))
    top.addWidget(btn_clean)
    window._crm_btn_clean = btn_clean
    lay.addLayout(top)

    progress_row = QHBoxLayout()
    window._crm_progress_label = QLabel("")
    window._crm_progress_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
    window._crm_progress_label.setWordWrap(True)
    progress_row.addWidget(window._crm_progress_label, 1)
    window._crm_progress_bar = QProgressBar()
    window._crm_progress_bar.setVisible(False)
    window._crm_progress_bar.setTextVisible(True)
    window._crm_progress_bar.setFixedHeight(18)
    window._crm_progress_bar.setMinimumWidth(160)
    progress_row.addWidget(window._crm_progress_bar)
    lay.addLayout(progress_row)

    splitter = QSplitter(Qt.Orientation.Horizontal)

    left = QFrame()
    left.setObjectName("CrmLeft")
    left_lay = QVBoxLayout(left)
    left_lay.setContentsMargins(0, 0, 0, 0)

    window._crm_filter = QComboBox()
    window._crm_filter.addItems(["Все", "Ждут ответа", "Ответили"])
    window._crm_filter.currentIndexChanged.connect(
        lambda _: _refresh_dialog_tree(window)
    )
    left_lay.addWidget(window._crm_filter)

    window._crm_dialog_tree = QTreeWidget()
    window._crm_dialog_tree.setObjectName("CrmDialogTree")
    window._crm_dialog_tree.setHeaderHidden(True)
    window._crm_dialog_tree.setIndentation(16)
    window._crm_dialog_tree.setAnimated(True)
    window._crm_dialog_tree.setRootIsDecorated(True)
    window._crm_dialog_tree.currentItemChanged.connect(
        lambda cur, _prev: _on_dialog_selected(window, cur)
    )
    left_lay.addWidget(window._crm_dialog_tree, 1)

    right = QFrame()
    right_lay = QVBoxLayout(right)
    right_lay.setContentsMargins(8, 0, 0, 0)

    window._crm_chat_title = QLabel("Выберите диалог")
    window._crm_chat_title.setStyleSheet(
        f"color: {TEXT}; font-weight: 700; font-size: 14px;"
    )
    right_lay.addWidget(window._crm_chat_title)

    window._crm_chat_meta = QLabel("")
    window._crm_chat_meta.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
    window._crm_chat_meta.setWordWrap(True)
    right_lay.addWidget(window._crm_chat_meta)

    window._crm_messages = QTextEdit()
    window._crm_messages.setReadOnly(True)
    window._crm_messages.setObjectName("CrmMessages")
    window._crm_messages.setMinimumHeight(280)
    right_lay.addWidget(window._crm_messages, 1)

    compose = QHBoxLayout()
    window._crm_compose = QLineEdit()
    window._crm_compose.setPlaceholderText("Сообщение…")
    window._crm_compose.returnPressed.connect(lambda: _on_send(window))
    compose.addWidget(window._crm_compose, 1)
    btn_send = QPushButton("Отправить")
    btn_send.setObjectName("CyanBtn")
    btn_send.clicked.connect(lambda: _on_send(window))
    compose.addWidget(btn_send)
    right_lay.addLayout(compose)

    actions = QHBoxLayout()
    btn_del_crm = QPushButton("Удалить чат")
    btn_del_crm.clicked.connect(lambda: _on_delete(window, delete_in_max=False))
    actions.addWidget(btn_del_crm)
    btn_del_max = QPushButton("Удалить группу")
    btn_del_max.clicked.connect(lambda: _on_delete(window, delete_in_max=True))
    actions.addWidget(btn_del_max)
    actions.addStretch(1)
    right_lay.addLayout(actions)

    splitter.addWidget(left)
    splitter.addWidget(right)
    splitter.setStretchFactor(0, 1)
    splitter.setStretchFactor(1, 2)
    lay.addWidget(splitter, 1)

    from crm_filter import get_crm_keyword

    keyword = get_crm_keyword()
    kw_hint = (
        f"Подтягиваются только чаты со словом «{keyword}» в названии. "
        if keyword
        else ""
    )
    hint = QLabel(
        "Слева: блок = сессия (токен), под ней чаты. "
        + kw_hint
        + "Синхронизация при открытии CRM и каждые ~12 сек."
    )
    hint.setWordWrap(True)
    hint.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
    lay.addWidget(hint)

    return page


def _session_dir(window: Any) -> str:
    return getattr(window, "session_dir", "") or ""


def _filter_status(window: Any) -> str | None:
    idx = window._crm_filter.currentIndex()
    if idx == 1:
        return STATUS_AWAITING
    if idx == 2:
        return STATUS_REPLIED
    return None


def _style_chat_item(item: QTreeWidgetItem, dialog) -> None:
    if dialog.status == STATUS_REPLIED:
        item.setForeground(0, Qt.GlobalColor.green)
        font = item.font(0)
        font.setBold(int(dialog.unread or 0) > 0)
        item.setFont(0, font)
    elif dialog.status == STATUS_AWAITING:
        item.setForeground(0, QColor("#ca8a04"))


def _find_item_by_dialog_id(tree: QTreeWidget, dialog_id: str) -> QTreeWidgetItem | None:
    for i in range(tree.topLevelItemCount()):
        parent = tree.topLevelItem(i)
        for j in range(parent.childCount()):
            child = parent.child(j)
            if str(child.data(0, _ROLE_DIALOG_ID) or "") == dialog_id:
                return child
    return None


def _dialogs_fingerprint(dialogs: list) -> tuple:
    return tuple(
        (d.id, d.status, int(d.unread or 0), d.updated_at or d.created_at)
        for d in dialogs
    )


def _refresh_dialog_tree(window: Any, *, force: bool = False) -> None:
    visible = list_visible_dialogs(
        window, status=_filter_status(window), operator_order=True
    )
    stats = {
        "total": len(visible),
        "awaiting": sum(1 for d in visible if d.status == STATUS_AWAITING),
        "replied": sum(1 for d in visible if d.status == STATUS_REPLIED),
        "unread": sum(int(d.unread or 0) for d in visible),
        "sessions": len(group_dialogs_by_session(visible)),
    }
    window._crm_stats.setText(
        f"Сессий: {stats['sessions']} · чатов: {stats['total']} · "
        f"ждут: {stats['awaiting']} · ответили: {stats['replied']} · "
        f"непрочитано: {stats['unread']}"
    )

    fp = _dialogs_fingerprint(visible)
    if not force and fp == getattr(window, "_crm_tree_fp", None):
        return
    window._crm_tree_fp = fp

    selected = window._crm_selected_id
    tree = window._crm_dialog_tree
    tree.blockSignals(True)
    tree.clear()

    bold = QFont()
    bold.setBold(True)

    for sess_name, chats in group_dialogs_by_session(visible):
        session_item = QTreeWidgetItem([format_session_row(sess_name, len(chats))])
        session_item.setData(0, _ROLE_IS_SESSION, True)
        session_item.setFont(0, bold)
        session_item.setForeground(0, QColor("#94a3b8"))
        session_item.setFlags(
            session_item.flags()
            & ~Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEnabled
        )
        session_item.setExpanded(True)

        for dialog in chats:
            child = QTreeWidgetItem([format_chat_row(dialog)])
            child.setData(0, _ROLE_DIALOG_ID, dialog.id)
            child.setData(0, _ROLE_IS_SESSION, False)
            _style_chat_item(child, dialog)
            session_item.addChild(child)

        tree.addTopLevelItem(session_item)

    if selected:
        item = _find_item_by_dialog_id(tree, selected)
        if item is not None:
            tree.setCurrentItem(item)
            tree.scrollToItem(item)

    tree.blockSignals(False)


def _refresh_if_visible(window: Any) -> None:
    if window.tabs.currentIndex() != _CRM_INDEX:
        return
    if window._crm_selected_id:
        try:
            sync_one(window, window._crm_selected_id)
        except Exception:
            pass
        _load_messages(window, window._crm_selected_id)
    _refresh_dialog_tree(window, force=True)


def _on_dialog_selected(window: Any, item: QTreeWidgetItem | None) -> None:
    if not item or item.data(0, _ROLE_IS_SESSION):
        return
    did = item.data(0, _ROLE_DIALOG_ID)
    if not did:
        return
    window._crm_selected_id = str(did)
    open_dialog_read(window, window._crm_selected_id)
    _load_messages(window, window._crm_selected_id)
    try:
        sync_one(window, window._crm_selected_id)
        _load_messages(window, window._crm_selected_id)
        _refresh_dialog_tree(window, force=True)
    except Exception:
        pass


def _load_messages(window: Any, dialog_id: str) -> None:
    from campaign_store import get_dialog

    sd = _session_dir(window)
    dialog = get_dialog(sd, dialog_id)
    if not dialog:
        return
    token = format_token_label(dialog.session_name)
    contact = contact_label(dialog)
    window._crm_chat_title.setText(contact)
    status_ru = {
        STATUS_AWAITING: "ждём ответа клиента",
        STATUS_REPLIED: "клиент ответил",
    }.get(dialog.status, dialog.status)
    window._crm_chat_meta.setText(
        f"Токен: {token} · Группа: {dialog.group_title} · {status_ru}"
        + (f" · тел. {dialog.lead_phone}" if dialog.lead_phone else "")
    )
    lines: list[str] = []
    for m in list_messages(sd, dialog_id):
        prefix = "Вы" if m.direction == "out" else "Клиент"
        lines.append(f"[{prefix}] {m.text}")
    if not lines and dialog.last_message_text:
        prefix = "Вы" if dialog.last_message_dir == "out" else "Клиент"
        lines.append(f"[{prefix}] {dialog.last_message_text}")
    window._crm_messages.setPlainText("\n\n".join(lines))


def _format_progress(phase: str, cur: int, total: int, detail: str) -> str:
    label = _PHASE_LABELS.get(phase, phase)
    detail = (detail or "").strip()
    if total > 1:
        base = f"{label} {cur}/{total}"
    else:
        base = label
    return f"{base}: {detail}" if detail else base


def _set_crm_job_running(window: Any, running: bool) -> None:
    window._crm_job_running = running
    for attr in ("_crm_btn_sync", "_crm_btn_import", "_crm_btn_clean"):
        btn = getattr(window, attr, None)
        if btn is not None:
            btn.setEnabled(not running)
    bar = getattr(window, "_crm_progress_bar", None)
    if bar is not None and not running:
        bar.setVisible(False)
        bar.setRange(0, 100)
        bar.setValue(0)


def _on_crm_progress(
    window: Any, phase: str, cur: int, total: int, detail: str
) -> None:
    lbl = getattr(window, "_crm_progress_label", None)
    bar = getattr(window, "_crm_progress_bar", None)
    if lbl is not None:
        lbl.setText(_format_progress(phase, cur, total, detail))
    if bar is None:
        return
    bar.setVisible(True)
    if total <= 0:
        bar.setRange(0, 0)
    else:
        bar.setRange(0, total)
        bar.setValue(min(cur, total))


def _progress_callback(window: Any):
    bridge = window._crm_progress_bridge

    def _cb(phase: str, cur: int, total: int, detail: str) -> None:
        bridge.progress.emit(phase, cur, total, detail)

    return _cb


def _run_crm_job(window: Any, job_name: str, worker) -> None:
    if getattr(window, "_crm_job_running", False):
        return
    _set_crm_job_running(window, True)
    _on_crm_progress(window, job_name, 0, 0, "запуск…")

    def _run() -> None:
        try:
            result = worker(_progress_callback(window))
            window._crm_progress_bridge.job_finished.emit(job_name, result)
        except Exception as ex:
            window._crm_progress_bridge.job_failed.emit(job_name, str(ex))

    threading.Thread(target=_run, name=f"crm-{job_name}", daemon=True).start()


def _on_crm_job_finished(window: Any, job_name: str, result: object) -> None:
    _set_crm_job_running(window, False)
    res = result if isinstance(result, dict) else {}
    _refresh_dialog_tree(window, force=True)

    if job_name == "bootstrap":
        request_crm_ui_refresh(window, force=True)
        if hasattr(window, "signals"):
            window.signals.notify.emit(
                f"CRM: найдено чатов {res.get('found', 0)}, по слову «{res.get('keyword') or '—'}» "
                f"подходит {res.get('matched', 0)}, подтянуто {res.get('imported', 0)}, "
                f"+{res.get('added_messages', 0)} сообщ.",
                SUCCESS if res.get("matched") else WARNING,
            )
        return

    if job_name == "sync":
        if window._crm_selected_id:
            from campaign_store import get_dialog

            if get_dialog(_session_dir(window), window._crm_selected_id):
                _load_messages(window, window._crm_selected_id)
            else:
                window._crm_selected_id = None
        if hasattr(window, "signals"):
            color = SUCCESS if not res.get("errors") else WARNING
            errs = res.get("errors") or []
            err_hint = f" · ошибок: {len(errs)}" if errs else ""
            window.signals.notify.emit(
                f"CRM: +{res.get('added', 0)} сообщ. · чатов {res.get('synced', 0)}{err_hint}",
                color,
            )
        return

    if job_name == "import":
        if hasattr(window, "signals"):
            window.signals.notify.emit(
                f"CRM: найдено {res.get('found', 0)}, по слову «{res.get('keyword') or '—'}» "
                f"подходит {res.get('matched', 0)}, добавлено {res.get('added', 0)}",
                SUCCESS if res.get("added") else WARNING,
            )
        return

    if job_name == "reconcile":
        window._crm_selected_id = None
        window._crm_messages.clear()
        window._crm_chat_title.setText("Выберите диалог")
        window._crm_chat_meta.setText("")
        if hasattr(window, "signals"):
            window.signals.notify.emit(
                f"CRM: убрано {res.get('removed', 0)}",
                SUCCESS if not res.get("removed") else WARNING,
            )


def _on_crm_job_failed(window: Any, job_name: str, err: str) -> None:
    _set_crm_job_running(window, False)
    lbl = getattr(window, "_crm_progress_label", None)
    if lbl is not None:
        lbl.setText(f"Ошибка ({job_name}): {err}")
    if hasattr(window, "signals"):
        window.signals.notify.emit(f"CRM {job_name}: {err}", WARNING)


def _bootstrap_async(window: Any) -> None:
    if getattr(window, "_crm_job_running", False):
        return

    def _worker(on_progress):
        result = crm_bootstrap(window, on_progress=on_progress)
        request_crm_ui_refresh(window, force=True)
        return result

    _run_crm_job(window, "bootstrap", _worker)


def _on_import(window: Any) -> None:
    def _worker(on_progress):
        imported = import_chats_from_max(window, on_progress=on_progress)
        synced = sync_all(window, on_progress=on_progress)
        return {
            "added": imported.get("added", 0),
            "found": imported.get("found", 0),
            "matched": imported.get("matched", 0),
            "keyword": imported.get("keyword", ""),
            "synced": synced.get("synced", 0),
            "errors": (imported.get("errors") or []) + (synced.get("errors") or []),
        }

    _run_crm_job(window, "import", _worker)


def _on_reconcile(window: Any) -> None:
    def _worker(on_progress):
        result = reconcile_crm(window, on_progress=on_progress)
        purge_ui_chrome_dialogs(window)
        return result

    _run_crm_job(window, "reconcile", _worker)


def _on_sync(window: Any) -> None:
    def _worker(on_progress):
        return run_manual_sync(window, on_progress=on_progress)

    _run_crm_job(window, "sync", _worker)


def _on_delete(window: Any, *, delete_in_max: bool) -> None:
    did = window._crm_selected_id
    if not did:
        return
    from campaign_store import get_dialog

    dialog = get_dialog(_session_dir(window), did)
    if not dialog:
        return
    title = "Удалить группу в MAX?" if delete_in_max else "Удалить чат из CRM?"
    text = (
        f"Группа «{dialog.group_title}» будет удалена в MAX и убрана из CRM."
        if delete_in_max
        else f"Диалог «{contact_label(dialog)}» будет убран из CRM."
    )
    box = QMessageBox(window)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    if box.exec() != QMessageBox.StandardButton.Yes:
        return

    ok, detail = delete_dialog_crm(window, did, delete_in_max=delete_in_max)
    if ok:
        window._crm_selected_id = None
        window._crm_messages.clear()
        window._crm_chat_title.setText("Выберите диалог")
        window._crm_chat_meta.setText("")
        _refresh_dialog_tree(window, force=True)
    if hasattr(window, "signals"):
        window.signals.notify.emit(f"CRM: {detail}", SUCCESS if ok else WARNING)


def _on_send(window: Any) -> None:
    did = window._crm_selected_id
    text = (window._crm_compose.text() or "").strip()
    if not did or not text:
        return
    ok, detail = send_from_crm(window, did, text)
    if ok:
        window._crm_compose.clear()
        _load_messages(window, did)
        _refresh_dialog_tree(window, force=True)
    if hasattr(window, "signals"):
        window.signals.notify.emit(f"CRM: {detail}", SUCCESS if ok else WARNING)
