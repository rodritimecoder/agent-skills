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
import shutil
import hashlib
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

STATE_DIR = Path(".kem-loop")

# The builder runs non-interactively from one task file, with all of its output
# buffered to disk. {task} is replaced with the absolute path of that file.
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


def _stamp_us():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")[:-3]


def run_cmd(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True)


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


def receipt(line, as_json, payload):
    print(json.dumps(payload) if as_json else line)


def tail(path, lines=25):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(text[-lines:])


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
        print("   1. Write and human-approve plan.md: `kem-dev-loop approve <run>`")
        print("   2. Register hidden holdouts BEFORE any builder: `kem-dev-loop holdout add <run> <file> --kind pass|control`")
        print("   3. Dispatch one bounded builder from one task file: `kem-dev-loop dispatch <run> --task <file>`")
        print("   4. Validate journey & holdouts before review: `kem-dev-loop validate <run>`")
    else:
        print("⚡ Protocol for FAST_ROUTE:")
        print("   - Small or greenfield routine change.")
        print("   - Direct execution permitted with standard verification.")
        print("   - Note: this route skips human plan approval. Say so out loud before you build.")


    return 0


def cmd_init(args):
    name = args.name.strip().replace(" ", "_")
    target_dir = STATE_DIR / name
    meta_path = target_dir / "meta.json"
    if meta_path.exists() and not args.force:
        print(f"❌ Run '{name}' already exists with state in {meta_path}.")
        print("   Re-initializing would erase approval, holdouts, dispatch and validation history.")
        print("   Use another name, or --force to reset it deliberately.")
        return 1
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
        "holdouts": {},
        "dispatch": None,
        "validation_passed": False,
        "review_passed": False,
        "waivers": []
    }, indent=2), encoding="utf-8")

    print(f"✅ Initialized Kem Dev Loop feature run: {target_dir}")
    print(f"   • Plan: {plan_path}")
    print(f"   • Hidden Holdouts Directory: {target_dir / 'holdouts'}")
    print(f"   • Evidence Output: {target_dir / 'evidence'}")
    return 0


def _plan_filled(plan_text):
    """A plan that still holds the template's empty labels is not a plan."""
    fields = [
        r"\*\*Why we are building this:\*\*(.{0,200})",
        r"\*\*Explicit non-goals \(What we are NOT building\):\*\*(.{0,200})",
    ]
    for pattern in fields:
        m = re.search(pattern, plan_text)
        if not m or not m.group(1).strip().split("\n")[0].strip():
            return False
    return True


def cmd_approve(args):
    run_dir = require_run(args.name)
    if not run_dir:
        return 1

    plan = run_dir / "plan.md"
    if not plan.exists():
        print(f"❌ Refusing to approve: {plan} does not exist.")
        return 1
    if not _plan_filled(plan.read_text(encoding="utf-8")):
        print(f"❌ Refusing to approve: {plan} still has empty 'Why' / 'Why Not' fields.")
        print("   A plan with no stated intent approves nothing. Fill them in, then re-run.")
        return 1

    meta = load_meta(run_dir)
    meta["plan_approved"] = True
    meta["approved_by"] = args.by
    meta["approved_at"] = _now()
    meta["phase"] = "PHASE_3_BUILD"
    save_meta(run_dir, meta)
    print(f"✅ Plan approved by {args.by}. Next: register the hidden holdouts.")
    print(f"   kem-dev-loop holdout add {run_dir.name} .kem-loop/{run_dir.name}/holdouts/<file> --kind pass")
    print(f"   kem-dev-loop holdout add {run_dir.name} .kem-loop/{run_dir.name}/holdouts/<file> --kind control")
    return 0


def cmd_holdout(args):
    run_dir = require_run(args.name)
    if not run_dir:
        return 1
    meta = load_meta(run_dir)
    registered = meta.setdefault("holdouts", {})
    holdout_dir = (run_dir / "holdouts").resolve()

    if args.action == "list":
        if not registered:
            print(f"   No holdouts registered for '{run_dir.name}'.")
            return 0
        for name in sorted(registered):
            h = registered[name]
            print(f"   • {name}: kind={h.get('kind')} sha={h.get('sha256', '')[:12]}")
        return 0

    if not args.path:
        print("❌ holdout add needs a path: kem-dev-loop holdout add <run> <file> --kind pass|control")
        return 1
    path = Path(args.path)
    if not path.exists():
        print(f"❌ {path} does not exist. Write the holdout first; it is the gate, not an afterthought.")
        return 1
    resolved = path.resolve()
    if holdout_dir not in resolved.parents:
        print(f"❌ Holdouts stay locked in {holdout_dir}.")
        print("   Move it there, then register it. Builders must never be able to see it in-tree.")
        return 1

    registered[resolved.name] = {
        "kind": args.kind,
        "sha256": sha256(resolved),
        "added_at": _now(),
        "added_at_epoch": time.time(),
    }
    meta["phase"] = "PHASE_2_HOLDOUTS_AND_PLAN"
    save_meta(run_dir, meta)
    print(f"✅ Holdout registered: {resolved.name} (kind={args.kind})")
    return 0


