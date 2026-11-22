#!/usr/bin/env python3
"""Prove the one-tool describe flow with one real `omnicli exec` plan.

The plan gets a tool's exact schema from ``describe(toolId)`` at runtime — no
generated contract tree and no filesystem reads — invokes that tool with a raw
argv array, and ends with a bounded ``result()`` / emitResult. Discovery uses
no ranking service and no discovery tool: the catalog is the index and
``describe()`` supplies the one schema on demand.

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
OMNICLI = SKILL / "omnicli.py"

sys.path.insert(0, str(SKILL))
from catalog import builder  # noqa: E402

TARGET_TOOL = "guard-hooks/scripts/guard:check"  # deterministic, offline tool
CHECK_COMMAND = "echo hello"
BOUND = 120
PROOF = "describe-schema"


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
    """One plan: describe(toolId) -> raw-argv invoke -> one bounded result."""
    return f'''import {{ describe, invoke, result }} from "omnicli_tools";

const TOOL = {json.dumps(TARGET_TOOL)};
const COMMAND = {json.dumps(CHECK_COMMAND)};
const BOUND = {BOUND};

// The tool schema comes from describe() at runtime: one exact contract, no
// ranking call, no discovery tool, and no generated filesystem contract tree.
const schema = await describe(TOOL);
if (!schema || schema.id !== TOOL) throw new Error("describe returned wrong tool: " + (schema && schema.id));
const contract = schema.contract || {{}};
if (!contract.inputSchema) throw new Error("describe returned no input schema");

// Exactly one catalogued tool call, with a raw argv array.
const envelope = await invoke(TOOL, [COMMAND]);
const output = String(envelope.output || "").slice(0, BOUND);

result({{
  ok: envelope.exit_code === 0 && Boolean(contract.inputSchema),
  tool: TOOL,
  proof: {json.dumps(PROOF)},
  data: {{
    described: schema.id,
    summary: String(schema.summary || "").slice(0, BOUND),
    hasSchema: Boolean(contract.inputSchema),
    usage: String(contract.usage || "").slice(0, BOUND),
    exitCode: envelope.exit_code,
    output,
  }},
}});
'''


def static_proof(source: str) -> None:
    """Prove, in the plan source, that no ranking call is possible."""
    _require(re.search(r"\bsearch\s*\(", source) is None,
             "plan source contains a search call")
    _require(source.count("await describe(") == 1,
             "plan must make exactly one describe call")
    _require(source.count("await invoke(") == 1,
             "plan must make exactly one invoke call")
    _require(source.count("result({") == 1,
             "plan must emit exactly one result")


def run_plan(tmp: Path, db: Path) -> tuple[dict, str]:
    plan = tmp / "plan.mjs"
    source = plan_source()
    plan.write_text(source, encoding="utf-8")
    static_proof(source)

    # Use the installed `omnicli` launcher (host-visible inside the sandbox).
    # Its catalog is the isolated copy via OMNICLI_DB; HOME is isolated too.
    env = os.environ.copy()
    env.pop("OMNICLI_DB_RO", None)
    env["HOME"] = str(tmp)
    env["OMNICLI_DB"] = str(db)
    env["OMNICLI_SESSION"] = "exec-only-flow-test"
    env["OMNICLI_USER_TRACE"] = str(tmp / "trace.jsonl")

    proc = subprocess.run(
        [sys.executable, str(OMNICLI), "exec", str(plan), "--json",
         "--workspace", str(tmp), "--sandbox", "strict", "--max-calls", "10"],
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
    _require(report.get("sandbox") == "strict", "plan did not run in strict sandbox")
    result = report.get("result")
    _require(isinstance(result, dict), "no bounded emitResult recorded")
    _require(result.get("ok") is True, f"result not ok: {result}")
    _require(result.get("tool") == TARGET_TOOL,
             f"wrong discovered tool: {result.get('tool')}")
    _require(result.get("proof") == PROOF, "wrong proof marker")

    data = result.get("data") or {}
    _require(data.get("described") == TARGET_TOOL, "described tool mismatch")
    _require(data.get("hasSchema") is True, "describe returned no input schema")
    _require(data.get("exitCode") == 0, f"invocation failed: {data.get('exitCode')}")
    for key in ("summary", "usage", "output"):
        _require(len(str(data.get(key, ""))) <= BOUND, f"{key} is not bounded")

    # Dynamic proof: the trace records every real tool call. Zero ranking
    # calls, exactly one describe() and one invoke(), both for the target tool.
    trace = tmp / ".omnicli_trace.jsonl"
    _require(trace.is_file(), "no exec trace recorded")
    rows = [json.loads(line) for line in trace.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    calls = [row for row in rows if row.get("kind") in (None, "call")]
    search_calls = [row for row in calls if row.get("call") == "search"]
    _require(len(search_calls) == 0,
             f"discovery-tool calls found in trace: {search_calls[:3]}")
    describes = [row for row in calls if row.get("call") == "describe"]
    _require(len(describes) == 1 and describes[0].get("tool") == TARGET_TOOL,
             f"expected exactly one describe call, got: "
             f"{[(r.get('call'), r.get('tool')) for r in calls]}")
    invokes = [row for row in calls if row.get("call") == "invoke"]
    _require(len(invokes) == 1 and invokes[0].get("tool") == TARGET_TOOL,
             f"expected exactly one invoke call, got: "
             f"{[(r.get('call'), r.get('tool')) for r in calls]}")
    _require(len(calls) == 2,
             f"expected describe + invoke calls only, got: "
             f"{[row.get('call') for row in calls]}")
    _require(report.get("tool_calls") == len(calls),
             "report tool_calls disagrees with trace")
    _require(report.get("bridge_denied") == [],
             f"bridge denied calls: {report.get('bridge_denied')}")

    record = {
        "flow": "exec-only-describe-schema",
        "assertion": "zero-search-calls",
        "search_calls": len(search_calls),
        "describe_calls": len(describes),
        "tool_calls": len(calls),
        "tool_call_verbs": [row.get("call") for row in calls],
        "passed": True,
    }
    (tmp / "zero_search_assertion.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main() -> int:
    try:
        _require(OMNICLI.is_file(), f"missing {OMNICLI}")
        with tempfile.TemporaryDirectory(prefix="omnicli-exec-only-") as name:
            tmp = Path(name)
            db = isolate_catalog(tmp)
            report, _ = run_plan(tmp, db)
            record = assert_flow(report, tmp)
        print(f"PASS — one exec plan, describe schema, "
              f"{record['tool_calls']} tool calls (1 describe + 1 invoke), "
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
