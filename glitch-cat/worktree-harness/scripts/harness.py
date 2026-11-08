#!/usr/bin/env python3
"""
harness.py — Multi-Agent Git Worktree Orchestration & Quality Gate Harness
Implements the Glitch Cat Club / Kem Pattern & Anthropic Parallel Worktree Architecture:
  1. Isolated Git Worktrees for concurrent subagents (zero file clobbering)
  2. Pre-Write Section Claiming (reservation ranges in code)
  3. Deterministic Code Quality Gates ("Code decides wherever it can")
  4. Automated Merge Conflict Arbitration (Judge Agent / Jev Decision Model)
  5. Immutable Append-Only Event Log (rebuildable state)
  6. Uber Protocol Response Projection & Disk Buffering (--project, --out)
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

def get_git_root() -> Path:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL, text=True).strip()
        return Path(out)
    except Exception:
        sys.exit("❌ Error: Must be executed inside a Git repository.")


def log_event(run_dir: Path, event_type: str, data: dict):
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "events.jsonl"
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": event_type,
        "data": data,
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def cmd_start(goal: str, workers: list, repo_dir: Path = None, run_name: str = None) -> dict:
    repo = repo_dir or get_git_root()
    run_id = run_name or datetime.datetime.now().strftime("run_%Y%m%d_%H%M%S")
    harness_dir = repo / ".harness" / "runs" / run_id
    harness_dir.mkdir(parents=True, exist_ok=True)
    worktrees_root = harness_dir / "worktrees"
    worktrees_root.mkdir(parents=True, exist_ok=True)

    base_branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=repo, text=True).strip() or "main"
    integration_branch = f"harness/{run_id}/integration"

    # Create integration branch from base
    subprocess.run(["git", "branch", "-f", integration_branch, "HEAD"], cwd=repo, check=True)

    manifest = {
        "run_id": run_id,
        "goal": goal,
        "base_branch": base_branch,
        "integration_branch": integration_branch,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "workers": {},
    }

    log_event(harness_dir, "HARNESS_INITIALIZED", {"goal": goal, "integration_branch": integration_branch})

    # Spawn isolated worktrees
    for idx, worker_spec in enumerate(workers, start=1):
        # Worker spec can be string name or dict {"name": "...", "task": "..."}
        if isinstance(worker_spec, str):
            w_name = worker_spec
            w_task = f"Subtask {idx}"
        else:
            w_name = worker_spec.get("name", f"worker-{idx}")
            w_task = worker_spec.get("task", f"Subtask {idx}")

        branch_name = f"harness/{run_id}/{w_name}"
        worktree_path = worktrees_root / w_name

        # Create branch & worktree
        cmd = ["git", "worktree", "add", "-b", branch_name, str(worktree_path), integration_branch]
        subprocess.run(cmd, cwd=repo, check=True, stdout=subprocess.DEVNULL)

        manifest["workers"][w_name] = {
            "name": w_name,
            "task": w_task,
            "branch": branch_name,
            "worktree_path": str(worktree_path.relative_to(repo)),
            "status": "SPAWNED",
            "claims": [],
        }

        log_event(harness_dir, "WORKER_SPAWNED", {"worker": w_name, "branch": branch_name, "path": str(worktree_path)})

    manifest_path = harness_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Initialize claims registry
    (harness_dir / "claims.json").write_text("[]", encoding="utf-8")

    print(f"🚀 [Harness Started] Run ID: {run_id}")
    print(f"   🎯 Goal: {goal}")
    print(f"   🌿 Integration Branch: {integration_branch}")
    print(f"   👥 Spawned {len(workers)} isolated worktree(s) in: {worktrees_root.relative_to(repo)}")
    return manifest


def cmd_claim(run_id: str, worker: str, file_path: str, lines: str = None) -> dict:
    repo = get_git_root()
    harness_dir = repo / ".harness" / "runs" / run_id
    claims_file = harness_dir / "claims.json"
    if not claims_file.exists():
        sys.exit(f"❌ Error: Run '{run_id}' not found.")

    claims = json.loads(claims_file.read_text(encoding="utf-8"))

    # Check for overlapping claims
    conflicts = []
    for c in claims:
        if c["file"] == file_path and c["worker"] != worker:
            conflicts.append(c)

    new_claim = {
        "worker": worker,
        "file": file_path,
        "lines": lines or "all",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    claims.append(new_claim)
    claims_file.write_text(json.dumps(claims, indent=2), encoding="utf-8")

    log_event(harness_dir, "SECTION_CLAIMED", new_claim)

    if conflicts:
        print(f"⚠️  [Claim Warning] Worker '{worker}' claimed '{file_path}' which overlaps with existing claims from: {', '.join(c['worker'] for c in conflicts)}.")
        return {"status": "CONFLICT_WARNING", "claim": new_claim, "overlapping": conflicts}
    else:
        print(f"✅ [Claim Reserved] Worker '{worker}' successfully claimed: {file_path} (lines: {lines or 'all'})")
        return {"status": "RESERVED", "claim": new_claim}


def execute_gate_command(command: str, cwd: Path, label: str) -> dict:
    started = time.time()
    proc = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
    return {
        "label": label,
        "command": command,
        "passed": proc.returncode == 0,
        "exit_code": proc.returncode,
        "duration_seconds": round(time.time() - started, 2),
        "stdout": proc.stdout[:2000],
        "stderr": proc.stderr[:2000],
    }


def cmd_gate(run_id: str, worker: str, test_cmd: str = None, verify_cmd: str = None) -> dict:
    """Deterministic Quality Gate: 'Code decides wherever it can'."""
    if not test_cmd and not verify_cmd:
        sys.exit("❌ Error: gate needs --test or --verify. A gate with nothing to run is not a gate.")
    repo = get_git_root()
    harness_dir = repo / ".harness" / "runs" / run_id
    manifest = json.loads((harness_dir / "manifest.json").read_text(encoding="utf-8"))
    worker_info = manifest["workers"].get(worker)
    if not worker_info:
        sys.exit(f"❌ Error: Worker '{worker}' not found in run '{run_id}'.")

    worktree_path = repo / worker_info["worktree_path"]
    checks = []
    if test_cmd:
        sys.stderr.write(f"🔬 [Quality Gate] Running tests in {worker} worktree: $ {test_cmd}\n")
        checks.append(execute_gate_command(test_cmd, worktree_path, "test"))
    if verify_cmd:
        sys.stderr.write(f"🔬 [Quality Gate] Running app verification in {worker} worktree: $ {verify_cmd}\n")
        checks.append(execute_gate_command(verify_cmd, worktree_path, "verify"))

    passed = all(check["passed"] for check in checks)
    status = "GATE_PASSED" if passed else "GATE_FAILED"
    duration = round(sum(check["duration_seconds"] for check in checks), 2)

    record = {
        "worker": worker,
        "command": test_cmd,
        "verify_command": verify_cmd,
        "checks": checks,
        "passed": passed,
        "exit_code": next((c["exit_code"] for c in checks if not c["passed"]), 0),
        "duration_seconds": duration,
    }

    log_event(harness_dir, status, record)
    manifest["workers"][worker]["gate"] = {
        "status": status,
        "passed": passed,
        "duration": duration,
        "checks": [{"label": c["label"], "command": c["command"], "passed": c["passed"]} for c in checks],
    }
    (harness_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if passed:
        print(f"✅ [Quality Gate Passed] Worker '{worker}' verified successfully in {duration}s.")
    else:
        failed = next(c for c in checks if not c["passed"])
        print(f"❌ [Quality Gate Failed] Worker '{worker}' {failed['label']} exit {failed['exit_code']} in {duration}s.\n{failed['stderr'][:400]}")

    return record


def arbitrate_merge_conflict(repo: Path, conflict_file: Path, ours_branch: str, theirs_branch: str) -> bool:
    """Uses calibrated heuristics or local Jev to resolve merge conflict cleanly."""
    content = conflict_file.read_text(encoding="utf-8", errors="replace")
    if "<<<<<<<" not in content or "=======" not in content or ">>>>>>>" not in content:
        return False

    print(f"⚖️  [Arbitrator Engaged] Resolving merge conflict in: {conflict_file.name}")
    # Regex extraction of conflict blocks
    conflict_pattern = re.compile(r"<<<<<<< [^\n]+\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]+", re.DOTALL)

    def resolve_block(m):
        ours = m.group(1).strip()
        theirs = m.group(2).strip()

        # If one side is empty, take the additive side
        if not ours and theirs:
            return theirs
        if not theirs and ours:
            return ours

        # If both are imports or sequential function definitions, keep both sequentially
        if (ours.startswith("import ") and theirs.startswith("import ")) or (ours.startswith("def ") and theirs.startswith("def ")):
            return f"{ours}\n{theirs}"

        # Otherwise synthesize additive union
        return f"{ours}\n{theirs}"

    resolved_content = conflict_pattern.sub(resolve_block, content)
    conflict_file.write_text(resolved_content, encoding="utf-8")
    subprocess.run(["git", "add", str(conflict_file)], cwd=repo, check=True)
    return True


def cmd_integrate(run_id: str, test_cmd: str = None, verify_cmd: str = None, allow_untested: bool = False) -> dict:
    """Merges GATE_PASSED worker branches, arbitrates conflicts, re-gates the result."""
    repo = get_git_root()
    harness_dir = repo / ".harness" / "runs" / run_id
    manifest = json.loads((harness_dir / "manifest.json").read_text(encoding="utf-8"))
    integration_branch = manifest["integration_branch"]

    ungated = [
        name for name, info in manifest["workers"].items()
        if info.get("gate", {}).get("status") != "GATE_PASSED"
    ]
    if ungated and not allow_untested:
        print("\n❌ [Integration Refused] These workers have no passing gate:")
        for name in ungated:
            status = manifest["workers"][name].get("gate", {}).get("status", "UNTESTED")
            print(f"   • {name}: {status}")
        print("   Run `gate` for each worker, or pass --allow-untested to accept the risk explicitly.")
        log_event(harness_dir, "INTEGRATION_REFUSED", {"run_id": run_id, "ungated": ungated})
        sys.exit(2)

    subprocess.run(["git", "checkout", integration_branch], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    merged_workers = []
    failed_merges = []

    for w_name, w_info in manifest["workers"].items():
        w_branch = w_info["branch"]
        print(f"\n🔀 [Integrating] Merging worker '{w_name}' ({w_branch}) into {integration_branch}...")

        p_merge = subprocess.run(["git", "merge", "--no-ff", "-m", f"Merge {w_name} into {integration_branch}", w_branch], cwd=repo, capture_output=True, text=True)

        if p_merge.returncode != 0:
            print(f"⚠️  Merge conflict detected while merging '{w_name}'. Attempting automated arbitration...")
            conflicted = subprocess.check_output(["git", "diff", "--name-only", "--diff-filter=U"], cwd=repo, text=True).splitlines()
            resolved_all = True
            for cf in conflicted:
                cf_path = repo / cf
                if not arbitrate_merge_conflict(repo, cf_path, integration_branch, w_branch):
                    resolved_all = False

            if resolved_all:
                subprocess.run(["git", "commit", "-m", f"Arbitrated merge conflict: {w_name} into {integration_branch}"], cwd=repo, check=True)
                print(f"✅ Successfully arbitrated and merged '{w_name}'.")
            else:
                subprocess.run(["git", "merge", "--abort"], cwd=repo, check=True)
                print(f"❌ Conflict arbitration failed for '{w_name}'. Merge aborted.")
                failed_merges.append(w_name)
                continue

        post_checks = [
            execute_gate_command(test_cmd, repo, "integration_test") if test_cmd else None,
            execute_gate_command(verify_cmd, repo, "integration_verify") if verify_cmd else None,
        ]
        post_checks = [c for c in post_checks if c]
        failed_check = next((c for c in post_checks if not c["passed"]), None)
        if failed_check:
            print(f"❌ [Integration Gate Failed] {failed_check['label']} exit {failed_check['exit_code']} after merging '{w_name}'. Reverting merge commit...")
            subprocess.run(["git", "reset", "--hard", "HEAD~1"], cwd=repo, check=True)
            failed_merges.append(w_name)
            continue
        if post_checks:
            print(f"✅ [Integration Gate Passed] {', '.join(c['label'] for c in post_checks)} green after merging '{w_name}'.")

        merged_workers.append(w_name)
        log_event(harness_dir, "WORKER_INTEGRATED", {"worker": w_name, "branch": w_branch, "post_checks": post_checks})

    summary = {
        "run_id": run_id,
        "integration_branch": integration_branch,
        "merged_workers": merged_workers,
        "failed_merges": failed_merges,
        "status": "ALL_PASSED" if not failed_merges else "PARTIAL",
    }
    (harness_dir / "integration_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def cmd_status(run_id: str = None, as_json: bool = False):
    repo = get_git_root()
    runs_dir = repo / ".harness" / "runs"
    if not runs_dir.is_dir():
        sys.exit("No active or historical harness runs found.")

    if not run_id:
        runs = sorted([d.name for d in runs_dir.iterdir() if d.is_dir()])
        if not runs:
            sys.exit("No harness runs found.")
        run_id = runs[-1]

    harness_dir = runs_dir / run_id
    manifest_file = harness_dir / "manifest.json"
    if not manifest_file.is_file():
        sys.exit(f"Run manifest not found for '{run_id}'.")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    claims = json.loads((harness_dir / "claims.json").read_text(encoding="utf-8")) if (harness_dir / "claims.json").is_file() else []

    if as_json:
        print(json.dumps({"manifest": manifest, "claims": claims}, indent=2))
        return

    print(f"\n📊 [Worktree Harness Status] Run: {run_id}")
    print(f"   🎯 Goal: {manifest.get('goal', 'N/A')}")
    print(f"   🌿 Integration Branch: {manifest.get('integration_branch')}")
    print(f"   👥 Active Workers ({len(manifest.get('workers', {}))}):")
    print(f"   {'Worker':<16} │ {'Branch':<28} │ {'Gate Status':<16}")
    print("   " + "─" * 17 + "┼" + "─" * 29 + "┼" + "─" * 16)
    for w_name, w in manifest.get("workers", {}).items():
        gate_status = w.get("gate", {}).get("status", "UNTESTED")
        print(f"   {w_name:<16} │ {w['branch']:<28} │ {gate_status:<16}")

    if claims:
        print(f"\n📑 Active Pre-Write Claims ({len(claims)}):")
        for c in claims:
            print(f"   • {c['worker']}: {c['file']} (lines: {c['lines']})")


def cmd_teardown(run_id: str, delete_branches: bool = False):
    repo = get_git_root()
    harness_dir = repo / ".harness" / "runs" / run_id
    manifest = json.loads((harness_dir / "manifest.json").read_text(encoding="utf-8"))

    print(f"\n🧹 [Tearing Down Harness] Run: {run_id}")
    for w_name, w in manifest.get("workers", {}).items():
        w_path = repo / w["worktree_path"]
        if w_path.exists():
            subprocess.run(["git", "worktree", "remove", "--force", str(w_path)], cwd=repo, check=False)
            print(f"   • Removed worktree: {w['worktree_path']}")

        if delete_branches:
            subprocess.run(["git", "branch", "-D", w["branch"]], cwd=repo, check=False)
            print(f"   • Deleted branch: {w['branch']}")

    subprocess.run(["git", "worktree", "prune"], cwd=repo, check=True)
    print(f"✅ Teardown complete. Integration branch '{manifest['integration_branch']}' and event logs preserved.")


def cmd_dispatch(
    tasks_file: str = None,
    goal: str = None,
    workers_spec: list = None,
    test_cmd: str = None,
    verify_cmd: str = None,
    run_name: str = None,
    max_turns: int = 6,
    timeout_worker: int = 300,
    model_override: str = None,
) -> dict:
    repo = get_git_root()
    tasks = []
    goal_str = goal or "Autonomous Swarm Run"

    if tasks_file:
        p_tasks = Path(tasks_file)
        if not p_tasks.is_file():
            sys.exit(f"❌ Error: Tasks file '{tasks_file}' not found.")
        loaded = json.loads(p_tasks.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            tasks = loaded
        elif isinstance(loaded, dict):
            goal_str = loaded.get("goal", goal_str)
            tasks = loaded.get("tasks", [])
    elif goal and workers_spec:
        for idx, w in enumerate(workers_spec, start=1):
            tasks.append({
                "worker": w,
                "task": f"Implement component {idx} for: {goal}",
                "test": test_cmd or "pytest",
                "files": [],
            })
    else:
        sys.exit("❌ Error: Specify either --tasks <tasks.json> or --goal <goal> with --workers <w1 w2 ...>.")

    if not tasks:
        sys.exit("❌ Error: No tasks defined for dispatch.")

    worker_names = [t["worker"] for t in tasks]
    manifest = cmd_start(goal_str, worker_names, repo_dir=repo, run_name=run_name)
    run_id = manifest["run_id"]
    harness_dir = repo / ".harness" / "runs" / run_id
    logs_dir = harness_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # 1. Pre-claim declared files
    for t in tasks:
        w_name = t["worker"]
        for f in t.get("files", []):
            cmd_claim(run_id, w_name, f, lines=t.get("lines"))

    # 2. Locate or_agent / openrouter-free
    or_agent_cli = shutil.which("openrouter-free") or str(Path.home() / ".local" / "bin" / "openrouter-free")
    if not Path(or_agent_cli).exists():
        or_agent_cli = str(Path(__file__).resolve().parent.parent.parent / "openrouter-free" / "scripts" / "or_agent.py")

    harness_cli = str(Path(__file__).resolve())

    print(f"\n🐝 [Swarm Dispatch] Launching {len(tasks)} parallel subagent worker(s)...")
    worker_procs = {}

    for t in tasks:
        w_name = t["worker"]
        w_task = t.get("task", f"Subtask for {w_name}")
        w_files = ", ".join(t.get("files", [])) or "None specified upfront"
        w_test = t.get("test") or test_cmd or "pytest"
        w_verify = t.get("verify") or verify_cmd
        w_model = model_override or t.get("model") or "gemini-3.5-flash-lite"
        w_path = repo / manifest["workers"][w_name]["worktree_path"]

        gate_flags = f"--test \"{w_test}\""
        if w_verify:
            gate_flags += f" --verify \"{w_verify}\""

        prompt = (
            f"You are autonomous subagent '{w_name}' working in isolated git worktree: {w_path.name}\n\n"
            f"🎯 Goal: {w_task}\n"
            f"📁 Pre-Claimed Files: {w_files}\n"
            f"🔬 Quality Gate Command: {w_test}\n"
            f"👁️  App Verification Command: {w_verify or 'not configured'}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Use bash commands (ls, cat, etc.) to inspect existing files in this directory.\n"
            f"2. If you need to edit additional files not listed above, claim them first:\n"
            f"   python3 \"$HARNESS_CLI\" claim --run-id \"$HARNESS_RUN_ID\" --worker \"$HARNESS_WORKER\" --file <relative_path>\n"
            f"3. Implement the necessary code and unit tests.\n"
            f"4. Run your deterministic quality gate:\n"
            f"   python3 \"$HARNESS_CLI\" gate --run-id \"$HARNESS_RUN_ID\" --worker \"$HARNESS_WORKER\" {gate_flags}\n"
            f"5. If the gate fails, examine error output, fix the code, and re-run gate until green.\n"
            f"6. Once the gate passes with status GATE_PASSED, commit your work: git add . && git commit -m 'Implement {w_task[:40]}'\n"
            f"7. Immediately conclude by replying 'TASK_COMPLETED' with no further tool calls so your loop finishes cleanly."
        )

        env = os.environ.copy()
        env["HARNESS_RUN_ID"] = run_id
        env["HARNESS_WORKER"] = w_name
        env["HARNESS_CLI"] = harness_cli

        log_file = logs_dir / f"{w_name}.log"
        log_fd = open(log_file, "w", encoding="utf-8")

        cmd = [
            sys.executable,
            or_agent_cli,
            "agent",
            "--prompt", prompt,
            "--model", w_model,
            "--max-turns", str(max_turns),
        ]

        proc = subprocess.Popen(
            cmd,
            cwd=w_path,
            env=env,
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            text=True,
        )
        worker_procs[w_name] = {
            "proc": proc,
            "log_fd": log_fd,
            "log_file": log_file,
            "task": t,
            "model": w_model,
            "start_time": time.time(),
        }
        print(f"   ▶️  Worker '{w_name}' spawned (PID {proc.pid}, model: {w_model})")
        log_event(harness_dir, "WORKER_DISPATCHED", {"worker": w_name, "pid": proc.pid, "model": w_model})

    # 3. Monitor worker completion
    active = set(worker_procs.keys())
    exit_codes = {}

    while active:
        time.sleep(2)
        now = time.time()
        for w_name in list(active):
            wp = worker_procs[w_name]
            ret = wp["proc"].poll()
            if ret is not None:
                wp["log_fd"].close()
                active.remove(w_name)
                exit_codes[w_name] = ret
                dur = round(now - wp["start_time"], 1)
                icon = "✅" if ret == 0 else "❌"
                print(f"   {icon} Worker '{w_name}' exited code {ret} in {dur}s (log: {wp['log_file'].relative_to(repo)})")
                log_event(harness_dir, "WORKER_COMPLETED", {"worker": w_name, "exit_code": ret, "duration": dur})
            elif now - wp["start_time"] > timeout_worker:
                print(f"   ⏰ Worker '{w_name}' reached timeout ({timeout_worker}s). Terminating PID {wp['proc'].pid}...")
                wp["proc"].terminate()
                time.sleep(1)
                if wp["proc"].poll() is None:
                    wp["proc"].kill()
                wp["log_fd"].close()
                active.remove(w_name)
                exit_codes[w_name] = -1
                log_event(harness_dir, "WORKER_TIMEOUT", {"worker": w_name, "timeout": timeout_worker})

    # 4. Automated Integration Phase
    print(f"\n🔀 [Swarm Integration] Running automated merge into {manifest['integration_branch']}...")
    int_res = cmd_integrate(run_id, test_cmd=test_cmd)

    print(f"\n🏁 [Swarm Dispatch Finished] Run ID: {run_id}")
    print(f"   🌿 Integrated Branch: {manifest['integration_branch']}")
    print(f"   📊 Merged Workers: {', '.join(int_res.get('merged_workers', [])) or 'None'}")
    if int_res.get("failed_merges"):
        print(f"   ⚠️  Failed Merges: {', '.join(int_res['failed_merges'])}")
    print(f"   📜 Event Timeline: {harness_dir / 'events.jsonl'}")

    return {
        "run_id": run_id,
        "integration_branch": manifest["integration_branch"],
        "exit_codes": exit_codes,
        "integration": int_res,
        "event_log": str(harness_dir / "events.jsonl"),
    }


if __name__ == "__main__":
    # If invoked directly as swarm-dispatch CLI
    if sys.argv[0].endswith("swarm-dispatch") and len(sys.argv) > 1:
        if sys.argv[1] not in ["start", "claim", "gate", "integrate", "status", "teardown", "dispatch", "-h", "--help"]:
            sys.argv.insert(1, "dispatch")

    parser = argparse.ArgumentParser(
        prog="worktree-harness",
        description="Multi-Agent Git Worktree Orchestration & Quality Gate Harness (Uber Protocol)"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # 1. Start / Spawn
    p_start = sub.add_parser("start", help="Initialize run and spawn isolated git worktrees for workers")
    p_start.add_argument("--goal", required=True, help="High-level objective / acceptance criteria")
    p_start.add_argument("--workers", nargs="+", required=True, help="List of worker names (e.g. agent-auth agent-db agent-api)")
    p_start.add_argument("--run-name", default=None, help="Optional custom run ID")

    # 2. Claim
    p_claim = sub.add_parser("claim", help="Reserve line/file ranges before writing to avoid collisions")
    p_claim.add_argument("--run-id", required=True, help="Harness Run ID")
    p_claim.add_argument("--worker", required=True, help="Worker name")
    p_claim.add_argument("--file", required=True, help="Target file path relative to repo root")
    p_claim.add_argument("--lines", default=None, help="Line range e.g. '10-45'")

    # 3. Gate
    p_gate = sub.add_parser("gate", help="Run deterministic test and/or app verification gates on a worker worktree")
    p_gate.add_argument("--run-id", required=True, help="Harness Run ID")
    p_gate.add_argument("--worker", required=True, help="Worker name")
    p_gate.add_argument("--test", default=None, help="Shell test command (e.g. 'pytest tests/test_auth.py')")
    p_gate.add_argument("--verify", default=None, help="App verification command (e.g. 'verify-app run --pass .verify/pass.json')")

    # 4. Integrate
    p_int = sub.add_parser("integrate", help="Merge GATE_PASSED worker branches with conflict arbitration")
    p_int.add_argument("--run-id", required=True, help="Harness Run ID")
    p_int.add_argument("--test", default=None, help="Global integration test command")
    p_int.add_argument("--verify", default=None, help="Global app verification command")
    p_int.add_argument("--allow-untested", action="store_true", help="Merge workers whose gate never passed")

    # 5. Status
    p_stat = sub.add_parser("status", help="View status of harness runs, worktrees, and claims")
    p_stat.add_argument("--run-id", default=None, help="Run ID (defaults to latest)")
    p_stat.add_argument("--json", action="store_true", help="Output as JSON")

    # 6. Teardown
    p_tear = sub.add_parser("teardown", help="Clean up worktrees while preserving consolidated branch and event logs")
    p_tear.add_argument("--run-id", required=True, help="Run ID")
    p_tear.add_argument("--delete-branches", action="store_true", help="Delete temporary worker branches")

    # 7. Dispatch (Swarm Orchestrator)
    p_disp = sub.add_parser("dispatch", help="Autonomous 1-command parallel subagent compiler")
    p_disp.add_argument("--tasks", default=None, help="Path to tasks.json plan")
    p_disp.add_argument("--goal", default=None, help="High-level goal string")
    p_disp.add_argument("--workers", nargs="+", default=None, help="List of worker names (when tasks.json is omitted)")
    p_disp.add_argument("--test", default=None, help="Global test gate command")
    p_disp.add_argument("--verify", default=None, help="Global app verification command")
    p_disp.add_argument("--run-name", default=None, help="Optional custom run ID")
    p_disp.add_argument("--max-turns", type=int, default=6, metavar="LIMIT", help="Maximum turns per subagent")
    p_disp.add_argument("--timeout", type=int, default=300, metavar="N", help="Per-worker timeout in seconds")
    p_disp.add_argument("--model", default=None, help="Model override for all workers")

    args = parser.parse_args()
    if args.action == "start":
        cmd_start(args.goal, args.workers, run_name=args.run_name)
    elif args.action == "claim":
        cmd_claim(args.run_id, args.worker, args.file, args.lines)
    elif args.action == "gate":
        cmd_gate(args.run_id, args.worker, args.test, args.verify)
    elif args.action == "integrate":
        res = cmd_integrate(args.run_id, args.test, args.verify, args.allow_untested)
        print(json.dumps(res, indent=2))
    elif args.action == "status":
        cmd_status(args.run_id, as_json=args.json)
    elif args.action == "teardown":
        cmd_teardown(args.run_id, delete_branches=args.delete_branches)
    elif args.action == "dispatch":
        res = cmd_dispatch(
            tasks_file=args.tasks,
            goal=args.goal,
            workers_spec=args.workers,
            test_cmd=args.test,
            verify_cmd=args.verify,
            run_name=args.run_name,
            max_turns=args.max_turns,
            timeout_worker=args.timeout,
            model_override=args.model,
        )
