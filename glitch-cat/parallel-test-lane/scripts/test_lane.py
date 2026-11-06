#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TEST_PATTERNS = [
    "test_*.py", "*_test.py",
    "*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx",
    "*.test.js", "*.spec.js",
    "*_test.go"
]

def discover_test_files(target_dir: Path) -> List[Path]:
    files = []
    for root, _, filenames in os.walk(target_dir):
        if any(skip in root for skip in [".git", "node_modules", ".venv", "__pycache__", "build", "dist"]):
            continue
        for fn in filenames:
            for pat in TEST_PATTERNS:
                if fnmatch.fnmatch(fn, pat):
                    files.append(Path(root) / fn)
                    break
    return sorted(files)

def partition_tests(test_files: List[Path], max_lanes: int) -> Tuple[List[Path], List[List[Path]]]:
    serial_tests: List[Path] = []
    parallel_tests: List[Path] = []

    for tf in test_files:
        try:
            content = tf.read_text(errors="replace")
            if re.search(r"\b(serial|@pytest\.mark\.serial|//\s*serial|#\s*serial)\b", content, re.I):
                serial_tests.append(tf)
            else:
                parallel_tests.append(tf)
        except Exception:
            parallel_tests.append(tf)

    num_lanes = min(max_lanes, max(1, len(parallel_tests)))
    lanes: List[List[Path]] = [[] for _ in range(num_lanes)]
    for idx, tf in enumerate(parallel_tests):
        lanes[idx % num_lanes].append(tf)

    return serial_tests, lanes

def _run_single_test(test_path: Path, cmd_template: str) -> Dict[str, Any]:
    cmd = cmd_template.replace("{file}", str(test_path))
    t0 = time.time()
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    duration = time.time() - t0
    return {
        "file": str(test_path),
        "cmd": cmd,
        "passed": res.returncode == 0,
        "exit_code": res.returncode,
        "duration": duration,
        "stdout": res.stdout,
        "stderr": res.stderr
    }

def _run_lane(lane_id: int, tests: List[Path], cmd_template: str) -> List[Dict[str, Any]]:
    results = []
    for tf in tests:
        res = _run_single_test(tf, cmd_template)
        results.append(res)
    return results

def run_test_suite(
    target_dir: str,
    cmd_template: Optional[str] = None,
    lanes_count: Optional[int] = None,
    out_report: Optional[str] = None
) -> int:
    base = Path(target_dir).resolve()
    all_tests = discover_test_files(base)

    if not all_tests:
        print(f"[parallel-test-lane] No test files found in {base} matching standard test patterns.")
        return 0

    if not cmd_template:
        first = all_tests[0]
        if first.suffix == ".py":
            cmd_template = "pytest -q {file}" if subprocess.run("which pytest", shell=True, capture_output=True).returncode == 0 else "python3 {file}"
        elif first.suffix in (".ts", ".js", ".tsx", ".jsx"):
            cmd_template = "npm test -- {file}"
        elif first.suffix == ".go":
            cmd_template = "go test {file}"
        else:
            cmd_template = "python3 {file}"

    cpu_cores = os.cpu_count() or 4
    num_lanes = lanes_count or min(16, max(2, cpu_cores))

    serial_tests, parallel_lanes = partition_tests(all_tests, num_lanes)
    active_lanes = [l for l in parallel_lanes if l]

    print("\n" + "=" * 65)
    print(" ⚡ PARALLEL TEST LANE — BLAST RADIUS RUNNER (Kem Glitch Architecture)")
    print("=" * 65)
    print(f" Target Path       : {base}")
    print(f" Discovered Tests  : {len(all_tests)} test files")
    print(f" Execution Command : `{cmd_template}`")
    print(f" Worker Lanes      : {len(active_lanes)} parallel lanes (Cores available: {cpu_cores})")
    print(f" Serial Partition  : {len(serial_tests)} tests reserved for sequential isolation")
    print("=" * 65 + "\n")

    start_time = time.time()
    results: List[Dict[str, Any]] = []

    if active_lanes:
        print(f"🚀 Launching {len(active_lanes)} parallel lanes across CPU threads...")
        with ThreadPoolExecutor(max_workers=len(active_lanes)) as executor:
            futures = [
                executor.submit(_run_lane, idx, lane_tests, cmd_template)
                for idx, lane_tests in enumerate(active_lanes, 1)
            ]
            for f in as_completed(futures):
                results.extend(f.result())

    if serial_tests:
        print(f"\n🔒 Running {len(serial_tests)} isolated serial tests sequentially...")
        for tf in serial_tests:
            results.append(_run_single_test(tf, cmd_template))

    total_duration = time.time() - start_time
    total_sequential_time = sum(r["duration"] for r in results)
    speedup = total_sequential_time / max(0.001, total_duration)

    passed_count = sum(1 for r in results if r["passed"])
    failed_count = sum(1 for r in results if not r["passed"])

    print("\n" + "=" * 65)
    print(" 📊 EXECUTION SUMMARY")
    print("=" * 65)
    print(f" Total Tests Run    : {len(results)}")
    print(f" Passed             : {passed_count} ✅")
    print(f" Failed             : {failed_count} ❌")
    print(f" Wall Clock Time    : {total_duration:.2f}s")
    print(f" Sequential Est.    : {total_sequential_time:.2f}s")
    print(f" Speedup Factor     : {speedup:.2f}x faster across parallel CPU lanes")
    print("=" * 65)

    if failed_count > 0:
        print("\n❌ FAILED TEST DETAILS:")
        for r in results:
            if not r["passed"]:
                print(f"\n[FAIL] {r['file']} (exit code: {r['exit_code']})")
                if r["stderr"].strip():
                    print("  Stderr:\n    " + "\n    ".join(r["stderr"].strip().splitlines()[:5]))
                if r["stdout"].strip():
                    print("  Stdout:\n    " + "\n    ".join(r["stdout"].strip().splitlines()[:5]))

    if out_report:
        report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total": len(results),
            "passed": passed_count,
            "failed": failed_count,
            "wall_duration_sec": round(total_duration, 2),
            "speedup_factor": round(speedup, 2),
            "results": results
        }
        Path(out_report).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n[parallel-test-lane] Full JSON report buffered to {out_report}")

    return 0 if failed_count == 0 else 1

