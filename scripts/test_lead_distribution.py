# -*- coding: utf-8 -*-
"""Проверка: 1 уникальный лид на сессию (round-robin)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from campaign_coordinator import assignments_for_session, plan_round_robin
from contact_database import ContactRecord


def main() -> int:
    sessions = sorted(["c.txt", "a.txt", "b.txt"])
    records = [
        ContactRecord(fio=f"Lead {i}", phones=[(f"7900000000{i}", "")])
        for i in range(7)
    ]
    plan = plan_round_robin(sessions, records, start_cursor=0)

    by_sess = {s: assignments_for_session(plan, s) for s in sessions}
    indices = [a.record_index for a in plan]
    ok = len(set(indices)) == len(indices)

    first_round = {s: (by_sess[s][0].record_index if by_sess[s] else None) for s in sessions}
    ok = ok and first_round == {"a.txt": 0, "b.txt": 1, "c.txt": 2}

    a_leads = [a.record_index for a in by_sess["a.txt"]]
    ok = ok and a_leads == [0, 3, 6]

    print("first_round", first_round)
    print("per_session", {s: len(v) for s, v in by_sess.items()})
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
