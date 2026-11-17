#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent / "scripts"))
from pipeline_core import EvalPipeline, PropagationRiskError

FAILED = "failed"
NON_FAILURE_STATUSES = {"passed", "ok", "success", "skipped"}


def _step_index(data):
    value = data.get("step_index", data.get("stage"))
    return value if value is not None else "?"


def _step_name(data, artifact):
    return data.get("step_name") or data.get("stage_name") or artifact.stem


def _read_artifact(artifact):
    try:
        data = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"unreadable artifact: {exc}"
    if not isinstance(data, dict):
        return None, "artifact is not a JSON object"
    return data, None


def audit_ledger(ledger_dir):
    """Return (report, failed) where failed is True if the gate must exit non-zero."""
    ld = Path(ledger_dir)
    if not ld.exists():
        return {"ledger_dir": str(ld), "status": "failed", "error": f"no ledger found at {ld}", "steps": []}, True

    artifacts = sorted(ld.glob("step_*.json"))
    if not artifacts:
        return {
            "ledger_dir": str(ld),
            "status": "failed",
            "error": f"no step_*.json artifacts in '{ld}' - nothing was audited",
            "steps": [],
        }, True

    steps = []
    failed = False
    for artifact in artifacts:
        data, error = _read_artifact(artifact)
        if error:
            steps.append({
                "artifact": str(artifact),
                "index": "?",
                "name": artifact.stem,
                "step_type": None,
                "status": FAILED,
                "error": error,
            })
            failed = True
            continue

        status = data.get("status")
        normalized = str(status).strip().lower() if status is not None else ""
        entry = {
            "artifact": str(artifact),
            "index": _step_index(data),
            "name": _step_name(data, artifact),
            "step_type": data.get("step_type"),
            "status": normalized or None,
        }
        if normalized == FAILED:
            failed = True
        elif normalized not in NON_FAILURE_STATUSES:
            # Anything that is neither a known success nor an explicit skip is
            # unverified evidence: it must not read as a pass.
            entry["error"] = f"unrecognised status {status!r}"
            entry["status"] = FAILED
            failed = True
        reason = data.get("failure_reason") or data.get("errors")
        if reason:
            entry["failure_reason"] = reason
        steps.append(entry)

    report = {
        "ledger_dir": str(ld),
        "status": "failed" if failed else "ok",
        "total_steps": len(steps),
        "failed_steps": sum(1 for s in steps if s.get("status") == FAILED),
        "steps": steps,
    }
    return report, failed


def print_audit_report(report):
    print(f"📋 Step Artifacts in '{report['ledger_dir']}' ({report.get('total_steps', 0)} step(s)):")
    if report.get("error"):
        print(f"  🛑 {report['error']}")
    for step in report.get("steps", []):
        status = (step.get("status") or "unknown").upper()
        icon = "✓" if status in {"PASSED", "OK", "SUCCESS"} else ("⏭" if status == "SKIPPED" else "🛑")
        name = step.get("name") or "?"
        line = f"  {icon} Step {step.get('index')}: [{step.get('step_type') or '?'}] '{name}' -> {status}"
        if step.get("error"):
            line += f" ({step['error']})"
        if step.get("failure_reason"):
            line += f" — {step['failure_reason']}"
        print(line)
    verdict = "PASS" if report["status"] == "ok" else "FAIL"
    print(f"  {verdict}: {report.get('failed_steps', 0)} failed of {report.get('total_steps', 0)} step(s)")


def main():
    parser = argparse.ArgumentParser(description="Eval Pipeline CLI — Step-Level Propagation Risk Shield")
    parser.add_argument("--ledger", default=".eval_ledger", help="Artifact ledger directory (default: .eval_ledger)")
    parser.add_argument("--json", action="store_true", help="Output in structured JSON")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output in structured JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_aud = subparsers.add_parser("audit", parents=[common], help="Audit recorded step artifacts in ledger")
    p_aud.add_argument("--ledger-dir", default=None, help="Ledger directory path (default: --ledger)")

    subparsers.add_parser("verify-sample", parents=[common], help="Run self-diagnostic verification pipeline")

    args = parser.parse_args()
    as_json = getattr(args, "json", False)

    if args.command == "audit":
        report, failed = audit_ledger(args.ledger_dir or args.ledger)
        if as_json:
            print(json.dumps(report, indent=2))
        else:
            print_audit_report(report)
        sys.exit(1 if failed else 0)

    elif args.command == "verify-sample":
        try:
            pipe = EvalPipeline(Path(".eval_ledger_sample"))
            pipe.register_step("ingest", "D", lambda x: {"parsed_ids": [1, 2, 3]}, lambda out: (len(out["parsed_ids"]) > 0, "IDs list empty"))
            pipe.register_step("reason", "P", lambda x: {"confidence": 0.95, "plan": "execute"}, lambda out: (out["confidence"] >= 0.80, "Confidence below 0.80"))
            pipe.register_step("transform", "D", lambda x: {"status": "ready", "count": 3}, lambda out: (out["status"] == "ready", "Status not ready"))
            res = pipe.run({"raw": "sample_input"})
        except PropagationRiskError as exc:
            if as_json:
                print(json.dumps({"status": "failed", "error": str(exc), "step_index": exc.step_idx}))
            else:
                print(f"🛑 Sample pipeline halted: {exc}")
            sys.exit(1)
        if as_json:
            print(json.dumps({"status": res["status"], "total_steps": res["total_steps"]}, indent=2))
        else:
            print(f"✓ Sample pipeline executed with 0 propagation failures. ({res['total_steps']} steps verified)")


if __name__ == "__main__":
    main()
