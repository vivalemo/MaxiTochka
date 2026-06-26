# -*- coding: utf-8 -*-
"""Проверка contact_book_name без браузера."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from contact_database import ContactRecord, parse_contact_database


def test_book_name_with_fio() -> None:
    rec = parse_contact_database(
        """Тестов Тест Тестович
01.01.1990
79045765745 Вадим
-------"""
    )[0]
    assert rec.contact_book_name() == "Тестов Тест Тестович 01.01.1990"


def test_book_name_fio_only() -> None:
    rec = ContactRecord(fio="Иванов Иван", dob="15.03.1985", phones=[("79001234567", "")])
    assert rec.contact_book_name() == "Иванов Иван 15.03.1985"


def test_book_name_no_dob() -> None:
    rec = ContactRecord(fio="Петров Петр Петрович", phones=[("79001234567", "Пётр")])
    assert rec.contact_book_name() == "Петров Петр Петрович"


def main() -> int:
    test_book_name_with_fio()
    test_book_name_fio_only()
    test_book_name_no_dob()
    print("OK: contact_book_name")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
