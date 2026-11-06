#!/usr/bin/env python3
"""Fan one task out to every free-swarm agent at once and land the answers on disk.

    fanout.py "review src/deck.py for bugs"
    fanout.py --models glm,minimax,flint "which of these two designs is simpler?"
    fanout.py --check
    fanout.py --file SKILL.md "what is underspecified here?"

Each worker is a real OpenCode subagent (`opencode run --agent free-…`), so it
gets its own model, its own context, and read-only permissions. Answers are
written as <out>/<agent>.md plus <out>/summary.json, and only a table comes back
to the caller's context.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

AGENTS = Path(__file__).resolve().parent.parent / "agents"
DEFAULT_OUT = Path("/tmp/opencode/free-swarm")
PROBE = "Reply with exactly one word: READY"


@dataclass
class Worker:
    name: str
    model: str


@dataclass
class Result:
    worker: Worker
    ok: bool = False
    seconds: float = 0.0
    text: str = ""
    error: str = ""
    tokens: int = 0


def roster() -> list[Worker]:
    workers = []
    for path in sorted(AGENTS.glob("free-*.md")):
        text = path.read_text()
        head = text.split("---")[1] if "---" in text else ""
        match = re.search(r"^model:\s*(\S+)\s*$", head, re.M)
        if match:
            workers.append(Worker(path.stem, match.group(1)))
    return workers


def selected(spec: str | None, workers: list[Worker]) -> list[Worker]:
    if not spec:
        return workers
    wanted = {part.strip().removeprefix("free-").lower() for part in spec.split(",") if part.strip()}
    chosen = [w for w in workers if w.name.removeprefix("free-").lower() in wanted or w.name.lower() in wanted]
    unknown = wanted - {w.name.removeprefix("free-").lower() for w in chosen}
    if unknown:
        raise SystemExit(f"unknown model(s): {', '.join(sorted(unknown))}\navailable: "
                         + ", ".join(w.name.removeprefix("free-") for w in workers))
    return chosen


def run(worker: Worker, prompt: str, files: list[str], timeout: int) -> Result:
    cmd = ["opencode", "run", "--agent", worker.name, "--format", "json"]
    for path in files:
        cmd += ["--file", path]
    cmd.append(prompt)
    started = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Result(worker, error=f"timeout after {timeout}s", seconds=time.perf_counter() - started)

    result = Result(worker, seconds=time.perf_counter() - started)
    chunks = []
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        part = event.get("part") or {}
        if kind == "text":
            chunks.append(part.get("text", ""))
        elif kind == "step_finish":
            result.tokens += int((part.get("usage") or {}).get("output") or 0)
        elif kind == "error":
            err = event.get("error") or {}
            result.error = f"{err.get('type', 'error')}: {err.get('message', '')}".strip()
            if err.get("status"):
                result.error += f" (HTTP {err['status']})"
    result.text = "".join(chunks).strip()
    result.ok = bool(result.text) and proc.returncode == 0 and not result.error
    if not result.error and proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        result.error = tail[-1][:200] if tail else f"exit {proc.returncode}"
    return result


def probe(workers: list[Worker], timeout: int) -> int:
    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        futures = {pool.submit(run, w, PROBE, [], timeout): w for w in workers}
        results = [f.result() for f in futures]
    failures = 0
    for res in results:
        state = "up" if res.ok else "down"
        body = (res.text or res.error).replace("\n", " ")[:48]
        if not res.ok:
            failures += 1
        print(f"  {res.worker.name:18} {res.worker.model:38} {state:4} {res.seconds:5.1f}s  {body!r}")
    print(f"  {len(results) - failures}/{len(results)} answering")
    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prompt", nargs="?", help="task sent verbatim to every worker")
    parser.add_argument("--models", help="comma-separated short names (glm,minimax,flint); default all")
    parser.add_argument("--out", type=Path, help="directory for answers (default /tmp/opencode/free-swarm/<time>)")
    parser.add_argument("--file", action="append", default=[], help="attach a file to every worker (repeatable)")
    parser.add_argument("--timeout", type=int, default=300, help="per-worker timeout in seconds")
    parser.add_argument("--check", action="store_true", help="probe every agent with a one-word prompt")
    parser.add_argument("--strict", action="store_true", help="exit 1 unless every worker answered")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args()

    workers = roster()
    if not workers:
        print(f"no agents found in {AGENTS}", file=sys.stderr)
        return 1
    try:
        workers = selected(args.models, workers)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.check:
        return probe(workers, args.timeout)
    if not args.prompt:
        parser.error("a prompt is required unless --check")

    out = args.out or (DEFAULT_OUT / time.strftime("%Y%m%dT%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        futures = [pool.submit(run, w, args.prompt, args.file, args.timeout) for w in workers]
        results = [f.result() for f in futures]

    rows = []
    for res in results:
        (out / f"{res.worker.name}.md").write_text(
            f"# {res.worker.name}\n\n"
            f"- model: `{res.worker.model}`\n"
            f"- status: {'ok' if res.ok else res.error or 'empty'}\n"
            f"- seconds: {res.seconds:.1f}\n\n"
            f"{res.text or '_no answer_'}\n"
        )
        rows.append({
            "agent": res.worker.name,
            "model": res.worker.model,
            "ok": res.ok,
            "seconds": round(res.seconds, 1),
            "chars": len(res.text),
            "output_tokens": res.tokens,
            "error": res.error,
        })
    (out / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            mark = "ok  " if row["ok"] else "fail"
            detail = f"{row['chars']} chars" if row["ok"] else row["error"][:60]
            print(f"  {row['agent']:18} {mark} {row['seconds']:5.1f}s  {detail}")
        print(f"  answers in {out}")
    return 0 if (all(r["ok"] for r in rows) if args.strict else any(r["ok"] for r in rows)) else 1


if __name__ == "__main__":
    sys.exit(main())
