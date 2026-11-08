#!/usr/bin/env python3
"""
kem-dev-loop — Kem Glitch's 6-Phase Autonomous AI Development Lifecycle.
Synthesized from Glitch Cat Club (Reel DemLMidtxxj: "How I Develop with AI (High Level)").

Phases:
  1. Classify & Route (Small/Routine -> Fast Route | Big/Complex -> Full Route)
  2. Holdouts & Intent (Anti-sycophancy: holdouts written upfront, hidden from builders)
  3. Parallel Build (Vertical slices in parallel worktrees)
  4. Grounded Validation (User persona: click, type, inspect UI; run holdouts; no adversarial loops)
  5. Decoupled Code Review (Cleanliness, typing, maintainability only AFTER functional pass)
  6. Human Intent Gate (Human validates the "Why and Why Not")
"""

import os
import sys
import re
import json
import time
import shlex
import hashlib
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

STATE_DIR = Path(".kem-loop")

# One bounded builder, one task file, all output on disk. {task} is the path
# of the copy dispatch writes, so the receipt never contains a diff.
DEFAULT_BUILDER_CMD = 'opencode run "$(cat {task})"'
DEFAULT_TIMEOUT = 900

# A classifier that is unsure is not allowed to grant autonomy. Ambiguity, a dead
# decision server, or a low-confidence answer all route to FULL_ROUTE, because the
# cost of a needless plan review is minutes and the cost of a skipped one is intent.
AUTONOMY_THRESHOLD = 0.75
MAX_VALIDATION_ATTEMPTS = 2

# Deterministic pre-screen. These surfaces cross module and ownership boundaries, so
# they get the human gate regardless of what any model says.
CROSS_CUTTING = (
    "auth", "authentication", "authorization", "login", "logout", "session",
    "sessions", "permission", "permissions", "rbac", "oauth", "jwt", "password",
    "credential", "credentials", "migration", "migrations", "migrate", "schema",
    "database", "sql", "api", "endpoint", "endpoints", "contract", "breaking",
    "payment", "billing", "pricing", "security", "encryption", "crypto",
    "concurrency", "race", "queue", "worker", "workers", "deploy", "deployment",
    "release", "infra", "refactor", "refactoring", "architecture", "redesign",
    "rewrite", "multi-agent", "orchestration", "pipeline", "distributed",
)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_meta(run_dir):
    meta_path = run_dir / "meta.json"
    return json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}


def save_meta(run_dir, meta):
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_run(name):
    run_dir = STATE_DIR / name
    if not run_dir.exists():
        print(f"❌ No run '{name}'. Start with: kem-dev-loop init {name}")
    return run_dir if run_dir.exists() else None


def tail(path, lines=25):
    try:
        return "\n".join(
            Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def run_cmd(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True)


def cross_cutting_signals(prompt):
    low = prompt.lower()
    return [w for w in CROSS_CUTTING if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low)]


def classify_by_model(prompt):
    """Ask the calibrated decision model. Never invent a verdict when it cannot answer."""
    if shutil.which("jev") is None:
        return ("FULL_ROUTE", "BIG", "unavailable", 0.0,
                "jev is not on PATH, so nothing can classify this")

    res = run_cmd([
        "jev", "choice", "--require-server", "--json",
        "--context", prompt,
        "--question", "Is this software task small enough to ship without a human-approved plan?",
        "--options", "small", "complex",
    ])
    if res.returncode != 0:
        detail = (res.stderr or res.stdout).strip().splitlines()
        return ("FULL_ROUTE", "BIG", "degraded", 0.0,
                detail[-1] if detail else "decision server did not answer")

    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return ("FULL_ROUTE", "BIG", "degraded", 0.0, "decision response was not JSON")

    selection = str(data.get("selection", "")).lower()
    source = str(data.get("source", "jev"))
    confidence = float(data.get("confidence") or 0.0)

    if "heuristic" in source:
        return ("FULL_ROUTE", "BIG", source, 0.0,
                "decision server unreachable, so the answer is a keyword fallback, not a calibrated decision")

    if selection == "small" and confidence >= AUTONOMY_THRESHOLD:
        return ("FAST_ROUTE", "SMALL", source, confidence,
                f"model judged small at {confidence:.0%} confidence")

    if selection == "complex":
        return ("FULL_ROUTE", "BIG", source, confidence,
                f"model judged complex at {confidence:.0%} confidence")

    return ("FULL_ROUTE", "BIG", source, confidence,
            f"model leaned '{selection}' but only at {confidence:.0%}; below the {AUTONOMY_THRESHOLD:.0%} bar for autonomy")


