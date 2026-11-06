#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

LIMITS = {
    "r2_gb": 10.0,
    "r2_class_a_per_month": 1_000_000,
    "r2_class_b_per_month": 10_000_000,
    "do_requests_per_day": 100_000,
    "do_writes_per_day": 100_000,
    "do_row_reads_per_day": 5_000_000,
    "do_sqlite_gb": 5.0,
    "workers_requests_per_day": 100_000,
    "d1_gb": 5.0,
    "kv_reads_per_day": 100_000,
    "kv_writes_per_day": 1_000,
    "workers_ai_neurons_per_day": 10_000,
    "whisper_neurons_per_audio_hour": 2_857,
}

SERVICES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("workers", ("cf", "workers", "list")),
    ("d1", ("cf", "d1", "list")),
    ("kv", ("cf", "kv", "namespaces", "list")),
    ("queues", ("cf", "queues", "list")),
    ("r2", ("cf", "r2", "buckets", "list")),
    ("containers", ("cf", "containers", "applications", "list")),
)

GATES = (
    ("10042", "enable R2 in the dashboard — no API path exists"),
    ("not entitled", "plan does not include this service"),
    ("unauthorized", "token lacks this scope"),
)

PAID_ONLY = ("containers",)

Runner = Callable[[Sequence[str]], Tuple[int, str]]


