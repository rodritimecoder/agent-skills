#!/usr/bin/env python3
"""Prove the one-tool contract-tree flow with one real `omnicli exec` plan.

The plan discovers a tool by listing and reading the generated ``contracts/``
tree (detail levels: name, name+description, full), invokes that tool, and ends
with a bounded ``result()`` / emitResult. Discovery uses no ranking service and
no discovery tool: the tree is the index and ``contract_fs.mjs`` ``ls`` / ``read``
are the whole discovery surface.

This driver runs the plan against an isolated catalog copy and HOME so shared
state (bindings, traces, session state, catalog) is untouched, then proves from
the exec trace that ZERO calls were made to the discovery tool. The proof is
recorded as JSON in the workspace and printed as a one-line verdict.

Exit codes: 0 pass, 1 assertion failed, 2 fatal.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
REPO = SKILL.parent.parent
OMNICLI = SKILL / "omnicli.py"
CONTRACT_FS = SKILL / "catalog" / "contract_fs.mjs"
CONTRACTS = REPO / "contracts"

sys.path.insert(0, str(SKILL))
from catalog import builder  # noqa: E402

TARGET_SKILL = "guard-hooks"          # deterministic, offline skill
TARGET_FILE = "scripts_guard_check"  # contracts/<skill>/<file>.md
TARGET_TOOL = "guard-hooks/scripts/guard:check"
CHECK_COMMAND = "echo hello"
DETAILS = ["name", "name+description", "full"]
BOUND = 120


class FlowFailure(AssertionError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FlowFailure(message)


def isolate_catalog(tmp: Path) -> Path:
    """Copy the built catalog into ``tmp`` and checkpoint it there.

    Nothing is written to the shared catalog or shared bindings directory: the
    exec subprocess gets ``OMNICLI_DB=<copy>`` and ``HOME=<tmp>``.
    """
    db = tmp / "catalog.db"
    source = builder.db_path()
    if source.is_file():
        shutil.copy2(source, db)
        for suffix in ("-wal", "-shm"):
            side = Path(str(source) + suffix)
            if side.is_file():
                shutil.copy2(side, Path(str(db) + suffix))
        con = sqlite3.connect(str(db))
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            count = con.execute("SELECT count(*) FROM tools").fetchone()[0]
        finally:
            con.close()
    else:
        count = 0

    if not count:
        con = builder.connect(db)
        try:
            builder.ensure_built(con, with_contracts=True, progress=False)
            count = con.execute("SELECT count(*) FROM tools").fetchone()[0]
        finally:
            con.close()
    _require(count > 0, "isolated catalog has no tools")
    return db


def plan_source() -> str:
    """One plan: tree discovery at three detail levels -> invoke -> result."""
    # Static import: the VM runner links and evaluates static dependencies,
    # so the sandbox-only contract_fs helper is ready before the plan runs.
    contract_fs_url = CONTRACT_FS.resolve().as_uri()
    return f'''import {{ invoke, result }} from "omnicli_tools";
import {{ ls, read }} from "{contract_fs_url}";

// Discovery reads the generated contract tree only. No ranking, no discovery
// tool call: the filesystem tree is the index and ls/read are the whole surface.
const DETAILS = {json.dumps(DETAILS)};
const SKILL_DIR = {json.dumps(TARGET_SKILL)};
const FILE = {json.dumps(TARGET_FILE)};
const COMMAND = {json.dumps(CHECK_COMMAND)};
const BOUND = {BOUND};

const skills = ls();                       // detail level: tree root
const files = ls(SKILL_DIR);               // one skill's tool files
const file = files.find((n) => n === FILE);
if (!file) throw new Error("contract missing in tree: " + SKILL_DIR + "/" + FILE);
const rel = SKILL_DIR + "/" + file;

const name = read(rel, DETAILS[0]);              // "name"
const brief = read(rel, DETAILS[1]);             // "name+description"
const full = read(rel, DETAILS[2]);              // "full"
if (name !== brief.name || name !== full.name) throw new Error("name mismatch across detail levels");

const envelope = await invoke(name, [COMMAND]);  // the one real tool call
const output = String(envelope.output || "").slice(0, BOUND);

result({{
  ok: envelope.exit_code === 0 && Boolean(full.inputSchema),
  tool: name,
  proof: "contract-tree",
  data: {{
    skillsListed: skills.length,
    detailLevels: DETAILS,
    discovered: name,
    description: String(brief.description || "").slice(0, BOUND),
    hasSchema: Boolean(full.inputSchema),
    example: String(full.example || "").slice(0, BOUND),
    exitCode: envelope.exit_code,
    output,
    ids: [name].slice(0, 3),
  }},
}});
'''


def run_plan(tmp: Path, db: Path) -> tuple[dict, str]:
    plan = tmp / "plan.mjs"
    source = plan_source()
    plan.write_text(source, encoding="utf-8")

    # Static proof: the plan never names the discovery tool as a call.
    _require(re.search(r"\bsearch\s*\(", source) is None,
             "plan source contains a search call")

    # Use the installed `omnicli` launcher (host-visible inside the sandbox).
    # Its catalog is the isolated copy via OMNICLI_DB; HOME is isolated too.
    env = os.environ.copy()
    env.pop("OMNICLI_DB_RO", None)
    env["HOME"] = str(tmp)
    env["OMNICLI_DB"] = str(db)
    env["OMNICLI_SESSION"] = "exec-only-flow-test"
    env["OMNICLI_USER_TRACE"] = str(tmp / "trace.jsonl")
    env["OMNICLI_CONTRACT_FS"] = str(CONTRACT_FS)
    env["OMNICLI_CONTRACTS_ROOT"] = str(CONTRACTS)

    proc = subprocess.run(
        [sys.executable, str(OMNICLI), "exec", str(plan), "--json",
         "--workspace", str(tmp), "--sandbox", "write", "--max-calls", "10"],
        capture_output=True, text=True, timeout=300, cwd=str(tmp), env=env,
    )
    try:
        report = json.loads(proc.stdout)
    except ValueError as exc:
        raise FlowFailure(f"exec produced no JSON report (rc={proc.returncode}): "
                          f"{proc.stderr[-600:]}") from exc
    return report, source


def assert_flow(report: dict, tmp: Path) -> dict:
    _require(report.get("exit_code") == 0,
             f"exec failed: {str(report.get('stderr'))[-600:]}")
    result = report.get("result")
    _require(isinstance(result, dict), "no bounded emitResult recorded")
    _require(result.get("ok") is True, f"result not ok: {result}")
    _require(result.get("tool") == TARGET_TOOL,
             f"wrong discovered tool: {result.get('tool')}")
    _require(result.get("proof") == "contract-tree", "wrong proof marker")

    data = result.get("data") or {}
    _require(data.get("detailLevels") == DETAILS,
             f"detail levels not all exercised: {data.get('detailLevels')}")
    _require(data.get("discovered") == TARGET_TOOL, "discovered name mismatch")
    _require(data.get("hasSchema") is True, "full contract had no input schema")
    _require(data.get("exitCode") == 0, f"invocation failed: {data.get('exitCode')}")
    for key in ("description", "example", "output"):
        _require(len(str(data.get(key, ""))) <= BOUND, f"{key} is not bounded")
    _require(len(data.get("ids") or []) <= 3, "ids are not bounded")

    # Dynamic proof: parse the exec trace written by the bindings. One call,
    # and its verb is invoke — never the discovery tool.
    trace = tmp / ".omnicli_trace.jsonl"
    _require(trace.is_file(), "no exec trace recorded")
    rows = [json.loads(line) for line in trace.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    calls = [row for row in rows if row.get("kind") in (None, "call")]
    search_calls = [row for row in calls if row.get("call") == "search"]
    _require(len(search_calls) == 0,
             f"discovery-tool calls found in trace: {search_calls[:3]}")
    _require(len(calls) == 1 and calls[0].get("call") == "invoke",
             f"expected exactly one invoke call, got: "
             f"{[row.get('call') for row in calls]}")
    _require(report.get("tool_calls") == len(calls),
             "report tool_calls disagrees with trace")

    record = {
        "flow": "exec-only-contract-tree",
        "assertion": "zero-search-calls",
        "search_calls": len(search_calls),
        "tool_calls": len(calls),
        "tool_call_verbs": [row.get("call") for row in calls],
        "passed": True,
    }
    (tmp / "zero_search_assertion.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main() -> int:
    try:
        _require(CONTRACT_FS.is_file(), f"missing {CONTRACT_FS}")
        _require((CONTRACTS / "INDEX.md").is_file(),
                 f"contract tree missing: {CONTRACTS / 'INDEX.md'}")
        with tempfile.TemporaryDirectory(prefix="omnicli-exec-only-") as name:
            tmp = Path(name)
            db = isolate_catalog(tmp)
            report, _ = run_plan(tmp, db)
            record = assert_flow(report, tmp)
        print(f"PASS — one exec plan, {record['tool_calls']} invoke call, "
              f"{record['search_calls']} search calls; "
              f"zero-search-call assertion recorded: PASS")
        print("assertion record: " + json.dumps(record, sort_keys=True))
        return 0
    except FlowFailure as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # fatal / environment problem
        print(f"FATAL — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
