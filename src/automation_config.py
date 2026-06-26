"""Настройки автоматизации: шаблоны групп, база контактов, сценарии."""

from __future__ import annotations

import copy
import json
import os
import random
import re
import string
from datetime import datetime
from typing import Any

from contact_database import ContactRecord, load_contact_database, parse_contact_database
from settings_store import load_settings, save_settings

_DEFAULT: dict[str, Any] = {
    "automation_mode": "database",
    "one_group_per_contact": True,
    "group_name_templates": [
        "{fio}",
        "{short_name}",
        "{short_name} {dob}",
        "Чат {n}",
    ],
    "group_name_counter": 1,
    "first_message_templates": [
        "Здравствуйте, {short_name}!",
        "Добрый день, {fio}!",
        "Привет!",
    ],
    "database_file": "",
    "database_inline": "",
    "contacts_source": "database",
    "contacts_file": "",
    "contacts_inline": [],
    "contacts_per_account_max": 5,
    "groups_per_account_max": 5,
    "members_per_group_max": 1,
    "database_start_index": 0,
    "delays_sec": {
        "before_contact": [20, 45],
        "after_contact_added": [30, 60],
        "before_group_create": [60, 120],
        "after_group_create": [10, 25],
        "between_records": [90, 180],
        "before_message": [5, 15],
        "between_accounts": [180, 360],
        "typing_char_ms": [40, 110],
    },
    "reply_wait": {
        "poll_interval_sec": 5,
        "default_timeout_sec": 3600,
        "stop_on_timeout": True,
        "ignore_own_messages": True,
    },
    "post_group_steps": [
        {"type": "send", "text": "Привет!"},
        {
            "type": "wait_reply",
            "timeout_sec": 3600,
            "match": "any",
            "keywords": [],
        },
    ],
    "conversation_scripts": [
        {
            "id": "database",
            "name": "База: 1 контакт = 1 группа",
            "steps": [],
        }
    ],
    "active_script_id": "database",
    "stop_on_account_ban": True,
    "stop_on_logout": True,
    # Не более N сессий одновременно (каждая — свой Playwright/CDP).
    "automation_max_parallel": 3,
    # Задержка между стартом потоков, сек (снижает пик нагрузки).
    "automation_stagger_sec": 2,
    # 0 = все круги за один запуск; 1 = только первый круг (1 лид на сессию).
    "automation_rounds_per_run": 0,
}


def _merge_defaults(data: dict) -> dict:
    out = copy.deepcopy(_DEFAULT)
    if not isinstance(data, dict):
        return out
    for key, val in data.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            merged = dict(out[key])
            merged.update(val)
            out[key] = merged
        else:
            out[key] = val
    if not isinstance(out.get("group_name_templates"), list):
        out["group_name_templates"] = list(_DEFAULT["group_name_templates"])
    if not isinstance(out.get("first_message_templates"), list):
        out["first_message_templates"] = list(_DEFAULT["first_message_templates"])
    # миграция: вынести send из post_group_steps в шаблоны, если шаблонов нет
    if not [t for t in out.get("first_message_templates") or [] if str(t).strip()]:
        sends = [
            str(s.get("text") or "")
            for s in (out.get("post_group_steps") or [])
            if isinstance(s, dict) and str(s.get("type") or "").lower() == "send"
        ]
        if sends:
            out["first_message_templates"] = sends
    return out


def load_automation_config() -> dict:
    return _merge_defaults(load_settings())


def save_automation_config(patch: dict) -> dict:
    data = load_automation_config()
    data.update(patch)
    save_settings(data)
    return data


