#!/usr/bin/env python3
"""Hard pre-push regression gate for the omnicli routing catalog.

Runs only the four offline proof legs and writes one verdict line plus a full
artifact under ~/.local/share/omnicli/routing-gate/. A leg's exit code is the
signal; no measurement outside these four legs can affect the result.

The four hard legs are ``exec_only_flow``, ``skills_bridge_flow``, ``doc_drift``
and ``skill_standard`` (the existing Agent Skills linter). Every leg is a hard
code check: no optional section and no retrieval scoring influences the result.

Exit 0 = all four hard legs green; exit 1 = any hard leg red; exit 2 = fatal
(the measurement could not be completed, so no verdict is claimed).

The decision itself lives in ``decide()``, a pure function over an injected
report, so unit tests can prove every leg can go RED without touching the
real catalog.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = Path.home() / ".local/share/omnicli/routing-gate"

# Only these four offline proof legs decide the verdict.
HARD_LEGS = ("exec_only_flow", "skills_bridge_flow", "doc_drift", "skill_standard")


def run_script(
    name: str,
    script: str,
    *,
    args=(),
    json_result: bool = False,
    json_key: str = "ok",
    timeout: int = 600,
) -> dict:
    """Run an offline proof/leg as a subprocess; exit 0 is mandatory."""
    path = HERE / script
    r = subprocess.run(
        [sys.executable, str(path), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=timeout,
    )
    if json_result:
        try:
            payload = json.loads(r.stdout)
            passed = bool(payload.get(json_key)) and r.returncode == 0
            detail = payload.get(json_key)
        except Exception:
            passed, detail = False, "unparseable json"
    else:
        passed = r.returncode == 0
        lines = r.stdout.strip().splitlines() or r.stderr.strip().splitlines()
        detail = lines[-1] if lines else None
    return {"pass": passed, "exit": r.returncode, "detail": detail}


def decide(report: dict) -> list[str]:
    """Pure gate decision: return human-readable failures ([] means green).

    Only the four hard legs (``HARD_LEGS``) are evaluated. A missing,
    malformed or non-passing hard leg is a failure. ``report`` may be a
    fabricated dict injected by tests; only its ``legs`` mapping is read.
    No I/O, no clock, no global state.
    """
    legs = report.get("legs", report)
    failures: list[str] = []

    def leg(name: str) -> dict:
        value = legs.get(name, {})
        return value if isinstance(value, dict) else {}

    for name in HARD_LEGS:
        leg_result = leg(name)
        if not leg_result.get("pass", False):
            reason = "missing" if not leg_result else "non-passing"
            failures.append(
                f"{name} leg failed ({reason}: exit={leg_result.get('exit')}, "
                f"detail={leg_result.get('detail')})"
            )

    return failures


def check() -> tuple[bool, dict]:
    report: dict = {"at": datetime.now(timezone.utc).isoformat(), "legs": {}}

    # The env vars below only point at an alternate script path for mutation
    # tests; they never skip a leg.
    report["legs"]["exec_only_flow"] = run_script(
        "exec_only_flow", os.environ.get("ROUTING_GATE_EXEC_ONLY_FLOW") or "exec_only_flow.py"
    )
    report["legs"]["skills_bridge_flow"] = run_script(
        "skills_bridge_flow", os.environ.get("ROUTING_GATE_SKILLS_BRIDGE_FLOW") or "skills_bridge_flow.py"
    )
    report["legs"]["doc_drift"] = run_script(
        "doc_drift", os.environ.get("ROUTING_GATE_DOC_DRIFT_CHECK") or "doc_drift_check.py",
        args=("--json",), json_result=True,
    )
    report["legs"]["skill_standard"] = run_script(
        "skill_standard", os.environ.get("ROUTING_GATE_SKILL_STANDARD") or "verify_agent_skills.py",
        args=("--json",), json_result=True, json_key="clean",
    )

    failures = decide(report)
    report["failures"] = failures
    report["pass"] = not failures
    return report["pass"], report


def _write_artifact(report: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def _verdict(ok: bool, report: dict, artifact: Path) -> str:
    legs = report.get("legs", {})
    state = lambda n: "ok" if legs.get(n, {}).get("pass") else "FAIL"
    return (
        f"routing_gate: {'PASS' if ok else 'FAIL'} | "
        f"exec_only_flow {state('exec_only_flow')} | "
        f"skills_bridge_flow {state('skills_bridge_flow')} | "
        f"doc_drift {state('doc_drift')} | "
        f"skill_standard {state('skill_standard')} | "
        f"artifact={artifact}"
    )


def main() -> int:
    try:
        ok, report = check()
    except Exception as exc:  # fatal: do not claim a verdict we cannot measure
        report = {
            "at": datetime.now(timezone.utc).isoformat(),
            "pass": False,
            "fatal": f"{type(exc).__name__}: {exc}",
            "legs": {},
        }
        artifact = _write_artifact(report)
        print(f"routing_gate: FATAL | {report['fatal']} | artifact={artifact}")
        return 2

    artifact = _write_artifact(report)
    print(_verdict(ok, report, artifact))
    if not ok:
        for failure in report.get("failures", []):
            print(f"  - {failure}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
