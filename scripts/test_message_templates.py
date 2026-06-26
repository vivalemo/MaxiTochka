# -*- coding: utf-8 -*-
"""Тесты шаблонов первого сообщения."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from automation_config import message_for_record, post_group_steps_for_record
from contact_database import ContactRecord


def test_message_rotation() -> None:
    rec = ContactRecord(
        fio="Иванов Иван",
        dob="01.01.1990",
        phones=[("79001234567", "Иван")],
    )
    cfg = {
        "first_message_templates": ["Привет, {short_name}!", "Добрый день, {fio}!"],
        "post_group_steps": [{"type": "wait_reply", "timeout_sec": 60, "match": "any"}],
        "group_name_counter": 1,
    }
    m0 = message_for_record(rec, 0, cfg=cfg)
    m1 = message_for_record(rec, 1, cfg=cfg)
    m2 = message_for_record(rec, 2, cfg=cfg)
    assert m0 == "Привет, Иван!"
    assert m1 == "Добрый день, Иванов Иван!"
    assert m2 == "Привет, Иван!"


def test_post_steps_merge() -> None:
    rec = ContactRecord(fio="Тест", phones=[("79001112233", "")])
    cfg = {
        "first_message_templates": ["Здравствуйте!"],
        "post_group_steps": [
            {"type": "send", "text": "старый send игнорируется"},
            {"type": "delay", "seconds": 2},
        ],
        "group_name_counter": 1,
    }
    steps = post_group_steps_for_record(rec, 0, cfg=cfg)
    assert steps[0] == {"type": "send", "text": "Здравствуйте!"}
    assert steps[1] == {"type": "delay", "seconds": 2}
    assert len(steps) == 2


def main() -> int:
    test_message_rotation()
    test_post_steps_merge()
    print("OK: message_templates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
