#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent / "scripts"))
from orchestra_conductor import OrchestraConductor


def main():
    parser = argparse.ArgumentParser(description="Glitch Orchestra CLI — Terminal Conductor & Multi-Session Supervisor")
    parser.add_argument("--dir", default=".", help="Workspace directory (default: .)")
    parser.add_argument("--json", action="store_true", help="Output in structured JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_plan = subparsers.add_parser("plan", help="Draft the alignment plan before dispatch")
    p_plan.add_argument("--audience", required=True)
    p_plan.add_argument("--great", required=True, help="What great looks like")
    p_plan.add_argument("--made", required=True, help="How the work is made")
    p_plan.add_argument("--moves", required=True, help="How the result should move or behave")
    p_plan.add_argument("--feel", required=True, help="How the result should feel")
    references = p_plan.add_mutually_exclusive_group(required=True)
    references.add_argument("--reference", action="append", help="Reference; repeat for multiple references")
    references.add_argument("--references-unnecessary", help="Why references are unnecessary for this run")
    p_plan.add_argument("--readiness-cue", help="Human-readable cue that the plan is aligned and ready")

    p_approve = subparsers.add_parser("approve", help="Record a human approval that unlocks dispatch")
    p_approve.add_argument("--by", required=True, help="Name or identifier of the human approver")

    p_reg = subparsers.add_parser("register", help="Register and dispatch a scoped specialist session")
    p_reg.add_argument("--id", required=True, help="Session ID")
    p_reg.add_argument("--task", required=True, help="Task description")
    p_reg.add_argument("--role", required=True, help="Specialist role")
    p_reg.add_argument("--scope", required=True, help="Explicit task boundary for this specialist")
    p_reg.add_argument("--term", default="term_01", help="Terminal label")

    p_signal = subparsers.add_parser("signal", help="Send a worker ping or status update to the conductor")
    p_signal.add_argument("--id", required=True, help="Active worker session ID")
    p_signal.add_argument("--message", help="Ping or progress detail")
    p_signal.add_argument("--status", dest="worker_status", help="Worker status, such as ready or blocked")

    p_compare = subparsers.add_parser("compare", help="Record a same-prompt before/after qualitative test")
    p_compare.add_argument("--id", required=True, help="Active worker session ID")
    p_compare.add_argument("--prompt", required=True, help="The exact prompt used for both runs")
    p_compare.add_argument("--before", required=True, help="Before result or artifact reference")
    p_compare.add_argument("--after", required=True, help="After result or artifact reference")
    p_compare.add_argument("--assessment", required=True, help="Human-readable qualitative assessment")

    p_comp = subparsers.add_parser("complete", help="Mark session completed")
    p_comp.add_argument("--id", required=True, help="Session ID")
    p_comp.add_argument("--summary", default="Finished", help="Completion summary")
    p_comp.add_argument("--evidence", default=None, help="Artifact that proves the work (e.g. .verify/verify.json)")

    p_alt = subparsers.add_parser("alert", help="Trigger completion alert chime")
    p_alt.add_argument("--message", default="All subagent workers finished.", help="Alert announcement message")

    p_status = subparsers.add_parser("status", help="View conductor state, workers, and events")
    p_status.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS)

    args = parser.parse_args()
    conductor = OrchestraConductor(Path(args.dir))

    try:
        if args.command == "plan":
            plan = conductor.draft_plan(
                audience=args.audience,
                great=args.great,
                made=args.made,
                moves=args.moves,
                feel=args.feel,
                references=args.reference,
                references_unnecessary=args.references_unnecessary,
                readiness_cue=args.readiness_cue,
            )
            print("📝 [Conductor] Plan drafted; a human must run 'approve' before dispatch.")
            print(json.dumps(plan, indent=2, ensure_ascii=False))

        elif args.command == "approve":
            approval = conductor.approve_plan(args.by)
            print(f"✓ [Conductor] Plan approved by {approval['approver']}; dispatch is unlocked.")

        elif args.command == "register":
            session = conductor.register_child_session(args.id, args.task, args.role, args.scope, args.term)
            print(f"🎻 [Conductor] Registered {session['role']} '{session['session_id']}' on {session['terminal_tag']}")

        elif args.command == "signal":
            event = conductor.record_worker_signal(args.id, args.message, args.worker_status)
            print(f"↩ [Conductor] Recorded worker signal #{event['sequence']} from '{args.id}'")

        elif args.command == "compare":
            event = conductor.record_worker_comparison(
                args.id,
                args.prompt,
                args.before,
                args.after,
                args.assessment,
            )
            print(f"✓ [Conductor] Recorded qualitative comparison #{event['sequence']} from '{args.id}'")

        elif args.command == "complete":
            c = conductor.mark_session_complete(args.id, args.summary, evidence=args.evidence)
            if c.get("verified"):
                print(f"✓ [Conductor] Completed session '{c['session_id']}' with evidence: {c['evidence']}")
            else:
                print(f"⚠️  [Conductor] Completed session '{c['session_id']}' UNVERIFIED — a summary is not evidence.")
                print("    Pass --evidence <artifact> from a gate run before you call this done.")

        elif args.command == "alert":
            al = conductor.trigger_completion_alert(args.message)
            print(f"🔔 [Alert] {al['alert_message']}")

        elif args.command == "status":
            st = conductor.status()
            if args.json:
                print(json.dumps(st, indent=2, ensure_ascii=False))
            else:
                plan_state = "approved" if st["dispatch_approved"] else "drafted" if st["plan"] else "missing"
                active_sessions = [
                    f"{session['session_id']} [{session.get('role', 'worker')}: {session.get('worker_status', session.get('status', 'unknown'))}]"
                    for session in st["active_sessions"]
                ]
                completed_sessions = [
                    f"{session['session_id']} [{session.get('role', 'worker')}: {session.get('status', 'completed')}; {f'evidence: {session.get("evidence")}' if session.get('verified') else 'UNVERIFIED'}]"
                    for session in st["completed_sessions"]
                ]
                print("🎼 Glitch Orchestra Conductor Status:")
                print(f"  • Plan: {plan_state}; dispatch approved: {st['dispatch_approved']}")
                print(f"  • Active Child Sessions ({st['active_count']}): {active_sessions}")
                print(f"  • Completed ({st['completed_count']}), with evidence ({st['verified_count']}): {completed_sessions}")
                print(f"  • Events ({len(st['events'])}):")
                for event in st["events"]:
                    print(f"    {json.dumps(event, ensure_ascii=False)}")

    except (ValueError, FileNotFoundError) as exc:
        print(f"❌ [Conductor] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
