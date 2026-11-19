#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_STATE_JSON = ".agent_state.json"
DEFAULT_STATE_MD = "STATE.md"
DEFAULT_SESSION_ROOT = Path.home() / ".local/state/state-compactor/sessions"


def session_state_paths(session_id: str, root: Optional[str] = None) -> tuple[Path, Path]:
    """Per-session ledger paths. Session ID is the only scope: no cwd walk."""
    if not session_id or not isinstance(session_id, str):
        raise ValueError("session_id must be a non-empty string")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", session_id):
        raise ValueError("session_id contains unsupported characters")
    base = Path(root).expanduser() if root else DEFAULT_SESSION_ROOT
    base = base / session_id
    base.mkdir(parents=True, exist_ok=True)
    return base / DEFAULT_STATE_JSON, base / DEFAULT_STATE_MD


def _effective_session_id(session_id: Optional[str] = None) -> Optional[str]:
    if session_id:
        return session_id
    return os.environ.get("STATE_SESSION_ID") or os.environ.get("OPENCODE_SESSION_ID")


def _find_state_file(target_dir: Optional[str] = None, session_id: Optional[str] = None) -> Path:
    sid = _effective_session_id(session_id)
    if sid:
        json_path, _ = session_state_paths(sid, target_dir)
        return json_path
    base = Path(target_dir) if target_dir else Path.cwd()
    json_path = base / DEFAULT_STATE_JSON
    if json_path.is_file():
        return json_path
    for p in base.parents:
        cand = p / DEFAULT_STATE_JSON
        if cand.is_file():
            return cand
    return base / DEFAULT_STATE_JSON

def init_state(goal: str, target_dir: Optional[str] = None, token_limit: int = 40000) -> Path:
    json_path = _find_state_file(target_dir)
    md_path = json_path.parent / DEFAULT_STATE_MD

    state_data = {
        "version": "1.1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "goal": goal,
        "token_compaction_limit": token_limit,
        "active_milestone": "Initialization",
        "turn_count": 0,
        "facts": [],
        "decisions": [],
        "tasks_open": [],
        "tasks_completed": [],
        "invariants": [],
        "forbidden": [],
        "failure_log": []
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)

    _sync_markdown(json_path, md_path, state_data)
    print(f"[state-compactor] Initialized state file at {json_path}")
    print(f"[state-compactor] Markdown mirror at {md_path}")
    return json_path

