#!/usr/bin/env python3
"""Hard pre-push regression gate for the omnicli routing catalog.

Parses eval JSON counts; never trusts eval_runner's exit code (the council
proved that leg can be green while a real regression passes). Writes one
verdict line and a full artifact under ~/.local/share/omnicli/routing-gate/.

Exit 0 = all legs green; exit 1 = any leg red (blocks the push).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNNER = Path(__file__).resolve().parent / "eval_runner.py"
OUT = Path.home() / ".local/share/omnicli/routing-gate"

FLOORS = {
    "golden": {"top1": 54, "top3": 54},       # still perfect; do not lower
    # Re-baselined 2026-11-23 after the two deleted skills removed their mostly
    # passing cases. These are the live scores: any regression below them fails.
    "fresh": {"top1": 24, "top3": 27},        # 31 cases, incl. 3 harvester-noise; 24/28 answerable
    "paraphrase": {"top1": 28},               # 34 cases
}


def run_eval(name: str) -> dict:
    r = subprocess.run(
        [sys.executable, str(RUNNER), f"--set={name}", "--rerank=never", "--fusion=never", "--json"],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    data = json.loads(r.stdout)
    bm = data["bm25"]
    answerable = [row for row in data.get("rows", []) if row.get("kind") != "harvester-noise"]
    return {
        "top1_raw": bm["top1_raw"],
        "top3_raw": bm["top3_raw"],
        "answerable_top1": sum(1 for row in answerable if row["pass_top1"]),
        "answerable_total": len(answerable),
        "runner_exit": r.returncode,  # recorded, never trusted
    }


def check() -> tuple[bool, dict]:
    report: dict = {"at": datetime.now(timezone.utc).isoformat(), "legs": {}}
    ok = True

    for name, floor in FLOORS.items():
        m = run_eval(name)
        report["legs"][name] = m
        if m["top1_raw"] < floor["top1"]:
            ok = False
        if "top3" in floor and m["top3_raw"] < floor["top3"]:
            ok = False
        if name == "fresh" and (m["answerable_top1"] < 24 or m["answerable_total"] < 28):
            ok = False

    for label, path in (
        ("overfit", ROOT / "orchestration/omnicli/tests/overfit_check.py"),
        ("doc_drift", ROOT / "orchestration/omnicli/tests/doc_drift_check.py"),
    ):
        r = subprocess.run([sys.executable, str(path), "--json"] if label == "doc_drift" else [sys.executable, str(path)],
                           cwd=ROOT, capture_output=True, text=True, timeout=120)
        if label == "overfit":
            passed = r.returncode == 0
            detail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else None
        else:
            try:
                payload = json.loads(r.stdout)
                passed = bool(payload.get("ok")) and r.returncode == 0
                detail = payload.get("ok")
            except Exception:
                passed, detail = False, "unparseable json"
        report["legs"][label] = {"pass": passed, "exit": r.returncode, "detail": detail}
        ok = ok and passed

    report["pass"] = ok
    return ok, report


def main() -> int:
    ok, report = check()
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (OUT / f"{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    g = report["legs"]
    print(
        f"routing_gate: {'PASS' if ok else 'FAIL'} | "
        f"golden {g['golden']['top1_raw']}/54 | fresh {g['fresh']['top1_raw']}/31 "
        f"(answerable {g['fresh']['answerable_top1']}/{g['fresh']['answerable_total']}) | "
        f"paraphrase {g['paraphrase']['top1_raw']}/34 | "
        f"overfit {'ok' if g['overfit']['pass'] else 'FAIL'} | "
        f"doc_drift {'ok' if g['doc_drift']['pass'] else 'FAIL'} | "
        f"artifact={OUT / (stamp + '.json')}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