def cmd_dispatch(args):
    run_dir = require_run(args.name)
    if not run_dir:
        return 1
    meta = load_meta(run_dir)

    if not meta.get("plan_approved"):
        print("❌ Refusing to dispatch: the plan is not approved.")
        print(f"   Fill in .kem-loop/{run_dir.name}/plan.md, then: kem-dev-loop approve {run_dir.name} --by human")
        return 1

    registered = meta.get("holdouts") or {}
    if not registered:
        print("❌ Refusing to dispatch: this run has no hidden holdouts.")
        print("   A builder with no gate to fail can only be graded on its own opinion.")
        print(f"   kem-dev-loop holdout add {run_dir.name} .kem-loop/{run_dir.name}/holdouts/<file> --kind pass")
        return 1

    kinds = {h.get("kind") for h in registered.values()}
    if "pass" not in kinds:
        print("❌ Refusing to dispatch: no positive ('pass') holdout registered.")
        return 1
    if "control" not in kinds and not args.allow_no_control:
        print("❌ Refusing to dispatch: no negative control holdout registered.")
        print("   A gate that cannot fail is not a gate. Add a control that must exit non-zero,")
        print("   then: kem-dev-loop holdout add <run> <file> --kind control")
        print("   (--allow-no-control records a visible waiver instead.)")
        return 1

    if args.allow_no_control:
        meta.setdefault("waivers", []).append(
            {"what": "no negative control holdout", "at": _now()})

    for name, h in registered.items():
        path = run_dir / "holdouts" / name
        if not path.exists():
            print(f"❌ Refusing to dispatch: registered holdout '{name}' is gone.")
            return 1
        if h.get("sha256") and sha256(path) != h["sha256"]:
            print(f"❌ Refusing to dispatch: holdout '{name}' changed after registration.")
            print("   Re-register it: kem-dev-loop holdout add ... --kind ...")
            return 1

    prior = meta.get("dispatch") or {}
    if prior.get("exit_code") == 0 and not args.redispatch:
        print(f"❌ '{run_dir.name}' already dispatched successfully at {prior.get('started_at')}.")
        print("   Pass --redispatch to spend another builder run, or validate what is already there.")
        return 1

    task_src = Path(args.task)
    if not task_src.exists():
        print(f"❌ Task file {task_src} does not exist. Write one bounded task file, then dispatch.")
        return 1
    if task_src.is_dir():
        print("❌ --task takes ONE file. A directory of briefs is how a slice becomes a crawl.")
        return 1

    dispatch_dir = run_dir / "dispatch"
    dispatch_dir.mkdir(exist_ok=True)
    stamp = _stamp_us()
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
            completed = subprocess.run(
                cmd, shell=True, stdout=fh, stderr=subprocess.STDOUT, timeout=args.timeout)
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            fh.write(f"\n[kem-dev-loop] killed after {args.timeout}s timeout\n")

    duration = round(time.time() - started_epoch, 1)
    meta["dispatch"] = {
        "started_at": started_at,
        "started_at_epoch": started_epoch,
        "duration_s": duration,
        "task_file": str(task_copy),
        "task_sha256": sha256(task_copy),
        "cmd": cmd,
        "log": str(log_path),
        "exit_code": exit_code,
    }
    meta["phase"] = "PHASE_4_VALIDATE" if exit_code == 0 else "PHASE_3_BUILD_FAILED"
    save_meta(run_dir, meta)

    payload = {
        "run": run_dir.name,
        "exit_code": exit_code,
        "duration_s": duration,
        "log": str(log_path),
        "task_file": str(task_copy),
    }
    if exit_code == 0:
        receipt(f"DISPATCH ok exit=0 {duration}s log={log_path}", args.json, payload)
        return 0

    receipt(f"DISPATCH failed exit={exit_code} {duration}s log={log_path}", args.json, payload)
    print(f"\n--- tail -n 25 {log_path} ---")
    print(tail(log_path))
    return 1


def pytest_available():
    probe = subprocess.run([sys.executable, "-c", "import pytest"], capture_output=True)
    return probe.returncode == 0


MISSING_RUNNER = re.compile(
    r"No module named '?(pytest|jest|vitest|mocha|tsx)'?|command not found|: not found",
    re.IGNORECASE,
)


def looks_like_missing_runner(res):
    return res.returncode in (126, 127) or bool(
        MISSING_RUNNER.search((res.stderr or "") + (res.stdout or "")))


