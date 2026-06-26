"""Парсер баз контактов (блоки через -------)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_BLOCK_SEP = re.compile(r"^-{3,}\s*$", re.MULTILINE)
_DOB_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_PHONE_LINE = re.compile(
    r"^\+?(?:7|8)?[\s\-()]*(\d{10,11})(?:\s+(.+))?$"
)


@dataclass
class ContactRecord:
    """Одна персона из базы."""

    fio: str = ""
    dob: str = ""
    phones: list[tuple[str, str]] = field(default_factory=list)
    raw_block: str = ""

    @property
    def primary_phone(self) -> str:
        return self.phones[0][0] if self.phones else ""

    @property
    def primary_alias(self) -> str:
        return self.phones[0][1] if self.phones else ""

    @property
    def short_name(self) -> str:
        if self.primary_alias:
            return self.primary_alias.strip()
        parts = (self.fio or "").split()
        if len(parts) >= 2:
            return parts[1].title()
        if parts:
            return parts[0].title()
        return ""

    def contact_book_name(self) -> str:
        """Подпись в контактах MAX: полное ФИО + дата рождения."""
        fio = (self.fio or "").strip()
        dob = (self.dob or "").strip()
        if fio and dob:
            return f"{fio} {dob}"
        if fio:
            return fio
        if not dob:
            return (self.primary_alias or self.short_name or "").strip()
        base = (self.primary_alias or self.short_name or "").strip()
        return f"{base} {dob}".strip() if base else dob

    def display_label(self) -> str:
        book = self.contact_book_name()
        ph = self.primary_phone
        if book and ph:
            return f"{book} · {ph}"
        if self.fio and ph:
            return f"{self.fio} · {ph}"
        return book or self.fio or ph or "?"


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return digits


def _parse_phone_line(line: str) -> tuple[str, str] | None:
    s = line.strip()
    if not s:
        return None
    m = _PHONE_LINE.match(s)
    if m:
        phone = normalize_phone(m.group(1))
        alias = (m.group(2) or "").strip()
        return phone, alias
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 10:
        rest = re.sub(r"[\d\s\-+()]", "", s).strip()
        return normalize_phone(digits), rest
    return None


def parse_contact_database(text: str) -> list[ContactRecord]:
    """Разбор текста базы на записи."""
    if not (text or "").strip():
        return []

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = _BLOCK_SEP.split(normalized)
    if len(blocks) == 1:
        blocks = [b for b in normalized.split("\n\n") if b.strip()]

    records: list[ContactRecord] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue

        rec = ContactRecord(raw_block=block.strip())
        idx = 0

        if idx < len(lines) and not _DOB_RE.match(lines[idx]) and not _parse_phone_line(lines[idx]):
            rec.fio = lines[idx]
            idx += 1

        if idx < len(lines) and _DOB_RE.match(lines[idx]):
            rec.dob = lines[idx]
            idx += 1

        while idx < len(lines):
            parsed = _parse_phone_line(lines[idx])
            if parsed:
                rec.phones.append(parsed)
            idx += 1

        if rec.phones or rec.fio:
            records.append(rec)

    return records


def load_contact_database(path: str) -> list[ContactRecord]:
    with open(path, encoding="utf-8") as f:
        return parse_contact_database(f.read())
