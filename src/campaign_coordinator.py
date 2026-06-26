"""Распределение лидов по токенам (round-robin) и фазы кампании."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contact_database import ContactRecord


@dataclass
class CampaignAssignment:
    round_index: int
    session_name: str
    record: ContactRecord
    record_index: int


def plan_round_robin(
    session_names: list[str],
    records: list[ContactRecord],
    start_cursor: int = 0,
) -> list[CampaignAssignment]:
    """Раздать лиды по кругам: 1 лид на 1 токен за круг."""
    sessions = [s for s in session_names if s]
    if not sessions or not records:
        return []

    out: list[CampaignAssignment] = []
    cursor = max(0, int(start_cursor or 0))
    total = len(records)
    round_i = 0

    while cursor < total:
        for sess in sessions:
            if cursor >= total:
                break
            out.append(
                CampaignAssignment(
                    round_index=round_i,
                    session_name=sess,
                    record=records[cursor],
                    record_index=cursor,
                )
            )
            cursor += 1
        round_i += 1
    return out


def assignments_for_session(
    assignments: list[CampaignAssignment], session_name: str
) -> list[CampaignAssignment]:
    return [a for a in assignments if a.session_name == session_name]


def validate_plan_unique(assignments: list[CampaignAssignment]) -> list[str]:
    """Проверить, что один индекс/телефон не назначены двум сессиям."""
    errors: list[str] = []
    by_index: dict[int, str] = {}
    by_phone: dict[str, str] = {}
    for a in assignments:
        if a.record_index in by_index and by_index[a.record_index] != a.session_name:
            errors.append(
                f"запись #{a.record_index + 1} назначена "
                f"{by_index[a.record_index]} и {a.session_name}"
            )
        by_index[a.record_index] = a.session_name
        phone = (a.record.primary_phone or "").strip()
        if phone:
            from contact_database import normalize_phone

            ph = normalize_phone(phone)
            if ph in by_phone and by_phone[ph] != a.session_name:
                errors.append(
                    f"номер {ph} назначен {by_phone[ph]} и {a.session_name}"
                )
            by_phone[ph] = a.session_name
    return errors


def limit_plan_per_session(
    assignments: list[CampaignAssignment],
    *,
    max_per_session: int = 0,
    max_rounds: int = 0,
) -> list[CampaignAssignment]:
    if max_rounds > 0:
        assignments = [a for a in assignments if a.round_index < max_rounds]
    if max_per_session <= 0:
        return assignments
    counts: dict[str, int] = {}
    out: list[CampaignAssignment] = []
    for a in assignments:
        n = counts.get(a.session_name, 0)
        if n >= max_per_session:
            continue
        counts[a.session_name] = n + 1
        out.append(a)
    return out


def summarize_plan(assignments: list[CampaignAssignment]) -> dict[str, Any]:
    per_session: dict[str, int] = {}
    for a in assignments:
        per_session[a.session_name] = per_session.get(a.session_name, 0) + 1
    rounds = max((a.round_index for a in assignments), default=-1) + 1
    return {
        "total_assignments": len(assignments),
        "rounds": rounds,
        "per_session": per_session,
    }
