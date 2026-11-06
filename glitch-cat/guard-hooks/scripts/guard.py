#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

GUARD_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = GUARD_DIR / "config.json"

def load_config(workspace_dir: Optional[str] = None) -> Dict[str, Any]:
    base_cfg = {}
    if CONFIG_PATH.is_file():
        try:
            with open(CONFIG_PATH) as f:
                base_cfg = json.load(f)
        except Exception:
            pass

    ws = Path(workspace_dir) if workspace_dir else Path.cwd()
    ws_cfg_path = ws / ".guard-hooks.json"
    if ws_cfg_path.is_file():
        try:
            with open(ws_cfg_path) as f:
                ws_cfg = json.load(f)
                if "protected_files" in ws_cfg:
                    base_cfg.setdefault("protected_files", []).extend(ws_cfg["protected_files"])
                if "forbidden_commands" in ws_cfg:
                    base_cfg.setdefault("forbidden_commands", []).extend(ws_cfg["forbidden_commands"])
        except Exception:
            pass

    return base_cfg

def is_protected_file(file_path: str, config: Dict[str, Any]) -> bool:
    name = Path(file_path).name
    full = str(file_path)
    protected = config.get("protected_files", [])
    for p in protected:
        if fnmatch.fnmatch(name, p) or fnmatch.fnmatch(full, p):
            return True
        if name.lower() == p.lower():
            return True
    return False

def check_file_action(action: str, file_path: str, workspace_dir: Optional[str] = None) -> Tuple[bool, str]:
    cfg = load_config(workspace_dir)
    if action in ("delete", "remove", "overwrite", "truncate"):
        if is_protected_file(file_path, cfg):
            return False, f"🛑 [GUARD-HOOK ERROR] Protected file '{file_path}' cannot be {action}d! (Kem Glitch Law: hooks always run regardless of prompt)"
    return True, "OK"

def check_command(cmd: str, workspace_dir: Optional[str] = None) -> Tuple[bool, str]:
    cfg = load_config(workspace_dir)

    for item in cfg.get("forbidden_commands", []):
        pat = item.get("pattern", "")
        reason = item.get("reason", "Forbidden destructive pattern")
        if re.search(pat, cmd, re.I):
            return False, f"🛑 [GUARD-HOOK BLOCKED] Command halted by deterministic hook: {reason} (Pattern: '{pat}')"

    rm_match = re.search(r"\brm\s+.*", cmd)
    if rm_match:
        tokens = cmd.split()
        for t in tokens:
            cleaned = t.strip("\"'")
            if is_protected_file(cleaned, cfg):
                return False, f"🛑 [GUARD-HOOK BLOCKED] Attempting to delete protected file '{cleaned}'! Intercepted before execution."

    for sec_pat in cfg.get("secret_leak_patterns", []):
        if re.search(sec_pat, cmd):
            return False, f"🛑 [GUARD-HOOK BLOCKED] Command contains exposed plaintext API key or private key! (Masked by secret shield)"

    return True, "OK"

def wrap_execution(cmd_tokens: List[str], workspace_dir: Optional[str] = None) -> int:
    cmd_str = " ".join(cmd_tokens)
    allowed, msg = check_command(cmd_str, workspace_dir)
    if not allowed:
        print(msg, file=sys.stderr)
        return 1

    try:
        proc = subprocess.run(cmd_str, shell=True)
        return proc.returncode
    except Exception as e:
        print(f"[guard-hooks] Execution failed: {e}", file=sys.stderr)
        return 1

def install_git_hook(repo_dir: Optional[str] = None):
    repo = Path(repo_dir) if repo_dir else Path.cwd()
    hooks_dir = repo / ".git" / "hooks"
    if not hooks_dir.is_dir():
        print(f"[guard-hooks] Error: {repo} is not a git repository.", file=sys.stderr)
        return 1

    pre_commit_file = hooks_dir / "pre-commit"
    hook_script = f"""#!/usr/bin/env bash
# Installed by guard-hooks (Kem Glitch Deterministic Hook Architecture)
set -eo pipefail

echo "🔒 [guard-hooks] Running pre-commit deterministic audit..."
python3 /run/media/rodri/AI/skills/guard-hooks/guard_hooks.py check-staged
"""
    pre_commit_file.write_text(hook_script)
    pre_commit_file.chmod(0o755)
    print(f"[guard-hooks] Successfully installed pre-commit hook at {pre_commit_file}")
    return 0

