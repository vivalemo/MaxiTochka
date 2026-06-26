# -*- coding: utf-8 -*-
"""
Полный прогон тестов.

  python scripts/run_all_tests.py          # unit + CRM (один браузер) + multi CRM
  python scripts/run_all_tests.py --quick  # только unit (без браузера)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "src"))

from test_suite_common import save_json


def run_unit() -> dict:
    from test_unit_all import run_all

    return run_all()


def run_single_crm() -> dict:
    from test_crm import test_coordinator, test_playwright_crm, test_store_roundtrip

    tests = []
    for fn in (test_store_roundtrip, test_coordinator, test_playwright_crm):
        try:
            tests.append(fn())
        except Exception as ex:
            tests.append({"test": fn.__name__, "ok": False, "error": str(ex)})
    return {
        "suite": "crm",
        "passed": sum(1 for t in tests if t.get("ok")),
        "total": len(tests),
        "tests": tests,
    }


def run_wait_reply() -> dict:
    from test_wait_reply import test_wait_reply_live

    t = test_wait_reply_live()
    return {
        "suite": "wait_reply",
        "passed": 1 if t.get("ok") else 0,
        "skipped": 1 if t.get("skip") else 0,
        "total": 1,
        "tests": [t],
    }


def run_multi_crm() -> dict:
    from test_multi_crm import test_cross_account_crm

    t = test_cross_account_crm()
    return {
        "suite": "multi_crm",
        "passed": 1 if t.get("ok") else 0,
        "skipped": 1 if t.get("skip") else 0,
        "total": 1,
        "tests": [t],
    }


def run_integration() -> dict:
    if not os.path.isfile(os.path.join(ROOT, "scripts", "integration_test.py")):
        return {"suite": "integration", "passed": 0, "total": 0, "tests": [], "skip": True}

    import integration_test

    code = integration_test.main()
    path = os.path.join(ROOT, "scripts", "test_results", "report.json")
    if os.path.isfile(path):
        import json

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {
            "suite": "integration",
            "passed": data.get("passed", 0),
            "total": data.get("total", 0),
            "tests": data.get("tests", []),
            "exit_code": code,
        }
    return {"suite": "integration", "passed": 0, "total": 1, "tests": [{"ok": code == 0}]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="только unit-тесты")
    parser.add_argument("--no-integration", action="store_true", help="без integration_test")
    args = parser.parse_args()

    started = datetime.now().isoformat()
    t0 = time.time()
    suites = [run_unit()]

    if not args.quick:
        suites.append(run_single_crm())
        suites.append(run_multi_crm())
        suites.append(run_wait_reply())
        if not args.no_integration:
            suites.append(run_integration())

    total_passed = sum(s.get("passed", 0) for s in suites)
    total_tests = sum(s.get("total", 0) for s in suites)
    total_skipped = sum(s.get("skipped", 0) for s in suites)

    report = {
        "started": started,
        "finished": datetime.now().isoformat(),
        "elapsed_sec": round(time.time() - t0, 1),
        "passed": total_passed,
        "total": total_tests,
        "skipped": total_skipped,
        "suites": suites,
    }
    path = save_json("full_report.json", report)

    print(f"\n{'='*50}")
    for s in suites:
        name = s.get("suite", "?")
        p, t = s.get("passed", 0), s.get("total", 0)
        sk = s.get("skipped", 0)
        extra = f" (+{sk} skip)" if sk else ""
        print(f"  {name}: {p}/{t}{extra}")
        for test in s.get("tests", []):
            mark = "OK" if test.get("ok") else ("SKIP" if test.get("skip") else "FAIL")
            label = test.get("test", test.get("name", "?"))
            print(f"    {mark}: {label}")
            if test.get("error"):
                print(f"         {test['error']}")
            if test.get("skip"):
                print(f"         {test['skip']}")
    print(f"\nИтого: {total_passed}/{total_tests} за {report['elapsed_sec']}с")
    print(f"Отчёт: {path}")

    failed = 0
    for s in suites:
        for test in s.get("tests", []):
            if not test.get("ok") and not test.get("skip"):
                failed += 1
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
