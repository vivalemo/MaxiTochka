"""Вкладка «Автоматизация»: шаблоны групп, контакты, сценарий общения."""

from __future__ import annotations

import json
import os
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from automation_config import (
    load_automation_config,
    load_contact_records,
    render_group_name,
    render_message,
    save_automation_config,
)
from contact_database import ContactRecord, parse_contact_database
from theme import ACCENT, BG_CARD, BORDER, SUCCESS, TEXT, TEXT_DIM, WARNING

_AUTOMATION_TAB_INDEX = 3


def install_automation_panel(window: Any, module: Any) -> None:
    page = _build_page(window)
    if page is None:
        return
    window.a_page = page
    tabs = getattr(window, "tabs", None)
    if tabs is not None:
        tabs.addWidget(page)

    btn = getattr(window, "btn_a", None)
    orig_switch = window.switch_tab

    def switch_tab(i: int) -> None:
        if i == _AUTOMATION_TAB_INDEX:
            window.tabs.setCurrentIndex(_AUTOMATION_TAB_INDEX)
            for attr in ("btn_p", "btn_l", "btn_crm"):
                b = getattr(window, attr, None)
                if b is not None:
                    b.setChecked(False)
            dash = getattr(window, "btn_d", None)
            if dash is not None and hasattr(dash, "set_nav_checked"):
                dash.set_nav_checked(False)
            if btn is not None:
                btn.setChecked(True)
            return
        if btn is not None:
            btn.setChecked(False)
        orig_switch(i)

    window.switch_tab = switch_tab
    if btn is not None:
        btn.clicked.connect(lambda: window.switch_tab(_AUTOMATION_TAB_INDEX))


def add_nav_button(window: Any) -> None:
    """Кнопка навигации — вызывается из modern_gui до install."""
    window.btn_a = _nav_btn("Авто")