def run(cmd: Sequence[str], timeout: int = 25) -> Tuple[int, str]:
    try:
        proc = subprocess.run(
            list(cmd), capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def _extract_json(text: str):
    start = text.find("{")
    stop = text.rfind("}")
    if start == -1 or stop <= start:
        return None
    try:
        return json.loads(text[start : stop + 1])
    except json.JSONDecodeError:
        return None


def _extract_list(text: str):
    start = text.find("[")
    stop = text.rfind("]")
    if start == -1 or stop <= start:
        return None
    try:
        parsed = json.loads(text[start : stop + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def classify(name: str, rc: int, output: str) -> Dict[str, str]:
    lowered = output.lower()
    for needle, remedy in GATES:
        if needle in lowered:
            return {"state": "gated", "detail": remedy}
    if rc != 0:
        first = next((ln.strip() for ln in output.splitlines() if ln.strip()), "")
        return {"state": "error", "detail": first[:120]}
    listed = _extract_list(output)
    if listed is not None:
        return {
            "state": "active" if listed else "empty",
            "detail": f"{len(listed)} resource(s)",
        }
    lines = [ln for ln in output.splitlines() if ln.strip()]
    return {"state": "unknown", "detail": f"{len(lines)} line(s) of output"}


def probe(runner: Runner = run) -> Dict[str, object]:
    version_rc, version_out = runner(("cf", "--version"))
    version = ""
    match = re.search(r"v(\d+\.\d+\.\d+)", version_out)
    if match:
        version = match.group(1)

    auth_rc, auth_out = runner(("cf", "auth", "whoami"))
    auth = _extract_json(auth_out) if auth_rc == 0 else None

    subs_rc, subs_out = runner(("cf", "accounts", "subscriptions", "get"))
    subs = _extract_list(subs_out) if subs_rc == 0 else None
    free_plan = subs == [] if subs is not None else None

    services: Dict[str, Dict[str, str]] = {}
    for name, cmd in SERVICES:
        rc, out = runner(cmd)
        services[name] = classify(name, rc, out)

    containers_available = None
    if free_plan is True:
        containers_available = False
        services["containers"] = {
            "state": "gated",
            "detail": "requires Workers Paid ($5/mo)",
        }

    return {
        "cf_version": version,
        "authenticated": bool(auth and auth.get("authenticated")),
        "email": (auth or {}).get("email"),
        "accounts": len((auth or {}).get("accounts") or []),
        "plan": None if free_plan is None else ("free" if free_plan else "paid"),
        "containers_available": containers_available,
        "services": services,
    }


def render_probe(report: Dict[str, object]) -> str:
    rows: List[Tuple[str, str, str]] = [
        ("cf", str(report["cf_version"] or "?"), ""),
        ("authenticated", "yes" if report["authenticated"] else "no", str(report["email"] or "")),
        ("plan", str(report["plan"] or "unknown"), ""),
    ]
    for name, info in sorted((report["services"] or {}).items()):
        rows.append((name, info["state"], info["detail"]))
    width = max(len(r[0]) for r in rows)
    out = []
    for a, b, c in rows:
        out.append(f"{a.ljust(width)}  {b:<8} {c}".rstrip())
    return "\n".join(out)


def budget(args: argparse.Namespace) -> int:
    checks = [
        ("r2 storage", "GB", args.r2_gb, LIMITS["r2_gb"]),
        ("r2 class A", "ops/mo", args.r2_class_a, LIMITS["r2_class_a_per_month"]),
        ("r2 class B", "ops/mo", args.r2_class_b, LIMITS["r2_class_b_per_month"]),
        ("do sqlite", "GB", args.do_sqlite_gb, LIMITS["do_sqlite_gb"]),
        ("do writes", "rows/day", args.do_writes_per_day, LIMITS["do_writes_per_day"]),
        ("do requests", "req/day", args.requests_per_day, LIMITS["do_requests_per_day"]),
        (
            "workers-ai audio",
            "h/day",
            args.audio_hours_per_day,
            LIMITS["workers_ai_neurons_per_day"] / LIMITS["whisper_neurons_per_audio_hour"],
        ),
    ]
    failed = 0
    print(
        f"{'dimension':<18}{'used':>10}  {'unit':<9}"
        f"{'limit':>12} {'headroom':>11}  verdict"
    )
    for label, unit, used, limit in checks:
        passed = used <= limit
        failed += 0 if passed else 1
        headroom = limit - used
        verdict = "pass" if passed else "FAIL"
        print(
            f"{label:<18}{used:>10.2f}  {unit:<9}"
            f"{limit:>12.2f} {headroom:>11.2f}  {verdict}"
        )
    print()
    if failed:
        print(f"{failed} dimension(s) exceed the free tier — paid plan or redesign.")
    else:
        print("fits the free tier on every dimension.")
    return 0 if failed == 0 else 1


def scripts_fix(package: str, context: str) -> int:
    if context == "global":
        print(f"npm install -g {package} --allow-scripts={package}")
        print(f"# or persist it for future globals:")
        print(f"npm config set allow-scripts={package} --location=user")
    else:
        print(f"npm install-scripts approve {package}")
        print(f"# writes package.json -> allowScripts: {{ \"{package}@<version>\": true }}")
        print(f"# name-only (all versions): npm install-scripts approve --no-allow-scripts-pin {package}")
    print()
    print("never pass --allow-scripts to a project-scoped install: it is EALLOWSCRIPTS.")
    return 0


def doctor() -> int:
    checks: List[Tuple[str, str]] = []

    cf_path = shutil.which("cf")
    rc, out = run(("cf", "--version"))
    version = re.search(r"v(\d+\.\d+\.\d+)", out)
    checks.append(("cf", f"{version.group(1) if version else 'missing'} -> {cf_path or 'not on PATH'}"))

    if cf_path and "/versions/node/" in cf_path:
        checks.append(("nvm", "cf is pinned to this Node version; it disappears if you switch"))

    wrangler = shutil.which("wrangler")
    if wrangler:
        _, wout = run((wrangler, "--version"))
        checks.append(("wrangler", wout.strip().splitlines()[-1] if wout.strip() else "?"))
    else:
        checks.append(("wrangler", "not global (use npx wrangler dev in a project)"))

    _, npm_out = run(("npm", "-v"))
    checks.append(("npm", npm_out.strip() or "missing"))
    _, policy = run(("npm", "config", "get", "allow-scripts"))
    checks.append(("allow-scripts", (policy.strip() or "(empty)") + "  advisory list, scripts still run"))

    root_rc, root_out = run(("npm", "root", "-g"))
    if root_rc == 0 and root_out.strip():
        for bin_path in Path(root_out.strip()).rglob("workerd/bin/workerd"):
            _, wv = run((str(bin_path), "--version"))
            checks.append(("workerd", wv.strip().splitlines()[-1] if wv.strip() else "present"))

    width = max(len(c[0]) for c in checks)
    for name, value in checks:
        print(f"{name.ljust(width)}  {value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cf-architect",
        description="Cloudflare capability probe, free-tier budget math, and CLI remedies.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="read-only service matrix for this account")
    p_probe.add_argument("--json", action="store_true", help="machine-readable output")

    sub.add_parser("doctor", help="local toolchain state and known papercuts")

    p_budget = sub.add_parser("budget", help="free-tier arithmetic for a workload")
    p_budget.add_argument("--r2-gb", type=float, default=0.0)
    p_budget.add_argument("--r2-class-a", type=float, default=0.0)
    p_budget.add_argument("--r2-class-b", type=float, default=0.0)
    p_budget.add_argument("--do-sqlite-gb", type=float, default=0.0)
    p_budget.add_argument("--do-writes-per-day", type=float, default=0.0)
    p_budget.add_argument("--requests-per-day", type=float, default=0.0)
    p_budget.add_argument("--audio-hours-per-day", type=float, default=0.0)

    p_fix = sub.add_parser("scripts-fix", help="correct npm allow-scripts remedy")
    p_fix.add_argument("--package", default="workerd")
    p_fix.add_argument("--context", choices=("global", "project"), default="global")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "probe":
        report = probe()
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(render_probe(report))
        return 0 if report["authenticated"] else 2
    if args.command == "doctor":
        return doctor()
    if args.command == "budget":
        return budget(args)
    if args.command == "scripts-fix":
        return scripts_fix(args.package, args.context)
    return 2


if __name__ == "__main__":
    sys.exit(main())