def _sync_markdown(json_path: Path, md_path: Path, data: Dict[str, Any]):
    lines = [
        f"# AGENT STATE — {data.get('goal', 'Untitled Task')}",
        f"\n**Last Updated:** `{data.get('updated_at')}` | **Active Milestone:** `{data.get('active_milestone')}`",
        f"**Compaction Threshold:** `{data.get('token_compaction_limit')} tokens` | **Turns:** `{data.get('turn_count')}`\n",
        "## 🔒 Hard Invariants & Facts (Preserved across Compactions)",
    ]

    facts = data.get("facts", [])
    if facts:
        for idx, f in enumerate(facts, 1):
            lines.append(f"{idx}. {f}")
    else:
        lines.append("_No facts recorded yet._")

    lines.append("\n## ⚖️ Key Architectural Decisions")
    decisions = data.get("decisions", [])
    if decisions:
        for idx, d in enumerate(decisions, 1):
            lines.append(f"- **D{idx}:** {d}")
    else:
        lines.append("_No architectural decisions recorded yet._")

    lines.append("\n## ⛔ Negative Constraints & Ruled Out Paths (Do Not Repeat)")
    forbidden = data.get("forbidden", [])
    if forbidden:
        for idx, f in enumerate(forbidden, 1):
            lines.append(f"- **[RULE-{idx}]** {f}")
    else:
        lines.append("_No dead-ends or negative constraints logged._")

    lines.append("\n## 📋 Completed Work")
    done = data.get("tasks_completed", [])
    if done:
        for t in done:
            lines.append(f"- [x] {t}")
    else:
        lines.append("_None yet._")

    lines.append("\n## ⏳ Open Tasks")
    open_t = data.get("tasks_open", [])
    if open_t:
        for t in open_t:
            lines.append(f"- [ ] {t}")
    else:
        lines.append("_No pending tasks._")

    lines.append("\n---\n*Maintained automatically by `state-compactor` (Kem Glitch Zero-Degradation Long Context Protocol).*")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def record(
    fact: Optional[str] = None,
    decision: Optional[str] = None,
    task: Optional[str] = None,
    done: Optional[str] = None,
    milestone: Optional[str] = None,
    invariant: Optional[str] = None,
    forbidden: Optional[str] = None,
    target_dir: Optional[str] = None
):
    json_path = _find_state_file(target_dir)
    if not json_path.is_file():
        sid = _effective_session_id()
        if sid and target_dir is None:
            init_state(goal=f"OpenCode session {sid}", target_dir=target_dir)
        else:
            raise FileNotFoundError(f"State file not found at {json_path}. Run `state-compactor init` first.")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data["turn_count"] = data.get("turn_count", 0) + 1

    if fact and fact not in data.setdefault("facts", []):
        data["facts"].append(fact)
        print(f"[state-compactor] 📌 Fact recorded: {fact}")
    if decision and decision not in data.setdefault("decisions", []):
        data["decisions"].append(decision)
        print(f"[state-compactor] ⚖️ Decision recorded: {decision}")
    if invariant and invariant not in data.setdefault("invariants", []):
        data["invariants"].append(invariant)
        print(f"[state-compactor] 🔒 Invariant locked: {invariant}")
    if forbidden and forbidden not in data.setdefault("forbidden", []):
        data["forbidden"].append(forbidden)
        print(f"[state-compactor] ⛔ Negative constraint recorded: {forbidden}")
    if task and task not in data.setdefault("tasks_open", []):
        data["tasks_open"].append(task)
        print(f"[state-compactor] ⏳ Open task added: {task}")
    if done:
        data.setdefault("tasks_open", [])
        data.setdefault("tasks_completed", [])
        if done in data["tasks_open"]:
            data["tasks_open"].remove(done)
        if done not in data["tasks_completed"]:
            data["tasks_completed"].append(done)
            print(f"[state-compactor] ✅ Task marked done: {done}")
    if milestone:
        data["active_milestone"] = milestone
        print(f"[state-compactor] 🎯 Milestone updated: {milestone}")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    md_path = json_path.parent / DEFAULT_STATE_MD
    _sync_markdown(json_path, md_path, data)

def wrap_command(
    cmd_args: List[str],
    fact_on_pass: Optional[str] = None,
    done_on_pass: Optional[str] = None,
    task_on_pass: Optional[str] = None,
    target_dir: Optional[str] = None
) -> int:
    cmd_str = " ".join(cmd_args)
    print(f"[state-compactor wrap] Running: {cmd_str}")
    res = subprocess.run(cmd_args)
    ret = res.returncode

    if ret == 0:
        print(f"[state-compactor wrap] ✅ Command passed with code 0.")
        record(
            fact=fact_on_pass or f"Command passed: `{cmd_str}`",
            done=done_on_pass,
            task=task_on_pass,
            target_dir=target_dir
        )
    else:
        err_msg = f"Command failed (code {ret}): `{cmd_str}`"
        print(f"[state-compactor wrap] ❌ {err_msg}")
        record(
            forbidden=f"Avoid failing pattern: `{cmd_str}` (exited {ret})",
            target_dir=target_dir
        )

    return ret