def list_group_templates(cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_automation_config()
    tpls = cfg.get("group_name_templates") or []
    return [str(t) for t in tpls if str(t).strip()]


def list_message_templates(cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_automation_config()
    tpls = cfg.get("first_message_templates") or []
    return [str(t) for t in tpls if str(t).strip()]


def render_message(
    template: str,
    *,
    counter: int | None = None,
    session_name: str = "",
    record: ContactRecord | None = None,
    cfg: dict | None = None,
) -> str:
    """Текст первого сообщения — те же подстановки, что у названия группы."""
    return render_group_name(
        template,
        counter=counter,
        session_name=session_name,
        record=record,
        cfg=cfg,
    )


def message_for_record(
    record: ContactRecord,
    record_index: int,
    session_name: str = "",
    cfg: dict | None = None,
) -> str:
    """Первое сообщение: строка шаблона = вариант (record_index mod кол-во строк)."""
    cfg = cfg or load_automation_config()
    tpls = list_message_templates(cfg)
    if not tpls:
        return ""
    tpl = tpls[record_index % len(tpls)]
    counter = int(cfg.get("group_name_counter") or 1)
    return render_message(
        tpl,
        counter=counter + record_index,
        session_name=session_name,
        record=record,
        cfg=cfg,
    )


def post_group_steps_for_record(
    record: ContactRecord,
    record_index: int,
    session_name: str = "",
    cfg: dict | None = None,
) -> list[dict]:
    """Шаги после группы: первое сообщение из шаблонов + wait_reply/delay из настроек."""
    cfg = cfg or load_automation_config()
    steps: list[dict] = []
    text = message_for_record(record, record_index, session_name, cfg)
    if text:
        steps.append({"type": "send", "text": text})
    for step in cfg.get("post_group_steps") or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("type") or "").lower() == "send":
            continue
        steps.append(copy.deepcopy(step))
    return steps


def load_contact_records(cfg: dict | None = None) -> list[ContactRecord]:
    """Загрузить записи из базы (файл или вставленный текст)."""
    cfg = cfg or load_automation_config()
    source = str(cfg.get("contacts_source") or "database").lower()
    if source == "database":
        inline = str(cfg.get("database_inline") or "").strip()
        if inline:
            return parse_contact_database(inline)
        path = str(cfg.get("database_file") or "").strip()
        if path and os.path.isfile(path):
            return load_contact_database(path)
        return []
    if source == "inline":
        text = "\n".join(str(x) for x in (cfg.get("contacts_inline") or []))
        if "-------" in text or _looks_like_database(text):
            return parse_contact_database(text)
        return [
            ContactRecord(fio="", phones=[(normalize_phone_line(x), "")])
            for x in (cfg.get("contacts_inline") or [])
            if normalize_phone_line(str(x))
        ]
    path = str(cfg.get("contacts_file") or "").strip()
    if not path or not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if "-------" in text or _looks_like_database(text):
        return parse_contact_database(text)
    records: list[ContactRecord] = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            ph = normalize_phone_line(s)
            if ph:
                records.append(ContactRecord(phones=[(ph, "")]))
    return records


def _looks_like_database(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3:
        return False
    dob_hits = sum(1 for ln in lines if re.match(r"^\d{2}\.\d{2}\.\d{4}$", ln))
    return dob_hits >= 1


def normalize_phone_line(raw: str) -> str:
    from contact_database import normalize_phone, _parse_phone_line

    parsed = _parse_phone_line(raw.strip())
    if parsed:
        return parsed[0]
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) >= 10:
        return normalize_phone(digits)
    return ""


def list_contacts(cfg: dict | None = None) -> list[str]:
    """Плоский список телефонов (для совместимости)."""
    return [r.primary_phone for r in load_contact_records(cfg) if r.primary_phone]


def get_active_script(cfg: dict | None = None) -> dict:
    cfg = cfg or load_automation_config()
    sid = str(cfg.get("active_script_id") or "database")
    for script in cfg.get("conversation_scripts") or []:
        if isinstance(script, dict) and str(script.get("id")) == sid:
            return script
    steps = cfg.get("post_group_steps") or []
    return {"id": "database", "name": "База", "steps": steps}


def _random_digits(n: int) -> str:
    n = max(1, min(16, int(n)))
    return "".join(random.choices(string.digits, k=n))


def render_group_name(
    template: str,
    *,
    counter: int | None = None,
    session_name: str = "",
    record: ContactRecord | None = None,
    cfg: dict | None = None,
) -> str:
    """Подстановки: {n}, {date}, {fio}, {dob}, {phone}, {short_name}, {alias}, {book_name}."""
    cfg = cfg or load_automation_config()
    now = datetime.now()
    token_name = session_name.replace(".txt", "").strip()

    if counter is None:
        counter = int(cfg.get("group_name_counter") or 1)

    rec = record or ContactRecord()
    phone = rec.primary_phone
    alias = rec.primary_alias
    fio = rec.fio
    dob = rec.dob
    short = rec.short_name
    book = rec.contact_book_name()

    out = template
    out = out.replace("{n}", str(counter))
    out = out.replace("{date}", now.strftime("%d.%m"))
    out = out.replace("{time}", now.strftime("%H:%M"))
    out = out.replace("{name}", token_name or short or "группа")
    out = out.replace("{fio}", fio or short or token_name)
    out = out.replace("{dob}", dob)
    out = out.replace("{phone}", phone or token_name)
    out = out.replace("{short_name}", short or fio.split()[0] if fio else "")
    out = out.replace("{alias}", alias or short)
    out = out.replace("{book_name}", book or alias or short or fio)

    def repl(match: re.Match) -> str:
        return _random_digits(int(match.group(1)))

    out = re.sub(r"\{random:(\d+)\}", repl, out)
    out = re.sub(r"\{random\}", lambda _m: _random_digits(4), out)
    return out.strip() or f"Группа {counter}"


def group_name_for_record(
    record: ContactRecord,
    record_index: int,
    session_name: str = "",
    cfg: dict | None = None,
) -> tuple[str, dict]:
    """Имя группы: шаблон = строка (record_index mod кол-во шаблонов)."""
    cfg = load_automation_config() if cfg is None else copy.deepcopy(cfg)
    tpls = list_group_templates(cfg)
    if not tpls:
        tpls = ["{fio}"]
    tpl = tpls[record_index % len(tpls)]
    counter = int(cfg.get("group_name_counter") or 1)
    name = render_group_name(
        tpl,
        counter=counter,
        session_name=session_name,
        record=record,
        cfg=cfg,
    )
    cfg["group_name_counter"] = counter + 1
    save_settings(cfg)
    return name, cfg


def next_group_name(
    session_name: str = "",
    cfg: dict | None = None,
    record: ContactRecord | None = None,
    record_index: int = 0,
) -> tuple[str, dict]:
    if record is not None:
        return group_name_for_record(record, record_index, session_name, cfg)
    cfg = load_automation_config() if cfg is None else copy.deepcopy(cfg)
    tpls = list_group_templates(cfg) or ["Группа {n}"]
    counter = int(cfg.get("group_name_counter") or 1)
    name = render_group_name(tpls[0], counter=counter, session_name=session_name, cfg=cfg)
    cfg["group_name_counter"] = counter + 1
    save_settings(cfg)
    return name, cfg


def pick_delay(key: str, cfg: dict | None = None) -> float:
    cfg = cfg or load_automation_config()
    block = cfg.get("delays_sec") or {}
    val = block.get(key)
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        lo, hi = float(val[0]), float(val[1])
        if hi < lo:
            lo, hi = hi, lo
        return random.uniform(lo, hi)
    if isinstance(val, (int, float)):
        return float(val)
    return 1.0