def cmd_route(args):
    as_json = getattr(args, "json", False)
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        if as_json:
            print("error: empty prompt", file=sys.stderr)
            return 2
        print("Usage: kem-dev-loop route <task description>")
        return 1

    if not as_json:
        print(f"\n🔍 [Phase 1: Classify & Route]")
        print(f'   "{prompt}"\n')

    signals = cross_cutting_signals(prompt)
    if signals:
        route, complexity, source, confidence = "FULL_ROUTE", "BIG", "deterministic", 1.0
        reason = "cross-cutting surface: " + ", ".join(signals[:6])
    else:
        route, complexity, source, confidence, reason = classify_by_model(prompt)

    if as_json:
        print(json.dumps({
            "prompt": prompt,
            "route": route,
            "complexity": complexity,
            "source": source,
            "confidence": float(confidence),
            "reason": reason,
        }))
        return 0

    print(f"🎯 Route: **{route}** ({complexity})")
    print(f"   Decided by: {source}")
    if source not in ("deterministic",):
        print(f"   Confidence: {confidence:.0%}")
    print(f"   Why: {reason}\n")

    if source in ("degraded", "unavailable") or "heuristic" in source:
        print("   ⚠️  DEGRADED: no calibrated model answered. Routed to the human gate.")
        print("       Start the decision server on :8083, then re-run to get a real verdict.\n")

    if route == "FULL_ROUTE":
        print("📋 Protocol for FULL_ROUTE:")
        print("   1. Write and human-approve PLAN.md (align on 'Why and Why Not').")
        print("   2. Scaffold hidden holdout tests: `kem-dev-loop init <name>`")
        print("   3. Dispatch parallel builders across vertical slices.")
        print("   4. Validate user journey & holdouts before code review.")
    else:
        print("⚡ Protocol for FAST_ROUTE:")
        print("   - Small or greenfield routine change.")
        print("   - Direct execution permitted with standard verification.")
        print("   - Note: this route skips human plan approval. Say so out loud before you build.")


    return 0


def cmd_init(args):
    name = args.name.strip().replace(" ", "_")
    target_dir = STATE_DIR / name
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "holdouts").mkdir(exist_ok=True)
    (target_dir / "evidence").mkdir(exist_ok=True)

    plan_path = target_dir / "plan.md"
    if not plan_path.exists():
        plan_path.write_text(f"""# Feature Plan: {name}

**Created:** {_now()}
**Status:** DRAFT (Awaiting Human Approval)

## 1. Intent: The 'Why' & 'Why Not'
- **Why we are building this:**
- **Explicit non-goals (What we are NOT building):**

## 2. Vertical Slices (Parallel Build Units)
- [ ] Slice A (e.g. backend / schema):
- [ ] Slice B (e.g. frontend / API):

## 3. Holdout Scenarios (Anti-Sycophancy)
- Hidden test cases stored in `holdouts/` that builders must NEVER inspect.
""", encoding="utf-8")

    meta_path = target_dir / "meta.json"
    meta_path.write_text(json.dumps({
        "name": name,
        "created_at": _now(),
        "phase": "PHASE_2_HOLDOUTS_AND_PLAN",
        "plan_approved": False,
        "validation_passed": False,
        "review_passed": False
    }, indent=2), encoding="utf-8")

    print(f"✅ Initialized Kem Dev Loop feature run: {target_dir}")
    print(f"   • Plan: {plan_path}")
    print(f"   • Hidden Holdouts Directory: {target_dir / 'holdouts'}")
    print(f"   • Evidence Output: {target_dir / 'evidence'}")
    return 0


