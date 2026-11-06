#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent / "scripts"))
from pipeline_core import EvalPipeline, PropagationRiskError


def main():
    parser = argparse.ArgumentParser(description="Eval Pipeline CLI — Step-Level Propagation Risk Shield")
    parser.add_argument("--ledger", default=".eval_ledger", help="Artifact ledger directory (default: .eval_ledger)")
    parser.add_argument("--json", action="store_true", help="Output in structured JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # audit
    p_aud = subparsers.add_parser("audit", help="Audit recorded step artifacts in ledger")
    p_aud.add_argument("--ledger-dir", default=".eval_ledger", help="Ledger directory path")

    # verify-sample
    subparsers.add_parser("verify-sample", help="Run self-diagnostic verification pipeline")

    args = parser.parse_args()

    if args.command == "audit":
        ld = Path(args.ledger_dir)
        if not ld.exists():
            print(f"No ledger found at {ld}")
            sys.exit(1)
        artifacts = sorted(ld.glob("step_*.json"))
        print(f"📋 Step Artifacts in '{ld}' ({len(artifacts)} steps):")
        for a in artifacts:
            data = json.loads(a.read_text(encoding="utf-8"))
            status_icon = "✓" if data.get("status") == "passed" else "🛑"
            print(f"  {status_icon} Step {data.get('step_index')}: [{data.get('step_type')}] '{data.get('step_name')}' -> {data.get('status').upper()}")

    elif args.command == "verify-sample":
        pipe = EvalPipeline(Path(".eval_ledger_sample"))
        # Step 1 [D]: Deterministic Parse
        pipe.register_step("ingest", "D", lambda x: {"parsed_ids": [1, 2, 3]}, lambda out: (len(out["parsed_ids"]) > 0, "IDs list empty"))
        # Step 2 [P]: Probabilistic Model reasoning simulation
        pipe.register_step("reason", "P", lambda x: {"confidence": 0.95, "plan": "execute"}, lambda out: (out["confidence"] >= 0.80, "Confidence below 0.80"))
        # Step 3 [D]: Deterministic Transformation
        pipe.register_step("transform", "D", lambda x: {"status": "ready", "count": 3}, lambda out: (out["status"] == "ready", "Status not ready"))
        res = pipe.run({"raw": "sample_input"})
        print(f"✓ Sample pipeline executed with 0 propagation failures. ({res['total_steps']} steps verified)")


if __name__ == "__main__":
    main()