def check_staged_git():
    cfg = load_config()
    res = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True)
    if res.returncode != 0:
        return 0

    staged_files = [f.strip() for f in res.stdout.splitlines() if f.strip()]
    for f in staged_files:
        if is_protected_file(f, cfg):
            print(f"🛑 [GUARD-HOOK REJECTED] Cannot commit protected file: '{f}'!", file=sys.stderr)
            sys.exit(1)

    diff_res = subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True)
    diff_text = diff_res.stdout
    for sec_pat in cfg.get("secret_leak_patterns", []):
        if re.search(sec_pat, diff_text):
            print(f"🛑 [GUARD-HOOK REJECTED] Commit aborted: Secret key leak detected in staged diff!", file=sys.stderr)
            sys.exit(1)

    print("✅ [guard-hooks] Staged changes passed all deterministic safety checks.")
    return 0

def protect_file(file_name: str, workspace_dir: Optional[str] = None):
    ws = Path(workspace_dir) if workspace_dir else Path.cwd()
    cfg_path = ws / ".guard-hooks.json"
    data = {"protected_files": []}
    if cfg_path.is_file():
        try:
            with open(cfg_path) as f:
                data = json.load(f)
        except Exception:
            pass

    if file_name not in data["protected_files"]:
        data["protected_files"].append(file_name)

    with open(cfg_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"[guard-hooks] Added '{file_name}' to local protection list at {cfg_path}")

def main():
    p = argparse.ArgumentParser(description="Deterministic Guard Hooks (Kem Glitch Architecture)")
    sub = p.add_subparsers(dest="cmd")

    chk_p = sub.add_parser("check", help="Check command or file action against deterministic guardrails")
    chk_p.add_argument("command", help="Shell command to validate")

    act_p = sub.add_parser("check-file", help="Check file action safety (delete/overwrite)")
    act_p.add_argument("action", choices=["delete", "overwrite", "truncate"], help="Action type")
    act_p.add_argument("file", help="Target file path")

    wrap_p = sub.add_parser("wrap", help="Wrap and execute command with pre-execution safety gate")
    wrap_p.add_argument("command", nargs=argparse.REMAINDER, help="Command to safely execute")

    prot_p = sub.add_parser("protect", help="Add file to protected targets in current repo")
    prot_p.add_argument("file", help="Filename or pattern to lock (e.g. KeepMD, *.key)")

    sub.add_parser("check-staged", help="Audit git staged files and diffs for protected files and leaks")
    sub.add_parser("install-git-hook", help="Install pre-commit hook in current git repository")

    args = p.parse_args()
    if args.cmd == "check":
        ok, msg = check_command(args.command)
        if not ok:
            print(msg, file=sys.stderr)
            sys.exit(1)
        print("✅ [guard-hooks] Command permitted.")
    elif args.cmd == "check-file":
        ok, msg = check_file_action(args.action, args.file)
        if not ok:
            print(msg, file=sys.stderr)
            sys.exit(1)
        print(f"✅ [guard-hooks] Action '{args.action}' permitted on {args.file}.")
    elif args.cmd == "wrap":
        if not args.command:
            p.print_help()
            sys.exit(1)
        code = wrap_execution(args.command)
        sys.exit(code)
    elif args.cmd == "protect":
        protect_file(args.file)
    elif args.cmd == "check-staged":
        sys.exit(check_staged_git())
    elif args.cmd == "install-git-hook":
        sys.exit(install_git_hook())
    else:
        p.print_help()

if __name__ == "__main__":
    main()