def _nav_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("NavBtn")
    btn.setCheckable(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def _section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setStyleSheet(
        f"color: {TEXT}; font-size: 14px; font-weight: 700; padding: 8px 0 4px 0;"
    )
    return lbl


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; padding-bottom: 6px;")
    return lbl


def _build_page(window: Any) -> QWidget | None:
    cont = getattr(window, "cont", None)
    if cont is None:
        return None

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)

    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setSpacing(10)
    lay.setContentsMargins(4, 4, 4, 12)

    cfg = load_automation_config()

    lay.addWidget(_section("Варианты названий групп"))
    lay.addWidget(
        _hint(
            "Каждая строка — отдельный вариант. Запись 1 → строка 1, запись 2 → строка 2, "
            "далее по кругу.\n"
            "Подстановки: {fio}, {dob}, {book_name}, {phone}, {short_name}, {alias}, "
            "{n}, {date}, {time}, {random:4}."
        )
    )
    window._auto_group_templates = QTextEdit()
    window._auto_group_templates.setPlainText(
        "\n".join(cfg.get("group_name_templates") or [])
    )
    window._auto_group_templates.setMinimumHeight(90)
    window._auto_group_templates.textChanged.connect(
        lambda: _refresh_template_preview(window)
    )
    lay.addWidget(window._auto_group_templates)

    tpl_row = QHBoxLayout()
    tpl_row.addWidget(QLabel("Счётчик {n}:"))
    window._auto_group_counter = QSpinBox()
    window._auto_group_counter.setMinimum(1)
    window._auto_group_counter.setMaximum(999999)
    window._auto_group_counter.setValue(int(cfg.get("group_name_counter") or 1))
    tpl_row.addWidget(window._auto_group_counter)
    window._auto_tpl_preview = QLabel("")
    window._auto_tpl_preview.setWordWrap(True)
    window._auto_tpl_preview.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
    tpl_row.addWidget(window._auto_tpl_preview, 1)
    lay.addLayout(tpl_row)

    lay.addWidget(_section("Варианты первого сообщения"))
    lay.addWidget(
        _hint(
            "Каждая строка — отдельный текст первого сообщения в группе. "
            "Ротация такая же, как у названий групп.\n"
            "Те же подстановки: {fio}, {short_name}, {book_name}, {dob} и др."
        )
    )
    window._auto_message_templates = QTextEdit()
    window._auto_message_templates.setPlainText(
        "\n".join(cfg.get("first_message_templates") or [])
    )
    window._auto_message_templates.setMinimumHeight(90)
    window._auto_message_templates.textChanged.connect(
        lambda: _refresh_template_preview(window)
    )
    lay.addWidget(window._auto_message_templates)

    window._auto_msg_preview = QLabel("")
    window._auto_msg_preview.setWordWrap(True)
    window._auto_msg_preview.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
    lay.addWidget(window._auto_msg_preview)

    lay.addWidget(_section("База контактов (ФИО / дата / телефон)"))
    lay.addWidget(
        _hint(
            "Формат блоков через -------\n"
            "ФИО\nдата рождения\n79012345678 Имя\n-------\n"
            "Контакты (внизу) → Добавить контакт: ФИО+д.р. и телефон. "
            "В группу — по той же подписи «Иванов И.И. 01.01.1990»."
        )
    )
    db_row = QHBoxLayout()
    window._auto_database_file = QLineEdit(str(cfg.get("database_file") or ""))
    window._auto_database_file.setPlaceholderText("Путь к файлу базы (.txt)")
    db_row.addWidget(window._auto_database_file, 1)
    btn_db = QPushButton("…")
    btn_db.setFixedWidth(36)
    btn_db.clicked.connect(lambda: _browse_database(window))
    db_row.addWidget(btn_db)
    btn_preview = QPushButton("Проверить базу")
    btn_preview.clicked.connect(lambda: _preview_database(window))
    db_row.addWidget(btn_preview)
    lay.addLayout(db_row)

    window._auto_database_inline = QTextEdit()
    window._auto_database_inline.setPlainText(str(cfg.get("database_inline") or ""))
    window._auto_database_inline.setPlaceholderText(
        "Или вставьте базу сюда целиком…"
    )
    window._auto_database_inline.setMinimumHeight(140)
    window._auto_database_inline.textChanged.connect(
        lambda: _preview_database(window, quiet=True)
    )
    lay.addWidget(window._auto_database_inline)

    window._auto_db_stats = QLabel("")
    window._auto_db_stats.setStyleSheet(f"color: {SUCCESS}; font-size: 12px;")
    lay.addWidget(window._auto_db_stats)

    lim_row = QHBoxLayout()
    for label, attr, key, default in (
        ("Макс. на аккаунт", "_auto_max_groups", "groups_per_account_max", 5),
        ("С какой записи", "_auto_db_start", "database_start_index", 0),
    ):
        lim_row.addWidget(QLabel(label))
        spin = QSpinBox()
        spin.setMinimum(0)
        spin.setMaximum(9999)
        spin.setValue(int(cfg.get(key) or default))
        setattr(window, attr, spin)
        lim_row.addWidget(spin)
    lim_row.addStretch(1)
    lay.addLayout(lim_row)

    lay.addWidget(_section("После первого сообщения"))
    lay.addWidget(
        _hint(
            "JSON-массив доп. шагов (без send — текст берётся из вариантов выше): "
            "wait_reply, delay."
        )
    )
    post_steps = [
        s
        for s in (cfg.get("post_group_steps") or [])
        if not (isinstance(s, dict) and str(s.get("type") or "").lower() == "send")
    ]
    if not post_steps:
        post_steps = [
            {
                "type": "wait_reply",
                "timeout_sec": int((cfg.get("reply_wait") or {}).get("default_timeout_sec") or 3600),
                "match": "any",
            }
        ]
    window._auto_post_steps = QTextEdit()
    window._auto_post_steps.setPlainText(
        json.dumps(post_steps, ensure_ascii=False, indent=2)
    )
    window._auto_post_steps.setMinimumHeight(120)
    lay.addWidget(window._auto_post_steps)

    lay.addWidget(_section("Ожидание ответа"))
    wait_row = QHBoxLayout()
    wait_row.addWidget(QLabel("Опрос, сек"))
    window._auto_poll = QSpinBox()
    window._auto_poll.setRange(1, 120)
    rw = cfg.get("reply_wait") or {}
    window._auto_poll.setValue(int(rw.get("poll_interval_sec") or 5))
    wait_row.addWidget(window._auto_poll)
    wait_row.addWidget(QLabel("Таймаут по умолчанию, сек"))
    window._auto_reply_timeout = QSpinBox()
    window._auto_reply_timeout.setRange(30, 86400)
    window._auto_reply_timeout.setValue(int(rw.get("default_timeout_sec") or 3600))
    wait_row.addWidget(window._auto_reply_timeout)
    wait_row.addStretch(1)
    lay.addLayout(wait_row)

    btn_save = QPushButton("Сохранить настройки автоматизации")
    btn_save.setObjectName("CyanBtn")
    btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_save.clicked.connect(lambda: _save(window))
    lay.addWidget(btn_save)

    lay.addWidget(_section("Запуск"))
    lay.addWidget(
        _hint(
            "Порядок: 1) «Запуск» — запустите токены и дождитесь MAX (10–15 сек). "
            "2) «Авто» — база + «Сохранить». 3) «Запустить автоматизацию». "
            "Лог и уведомления внизу. Скриншоты ошибок — logs/automation_shots."
        )
    )
    run_row = QHBoxLayout()
    btn_run = QPushButton("Запустить автоматизацию")
    btn_run.setObjectName("CyanBtn")
    btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_run.clicked.connect(lambda: _run_automation(window))
    run_row.addWidget(btn_run)
    btn_stop = QPushButton("Остановить")
    btn_stop.setObjectName("DangerBtn")
    btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_stop.clicked.connect(lambda: _stop_automation(window))
    run_row.addWidget(btn_stop)
    run_row.addStretch(1)
    lay.addLayout(run_row)

    window._auto_run_log = QTextEdit()
    window._auto_run_log.setObjectName("AutomationRunLog")
    window._auto_run_log.setReadOnly(True)
    window._auto_run_log.setMinimumHeight(120)
    window._auto_run_log.setPlaceholderText("Лог автоматизации…")
    lay.addWidget(window._auto_run_log)

    lay.addStretch(1)
    scroll.setWidget(inner)

    page = QWidget()
    page_lay = QVBoxLayout(page)
    page_lay.setContentsMargins(0, 0, 0, 0)
    page_lay.addWidget(scroll)
    _preview_database(window, quiet=True)
    _refresh_template_preview(window)
    return page