def cmd_approve(args):
    run_dir = require_run(args.name)
    if not run_dir:
        return 1
    meta = load_meta(run_dir)
    meta["plan_approved"] = True
    meta["approved_at"] = _now()
    save_meta(run_dir, meta)
    print(f"✅ Plan approved for '{run_dir.name}'. Next: holdout add, then dispatch.")
    return 0


def cmd_holdout(args):
    run_dir = require_run(args.name)
    if not run_dir:
        return 1
    meta = load_meta(run_dir)
    registered = meta.setdefault("holdouts", {})

    if args.action == "list":
        for name in sorted(registered):
            print(f"   • {name}: sha={registered[name]['sha256'][:12]}")
        if not registered:
            print(f"   No holdouts registered for '{run_dir.name}'.")
        return 0

    if not args.path:
        print("❌ kem-dev-loop holdout add <run> <file>")
        return 1
    path = Path(args.path)
    if not path.exists():
        print(f"❌ {path} does not exist. Write the gate first; it is not an afterthought.")
        return 1
    resolved = path.resolve()
    holdout_dir = (run_dir / "holdouts").resolve()
    if holdout_dir not in resolved.parents:
        print(f"❌ Holdouts stay locked in {holdout_dir}, where a builder cannot read them.")
        return 1

    if resolved.suffix == ".py":
        text = resolved.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*def test_", text, re.MULTILINE) and "__main__" not in text:
            print("❌ A holdout is a script that exits 0 or fails. This is a pytest-style")
            print("   file with no __main__ block, so running it would pass vacuously.")
            print("   Add `if __name__ == '__main__':` and real asserts (one of them the")
            print("   negative control), or run pytest yourself via --test.")
            return 1

    registered[resolved.name] = {
        "sha256": sha256(resolved),
        "added_at": _now(),
        "added_at_epoch": time.time(),
    }
    save_meta(run_dir, meta)
    print(f"✅ Holdout registered: {resolved.name}")
    return 0


