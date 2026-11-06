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

import sys
import re
import json
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

STATE_DIR = Path(".kem-loop")

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
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("Usage: kem-dev-loop route <task description>")
        return 1

    print(f"\n🔍 [Phase 1: Classify & Route]")
    print(f'   "{prompt}"\n')

    signals = cross_cutting_signals(prompt)
    if signals:
        route, complexity, source, confidence = "FULL_ROUTE", "BIG", "deterministic", 1.0
        reason = "cross-cutting surface: " + ", ".join(signals[:6])
    else:
        route, complexity, source, confidence, reason = classify_by_model(prompt)

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


def pytest_available():
    probe = subprocess.run([sys.executable, "-c", "import pytest"], capture_output=True)
    return probe.returncode == 0


def holdout_command(path):
    if path.suffix == ".py":
        return [sys.executable, "-m", "pytest", "-q", str(path)]
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

    holdouts = [
        p.resolve() for p in sorted((run_dir / "holdouts").iterdir())
        if p.is_file() and not p.name.startswith(".")
    ]
    if not args.test_cmd and not holdouts:
        print("❌ No gate configured. A validation with nothing that can fail is not a validation.")
        print("   Pass --test \"<cmd>\" or add a scenario to holdouts/ first.")
        return 1

    if any(h.suffix == ".py" for h in holdouts) and not pytest_available():
        print(f"❌ {sys.executable} cannot import pytest, so .py holdouts cannot be executed.")
        print("   Install a runner (`pip install pytest`) or write the holdout as a .sh scenario.")
        print("   Not counted as an attempt: this is an environment fault, not a failed build.")
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
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(run_dir))
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
    target = args.target or "."

    print(f"\n🤖 [Phase 5: Decoupled Code Review]")

    run_dir = active_run(args.run)
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

    # init
    p_init = subparsers.add_parser("init", help="Initialize a feature run with hidden holdouts and plan")
    p_init.add_argument("name", help="Feature or run name")

    # validate
    p_val = subparsers.add_parser("validate", help="Run grounded persona validation & holdout suite")
    p_val.add_argument("name", help="Feature run name")
    p_val.add_argument("--test", dest="test_cmd", default=None, help="Functional test command (e.g. pytest, npm test)")
    p_val.add_argument("--force", action="store_true", help="Spend an attempt past the retry cap")

    # review
    p_rev = subparsers.add_parser("review", help="Run decoupled code review (Phase 5)")
    p_rev.add_argument("--suite", default="ponytail", help="Review suite (ponytail, unslop, typescript, no-comments)")
    p_rev.add_argument("--run", default=None, help="Feature run name to gate on (defaults to the only run in .kem-loop)")
    p_rev.add_argument("target", nargs="?", default=".", help="Target directory or file")

    args = parser.parse_args()

    if args.command == "route":
        return cmd_route(args)
    elif args.command == "init":
        return cmd_init(args)
    elif args.command == "validate":
        return cmd_validate(args)
    elif args.command == "review":
        return cmd_review(args)


if __name__ == "__main__":
    sys.exit(main())
