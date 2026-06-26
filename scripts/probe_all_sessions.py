# -*- coding: utf-8 -*-
"""Проверка всех токенов в sessions/."""
from __future__ import annotations

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from probe_sessions import probe
from test_suite_common import save_json, phone_from_session_file


def main() -> int:
    files = sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(ROOT, "sessions", "*.txt"))
    )
    results = []
    port = 19400
    for fname in files:
        print(f"probe {fname}...", flush=True)
        results.append(probe(fname, port))
        port += 1

    ready = [r for r in results if r.get("ok")]
    print(f"\nREADY: {len(ready)}/{len(results)}")
    for r in ready:
        print(f"  {r['file']}  phone={r.get('phone')}")

    save_json(
        "probe_all_sessions.json",
        {
            "total": len(results),
            "ready_count": len(ready),
            "ready": [r["file"] for r in ready],
            "results": results,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