def _browse_database(window: Any) -> None:
    path, _ = QFileDialog.getOpenFileName(
        window,
        "Файл базы контактов",
        "",
        "Text (*.txt);;All (*.*)",
    )
    if path:
        window._auto_database_file.setText(path)
        _preview_database(window)


def _preview_database(window: Any, quiet: bool = False) -> None:
    text = window._auto_database_inline.toPlainText().strip()
    path = window._auto_database_file.text().strip()
    records: list[ContactRecord] = []
    try:
        if text:
            records = parse_contact_database(text)
        elif path and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                records = parse_contact_database(f.read())
    except Exception as ex:
        window._auto_db_stats.setText(f"Ошибка разбора: {ex}")
        return

    if not records:
        window._auto_db_stats.setText("Записей: 0 — проверьте формат или файл")
        return

    sample = records[0]
    window._auto_db_stats.setText(
        f"Записей: {len(records)} · в контактах: «{sample.contact_book_name()}» "
        f"({sample.display_label()})"
    )
    if not quiet and hasattr(window, "signals"):
        window.signals.notify.emit(
            f"База: {len(records)} человек", SUCCESS
        )


def _sample_record() -> ContactRecord:
    return ContactRecord(
        fio="ГУРЬЯНОВА ГАЛИНА ГАВРИЛОВНА",
        dob="05.12.1952",
        phones=[("79045765745", "Галина")],
    )


