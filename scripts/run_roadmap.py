# -*- coding: utf-8 -*-
"""
Полный прогон этапов ROADMAP_ALPHA.md с отчётом после каждого этапа.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "src"))

from test_suite_common import save_json, phone_from_session_file, session_exists, load_test_config


def _stage(name: str, fn):
    print(f"\n{'='*60}\nSTAGE: {name}\n{'='*60}", flush=True)
    t0 = time.time()
    try:
        result = fn()
        result.setdefault("stage", name)
        result["elapsed_sec"] = round(time.time() - t0, 1)
        mark = "OK" if result.get("ok") else ("SKIP" if result.get("skip") else "FAIL")
        print(f"{mark} ({result['elapsed_sec']}s)", flush=True)
        return result
    except Exception as ex:
        r = {"stage": name, "ok": False, "error": str(ex), "elapsed_sec": round(time.time() - t0, 1)}
        print(f"FAIL: {ex}", flush=True)
        return r


def stage_unit():
    from test_unit_all import run_all
    r = run_all()
    return {"ok": r["passed"] == r["total"], **r}


def stage_probe():
    import glob
    from probe_sessions import probe

    files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "sessions", "*.txt")))
    results = []
    port = 19500
    for fname in files:
        results.append(probe(fname, port))
        port += 1
    ready = [x for x in results if x.get("ok")]
    save_json("probe_all_sessions.json", {"ready": [r["file"] for r in ready], "results": results})
    # обновить test_accounts
    if len(ready) >= 2:
        cfg_path = os.path.join(ROOT, "scripts", "test_accounts.json")
        cfg = load_test_config()
        cfg["primary_session"] = ready[0]["file"]
        cfg["secondary_session"] = ready[1]["file"]
        cfg["secondary_candidates"] = [r["file"] for r in ready[1:6]]
        cfg["all_ready"] = [{"file": r["file"], "phone": r.get("phone")} for r in ready]
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    return {
        "ok": len(ready) >= 2,
        "ready_count": len(ready),
        "total": len(results),
        "ready": [{"file": r["file"], "phone": r.get("phone")} for r in ready],
    }


def stage_integration():
    import integration_test
    code = integration_test.main()
    path = os.path.join(ROOT, "scripts", "test_results", "report.json")
    data = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
    return {"ok": code == 0, "passed": data.get("passed"), "total": data.get("total"), "tests": data.get("tests")}


def stage_wait_reply():
    from test_wait_reply import test_wait_reply_live
    r = test_wait_reply_live()
    save_json("wait_reply_report.json", {"tests": [r]})
    return {**r, "ok": bool(r.get("ok"))}


def stage_multi_crm():
    from test_multi_crm import test_cross_account_crm
    r = test_cross_account_crm()
    save_json("multi_crm_report.json", {"tests": [r]})
    if r.get("skip"):
        return {**r, "ok": False, "skipped": True}
    return {**r, "ok": bool(r.get("ok"))}


def stage_round_robin_3():
    """Симуляция 3 токенов: уникальные индексы лидов."""
    from automation_runner import _build_session_assignments
    import glob

    files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "sessions", "*.txt")))
    probe_path = os.path.join(ROOT, "scripts", "test_results", "probe_all_sessions.json")
    if os.path.isfile(probe_path):
        data = json.load(open(probe_path, encoding="utf-8"))
        ready_set = set(data.get("ready") or [])
        files = [f for f in files if f in ready_set] or files
    if len(files) < 3:
        files = files[:3] if files else ["a.txt", "b.txt", "c.txt"]
    else:
        files = files[:3]

    by = _build_session_assignments(files)
    first_idx = {f: by[f][0].record_index for f in files if by.get(f)}
    unique = len(set(first_idx.values())) == len(first_idx)
    return {"ok": unique and len(first_idx) >= min(3, len(files)), "assignments": first_idx}


def stage_contacts_flow():
    from test_contacts_flow import main as cf_main
    code = cf_main()
    return {"ok": code == 0}


def main() -> int:
    report = {
        "started": datetime.now().isoformat(),
        "stages": [],
    }

    stages = [
        ("1_unit_tests", stage_unit),
        ("2_probe_sessions", stage_probe),
        ("3_integration_1session", stage_integration),
        ("4_round_robin_3tokens", stage_round_robin_3),
        ("5_wait_reply_2accounts", stage_wait_reply),
        ("6_multi_crm", stage_multi_crm),
        ("7_contacts_flow", stage_contacts_flow),
    ]

    for name, fn in stages:
        report["stages"].append(_stage(name, fn))

    report["finished"] = datetime.now().isoformat()
    passed = sum(1 for s in report["stages"] if s.get("ok"))
    skipped = sum(1 for s in report["stages"] if s.get("skipped"))
    report["passed"] = passed
    report["total"] = len(report["stages"])
    report["skipped"] = skipped
    path = save_json("roadmap_run_report.json", report)

    print(f"\n{'='*60}")
    print(f"ROADMAP: {passed}/{report['total']} stages OK ({skipped} skipped)")
    print(f"Report: {path}")
    for s in report["stages"]:
        m = "OK" if s.get("ok") else ("SKIP" if s.get("skipped") else "FAIL")
        print(f"  [{m}] {s.get('stage')}")

    failed = sum(1 for s in report["stages"] if not s.get("ok") and not s.get("skipped"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
