#!/usr/bin/env python3
"""Multi-step evaluation: shelf vs sequential gateway vs one code-exec plan.

Every task in ``multistep_tasks.json`` is one realistic four-step workflow
(discover a tool by intent, fetch that skill's tool rows, filter them in
memory, compose a bounded projection, emit it). This runner executes the SAME
task set three ways on identical inputs:

  A  shelf      sequential frontmatter reads + CLI tool calls (one model
                decision per step: choose from the shelf, read the body, call
                the tool, emit).
  B  gateway    sequential meta-tool calls: search -> describe -> tools/fetch
                -> emit, one model decision per call.
  C  plan       ONE ``omnicli exec`` JavaScript plan that discovers, composes
                and emits in a single turn; bulky rows stay in the VM.

For each arm and each task we report five metrics:

  model_turns   number of sequential model decisions the protocol requires.
  tokens_in     tokens of every artifact the model must READ (contracts plus
                returned data) under the stated context model.
  tokens_out    tokens of every artifact the model must WRITE (tool calls /
                plan code plus the final bounded answer).
  wall_time_ms  real elapsed time of the I/O the arm performs (file reads and
                CLI/exec subprocesses), measured with perf_counter.
  correctness   the arm's bounded result equals the task's expected_result.

HONESTY — what is measured vs simulated (also emitted in the JSON report under
``measurement_model`` and written up in docs/multistep-eval.md):

  MEASURED (grounded in real execution):
    * wall_time_ms      real perf_counter around actual file reads and
                        subprocess calls.
    * correctness       real comparison of the emitted result to the task's
                        snapshot expected_result.
    * tokens_in/out     real tokenization (local Qwen3.5 tokenizer when the
                        omnicli venv is available, otherwise a documented
                        deterministic chars/4 fallback) of the real artifacts
                        each arm loads or writes. The token COUNTS are real;
                        the choice of which artifacts count as "in context" is
                        the stated context model below.

  SIMULATED / MODELED (no live model call is made):
    * model_turns       derived deterministically from the protocol: A=4,
                        B=4, C=1 (see TURNS_PER_ARM). A live model might use a
                        different number; no model is called here.
    * gateway_contract  a fixed textual stand-in for the meta-tool surface the
                        harness shows the model in arms B and C (identical in
                        both). It is a modeled constant, not scraped output.
    * call_text         the CLI command string a model would write for each
                        tool invocation in arms A and B, modeled as text.
    * token fallback    if the local tokenizer cannot be loaded, token counts
                        use ``round(len(text)/4)`` (min 1); the report records
                        which mode was used.

This is a NEW eval. It never reads, edits, or gates the committed
golden/fresh/paraphrase routing sets, gate floors, aliases, or BM25/fusion/
rerank code.

Usage:
    python3 orchestration/omnicli/tests/multistep_eval.py
    python3 orchestration/omnicli/tests/multistep_eval.py --json
    python3 orchestration/omnicli/tests/multistep_eval.py --out PATH
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
REPO_ROOT = HERE.parent.parent.parent
OMNICLI = SKILL_ROOT / "omnicli.py"
TASKS_FILE = HERE / "multistep_tasks.json"
VENV_PYTHON = SKILL_ROOT / ".venv" / "bin" / "python"
# Worktrees do not carry a .venv, so also try the canonical checkout's venv
# (the machine's documented source of truth for the local tokenizer).
VENV_PYTHON_CANDIDATES = [
    VENV_PYTHON,
    Path.home() / "src" / "my-agent-skills" / "orchestration" / "omnicli" / ".venv" / "bin" / "python",
]
DEFAULT_OUT = Path.home() / ".local" / "share" / "omnicli" / "multistep-eval" / "report.json"

ARMS = ("shelf", "gateway", "plan")

# Deterministic turn model. A live model is not called; these are the number
# of sequential model decisions each protocol structurally requires.
TURNS_PER_ARM = {"shelf": 4, "gateway": 4, "plan": 1}

# Modeled, fixed gateway tool surface shown to the model in arms B and C.
# Identical in both arms so the only difference between them is call count.
GATEWAY_CONTRACT = (
    "omnicli search <intent> --json  -> ranked skills by intent\n"
    "omnicli describe <tool|skill> --json  -> one contract on demand\n"
    "omnicli tools <skill> --json  -> that skill's tool rows\n"
    "omnicli exec <plan.mjs>  -> one sandboxed code plan (result <= 8 KB)\n"
)

# Context model: which labeled artifacts count as tokens_in / tokens_out for
# each arm. Labels map to strings collected in each arm's ``artifacts`` dict.
CONTEXT_MODEL = {
    "shelf": {
        "tokens_in": ["shelf_frontmatter", "skill_body", "tools_json"],
        "tokens_out": ["call_text", "emit_json"],
        "rationale": (
            "A shelf harness preloads every skill frontmatter; the model reads "
            "the chosen body and one tool result, writes one tool call, then "
            "the bounded answer."
        ),
    },
    "gateway": {
        "tokens_in": ["gateway_contract", "search_json", "describe_json", "tools_json"],
        "tokens_out": ["call_text", "emit_json"],
        "rationale": (
            "The model sees the fixed meta-tool contract, then each returned "
            "(bounded) result re-enters context; it writes three tool calls "
            "then the bounded answer."
        ),
    },
    "plan": {
        "tokens_in": ["gateway_contract", "result_json"],
        "tokens_out": ["plan_code"],
        "rationale": (
            "Only the single exec contract is on the tool surface. Discovery, "
            "filtering and composition happen inside the VM; only the plan "
            "the model writes and the one bounded result cross the boundary."
        ),
    },
}


# ---------------------------------------------------------------------------
# deterministic helpers
# ---------------------------------------------------------------------------
def task_checksum(obj) -> str:
    """SHA256 of the canonical task set; identical for every arm by design."""
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_cli(args: list[str], timeout: float = 180.0) -> tuple[str, str, int]:
    cmd = [sys.executable, str(OMNICLI), *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as exc:
        return "", f"timeout after {timeout}s: {exc}", 124


def parse_json(text: str):
    return json.loads(text)


def frontmatter(md: str) -> str:
    m = re.match(r"^---\s*\n(.*?)\n---", md, re.DOTALL)
    return m.group(1) if m else ""


def body(md: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", md, flags=re.DOTALL)


def project(rows: list[dict], grep: str, limit: int = 3) -> dict:
    """The shared, pure composition rule: filter -> dedupe -> sort -> take N."""
    rx = re.compile(grep, re.I)
    matched = [r for r in rows if rx.search(r.get("summary") or "")]
    ids = sorted({r["id"] for r in matched})[:limit]
    return {"matched": len(matched), "ids": ids}


# ---------------------------------------------------------------------------
# tokenization — real local tokenizer with a deterministic fallback
# ---------------------------------------------------------------------------
class Tokenizer:
    """Batch tokenizer. Mode is 'local' (Qwen3.5 via omnicli venv) or 'chars4'."""

    def __init__(self) -> None:
        self.mode = "chars4"
        self._counts: dict[str, int] = {}

    def count_many(self, texts: list[str]) -> list[int]:
        unique = list(dict.fromkeys(texts))
        local = self._count_local(unique)
        if local is not None and len(local) == len(unique):
            self.mode = "local"
            self._counts.update(zip(unique, local))
        else:
            self.mode = "chars4"
            for t in unique:
                self._counts[t] = max(1, round(len(t) / 4))
        return [self._counts[t] for t in texts]

    @staticmethod
    def _count_local(texts: list[str]) -> list[int] | None:
        """Tokenize in one subprocess using the omnicli venv's transformers."""
        payload = json.dumps(texts)
        code = (
            "import json,sys;from transformers import AutoTokenizer;"
            "t=AutoTokenizer.from_pretrained("
            "'/run/media/rodri/AI/models/perplexity-ai/pplx-decider-flash-v1.2');"
            "xs=json.load(sys.stdin);"
            "print(json.dumps([len(t(x,add_special_tokens=False)['input_ids']) for x in xs]))"
        )
        for py in VENV_PYTHON_CANDIDATES:
            if not py.is_file():
                continue
            try:
                p = subprocess.run(
                    [str(py), "-c", code], input=payload,
                    capture_output=True, text=True, timeout=180,
                )
                if p.returncode != 0:
                    continue
                out = json.loads(p.stdout)
                if isinstance(out, list):
                    return [int(x) for x in out]
            except Exception:
                continue
        return None