def _refresh_template_preview(window: Any) -> None:
    sample = _sample_record()
    tpls = [
        ln.strip()
        for ln in window._auto_group_templates.toPlainText().splitlines()
        if ln.strip()
    ]
    if tpls:
        previews = []
        for i, tpl in enumerate(tpls[:4]):
            previews.append(
                f"{i + 1}. {render_group_name(tpl, counter=i + 1, record=sample)}"
            )
        window._auto_tpl_preview.setText("Группы: " + " · ".join(previews))
    else:
        window._auto_tpl_preview.setText("Группы: укажите хотя бы один шаблон")

    msg_tpls = [
        ln.strip()
        for ln in getattr(window, "_auto_message_templates", QTextEdit()).toPlainText().splitlines()
        if ln.strip()
    ]
    msg_preview = getattr(window, "_auto_msg_preview", None)
    if msg_preview is None:
        return
    if msg_tpls:
        msgs = []
        for i, tpl in enumerate(msg_tpls[:4]):
            msgs.append(f"{i + 1}. {render_message(tpl, counter=i + 1, record=sample)}")
        msg_preview.setText("Сообщения: " + " · ".join(msgs))
    else:
        msg_preview.setText("Сообщения: укажите хотя бы один вариант")


def _save(window: Any) -> bool:
    templates = [
        ln.strip()
        for ln in window._auto_group_templates.toPlainText().splitlines()
        if ln.strip()
    ]
    message_templates = [
        ln.strip()
        for ln in window._auto_message_templates.toPlainText().splitlines()
        if ln.strip()
    ]
    try:
        post_steps = json.loads(window._auto_post_steps.toPlainText())
        if not isinstance(post_steps, list):
            raise ValueError("ожидается JSON-массив")
    except (json.JSONDecodeError, ValueError) as ex:
        err = f"Ошибка JSON сообщений:\n{ex}"
        if hasattr(window, "signals"):
            window.signals.notify.emit(err, "#f43f5e")
        log_w = getattr(window, "_auto_run_log", None)
        if log_w is not None:
            log_w.append(f"✗ {err}")
        return False

    cfg = load_automation_config()
    max_groups = int(window._auto_max_groups.value())
    patch = {
        "automation_mode": "database",
        "one_group_per_contact": True,
        "members_per_group_max": 1,
        "group_name_templates": templates or ["{fio}"],
        "first_message_templates": message_templates or ["Привет!"],
        "group_name_counter": int(window._auto_group_counter.value()),
        "database_file": window._auto_database_file.text().strip(),
        "database_inline": window._auto_database_inline.toPlainText(),
        "contacts_source": "database",
        "contacts_per_account_max": max_groups,
        "groups_per_account_max": max_groups,
        "database_start_index": int(window._auto_db_start.value()),
        "post_group_steps": post_steps,
        "active_script_id": "database",
        "reply_wait": {
            **(cfg.get("reply_wait") or {}),
            "poll_interval_sec": int(window._auto_poll.value()),
            "default_timeout_sec": int(window._auto_reply_timeout.value()),
        },
    }
    save_automation_config(patch)
    if hasattr(window, "signals"):
        window.signals.notify.emit("Настройки автоматизации сохранены", SUCCESS)
    return True


def _run_automation(window: Any) -> None:
    log_w = getattr(window, "_auto_run_log", None)
    if log_w is not None:
        log_w.append("▶ Нажата кнопка «Запустить автоматизацию»")

    if not _save(window):
        return

    if hasattr(window, "start_automation"):
        started = window.start_automation()
    else:
        from automation_runner import start_automation

        started = start_automation(window)

    if log_w is not None and started == 0:
        log_w.append("⚠ Автоматизация не запущена — см. сообщение выше")


def _stop_automation(window: Any) -> None:
    if hasattr(window, "stop_automation"):
        window.stop_automation()
    else:
        from automation_runner import stop_automation

        stop_automation(window)


def _wire_save(window: Any) -> None:
    pass
