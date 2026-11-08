#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent / "scripts"))
from swarm_engine import SwarmContract, SwarmBudgetExceededError, ScorecardValidationError


def main():
    parser = argparse.ArgumentParser(description="Swarm Contract CLI — Tripartite Contract & Hard Budget Enforcement")
    parser.add_argument("--dir", default=".", help="Workspace directory (default: .)")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize dynamic swarm with goal and hard budget")
    p_init.add_argument("--goal", required=True, help="Swarm discovery goal or hit list")
    p_init.add_argument("--budget", type=float, default=5.0, metavar="SCORE", help="Hard dollar budget limit (default: 5.00)")
    p_init.add_argument("--tokens", type=int, default=500000, metavar="COUNT", help="Hard token limit (default: 500000)")
    p_init.add_argument("--fields", nargs="+", default=["worker_id", "target", "status", "findings"], help="Required scorecard schema fields")

    # record
    p_rec = subparsers.add_parser("record", help="Record completed worker scorecard under budget validation")
    p_rec.add_argument("--scorecard", required=True, help="JSON string or file path containing worker scorecard")
    p_rec.add_argument("--tokens", type=int, default=0, metavar="COUNT", help="Tokens consumed by worker")
    p_rec.add_argument("--cost", type=float, default=0.0, metavar="SCORE", help="Cost in USD consumed by worker")

    # check
    p_chk = subparsers.add_parser("check", help="Pre-flight check if budget exists to spawn next worker")
    p_chk.add_argument("--est-tokens", type=int, default=10000, metavar="COUNT", help="Estimated tokens")
    p_chk.add_argument("--est-cost", type=float, default=0.05, metavar="SCORE", help="Estimated cost in USD")

    # status
    subparsers.add_parser("status", help="View swarm status and budget metrics")

    args = parser.parse_args()
    swarm = SwarmContract(Path(args.dir))

    if args.command == "init":
        m = swarm.init_swarm(args.goal, max_budget_usd=args.budget, max_tokens=args.tokens, required_schema=args.fields)
        if args.json:
            print(json.dumps(m, indent=2))
        else:
            print(f"🐝 [Swarm Init] Goal: {m['goal']}")
            print(f"  • Hard Budget: ${m['max_budget_usd']:.2f} USD / {m['max_tokens']:,} tokens")
            print(f"  • Scorecard Schema: {m['required_fields']}")

    elif args.command == "record":
        sc_data = json.loads(Path(args.scorecard).read_text(encoding="utf-8") if Path(args.scorecard).exists() else args.scorecard)
        try:
            entry = swarm.record_scorecard(sc_data, tokens_used=args.tokens, cost_usd=args.cost)
            if args.json:
                print(json.dumps(entry, indent=2))
            else:
                print(f"✓ Recorded scorecard for worker '{sc_data.get('worker_id')}' (Tokens: {args.tokens}, Cost: ${args.cost:.4f})")
        except (SwarmBudgetExceededError, ScorecardValidationError) as e:
            if args.json:
                print(json.dumps({"halted": True, "error": str(e)}, indent=2))
            else:
                print(f"🛑 [HALTED] {e}")
            sys.exit(2)

    elif args.command == "check":
        can_run = swarm.check_budget_availability(estimated_tokens=args.est_tokens, estimated_usd=args.est_cost)
        if args.json:
            print(json.dumps({"can_run": can_run}, indent=2))
        elif can_run:
            print("✓ Budget available for worker spawn.")
        else:
            print("🛑 Insufficient budget remaining to spawn worker.")
        sys.exit(0 if can_run else 2)

    elif args.command == "status":
        summ = swarm.summary()
        if args.json:
            print(json.dumps(summ, indent=2))
        else:
            b = summ["budget"]
            print(f"🐝 Swarm Status: {summ['status'].upper()} (Goal: {summ['goal']})")
            print(f"  • Budget Spend: ${b['spent_usd']:.4f} / ${b['max_usd']:.2f} (Remaining: ${b['remaining_usd']:.4f})")
            print(f"  • Tokens: {b['tokens_used']:,} / {b['max_tokens']:,} (Remaining: {b['tokens_remaining']:,})")
            print(f"  • Scorecards Compiled: {summ['total_scorecards']}")


if __name__ == "__main__":
    main()
