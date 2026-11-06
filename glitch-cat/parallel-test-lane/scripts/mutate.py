#!/usr/bin/env python3
"""Tiny stdlib-only mutation tester: prove a test can fail.

Mutations are textual, one line at a time: flip a comparison operator, bump an
integer literal, replace `and` with `or`, delete a `raise`/`return` line.
A mutant is "killed" when the test command exits non-zero.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FLIP = {"==": "!=", "!=": "==", "<=": ">", ">=": "<", "<": ">=", ">": "<="}
CMP_RE = re.compile(r"==|!=|<=|>=|<|>")
INT_RE = re.compile(r"(?<![\w.])\d+(?![\w.])")
AND_RE = re.compile(r"\band\b")


def _mutations(line, line_no):
    """Yield (line_no, mutated_line, description) for one source line."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return
    for m in CMP_RE.finditer(line):
        op = m.group()
        if op == ">" and m.start() and line[m.start() - 1] == "-":
            continue  # never turn `->` into `-=`
        yield line_no, line[:m.start()] + FLIP[op] + line[m.end():], f"{op} -> {FLIP[op]}"
    for m in INT_RE.finditer(line):
        n = int(m.group())
        yield line_no, line[:m.start()] + str(n + 1) + line[m.end():], f"int {n} -> {n + 1}"
    for m in AND_RE.finditer(line):
        yield line_no, line[:m.start()] + "or" + line[m.end():], "and -> or"
    word = stripped.split()[0]
    if word in ("raise", "return"):
        yield line_no, "", f"delete {word}"


def _plan(path):
    """Return [(line_no, mutated_text, description), ...]."""
    lines = Path(path).read_text().splitlines(keepends=True)
    out, seen = [], set()
    for i, line in enumerate(lines, 1):
        for item in _mutations(line, i):
            line_no, text = item[0], item[1]
            if text != line and (line_no, text) not in seen:
                seen.add((line_no, text))
                out.append(item)
    return out


def plan(path):
    """Return [(line_no, mutated_text), ...] for every single-line mutation."""
    return [(line_no, text) for line_no, text, _ in _plan(path)]


def check(path, test_cmd, limit=8):
    """Run test_cmd against each mutant; restore the file in a finally block.

    The test command runs with the mutated file's directory as cwd. Returns
    [{"line", "mutation", "killed"}, ...].
    """
    path = Path(path)
    original = path.read_text()
    base = original.splitlines(keepends=True)
    results = []
    try:
        for line_no, text, desc in _plan(path)[:limit]:
            lines = list(base)
            lines[line_no - 1] = text
            path.write_text("".join(lines))
            proc = subprocess.run(
                test_cmd, shell=True, cwd=str(path.resolve().parent),
                capture_output=True, text=True,
            )
            results.append({"line": line_no, "mutation": desc, "killed": proc.returncode != 0})
    finally:
        path.write_text(original)
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mutation-test one Python file.")
    ap.add_argument("file", help="source file to mutate")
    ap.add_argument("--test", required=True, help="test command; non-zero exit kills a mutant")
    ap.add_argument("--limit", type=int, default=8, metavar="LIMIT", help="max mutants to run (default 8)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args(argv)

    results = check(args.file, args.test, args.limit)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            tag = "KILLED  " if r["killed"] else "SURVIVED"
            print(f"{tag} line {r['line']:>4}  {r['mutation']}")
        print(f"{len(results)} mutants, {sum(not r['killed'] for r in results)} survived")
    return 0


if __name__ == "__main__":
    sys.exit(main())
