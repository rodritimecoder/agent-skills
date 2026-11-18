#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

_argv = sys.argv[1:]

_OMNI_SCHEMA = {
    "name": "guard-hooks",
    "description": "Deterministic pre-execution guard rails",
    "version": 1,
    "flags": [
        {"name": "--json", "kind": "bool", "help": "Emit structured JSON on stdout"},
        {"name": "--omni-schema", "kind": "bool", "help": "Print this schema and exit 0"},
    ],
    "commands": [
        {"name": "check", "args": ["command"], "flags": ["--json"], "mutating": False,
         "help": "Check a shell command against guard rails"},
        {"name": "check-file", "args": ["action", "file"], "flags": ["--json"],
         "action_choices": ["delete", "overwrite", "truncate"], "mutating": False,
         "help": "Check a file action against guard rails"},
        {"name": "wrap", "args": ["command"], "flags": ["--dry-run", "--json"], "mutating": True,
         "help": "Execute a command behind the safety gate"},
        {"name": "protect", "args": ["file"], "mutating": True,
         "help": "Add a file or pattern to protected targets"},
        {"name": "check-staged", "mutating": False, "help": "Audit staged files and diffs"},
        {"name": "install-git-hook", "mutating": True, "help": "Install the pre-commit hook"},
    ],
}

if "--omni-schema" in _argv:
    print(json.dumps(_OMNI_SCHEMA, indent=2))
    sys.exit(0)

# The Rust binary is exec'd below, so a `wrap --dry-run` must be intercepted
# here at the Python wrapper before any native code can mutate anything.
if "wrap" in _argv and "--dry-run" in _argv:
    _plan = {"command": "wrap", "dry_run": True, "argv": _argv}
    print(json.dumps(_plan, indent=2) if "--json" in _argv else
          f"[dry-run] guard-hooks wrap: would apply guard with {_argv}")
    sys.exit(0)

# The native binary has no --json flag; serve structural requests with the
# Python implementation instead of exec'ing it.
_JSON_MODE = "--json" in _argv
if _JSON_MODE:
    _commands = tuple(c["name"] for c in _OMNI_SCHEMA["commands"])
    _command = next((a for a in _argv if a in _commands), None)
    if _command is None:
        print(json.dumps({
            "tool": "guard-hooks", "json": True,
            "native_exec": "disabled in --json mode",
            "commands": list(_commands),
        }, indent=2))
        sys.exit(0)
    if _command not in ("check", "check-file"):
        print(json.dumps({
            "command": _command, "allowed": False,
            "reason": "--json is only supported for check and check-file",
        }, indent=2))
        sys.exit(2)
    _rest = [a for a in _argv if a != "--json"]
    _rest.remove(_command)
    sys.argv = [sys.argv[0], _command, "--json"] + _rest

bin_path = Path(__file__).resolve().parent / "bin" / "guard-hooks"
if not _JSON_MODE and bin_path.is_file() and os.access(bin_path, os.X_OK):
    os.execv(str(bin_path), [str(bin_path)] + sys.argv[1:])

sys.path.append(str(Path(__file__).resolve().parent / "scripts"))
import guard

if __name__ == "__main__":
    guard.main()