def plan_partition(target_dir: str, lanes_count: Optional[int] = None):
    base = Path(target_dir).resolve()
    all_tests = discover_test_files(base)
    num_lanes = lanes_count or min(16, max(2, os.cpu_count() or 4))
    serial_tests, parallel_lanes = partition_tests(all_tests, num_lanes)

    print("\n" + "=" * 60)
    print(f" 📋 TEST PARTITION PLAN: {base}")
    print("=" * 60)
    print(f" Total Discovered : {len(all_tests)}")
    print(f" Serial Reserved  : {len(serial_tests)}")
    for idx, st in enumerate(serial_tests, 1):
        print(f"   [Serial-{idx}] {st.name}")

    print(f"\n Parallel Lanes ({len(parallel_lanes)} lanes):")
    for idx, lane in enumerate(parallel_lanes, 1):
        names = ", ".join(t.name for t in lane) if lane else "(empty)"
        print(f"   Lane {idx:02d} ({len(lane)} files): {names}")
    print("=" * 60 + "\n")

def main():
    p = argparse.ArgumentParser(description="Parallel Test Lane — AI Blast Radius Containment")
    sub = p.add_subparsers(dest="subcommand", required=True)

    run_p = sub.add_parser("run", help="Run test suite in parallel worker lanes")
    run_p.add_argument("--dir", default=".", help="Directory to search for test files")
    run_p.add_argument("--cmd", help="Command template containing {file}, e.g. 'pytest -q {file}'")
    run_p.add_argument("--lanes", type=int, metavar="N", help="Number of parallel worker lanes (default: CPU cores)")
    run_p.add_argument("--out", help="Write JSON execution report to file")

    plan_p = sub.add_parser("plan", help="Preview sequential vs parallel lane partition map")
    plan_p.add_argument("--dir", default=".", help="Directory to search for test files")
    plan_p.add_argument("--lanes", type=int, metavar="N", help="Number of parallel worker lanes")

    args = p.parse_args()
    if args.subcommand == "run":
        code = run_test_suite(args.dir, cmd_template=args.cmd, lanes_count=args.lanes, out_report=args.out)
        sys.exit(code)
    elif args.subcommand == "plan":
        plan_partition(args.dir, lanes_count=args.lanes)
    else:
        p.print_help()

if __name__ == "__main__":
    main()
