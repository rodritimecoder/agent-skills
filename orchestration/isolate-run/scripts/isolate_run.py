#!/usr/bin/env python3
"""isolate-run — capability-gated Deno (V8 isolate) sandbox for untrusted JS/TS.

Never uses `deno eval` (which grants all permissions by default in Deno 2.x).
Always uses `deno run --no-prompt` with an explicit allow-list, explicit deny
flags for every other capability, a V8 heap cap and a wall-clock timeout.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CAPS = ["read", "write", "net", "env", "sys", "run", "ffi"]


def deno_bin():
    return os.environ.get("DENO_BIN") or shutil.which("deno") or ""


def build_flags(profile, allow_path, allow_host, mem):
    flags = ["run", "--no-prompt", "--no-remote", "--no-npm", "--no-check",
             f"--v8-flags=--max-old-space-size={mem}"]
    allowed = set()
    if profile == "read":
        allowed.add("read")
        flags.append(f"--allow-read={allow_path}")
    elif profile == "net":
        allowed.add("net")
        flags.append(f"--allow-net={allow_host}")
    for cap in CAPS:
        if cap not in allowed:
            flags.append(f"--deny-{cap}")
    return flags


def main():
    ap = argparse.ArgumentParser(epilog='Exit codes: 0 success; 1 runtime/validation error; 2 invalid arguments (usage error); other non-zero values are script-specific.', description=__doc__)
    ap.add_argument("--profile", choices=["pure", "read", "net"], default="pure")
    ap.add_argument("--allow-path", help="exact path readable in 'read' profile")
    ap.add_argument("--allow-host", help="exact host[:port] reachable in 'net' profile")
    ap.add_argument("--mem", type=int, default=128, help="V8 heap cap in MiB (default 128)")
    ap.add_argument("--timeout", type=float, default=10.0, help="wall-clock seconds (default 10)")
    ap.add_argument("--json", action="store_true", help="emit a JSON result envelope")
    ap.add_argument("script", help="JS/TS file to execute inside the isolate")
    ap.add_argument("args", nargs="*", help="arguments passed to the script")
    a = ap.parse_args()

    if a.profile == "read" and not a.allow_path:
        ap.error("read profile requires --allow-path")
    if a.profile == "net" and not a.allow_host:
        ap.error("net profile requires --allow-host")
    if not Path(a.script).is_file():
        ap.error(f"script not found: {a.script}")
    deno = deno_bin()
    if not deno:
        ap.error("deno not found on PATH; install Deno 2.x or set DENO_BIN")

    flags = build_flags(a.profile, a.allow_path, a.allow_host, a.mem)
    cmd = [deno] + flags + [a.script] + a.args
    started = time.monotonic()
    timed_out = False
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=a.timeout)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        timed_out, rc = True, 124
        out = e.stdout or ""
        err = (e.stderr or "") + f"\n[timed out after {a.timeout}s]"
    ms = int((time.monotonic() - started) * 1000)

    if a.json:
        print(json.dumps({
            "profile": a.profile,
            "flags": flags,
            "exit": rc,
            "timed_out": timed_out,
            "duration_ms": ms,
            "stdout": out[:4000],
            "stderr": err[:2000],
        }, indent=2))
    else:
        sys.stdout.write(out)
        sys.stderr.write(err)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
