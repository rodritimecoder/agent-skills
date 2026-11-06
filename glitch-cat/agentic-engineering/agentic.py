#!/usr/bin/env python3
"""
agentic.py — Unified CLI for Agentic Engineering (Kem's 7-Step Pipeline)
Kanban Engine, Event Listener, Fresh-Context Judge, Splitter, and Multi-Model Sandboxes.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
SCRIPTS_DIR = SCRIPT_PATH.parent / "scripts" if SCRIPT_PATH.parent.name != "scripts" else SCRIPT_PATH.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import kanban
import listener
import judge
import json
from datetime import datetime, timezone
import splitter


def log_event(target_dir: Path, event_type: str, data: dict):
    shared_dir = target_dir / "_shared"
    if not shared_dir.exists():
        shared_dir = target_dir / ".harness"
    shared_dir.mkdir(parents=True, exist_ok=True)
    log_file = shared_dir / "events.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "data": data,
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def run_code_gate(name: str, command: str, cwd: Path) -> dict:
    if not command:
        return {"name": name, "status": "SKIPPED", "command": None, "passed": None}
    started = time.time()
    proc = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
    return {
        "name": name,
        "status": "PASSED" if proc.returncode == 0 else "FAILED",
        "command": command,
        "exit_code": proc.returncode,
        "duration_seconds": round(time.time() - started, 2),
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-2000:],
        "passed": proc.returncode == 0,
    }


def check_evidence(path: str, cwd: Path) -> dict:
    if not path:
        return {"name": "gate_evidence", "status": "SKIPPED", "passed": None, "path": None}
    evidence = Path(path)
    if not evidence.is_absolute():
        evidence = Path(cwd) / evidence
    size = evidence.stat().st_size if evidence.is_file() else 0
    passed = size > 0
    return {
        "name": "gate_evidence",
        "status": "PASSED" if passed else "FAILED",
        "passed": passed,
        "path": str(evidence),
        "bytes": size,
    }


def print_gate(report: dict) -> None:
    icon = {"PASSED": "✅", "FAILED": "❌", "SKIPPED": "⏭️"}[report["status"]]
    detail = report.get("command") or report.get("path") or "not configured"
    print(f"  🔹 {report['name']}: {detail} -> {icon} {report['status']}")


def cmd_run_pipeline(
    card_id: str,
    target_dir: Path = None,
    model: str = "flash",
    mock_judge: str = None,
    lint_cmd: str = None,
    test_cmd: str = None,
    evidence: str = None,
    allow_ungated: bool = False,
    dry_run: bool = False,
    mark_done: bool = False,
    judge_cmd: str = None,
    judge_url: str = None,
):
    target = (target_dir or Path.cwd()).resolve()
    kanban_dir = kanban.find_kanban_root(target)

    print("\n" + "═" * 80)
    print(f"🚀 [AGENTIC ENGINEERING PIPELINE] Running Kem's 7-Step Loop for {card_id}")
    print("═" * 80)
    log_event(target, "PIPELINE_STARTED", {"card_id": card_id, "model": model})

    # 1. Kanban pickup (Step 2 -> 3)
    print(f"\n[Step 2-3] Picking up card {card_id}...")
    card_path = kanban.move_card(card_id, "picked_up", target_dir=target)
    card_info = kanban.parse_card(card_path)
    log_event(target, "CARD_PICKED_UP", {"card_id": card_id, "title": card_info.get("title")})

    # 2. Deterministic Code Gates (Step 4.1)
    print(f"\n[Step 4.1] Executing Deterministic Code Gates (Blue Diamonds)...")
    if dry_run:
        print("  ⚠️  DRY RUN: gates are reported, not trusted. Never ship a dry-run verdict.")
    gates = [
        run_code_gate("gate_lint", lint_cmd, target),
        run_code_gate("gate_test", test_cmd, target),
        check_evidence(evidence, target),
    ]
    for gate in gates:
        print_gate(gate)
    log_event(target, "CODE_GATES_EVALUATED", {"card_id": card_id, "gates": gates, "dry_run": dry_run})

    failed = [g for g in gates if g["status"] == "FAILED"]
    skipped = [g for g in gates if g["status"] == "SKIPPED"]
    if failed:
        names = ", ".join(g["name"] for g in failed)
        print(f"\n❌ Deterministic gate failed: {names}. Card returned to 02_picked_up.")
        kanban.move_card(card_id, "picked_up", target_dir=target)
        log_event(target, "CODE_GATES_FAILED", {"card_id": card_id, "failed": names})
        sys.exit(1)
    if len(skipped) == len(gates) and not allow_ungated and not dry_run:
        print("\n❌ No deterministic gate configured. Nothing could fail, so nothing passed.")
        print("   Pass --lint, --test or --evidence, or acknowledge the risk with --allow-ungated.")
        log_event(target, "CODE_GATES_REFUSED", {"card_id": card_id, "reason": "no gate configured"})
        sys.exit(2)

    # 3. Unbiased Judge with Fresh Context (Step 4.2)
    print(f"\n[Step 4.2] Invoking Fresh-Context Judge (Model: {model})...")
    approved = judge.run_judge(
        card_id,
        target_dir=target,
        model=model,
        mock=mock_judge,
        gate_report=gates,
        judge_cmd=judge_cmd,
        judge_url=judge_url,
    )
    log_event(target, "JUDGE_EVALUATION", {"card_id": card_id, "approved": approved, "model": model})

    if not approved:
        print(f"\n❌ Pipeline halted: Card {card_id} failed Judge review.")
        print(f"🏹 Kem's Pink Arrow triggered: Returned to worker with rejection delta.")
        log_event(target, "PIPELINE_REJECTED", {"card_id": card_id})
        sys.exit(1)

    # 4. The Splitter (Step 5)
    print(f"\n[Step 5] Gated plan approved. Invoking Task Splitter...")
    plan = splitter.split_task(card_info.get("title", card_id))
    splitter.print_split_plan(plan)
    log_event(target, "TASK_SPLIT", {"card_id": card_id, "lanes": len(plan["lanes"])})

    # 5. Multi-Model Sandboxes (Step 6): allocation only, execution is the worker's job
    print(f"[Step 6] Allocating parallel sandboxes...")
    for lane in plan["lanes"]:
        print(f"  📦 {lane['sandbox']} [{lane['model'].upper()}]: {lane['output_target']} -> DISPATCHED")
        log_event(target, "SANDBOX_LANE_DISPATCHED", lane)

    # 6. Delivery to the human verifier (Step 7)
    if mark_done:
        kanban.move_card(card_id, "done", target_dir=target)
        print(f"\n🎉 Card {card_id} marked DONE by explicit --mark-done.")
        log_event(target, "DELIVERY_COMPLETED", {"card_id": card_id, "total_lanes": len(plan["lanes"]), "marked_done": True})
    else:
        kanban.move_card(card_id, "review", target_dir=target)
        print(f"\n👤 Card {card_id} moved to 03_review. The human is the final verifier.")
        print("   Move it to done yourself once you have checked the intent: agentic kanban move "
              f"{card_id} done")
        log_event(target, "DELIVERY_COMPLETED", {"card_id": card_id, "total_lanes": len(plan["lanes"]), "marked_done": False})
    print("═" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        prog="agentic",
        description="Agentic Engineering Pipeline: Kanban, Event Listener, Fresh-Context Judge, Splitter & Sandboxes"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Initialize .kanban/ board in target project")
    p_init.add_argument("target", nargs="?", default=".", help="Target project directory")

    # kanban
    p_kb = sub.add_parser("kanban", help="Manage task board (list, add, move)")
    kb_sub = p_kb.add_subparsers(dest="kb_action", required=True)
    
    p_kblist = kb_sub.add_parser("list", help="Render ASCII Kanban board")
    p_kblist.add_argument("target", nargs="?", default=".", help="Target directory")
    p_kblist.add_argument("--json", action="store_true", help="Output board as JSON")

    p_kbadd = kb_sub.add_parser("add", help="Add new task card to 01_new/")
    p_kbadd.add_argument("title", help="Title of task card")
    p_kbadd.add_argument("--model", default="flash", help="Model tier")
    p_kbadd.add_argument("--req", help="Primary requirement [REQ-01]")
    p_kbadd.add_argument("--target", default=".", help="Target directory")

    p_kbmove = kb_sub.add_parser("move", help="Move card between columns")
    p_kbmove.add_argument("card_id", help="Card ID (e.g. CARD-001)")
    p_kbmove.add_argument("column", choices=["new", "picked_up", "review", "done"], help="Target column")
    p_kbmove.add_argument("--target", default=".", help="Target directory")

    # listen
    p_listen = sub.add_parser("listen", help="Run the Event Listener on 01_new/ cards")
    p_listen.add_argument("target", nargs="?", default=".", help="Target project directory")
    p_listen.add_argument("--once", action="store_true", help="Run single poll pass")
    p_listen.add_argument("--interval", type=int, default=5, help="Polling interval in seconds")
    p_listen.add_argument("--worker", default=None, help="Command to run when card is claimed")

    # judge
    p_judge = sub.add_parser("judge", help="Run the Fresh-Context Unbiased Judge on a card")
    p_judge.add_argument("card_id", help="Card ID to evaluate")
    p_judge.add_argument("target", nargs="?", default=".", help="Target directory")
    p_judge.add_argument("--model", default="flash", help="Judge model tier (default: flash)")
    p_judge.add_argument("--mock", choices=["PASS", "FAIL"], help="Mock verdict for dry-run testing")

    # split
    p_split = sub.add_parser("split", help="Split task into parallel sandbox lanes")
    p_split.add_argument("title", help="Task title to split")
    p_split.add_argument("--subtasks", help="Comma-separated subtasks")
    p_split.add_argument("--json", action="store_true", help="Output as JSON")

    # run
    p_run = sub.add_parser("run", help="Run full 7-step Agentic Engineering loop on a card")
    p_run.add_argument("card_id", help="Card ID to execute")
    p_run.add_argument("target", nargs="?", default=".", help="Target directory")
    p_run.add_argument("--model", default="flash", help="Judge model tier")
    p_run.add_argument("--mock-judge", choices=["PASS", "FAIL"], help="Mock judge outcome for dry-run testing")
    p_run.add_argument("--lint", default=None, help="Lint/typecheck command that must exit 0")
    p_run.add_argument("--test", default=None, help="Test command that must exit 0")
    p_run.add_argument("--evidence", default=None, help="Artifact that must exist and be non-empty (e.g. .verify/verify.json)")
    p_run.add_argument("--allow-ungated", action="store_true", help="Proceed when no deterministic gate is configured")
    p_run.add_argument("--dry-run", action="store_true", help="Report gates without trusting them")
    p_run.add_argument("--mark-done", action="store_true", help="Move the card to done yourself; default leaves it in review for the human")
    p_run.add_argument("--judge-cmd", default=os.environ.get("AGENTIC_JUDGE_CMD"), help="Command that reads the judge prompt on stdin and prints a verdict")
    p_run.add_argument("--judge-url", default=os.environ.get("AGENTIC_JUDGE_URL", "http://127.0.0.1:8080/v1/chat/completions"), help="OpenAI-compatible endpoint for the fresh-context judge")

    args = parser.parse_args()

    if args.command == "init":
        kanban.init_kanban(Path(args.target).resolve())
    elif args.command == "kanban":
        target = Path(getattr(args, "target", ".")).resolve()
        if args.kb_action == "list":
            k_dir = kanban.find_kanban_root(target)
            kanban.render_ascii_board(k_dir, as_json=args.json)
        elif args.kb_action == "add":
            kanban.add_card(args.title, target_dir=target, model=args.model, req=args.req)
        elif args.kb_action == "move":
            kanban.move_card(args.card_id, args.column, target_dir=target)
    elif args.command == "listen":
        target = Path(args.target).resolve()
        k_dir = kanban.find_kanban_root(target)
        listener.listen_loop(k_dir, interval=args.interval, once=args.once, worker_cmd=args.worker)
    elif args.command == "judge":
        judge.run_judge(args.card_id, target_dir=Path(args.target).resolve(), model=args.model, mock=args.mock)
    elif args.command == "split":
        st = [s.strip() for s in args.subtasks.split(",")] if args.subtasks else None
        p = splitter.split_task(args.title, st)
        if args.json:
            import json
            print(json.dumps(p, indent=2))
        else:
            splitter.print_split_plan(p)
    elif args.command == "run":
        cmd_run_pipeline(
            args.card_id,
            target_dir=Path(args.target).resolve(),
            model=args.model,
            mock_judge=args.mock_judge,
            lint_cmd=args.lint,
            test_cmd=args.test,
            evidence=args.evidence,
            allow_ungated=args.allow_ungated,
            dry_run=args.dry_run,
            mark_done=args.mark_done,
            judge_cmd=args.judge_cmd,
            judge_url=args.judge_url,
        )


if __name__ == "__main__":
    main()