def cmd_dispatch(args):
    run_dir = require_run(args.name)
    if not run_dir:
        return 1
    meta = load_meta(run_dir)
    if not meta.get("plan_approved") and not args.skip_plan_review:
        print("❌ Refusing to dispatch: the plan was never approved.")
        print(f"   Read .kem-loop/{run_dir.name}/plan.md, then: kem-dev-loop approve {run_dir.name}")
        print("   On a throwaway MVP the plan gets skipped unread; say so: --skip-plan-review")
        return 1
    if args.skip_plan_review:
        meta["plan_review"] = "skipped"

    registered = meta.get("holdouts") or {}
    if not registered:
        print("❌ Refusing to dispatch: this run has no hidden holdouts.")
        print("   A builder with no gate to fail can only be graded on its own opinion.")
        print(f"   kem-dev-loop holdout add {run_dir.name} .kem-loop/{run_dir.name}/holdouts/<file>")
        return 1
    for name, gate in registered.items():
        path = run_dir / "holdouts" / name
        if not path.exists() or sha256(path) != gate["sha256"]:
            print(f"❌ Refusing to dispatch: holdout '{name}' changed after it was registered.")
            return 1

    task_src = Path(args.task)
    if not task_src.is_file():
        print("❌ --task takes ONE file holding the bounded brief.")
        return 1

    dispatch_dir = run_dir / "dispatch"
    dispatch_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")[:-3]
    task_copy = dispatch_dir / f"task_{stamp}.md"
    task_copy.write_text(task_src.read_text(encoding="utf-8"), encoding="utf-8")
    log_path = dispatch_dir / f"builder_{stamp}.log"
    cmd = args.cmd.replace("{task}", shlex.quote(str(task_copy.resolve())))

    started_epoch = time.time()
    started_at = _now()
    with log_path.open("w", encoding="utf-8") as fh:
        fh.write(f"cmd: {cmd}\nstarted: {started_at}\n\n")
        fh.flush()
        try:
            exit_code = subprocess.run(
                cmd, shell=True, stdout=fh, stderr=subprocess.STDOUT,
                timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            fh.write(f"\n[kem-dev-loop] killed after {args.timeout}s timeout\n")

    meta["dispatch"] = {
        "started_at": started_at,
        "started_at_epoch": started_epoch,
        "exit_code": exit_code,
        "log": str(log_path),
        "task_file": str(task_copy),
    }
    save_meta(run_dir, meta)

    duration = round(time.time() - started_epoch, 1)
    if exit_code == 0:
        print(f"DISPATCH ok exit=0 {duration}s log={log_path}")
        return 0
    print(f"DISPATCH failed exit={exit_code} {duration}s log={log_path}")
    print(f"\n--- tail -n 25 {log_path} ---")
    print(tail(log_path))
    return 1


def holdout_command(path):
    if path.suffix == ".py":
        return [sys.executable, str(path)]
    if path.suffix in (".sh", ".bash"):
        return ["bash", str(path)]
    if path.suffix in (".js", ".mjs"):
        return ["node", str(path)]
    return None


def cmd_validate(args):
    name = args.name
    run_dir = STATE_DIR / name
    if not run_dir.exists():
        print(f"❌ Error: Run directory {run_dir} not found. Run: kem-dev-loop init {name}")
        return 1

    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    attempts = int(meta.get("validation_attempts", 0))
    if attempts >= MAX_VALIDATION_ATTEMPTS and not args.force:
        print(f"❌ Retry cap reached: {attempts} failed validations on '{name}'.")
        print("   Adversarial death loops are dangerous. Fix the cause, or pass --force to spend another attempt.")
        return 1

    registered = meta.get("holdouts") or {}
    if not registered:
        print("❌ Refusing to validate: no holdouts registered.")
        print("   kem-dev-loop holdout add <run> <file>   # before any builder runs")
        return 1

    dispatch = meta.get("dispatch")
    if dispatch is None and not args.local:
        print("❌ Refusing to validate: no builder dispatch recorded for this run.")
        print(f"   kem-dev-loop dispatch {name} --task <file>   (or --local if you wrote it)")
        return 1

    for hname, gate in registered.items():
        path = run_dir / "holdouts" / hname
        if not path.exists() or sha256(path) != gate["sha256"]:
            print(f"❌ Refusing to validate: holdout '{hname}' changed after it was registered.")
            print("   A gate edited to fit the code is not a gate.")
            return 1
        if dispatch and (float(gate.get("added_at_epoch") or 0) > dispatch["started_at_epoch"] + 0.5
                         or path.stat().st_mtime > dispatch["started_at_epoch"] + 0.5):
            print(f"❌ Refusing to validate: holdout '{hname}' postdates the dispatch.")
            print("   That is the sycophancy breach this loop exists to prevent.")
            print("   Discard the builder's work and restart from Phase 2, holdouts first.")
            return 1

    if dispatch and dispatch.get("exit_code") != 0:
        print(f"❌ Refusing to validate: the builder exited {dispatch['exit_code']}, so nothing landed.")
        print(f"   tail -n 25 {dispatch['log']}:")
        print(tail(dispatch["log"]))
        return 1

    holdouts = [run_dir / "holdouts" / hname for hname in registered]
    if not args.test_cmd and not holdouts:
        print("❌ No gate configured. A validation with nothing that can fail is not a validation.")
        print("   Pass --test \"<cmd>\" or add a scenario to holdouts/ first.")
        return 1

    print(f"\n👁️ [Phase 4: Grounded Validation] Exercising {name}...")
    if attempts:
        print(f"   Attempt {attempts + 1} of {MAX_VALIDATION_ATTEMPTS}")
    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    stamp = _stamp()
    failures = []
    ran = 0

    if args.test_cmd:
        print(f"   Running functional suite: `{args.test_cmd}`")
        res = run_cmd(args.test_cmd)
        log_file = evidence_dir / f"test_{stamp}.log"
        log_file.write_text(
            f"Command: {args.test_cmd}\nExit Code: {res.returncode}\n\nSTDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}",
            encoding="utf-8",
        )
        ran += 1
        if res.returncode != 0:
            failures.append(("functional suite", log_file, res.returncode))
            print(f"   ❌ Functional suite failed (exit {res.returncode}).")
        else:
            print("   ✅ Functional suite passed.")

    if holdouts:
        print(f"   🛡️ Running {len(holdouts)} hidden holdout scenario(s)...")
    for h in holdouts:
        cmd = holdout_command(h)
        if cmd is None:
            print(f"     • {h.name}: unsupported type '{h.suffix}', refusing to count it as a gate")
            failures.append((h.name, None, None))
            continue
        env = dict(os.environ, KEM_RUN_DIR=str(run_dir.resolve()))
        res = subprocess.run(cmd, capture_output=True, text=True, env=env)
        log_file = evidence_dir / f"holdout_{h.stem}_{stamp}.log"
        log_file.write_text(
            f"Holdout: {h.name}\nCommand: {' '.join(cmd)}\nExit Code: {res.returncode}\n\nSTDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}",
            encoding="utf-8",
        )
        ran += 1
        if res.returncode != 0:
            failures.append((h.name, log_file, res.returncode))
            print(f"     • {h.name}: ❌ FAILED (exit {res.returncode})")
        else:
            print(f"     • {h.name}: ✅ passed")

    summary = {
        "run": name,
        "finished_at": _now(),
        "attempt": attempts + 1,
        "gates_run": ran,
        "holdouts": [h.name for h in holdouts],
        "failures": [{"gate": g, "log": str(l.resolve()) if l else None, "exit_code": c} for g, l, c in failures],
        "passed": not failures,
    }
    (evidence_dir / f"validation_{stamp}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if failures:
        meta["validation_passed"] = False
        meta["validation_attempts"] = attempts + 1
        meta["phase"] = "PHASE_3_BUILD"
        meta["last_validation_failed_at"] = _now()
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"\n❌ Validation FAILED ({len(failures)} gate(s)).")
        print(f"   Evidence serialized to: {evidence_dir}")
        print("   🚨 SENT BACK TO BUILDERS with observable failure logs, not with opinions.")
        if attempts + 1 >= MAX_VALIDATION_ATTEMPTS:
            print("   That was the last automatic retry. Next failure needs a human decision.")
        return 1

    meta["validation_passed"] = True
    meta["validation_attempts"] = attempts
    meta["phase"] = "PHASE_5_CODE_REVIEW"
    meta["last_validation_passed_at"] = _now()
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"\n🎉 Validation passed ({ran} gate(s) run). Proceeding to decoupled Phase 5: Code Review.")
    return 0