def holdout_command(path):
    """A holdout is a script that either passes or fails. pytest is used when it
    exists; without it a plain assert-and-print script runs directly."""
    if path.suffix == ".py":
        if pytest_available():
            return [sys.executable, "-m", "pytest", "-q", str(path)]
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*def test_", text, re.MULTILINE) and "__main__" not in text:
            return None
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

    if not meta.get("plan_approved"):
        print("❌ Refusing to validate: this run's plan was never approved.")
        print(f"   Fill in plan.md, then: kem-dev-loop approve {name} --by human")
        return 1

    registered = meta.get("holdouts") or {}
    dispatch = meta.get("dispatch")
    waivers = meta.setdefault("waivers", [])

    if not registered:
        print("❌ Refusing to validate: no holdouts are registered for this run.")
        print("   The gate is written BEFORE the builder runs: kem-dev-loop holdout add ... --kind pass|control")
        return 1

    for hname, h in registered.items():
        path = run_dir / "holdouts" / hname
        if not path.exists():
            print(f"❌ Refusing to validate: registered holdout '{hname}' is missing.")
            return 1
        if h.get("sha256") and sha256(path) != h["sha256"]:
            print(f"❌ Refusing to validate: holdout '{hname}' changed after it was registered.")
            print("   A gate edited to fit the code is not a gate. Restore it or re-register with intent.")
            return 1

    if "control" not in {h.get("kind") for h in registered.values()}:
        if not args.allow_no_control:
            print("❌ Refusing to validate: no negative control holdout is registered.")
            print("   A gate that cannot fail is not a gate. Add one that must exit non-zero,")
            print("   or pass --allow-no-control to record a visible waiver.")
            return 1
        waivers.append({"what": "no negative control holdout", "at": _now()})

    if dispatch is None:
        if not args.local:
            print("❌ Refusing to validate: no builder dispatch is recorded for this run.")
            print(f"   Phase 3 is a dispatched builder: kem-dev-loop dispatch {name} --task <file>")
            print("   If you wrote the code yourself, say so: --local")
            return 1
    else:
        if dispatch.get("exit_code") != 0:
            print(f"❌ Refusing to validate: the builder exited {dispatch.get('exit_code')}, "
                  "so the slice never landed.")
            log = dispatch.get("log")
            print(f"   Inspect: tail -n 25 {log}")
            if log:
                print(f"\n--- tail -n 25 {log} ---")
                print(tail(log))
            return 1
        horizon = float(dispatch.get("started_at_epoch") or 0) + 0.5
        late = []
        for hname, h in registered.items():
            if float(h.get("added_at_epoch") or 0) > horizon:
                late.append(f"{hname} (registered after dispatch)")
                continue
            path = run_dir / "holdouts" / hname
            if path.exists() and path.stat().st_mtime > horizon:
                late.append(f"{hname} (modified after dispatch)")
        if late:
            print(f"❌ Refusing to validate: holdout(s) postdate the dispatch: {'; '.join(sorted(late))}")
            print("   That is the exact sycophancy breach this loop exists to prevent.")
            print("   Discard the builder's work and restart from Phase 2, holdouts first.")
            return 1

    holdouts = [
        p.resolve() for p in sorted((run_dir / "holdouts").iterdir())
        if p.is_file() and not p.name.startswith(".")
    ]
    unregistered = sorted(p.name for p in holdouts if p.name not in registered)
    if unregistered:
        print(f"❌ Refusing to validate: unregistered file(s) in holdouts/: {', '.join(unregistered)}")
        print("   Register each one: kem-dev-loop holdout add <run> <file> --kind pass|control")
        return 1

    if not args.test_cmd and not holdouts:
        print("❌ No gate configured. A validation with nothing that can fail is not a validation.")
        print("   Pass --test \"<cmd>\" or add a scenario to holdouts/ first.")
        return 1

    runner_note = "pytest" if pytest_available() else "direct python (pytest not installed)"

    print(f"\n👁️ [Phase 4: Grounded Validation] Exercising {name}...")
    if attempts:
        print(f"   Attempt {attempts + 1} of {MAX_VALIDATION_ATTEMPTS}")
    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    stamp = _stamp()
    failures = []
    env_faults = []
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
        if res.returncode != 0 and looks_like_missing_runner(res):
            env_faults.append((args.test_cmd, log_file))
            print(f"   ⚠️  Functional suite could not run: missing runner, not a failed build.")
            print(f"      Not counted as an attempt. Log: {log_file}")
        elif res.returncode != 0:
            failures.append(("functional suite", log_file, res.returncode))
            print(f"   ❌ Functional suite failed (exit {res.returncode}).")
        else:
            print("   ✅ Functional suite passed.")

    if holdouts:
        print(f"   🛡️ Running {len(holdouts)} hidden holdout scenario(s) [{runner_note}]...")
    for h in holdouts:
        cmd = holdout_command(h)
        if cmd is None:
            print(f"     • {h.name}: cannot run without pytest, and it is not a plain script.")
            print("       Install pytest, add an `if __name__ == '__main__'` block, or use .sh.")
            print("       Not counted as an attempt: this is an environment fault.")
            env_faults.append((h.name, None))
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
        "environment_faults": [g for g, _ in env_faults],
        "passed": not failures,
    }
    (evidence_dir / f"validation_{stamp}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if env_faults and not failures:
        meta["validation_passed"] = False
        meta["phase"] = "PHASE_4_VALIDATE"
        meta["last_environment_fault_at"] = _now()
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"\n⚠️  Validation could not run ({len(env_faults)} gate(s) lacked a runner).")
        print(f"   Evidence: {evidence_dir}")
        print("   Not counted as an attempt. Fix the environment, then re-run validate.")
        return 1

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
    paths = list(getattr(args, "paths", None) or [])
    run_name = args.run
    if run_name is None and paths and (STATE_DIR / paths[0] / "meta.json").exists():
        run_name = paths.pop(0)
    if len(paths) > 1:
        print(f"❌ Review takes one target, got: {' '.join(paths)}")
        print("   Usage: kem-dev-loop review [run] --suite ponytail <target>")
        return 1
    target = paths[0] if paths else "."

    print(f"\n🤖 [Phase 5: Decoupled Code Review]")

    run_dir = active_run(run_name)
    if run_dir is None:
        print("   ⚠️  No single .kem-loop run resolved, so the validation gate cannot be checked.")
        print("       Pass the run name (review <run> ...) to enforce validation-before-review.")
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
    p_init.add_argument("--force", action="store_true", help="Reset an existing run's state")

    # approve — the human gate, recorded so it cannot be skipped silently
    p_ok = subparsers.add_parser("approve", help="Record human approval of plan.md (Phase 2)")
    p_ok.add_argument("name", help="Feature run name")
    p_ok.add_argument("--by", default="human", help="Who approved it (default: human)")

    # holdout — register the gate BEFORE the builder exists
    p_ho = subparsers.add_parser("holdout", help="Register hidden holdout gates (Phase 2)")
    p_ho.add_argument("action", choices=["add", "list"], help="add or list")
    p_ho.add_argument("name", help="Feature run name")
    p_ho.add_argument("path", nargs="?", help="Holdout file inside .kem-loop/<run>/holdouts/")
    p_ho.add_argument("--kind", choices=["pass", "control"], default="pass",
                      help="pass = must succeed; control = asserts bad input is rejected (still exits 0 when it works)")

    # dispatch — one task file, one bounded builder, everything buffered to disk
    p_dis = subparsers.add_parser("dispatch", help="Dispatch the Phase 3 builder, output buffered to disk")
    p_dis.add_argument("name", help="Feature run name")
    p_dis.add_argument("--task", required=True, help="ONE file holding the bounded task brief")
    p_dis.add_argument("--cmd", default=DEFAULT_BUILDER_CMD,
                       help=f"Builder command; {{task}} is replaced with the task file path (default: {DEFAULT_BUILDER_CMD})")
    p_dis.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Seconds before the builder is killed")
    p_dis.add_argument("--redispatch", action="store_true", help="Spend another builder run after a clean one")
    p_dis.add_argument("--allow-no-control", action="store_true", help="Record a visible waiver instead of refusing")
    p_dis.add_argument("--json", action="store_true", help="Emit one JSON receipt")

    # validate
    p_val = subparsers.add_parser("validate", help="Run grounded persona validation & holdout suite")
    p_val.add_argument("name", help="Feature run name")
    p_val.add_argument("--test", dest="test_cmd", default=None, help="Functional test command (e.g. pytest, npm test)")
    p_val.add_argument("--force", action="store_true", help="Spend an attempt past the retry cap")
    p_val.add_argument("--local", action="store_true", help="Validate work you wrote yourself; no dispatch required")
    p_val.add_argument("--allow-no-control", action="store_true", help="Record a visible waiver for a missing control")

    # review
    p_rev = subparsers.add_parser("review", help="Run decoupled code review (Phase 5)")
    p_rev.add_argument("--suite", default="ponytail", help="Review suite (ponytail, unslop, typescript, no-comments)")
    p_rev.add_argument("--run", default=None, help="Feature run name to gate on (defaults to the only run in .kem-loop)")
    p_rev.add_argument("paths", nargs="*", help="[run] <target> — a run name is detected when it names a .kem-loop run")

    args, extra = parser.parse_known_args()
    if extra:
        if args.command != "review":
            parser.error("unrecognized arguments: " + " ".join(extra))
        # argparse cannot interleave an option between a greedy positional and
        # the target (`review run --suite x src/`), so collect the tail here.
        args.paths = list(getattr(args, "paths", None) or []) + extra

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