# ---------------------------------------------------------------------------
# arms — each returns a record with artifacts, timing, result and errors
# ---------------------------------------------------------------------------
def _blank(arm: str, task: dict, checksum: str) -> dict:
    return {
        "arm": arm,
        "task_id": task["id"],
        "task_checksum": checksum,
        "model_turns": TURNS_PER_ARM[arm],
        "artifacts": {},
        "result": None,
        "correct": False,
        "wall_time_ms": 0.0,
        "errors": [],
    }


def _finish(rec: dict, task: dict) -> dict:
    rec["correct"] = rec["result"] == task["expected_result"]
    return rec


def arm_shelf(task: dict, checksum: str, shelf: dict[str, str], paths: dict[str, Path]) -> dict:
    rec = _blank("shelf", task, checksum)
    t0 = time.perf_counter()
    # Step 1: the shelf -- every frontmatter preloaded (measurable real text).
    rec["artifacts"]["shelf_frontmatter"] = "\n".join(shelf.values())
    # Step 2: choose by name (simulated model pick) and read the body.
    skill = task["expected_skill"]
    md_path = paths.get(skill)
    if md_path is None:
        rec["errors"].append(f"shelf has no SKILL.md for {skill}")
        rec["wall_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return _finish(rec, task)
    rec["artifacts"]["skill_body"] = body(md_path.read_text(encoding="utf-8", errors="replace"))
    # Step 3/4: one tool call to fetch rows, then filter/compose/emit.
    out, err, rc = run_cli(["tools", skill, "--json"])
    if rc != 0:
        rec["errors"].append(f"tools {skill}: rc={rc} {err[:200]}")
        rec["wall_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return _finish(rec, task)
    rows = parse_json(out)
    rec["artifacts"]["tools_json"] = out
    rec["artifacts"]["call_text"] = f"omnicli tools {skill} --json"
    composed = project(rows, task["grep"])
    result = {"skill": skill, **composed}
    rec["result"] = result
    rec["artifacts"]["emit_json"] = json.dumps(result, sort_keys=True, separators=(",", ":"))
    rec["wall_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return _finish(rec, task)


def arm_gateway(task: dict, checksum: str) -> dict:
    rec = _blank("gateway", task, checksum)
    t0 = time.perf_counter()
    rec["artifacts"]["gateway_contract"] = GATEWAY_CONTRACT
    # Step 1: search by intent.
    so, se, src = run_cli(["search", task["intent"], "--json"])
    if src != 0:
        rec["errors"].append(f"search: rc={src} {se[:200]}")
        rec["wall_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return _finish(rec, task)
    rec["artifacts"]["search_json"] = so
    hits = parse_json(so).get("results", [])
    skill = hits[0]["skill"] if hits else None
    if not skill:
        rec["errors"].append("search returned no results")
        rec["wall_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return _finish(rec, task)
    # Step 2: fetch exactly one contract on demand.
    do, de, drc = run_cli(["describe", skill, "--json"])
    if drc != 0:
        rec["errors"].append(f"describe: rc={drc} {de[:200]}")
        rec["wall_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return _finish(rec, task)
    rec["artifacts"]["describe_json"] = do
    # Step 3: fetch rows, filter/compose/emit.
    to, te, trc = run_cli(["tools", skill, "--json"])
    if trc != 0:
        rec["errors"].append(f"tools: rc={trc} {te[:200]}")
        rec["wall_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return _finish(rec, task)
    rec["artifacts"]["tools_json"] = to
    rec["artifacts"]["call_text"] = (
        f"omnicli search {task['intent']!r} --json; "
        f"omnicli describe {skill} --json; omnicli tools {skill} --json"
    )
    composed = project(parse_json(to), task["grep"])
    result = {"skill": skill, **composed}
    rec["result"] = result
    rec["artifacts"]["emit_json"] = json.dumps(result, sort_keys=True, separators=(",", ":"))
    rec["wall_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return _finish(rec, task)


def _plan_code(task: dict) -> str:
    return (
        'import { search, spec, emitResult } from "omnicli_tools";\n'
        f"const hits = await search({json.dumps(task['intent'])}, 3);\n"
        "const skill = hits[0]?.skill ?? null;\n"
        "const rows = skill ? spec({ skill }) : [];\n"
        f"const rx = new RegExp({json.dumps(task['grep'])}, 'i');\n"
        "const matched = rows.filter(r => rx.test(r.summary || ''));\n"
        "const ids = [...new Set(matched.map(r => r.id))].sort().slice(0, 3);\n"
        "emitResult({ skill, matched: matched.length, ids });\n"
    )


def arm_plan(task: dict, checksum: str) -> dict:
    rec = _blank("plan", task, checksum)
    t0 = time.perf_counter()
    rec["artifacts"]["gateway_contract"] = GATEWAY_CONTRACT
    code = _plan_code(task)
    rec["artifacts"]["plan_code"] = code
    out, err, rc = run_cli(["exec", "-c", code, "--json", "--sandbox", "none"])
    if rc != 0:
        rec["errors"].append(f"exec: rc={rc} {err[:200]}")
        rec["wall_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return _finish(rec, task)
    try:
        meta = parse_json(out)
    except Exception as exc:
        rec["errors"].append(f"exec json parse: {exc}")
        rec["wall_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return _finish(rec, task)
    result = meta.get("result")
    rec["result"] = result
    rec["artifacts"]["result_json"] = json.dumps(result, sort_keys=True, separators=(",", ":"))
    rec["wall_time_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return _finish(rec, task)


# ---------------------------------------------------------------------------
# shelf paths (real repo files, read at run time)
# ---------------------------------------------------------------------------
_SHELF_PATHS: dict[str, Path] | None = None


def shelf_paths() -> dict[str, Path]:
    global _SHELF_PATHS
    if _SHELF_PATHS is None:
        found: dict[str, Path] = {}
        for p in sorted(REPO_ROOT.rglob("SKILL.md")):
            if "archived" in p.parts or ".venv" in p.parts:
                continue
            md = p.read_text(encoding="utf-8", errors="replace")
            if not md.startswith("---"):
                continue
            name_m = re.search(r"^name:\s*(.+)$", frontmatter(md), re.MULTILINE)
            name = name_m.group(1).strip().strip("\"'") if name_m else p.parent.name
            found[name] = p
        _SHELF_PATHS = found
    return _SHELF_PATHS


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def evaluate() -> dict:
    data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    tasks = data["tasks"]
    checksum = task_checksum(data)

    paths = shelf_paths()
    shelf_text = {
        name: frontmatter(p.read_text(encoding="utf-8", errors="replace"))
        for name, p in paths.items()
    }

    records: list[dict] = []
    for task in tasks:
        records.append(arm_shelf(task, checksum, shelf_text, paths))
        records.append(arm_gateway(task, checksum))
        records.append(arm_plan(task, checksum))

    # One batched tokenization pass over every artifact string.
    tok = Tokenizer()
    all_texts = [text for r in records for text in r["artifacts"].values()]
    counts = tok.count_many(all_texts)
    it = iter(counts)
    for r in records:
        r["token_counts"] = {label: next(it) for label in r["artifacts"]}
        model = CONTEXT_MODEL[r["arm"]]
        r["tokens_in"] = sum(r["token_counts"].get(x, 0) for x in model["tokens_in"])
        r["tokens_out"] = sum(r["token_counts"].get(x, 0) for x in model["tokens_out"])

    # Aggregate per arm.
    per_arm: dict[str, dict] = {}
    for arm in ARMS:
        rows = [r for r in records if r["arm"] == arm]
        n = len(rows)
        per_arm[arm] = {
            "tasks": n,
            "model_turns_per_task": TURNS_PER_ARM[arm],
            "model_turns_total": sum(r["model_turns"] for r in rows),
            "tokens_in_total": sum(r["tokens_in"] for r in rows),
            "tokens_out_total": sum(r["tokens_out"] for r in rows),
            "tokens_in_mean": round(sum(r["tokens_in"] for r in rows) / n, 1),
            "tokens_out_mean": round(sum(r["tokens_out"] for r in rows) / n, 1),
            "wall_time_ms_total": round(sum(r["wall_time_ms"] for r in rows), 3),
            "wall_time_ms_mean": round(sum(r["wall_time_ms"] for r in rows) / n, 3),
            "correct": sum(r["correct"] for r in rows),
            "errors": sum(len(r["errors"]) for r in rows),
            "task_checksums": sorted({r["task_checksum"] for r in rows}),
        }

    checksums = {arm: per_arm[arm]["task_checksums"] for arm in ARMS}
    return {
        "schema": "multistep-eval-v1",
        "task_set": str(TASKS_FILE.relative_to(SKILL_ROOT)),
        "task_count": len(tasks),
        "task_checksum": checksum,
        "checksum_identical_across_arms": all(v == [checksum] for v in checksums.values()),
        "tokenizer_mode": tok.mode,
        "arms": list(ARMS),
        "per_arm": per_arm,
        "measurement_model": {
            "measured": [
                "wall_time_ms (perf_counter around real file reads and CLI/exec subprocesses)",
                "correctness (emitted result compared to the task's expected_result snapshot)",
                "tokens_in / tokens_out (real tokenization of the concrete artifacts each arm "
                "loads or writes; only the artifact-to-context mapping is modeled)",
            ],
            "simulated": [
                "model_turns: deterministic per protocol (A=4, B=4, C=1); no live model is called",
                "gateway_contract: fixed textual stand-in for the meta-tool surface shown to "
                "the model in arms B and C (identical in both); not scraped output",
                "call_text: the CLI command string a model would write for each tool call in "
                "arms A and B, modeled as text",
                "token fallback: if the local Qwen3.5 tokenizer is unavailable, token counts "
                "use round(len(text)/4) with a minimum of 1 (see tokenizer_mode)",
            ],
            "context_model": CONTEXT_MODEL,
        },
        "records": records,
    }


def print_summary(report: dict) -> None:
    print("=" * 78)
    print("  MULTI-STEP EVALUATION — shelf vs gateway vs one code-exec plan")
    print("=" * 78)
    print(f"  tasks: {report['task_count']}   checksum: {report['task_checksum'][:16]}…"
          f"   identical across arms: {report['checksum_identical_across_arms']}")
    print(f"  tokenizer: {report['tokenizer_mode']}")
    print("-" * 78)
    hdr = f"  {'arm':<9}{'turns/task':>11}{'tok-in/task':>13}{'tok-out/task':>14}{'ms/task':>10}{'correct':>10}"
    print(hdr)
    print("-" * 78)
    for arm in ARMS:
        a = report["per_arm"][arm]
        print(f"  {arm:<9}{a['model_turns_per_task']:>11}{a['tokens_in_mean']:>13}"
              f"{a['tokens_out_mean']:>14}{a['wall_time_ms_mean']:>10}"
              f"{str(a['correct']) + '/' + str(a['tasks']):>10}")
    print("-" * 78)
    errs = sum(a["errors"] for a in report["per_arm"].values())
    print(f"  execution errors: {errs}")
    sims = report["measurement_model"]["simulated"]
    print(f"  simulated quantities listed: {len(sims)} (see JSON 'measurement_model.simulated')")
    print("=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="print the full report JSON to stdout")
    ap.add_argument("--out", default=None, help=f"write report JSON here (default {DEFAULT_OUT})")
    args = ap.parse_args()

    report = evaluate()
    out = Path(args.out) if args.out else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_summary(report)
        print(f"  report: {out}")

    # Non-zero only on real execution failure, so the mechanical "arms run
    # without error" check is meaningful. Incorrectness is reported, not gated.
    bad = any(a["errors"] for a in report["per_arm"].values())
    return 1 if bad or not report["checksum_identical_across_arms"] else 0


if __name__ == "__main__":
    sys.exit(main())
