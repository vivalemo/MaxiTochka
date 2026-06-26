"""Глобальная блокировка лидов между сессиями автоматизации."""

from __future__ import annotations

import threading

from contact_database import normalize_phone

_lock = threading.Lock()
_claimed: dict[str, str] = {}  # phone -> session_name


def reset_claims() -> None:
    with _lock:
        _claimed.clear()


def try_claim(phone: str, session_name: str) -> tuple[bool, str]:
    """Зарезервировать лид для сессии. Возвращает (ok, owner_session)."""
    key = normalize_phone(phone or "")
    if not key:
        return True, session_name
    with _lock:
        owner = _claimed.get(key)
        if owner and owner != session_name:
            return False, owner
        _claimed[key] = session_name
        return True, session_name


def release_claim(phone: str, session_name: str) -> None:
    key = normalize_phone(phone or "")
    if not key:
        return
    with _lock:
        if _claimed.get(key) == session_name:
            _claimed.pop(key, None)
