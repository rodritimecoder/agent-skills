#!/usr/bin/env python3
"""Tiny stdlib-only mutation tester: prove a test can fail.

Mutations are textual, one line at a time: flip a comparison or boolean
operator, bump an integer literal, replace `and` with `or`, delete a
`raise`/`return`/`throw` line. Language-agnostic: comment lines from Python,
JS/TS, C-like, SQL, INI and HTML sources are skipped.

A mutant is "killed" when the test command exits non-zero. A surviving mutant
means the suite still passes on broken code, so the run fails.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

COMMENT_PREFIXES = ("#", "//", "/*", "*", "--", ";", "<!--")
FLIP = {
    "==": "!=", "!=": "==", "<=": ">", ">=": "<", "<": ">=", ">": "<=",
    "&&": "||", "||": "&&",
}
CMP_RE = re.compile(r"==|!=|<=|>=|&&|\|\||<|>")
INT_RE = re.compile(r"(?<![\w.])\d+(?![\w.])")
AND_RE = re.compile(r"\band\b")
DELETE_KEYWORDS = ("raise", "return", "throw")


def _mutations(line, line_no):
    """Yield (line_no, mutated_line, description) for one source line."""
    stripped = line.strip()
    if not stripped or stripped.startswith(COMMENT_PREFIXES):
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
    if word in DELETE_KEYWORDS:
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


def check(path, test_cmd, limit=8, cwd=None):
    """Run test_cmd against each mutant; restore the file in a finally block.

    The test command runs in `cwd`, or the mutated file's directory when cwd is
    None, so a gate can point it at the project/worktree root. Raises
    ValueError when there is nothing to mutate: a run with zero mutants proves
    nothing and never reports success. Returns [{"line", "mutation", "killed"}].
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    mutations = _plan(path)
    if not mutations:
        raise ValueError(f"no mutations generated for {path}: nothing would be proven")
    path = Path(path)
    original = path.read_text()
    base = original.splitlines(keepends=True)
    run_dir = Path(cwd) if cwd is not None else path.resolve().parent
    results = []
    try:
        for line_no, text, desc in mutations[:limit]:
            lines = list(base)
            lines[line_no - 1] = text
            path.write_text("".join(lines))
            proc = subprocess.run(
                test_cmd, shell=True, cwd=str(run_dir),
                capture_output=True, text=True,
            )
            results.append({"line": line_no, "mutation": desc, "killed": proc.returncode != 0})
    finally:
        path.write_text(original)
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(
        epilog=('Exit codes: 0 every mutant killed; 1 a mutant survived or the run was refused; '
                '2 invalid arguments (usage error).'),
        description="Mutation-test one source file across Python, JS/TS, C-like, SQL, INI and HTML.",
    )
    ap.add_argument("file", help="source file to mutate")
    ap.add_argument("--test", required=True, help="test command; non-zero exit kills a mutant")
    ap.add_argument("--limit", type=int, default=8, metavar="LIMIT", help="max mutants to run (default 8)")
    ap.add_argument("--allow-survivors", action="store_true",
                    help="report survivors but exit 0 (old reporting-only behaviour)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args(argv)

    if args.limit < 1:
        ap.error("--limit must be >= 1")

    try:
        results = check(args.file, args.test, args.limit)
    except (OSError, ValueError) as exc:
        print(f"mutate: {exc}", file=sys.stderr)
        return 1

    survivors = sum(not r["killed"] for r in results)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            tag = "KILLED  " if r["killed"] else "SURVIVED"
            print(f"{tag} line {r['line']:>4}  {r['mutation']}")
        print(f"{len(results)} mutants, {survivors} survived")

    if survivors and not args.allow_survivors:
        print(f"mutate: {survivors} mutant(s) survived — the test cannot fail on this code", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