def active_run(explicit=None):
    if explicit:
        return STATE_DIR / explicit
    if not STATE_DIR.is_dir():
        return None
    runs = [p for p in sorted(STATE_DIR.iterdir()) if p.is_dir() and (p / "meta.json").exists()]
    return runs[0] if len(runs) == 1 else None


def cmd_review(args):
    suite = args.suite or "ponytail"
    paths = list(args.paths or [])
    run_name = args.run
    if run_name is None and paths and (STATE_DIR / paths[0] / "meta.json").exists():
        run_name = paths.pop(0)
    if len(paths) > 1:
        print(f"❌ Review takes one target, got: {' '.join(paths)}")
        return 1
    target = paths[0] if paths else "."

    print(f"\n🤖 [Phase 5: Decoupled Code Review]")

    run_dir = active_run(run_name)
    if run_dir is None:
        print("   ⚠️  No single .kem-loop run resolved, so the validation gate cannot be checked.")
        print("       Pass --run <name> to enforce validation-before-review.")
    else:
        meta_path = run_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        if not meta.get("validation_passed"):
            print(f"   ❌ Refusing to review '{run_dir.name}': validation has not passed.")
            print(f"      Run: kem-dev-loop validate {run_dir.name} --test \"<cmd>\"")
            print("      Review checks whether the code is clean, not whether it works.")
            return 1
        print(f"   ✅ Validation gate cleared for '{run_dir.name}'.")

    print(f"   Running review suite: `{suite}` against `{target}`")

    rh_check = run_cmd("which review-hub")
    if rh_check.returncode == 0:
        res = run_cmd(f"review-hub review {suite} {target}")
        print(res.stdout)
        if res.returncode != 0:
            print(res.stderr)
            return res.returncode
    else:
        print("   ℹ️  review-hub not found on PATH. Falling back to git diff check.")
        res = run_cmd(f"git diff --stat {target}")
        print(res.stdout)

    print("\n👤 [Phase 6: Final Human Intent Check]")
    print("   Validate: Does this change honor the original 'Why and Why Not'?")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Kem Glitch's 6-Phase AI Development Lifecycle")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # route
    p_route = subparsers.add_parser("route", help="Classify task complexity (Fast Route vs Full Route)")
    p_route.add_argument("prompt", nargs="+", help="Task description")
    p_route.add_argument("--json", action="store_true", help="Emit one JSON object")

    # init
    p_init = subparsers.add_parser("init", help="Initialize a feature run with hidden holdouts and plan")
    p_init.add_argument("name", help="Feature or run name")

    p_ok = subparsers.add_parser("approve", help="Record human approval of plan.md (Phase 2)")
    p_ok.add_argument("name", help="Feature run name")

    p_ho = subparsers.add_parser("holdout", help="Register hidden holdout gates (Phase 2)")
    p_ho.add_argument("action", choices=["add", "list"])
    p_ho.add_argument("name", help="Feature run name")
    p_ho.add_argument("path", nargs="?", help="Holdout file inside .kem-loop/<run>/holdouts/")

    p_dis = subparsers.add_parser("dispatch", help="Dispatch the Phase 3 builder, buffered to disk")
    p_dis.add_argument("name", help="Feature run name")
    p_dis.add_argument("--task", required=True, help="ONE file holding the bounded brief")
    p_dis.add_argument("--cmd", default=DEFAULT_BUILDER_CMD,
                       help=f"Builder command; {{task}} is the task file (default: {DEFAULT_BUILDER_CMD})")
    p_dis.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p_dis.add_argument("--skip-plan-review", action="store_true",
                       help="MVP-scale slice: the plan was deliberately not read")

    # validate
    p_val = subparsers.add_parser("validate", help="Run grounded persona validation & holdout suite")
    p_val.add_argument("name", help="Feature run name")
    p_val.add_argument("--test", dest="test_cmd", default=None, help="Functional test command (e.g. pytest, npm test)")
    p_val.add_argument("--force", action="store_true", help="Spend an attempt past the retry cap")
    p_val.add_argument("--local", action="store_true", help="You wrote the code; no dispatch required")

    # review
    p_rev = subparsers.add_parser("review", help="Run decoupled code review (Phase 5)")
    p_rev.add_argument("--suite", default="ponytail", help="Review suite (ponytail, unslop, typescript, no-comments)")
    p_rev.add_argument("--run", default=None, help="Feature run name to gate on (defaults to the only run in .kem-loop)")
    p_rev.add_argument("paths", nargs="*", help="[run] <target>")

    args, extra = parser.parse_known_args()
    if extra:
        if args.command != "review":
            parser.error("unrecognized arguments: " + " ".join(extra))
        args.paths = list(args.paths or []) + extra

    if args.command == "route":
        return cmd_route(args)
    elif args.command == "init":
        return cmd_init(args)
    elif args.command == "approve":
        return cmd_approve(args)
    elif args.command == "holdout":
        return cmd_holdout(args)
    elif args.command == "dispatch":
        return cmd_dispatch(args)
    elif args.command == "validate":
        return cmd_validate(args)
    elif args.command == "review":
        return cmd_review(args)


if __name__ == "__main__":
    sys.exit(main())