def check_compaction(target_dir: Optional[str] = None, transcript_path: Optional[str] = None) -> Dict[str, Any]:
    json_path = _find_state_file(target_dir)
    if not json_path.is_file():
        return {"needs_compaction": False, "reason": "No state file found"}

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    limit = data.get("token_compaction_limit", 40000)
    turns = data.get("turn_count", 0)

    est_tokens = turns * 800
    if transcript_path and os.path.exists(transcript_path):
        size = os.path.getsize(transcript_path)
        est_tokens = max(est_tokens, size // 4)

    needs_compaction = est_tokens >= limit or turns >= 40
    return {
        "needs_compaction": needs_compaction,
        "estimated_tokens": est_tokens,
        "token_limit": limit,
        "turns": turns,
        "active_milestone": data.get("active_milestone"),
        "facts_count": len(data.get("facts", [])),
        "forbidden_count": len(data.get("forbidden", [])),
        "open_tasks_count": len(data.get("tasks_open", []))
    }

def check_report(target_dir: Optional[str] = None, transcript_path: Optional[str] = None) -> List[Dict[str, Any]]:
    res = check_compaction(target_dir=target_dir, transcript_path=transcript_path)
    if "estimated_tokens" not in res:
        return [{
            "name": "state_file",
            "ok": False,
            "detail": f"{res.get('reason', 'no state file')}: {_find_state_file(target_dir)}",
        }]
    limit = res["token_limit"]
    turns = res["turns"]
    return [
        {
            "name": "token_budget",
            "ok": res["estimated_tokens"] < limit,
            "detail": f"{res['estimated_tokens']} estimated tokens / {limit} limit",
        },
        {
            "name": "turn_budget",
            "ok": turns < 40,
            "detail": f"{turns} turns / 40 max",
        },
    ]

def generate_handover(target_dir: Optional[str] = None, out_path: Optional[str] = None) -> str:
    json_path = _find_state_file(target_dir)
    if not json_path.is_file():
        raise FileNotFoundError(f"State file not found at {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    handover = [
        "================================================================================",
        "  ⚡ ZERO-DEGRADATION COMPACTION HANDOVER (Kem Glitch State Protocol)",
        "================================================================================",
        f"TASK GOAL        : {data.get('goal')}",
        f"ACTIVE MILESTONE : {data.get('active_milestone')}",
        f"TOTAL TURNS RUN  : {data.get('turn_count')}",
        "",
        "--- GROUND TRUTH FACTS & INVARIANTS (Preserved 100% without LLM summarizer) ---"
    ]

    for idx, f in enumerate(data.get("facts", []), 1):
        handover.append(f"  [{idx}] {f}")

    for idx, inv in enumerate(data.get("invariants", []), 1):
        handover.append(f"  [INV-{idx}] {inv}")

    if data.get("forbidden"):
        handover.append("\n--- ⛔ NEGATIVE CONSTRAINTS & DEAD-ENDS (DO NOT REPEAT) ---")
        for idx, forb in enumerate(data["forbidden"], 1):
            handover.append(f"  [RULE-{idx}] {forb}")

    handover.append("\n--- ARCHITECTURAL DECISIONS ---")
    for idx, d in enumerate(data.get("decisions", []), 1):
        handover.append(f"  [D{idx}] {d}")

    handover.append("\n--- OPEN TASKS TO EXECUTE NEXT ---")
    for idx, t in enumerate(data.get("tasks_open", []), 1):
        handover.append(f"  [ ] {t}")

    handover.append("\n--- COMPLETED WORK ---")
    for idx, t in enumerate(data.get("tasks_completed", []), 1):
        handover.append(f"  [✓] {t}")

    handover.append("================================================================================")
    content = "\n".join(handover) + "\n"

    if out_path:
        Path(out_path).write_text(content, encoding="utf-8")
        print(f"[state-compactor] Handover prompt written to {out_path}")

    return content

def bridge_summary(target_dir: Optional[str] = None) -> str:
    """Render session state in the shape OpenCode uses for compaction summaries.

    Only verified ledger fields are included — never raw transcript text — so an
    error cannot be silently summarized into a fact (context poisoning shield).
    """
    json_path = _find_state_file(target_dir)
    if not json_path.is_file():
        return (
            "## Objective\nNo state ledger initialized for this session yet.\n\n"
            "## Next Move\nRecord a verified fact with `state_record` before compacting.\n"
        )
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    lines = [
        "## Objective",
        data.get("goal") or "Untitled task",
        "",
        "## Active Milestone",
        data.get("active_milestone") or "None set",
        "",
        "## Ground Truth Facts (verbatim, zero-loss)",
    ]
    facts = data.get("facts", [])
    lines += [f"{i}. {fact}" for i, fact in enumerate(facts, 1)] or ["_None recorded._"]
    lines += ["", "## Decisions"]
    decisions = data.get("decisions", [])
    lines += [f"- D{i}: {d}" for i, d in enumerate(decisions, 1)] or ["_None recorded._"]
    lines += ["", "## Negative Constraints (Do Not Repeat)"]
    forbidden = data.get("forbidden", [])
    lines += [f"- RULE-{i}: {f}" for i, f in enumerate(forbidden, 1)] or ["_None recorded._"]
    lines += ["", "## Completed Work"]
    done = data.get("tasks_completed", [])
    lines += [f"- [x] {t}" for t in done] or ["_None yet._"]
    lines += ["", "## Active Work / Open Tasks"]
    open_tasks = data.get("tasks_open", [])
    lines += [f"- [ ] {t}" for t in open_tasks] or ["_None pending._"]
    lines += ["", "## Next Move"]
    if open_tasks:
        lines.append(open_tasks[0])
    elif data.get("active_milestone"):
        lines.append(f"Continue: {data['active_milestone']}")
    else:
        lines.append("Await direction from the user.")
    lines += [
        "",
        "---",
        f"Session ledger: `{json_path}` | turns: {data.get('turn_count', 0)} | "
        "supersede facts in place, never overwrite with an older summary.",
    ]
    return "\n".join(lines) + "\n"


def inspect_state(target_dir: Optional[str] = None, as_json: bool = False):
    json_path = _find_state_file(target_dir)
    if not json_path.is_file():
        if as_json:
            print(json.dumps({"ok": False, "state": {}}))
            return
        print(f"[state-compactor] No state file found in {Path.cwd()} or parent directories.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if as_json:
        print(json.dumps({"ok": True, "state": data}))
        return

    print("\n" + "=" * 60)
    print(f" 📂 AGENT STATE LEDGER: {data.get('goal')}")
    print("=" * 60)
    print(f" Milestone : {data.get('active_milestone')}")
    print(f" Turns Run : {data.get('turn_count')} (Compaction threshold: {data.get('token_compaction_limit')} tokens)")
    print(f" Facts     : {len(data.get('facts', []))} recorded")
    print(f" Decisions : {len(data.get('decisions', []))} locked")
    print(f" Forbidden : {len(data.get('forbidden', []))} constraints active")
    print(f" Open Tasks: {len(data.get('tasks_open', []))} pending")
    print(f" Done Tasks: {len(data.get('tasks_completed', []))} finished")
    print("=" * 60)

    if data.get("facts"):
        print("\nGround Truth Facts:")
        for idx, f in enumerate(data["facts"], 1):
            print(f"  {idx}. {f}")

    if data.get("forbidden"):
        print("\nNegative Constraints (Forbidden):")
        for idx, fb in enumerate(data["forbidden"], 1):
            print(f"  [RULE-{idx}] {fb}")

    if data.get("tasks_open"):
        print("\nPending Tasks:")
        for t in data["tasks_open"]:
            print(f"  [ ] {t}")

    print("")

def main():
    p = argparse.ArgumentParser(description="Kem Glitch Zero-Degradation State Compactor")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON on stdout")
    p.add_argument("--session", help="Session ID scope (overrides STATE_SESSION_ID / OPENCODE_SESSION_ID)")
    sub = p.add_subparsers(dest="cmd")

    init_p = sub.add_parser("init", help="Initialize a new agent state ledger")
    init_p.add_argument("--goal", required=True, help="High-level goal or mission")
    init_p.add_argument("--limit", type=int, default=40000, metavar="LIMIT", help="Token compaction limit (default: 40,000)")
    init_p.add_argument("--dir", help="Target directory")

    rec_p = sub.add_parser("record", help="Record verified facts, decisions, and tasks")
    rec_p.add_argument("--fact", help="Verified ground-truth fact")
    rec_p.add_argument("--decision", help="Key architectural decision")
    rec_p.add_argument("--task", help="Add open task")
    rec_p.add_argument("--done", help="Mark task completed")
    rec_p.add_argument("--milestone", help="Update current milestone")
    rec_p.add_argument("--invariant", help="Lock critical invariant")
    rec_p.add_argument("--forbidden", help="Record dead-end or negative constraint")
    rec_p.add_argument("--dir", help="Target directory")
    rec_p.add_argument("--dry-run", action="store_true", help="Print the planned record and exit without side effects")

    wrap_p = sub.add_parser("wrap", help="Execute command and auto-record results to state ledger")
    wrap_p.add_argument("--fact", help="Fact to record if command succeeds")
    wrap_p.add_argument("--done", help="Task to mark done if command succeeds")
    wrap_p.add_argument("--task", help="Task to queue if command succeeds")
    wrap_p.add_argument("--dir", help="Target directory")
    wrap_p.add_argument("--dry-run", action="store_true", help="Print the planned command/record and exit without side effects")
    wrap_p.add_argument("command", nargs=argparse.REMAINDER, help="Command to execute")

    chk_p = sub.add_parser("check", help="Check if context has crossed compaction threshold")
    chk_p.add_argument("--transcript", help="Optional transcript log file path")
    chk_p.add_argument("--dir", help="Target directory")
    chk_p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                       help="Emit machine-readable JSON on stdout")

    comp_p = sub.add_parser("compact", help="Generate zero-loss handover prompt from state ledger")
    comp_p.add_argument("--out", help="Write handover prompt to file")
    comp_p.add_argument("--dir", help="Target directory")
    comp_p.add_argument("--dry-run", action="store_true", help="Print the planned compaction and exit without side effects")

    ins_p = sub.add_parser("inspect", help="Display current state ledger")
    ins_p.add_argument("--dir", help="Target directory")
    ins_p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                       help="Emit machine-readable JSON on stdout")

    br_p = sub.add_parser("bridge-summary", help="Render the OpenCode-shaped handover summary")
    br_p.add_argument("--dir", help="Target directory")
    br_p.add_argument("--out", help="Write summary to file")

    args = p.parse_args()
    if getattr(args, "session", None):
        os.environ["STATE_SESSION_ID"] = args.session
    if getattr(args, "dry_run", False):
        plan = {"action": args.cmd, "dry_run": True}
        for key in ("fact", "decision", "task", "done", "milestone", "invariant",
                    "forbidden", "dir", "out", "goal", "limit"):
            if getattr(args, key, None) is not None:
                plan[key] = getattr(args, key)
        if args.cmd == "wrap":
            plan["command"] = args.command
        print(json.dumps(plan, indent=2) if args.json else
              f"[dry-run] {args.cmd}: {json.dumps(plan, sort_keys=True)}")
        return
    if args.cmd == "init":
        init_state(args.goal, target_dir=args.dir, token_limit=args.limit)
    elif args.cmd == "record":
        record(
            fact=args.fact,
            decision=args.decision,
            task=args.task,
            done=args.done,
            milestone=args.milestone,
            invariant=args.invariant,
            forbidden=args.forbidden,
            target_dir=args.dir
        )
    elif args.cmd == "wrap":
        cmd_to_run = args.command
        if cmd_to_run and cmd_to_run[0] == "--":
            cmd_to_run = cmd_to_run[1:]
        if not cmd_to_run:
            print("Error: No command provided to wrap.")
            sys.exit(1)
        ret = wrap_command(
            cmd_to_run,
            fact_on_pass=args.fact,
            done_on_pass=args.done,
            task_on_pass=args.task,
            target_dir=args.dir
        )
        sys.exit(ret)
    elif args.cmd == "check":
        if args.json:
            try:
                checks = check_report(target_dir=args.dir, transcript_path=args.transcript)
            except Exception as exc:
                print(f"[state-compactor] check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                sys.exit(2)
            ok = all(c["ok"] for c in checks)
            print(json.dumps({"ok": ok, "checks": checks}))
            if not ok:
                print("\n⚠️  [state-compactor] COMPACTION TRIGGERED!", file=sys.stderr)
        else:
            res = check_compaction(target_dir=args.dir, transcript_path=args.transcript)
            print(json.dumps(res, indent=2))
            if res["needs_compaction"]:
                print(f"\n⚠️  [state-compactor] COMPACTION TRIGGERED! (Estimated tokens: {res['estimated_tokens']}/{res['token_limit']})",
                      file=sys.stderr)
                sys.exit(2)
    elif args.cmd == "compact":
        out = generate_handover(target_dir=args.dir, out_path=args.out)
        if not args.out:
            print(out)
    elif args.cmd == "inspect":
        try:
            inspect_state(target_dir=args.dir if hasattr(args, "dir") else None, as_json=args.json)
        except Exception as exc:
            if not args.json:
                raise
            print(f"[state-compactor] inspect failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            sys.exit(2)
    elif args.cmd == "bridge-summary":
        summary = bridge_summary(target_dir=args.dir)
        if args.out:
            Path(args.out).write_text(summary, encoding="utf-8")
            print(f"[state-compactor] Handover summary written to {args.out}", file=sys.stderr)
        else:
            print(summary, end="")
    else:
        p.print_help()

if __name__ == "__main__":
    main()
