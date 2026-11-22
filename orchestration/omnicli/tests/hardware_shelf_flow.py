#!/usr/bin/env python3
"""Shelf-level proof: three hardware skills, one strict plan each.

For llama-build, model-layer and audiocpp this driver runs one ``omnicli exec``
plan (strict sandbox) that walks all three Agent Skills discovery levels through
the REAL skills window (``omnicli_skills``: lsSkills -> readSkill ->
readResource), invokes exactly one catalogued tool with a raw argv array, and
ends in one bounded ``result()``. The plan never calls ``search()``.

Each plan's source is checked statically (no search call, real window imports
and helpers, exactly one invoke / one result, no fixture fallback). Each exec
trace is checked dynamically (zero search calls, exactly one invoke of the
expected tool with the expected argv, no denied bridge calls). The result
payload must stay under the 8192-byte exec reply cap.

Catalog and HOME are isolated per skill: no shared bindings, traces, session
state or catalog rows are touched. Exit codes: 0 pass, 1 assertion failed,
2 fatal.
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
SKILL_FS = SKILL / "catalog" / "skill_fs.mjs"

sys.path.insert(0, str(SKILL))
from catalog import builder  # noqa: E402

# Each entry drives one plan. Markers are stable strings from the real skill
# files; the tool / argv pair is one that exits 0 with a `--help` probe.
SKILLS = [
    {
        "name": "llama-build",
        "desc_marker": "upstream llama.cpp checkout",     # L1 frontmatter
        "body_marker": "## Available scripts",            # L2 SKILL.md body
        "resource": "CONTEXT.md",                         # L3 reference
        "resource_marker": "llama.cpp Builds & Forks",
        "tool": "llama-build/scripts/llama_build",
        "argv": ["--json", "--help"],
    },
    {
        "name": "model-layer",
        "desc_marker": "model layer of this machine",
        "body_marker": "## Available scripts",
        "resource": "config/port_registry.json",
        "resource_marker": "total_vram_budget_mb",
        "tool": "model-layer/cli",
        "argv": ["--help"],
    },
    {
        "name": "audiocpp",
        "desc_marker": "Local audio intelligence",
        "body_marker": "## Available scripts",
        "resource": "CONTEXT.md",
        "resource_marker": "## Inputs",
        "tool": "audiocpp/scripts/audiocpp_cli",
        "argv": ["--help"],
    },
]

BOUND = 180                                 # per-field synthesis bound
MAX_RESULT_BYTES = 8 * 1024                 # the exec reply cap
PROOF = "hardware-shelf-three-skill-bridge"
LEVELS = ["L1", "L2", "L3"]


class FlowFailure(AssertionError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FlowFailure(message)


def isolate_catalog(tmp: Path) -> Path:
    """Copy the built catalog into ``tmp`` so shared state is never written."""
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


def plan_source(spec: dict) -> str:
    """One plan: real-window L1 -> L2 -> L3 -> raw-argv invoke -> result."""
    # Static imports only: the synthetic `omnicli_skills` module is the real
    # read-only skills window, and `omnicli_tools` supplies invoke/result.
    # No search(), no ranking service, no fixture fallback.
    return f'''import {{ invoke, result }} from "omnicli_tools";
import {{ lsSkills, readSkill, readResource }} from "omnicli_skills";

const TARGET = {json.dumps(spec["name"])};
const RESOURCE = {json.dumps(spec["resource"])};
const TOOL = {json.dumps(spec["tool"])};
const ARGV = {json.dumps(spec["argv"])};
const BOUND = {BOUND};

// The imported helpers MUST be the same functions the VM exposes as globals;
// otherwise this plan is not using the real skills bridge.
const realBridge = typeof globalThis.lsSkills === "function"
  && globalThis.lsSkills === lsSkills
  && globalThis.readSkill === readSkill
  && globalThis.readResource === readResource;
if (!realBridge) throw new Error("real skills bridge not in use");

// L1 — name + description for every skill, from the generated index.
const listed = lsSkills();
const entry = listed.find((s) => s.name === TARGET);
if (!entry) throw new Error("L1: skill not listed: " + TARGET);
const description = String(entry.description || "");
if (!description.includes({json.dumps(spec["desc_marker"])})) throw new Error("L1: description marker missing");

// L2 — the complete SKILL.md body for the chosen skill.
const body = String(readSkill(TARGET));
if (!body.includes({json.dumps(spec["body_marker"])})) throw new Error("L2: SKILL.md body marker missing");

// L3 — one reference file beneath the skill root, by relative path.
const resource = String(readResource(TARGET, RESOURCE));
if (!resource.includes({json.dumps(spec["resource_marker"])})) throw new Error("L3: resource marker missing");

// Exactly one catalogued tool call, with a raw argv array.
const envelope = await invoke(TOOL, ARGV);

result({{
  ok: envelope.exit_code === 0,
  tool: TOOL,
  proof: {json.dumps(PROOF)},
  data: {{
    bridge: realBridge,
    levels: ["L1", "L2", "L3"],
    skillsListed: listed.length,
    skill: entry.name,
    description: description.slice(0, BOUND),
    bodyMarker: body.includes({json.dumps(spec["body_marker"])}),
    bodyBytes: body.length,
    resource: RESOURCE,
    resourceMarker: resource.includes({json.dumps(spec["resource_marker"])}),
    resourceBytes: resource.length,
    argv: ARGV,
    exitCode: envelope.exit_code,
    output: String(envelope.output || "").slice(0, BOUND),
  }},
}});
'''


def static_proof(source: str, name: str) -> None:
    """Prove in the plan source that no search call is possible."""
    _require(re.search(r"\bsearch\s*\(", source) is None,
             f"{name}: plan source contains a search() call")
    for helper in ("lsSkills", "readSkill", "readResource"):
        _require(helper in source, f"{name}: plan source never uses {helper}")
    _require('from "omnicli_skills"' in source,
             f"{name}: plan never imports the real skills window")
    _require("globalThis.lsSkills" in source,
             f"{name}: plan never checks the real window helpers")
    _require("fixture" not in source,
             f"{name}: plan contains a fixture fallback")
    _require(source.count("await invoke(") == 1,
             f"{name}: plan must make exactly one invoke call")
    _require(source.count("result({") == 1,
             f"{name}: plan must emit exactly one result")


def run_plan(work: Path, db: Path, source: str, name: str) -> dict:
    plan = work / "plan.mjs"
    plan.write_text(source, encoding="utf-8")

    env = os.environ.copy()
    env.pop("OMNICLI_DB_RO", None)
    env["HOME"] = str(work)
    env["OMNICLI_DB"] = str(db)
    env["OMNICLI_SESSION"] = "hardware-shelf-flow-test"
    env["OMNICLI_USER_TRACE"] = str(work / "user_trace.jsonl")

    proc = subprocess.run(
        [sys.executable, str(OMNICLI), "exec", str(plan), "--json",
         "--workspace", str(work), "--sandbox", "strict", "--max-calls", "10"],
        capture_output=True, text=True, timeout=300, cwd=str(work), env=env,
    )
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise FlowFailure(
            f"{name}: exec produced no JSON report (rc={proc.returncode}): "
            f"{proc.stderr[-800:]}"
        ) from exc


def assert_plan(report: dict, work: Path, spec: dict) -> dict:
    """Prove the three levels, zero search calls and a bounded result."""
    name = spec["name"]
    _require(report.get("exit_code") == 0,
             f"{name}: exec failed: {str(report.get('stderr'))[-800:]}")
    _require(report.get("sandbox") == "strict", f"{name}: not in strict sandbox")

    result = report.get("result")
    _require(isinstance(result, dict), f"{name}: no bounded emitResult recorded")
    _require(result.get("ok") is True, f"{name}: result not ok: {result}")
    _require(result.get("proof") == PROOF, f"{name}: wrong proof marker")
    _require(result.get("tool") == spec["tool"], f"{name}: wrong invoked tool")

    data = result.get("data") or {}
    _require(data.get("bridge") is True, f"{name}: real skills bridge not used")
    _require(data.get("levels") == LEVELS, f"{name}: not all three levels exercised")
    _require(data.get("skillsListed", 0) > 0, f"{name}: L1 empty skills index")
    _require(data.get("skill") == name, f"{name}: L1 wrong skill selected")
    _require(spec["desc_marker"] in str(data.get("description", "")),
             f"{name}: L1 description not surfaced")
    _require(data.get("bodyMarker") is True and data.get("bodyBytes", 0) > 0,
             f"{name}: L2 SKILL.md body not read")
    _require(data.get("resource") == spec["resource"]
             and data.get("resourceMarker") is True
             and data.get("resourceBytes", 0) > 0,
             f"{name}: L3 reference file not read")
    _require(data.get("argv") == spec["argv"],
             f"{name}: tool was not invoked with the raw argv array")
    _require(data.get("exitCode") == 0,
             f"{name}: tool invocation failed: {data.get('exitCode')}")

    # ONE bounded result: both field slices and the whole payload stay under
    # the cap, and exec did not have to truncate.
    payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
    _require(report.get("result_truncated") is False, f"{name}: result truncated")
    _require(len(payload) < MAX_RESULT_BYTES,
             f"{name}: result payload {len(payload)} bytes >= {MAX_RESULT_BYTES}")
    for key in ("description", "output"):
        _require(len(str(data.get(key, ""))) <= BOUND,
                 f"{name}: {key} is not bounded")

    # Dynamic proof: the trace records every real tool call. Discovery through
    # the skills window is a filesystem read and leaves no trace row.
    trace = work / ".omnicli_trace.jsonl"
    _require(trace.is_file(), f"{name}: no exec trace recorded")
    rows = [json.loads(line) for line in trace.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    calls = [row for row in rows if row.get("kind") in (None, "call")]
    search_calls = [row for row in calls if row.get("call") == "search"]
    _require(not search_calls, f"{name}: search calls found: {search_calls[:3]}")
    invokes = [row for row in calls if row.get("call") == "invoke"]
    _require(len(invokes) == 1 and invokes[0].get("tool") == spec["tool"],
             f"{name}: expected exactly one invoke of {spec['tool']}, got: "
             f"{[(r.get('call'), r.get('tool')) for r in calls]}")
    _require(report.get("tool_calls") == len(calls),
             f"{name}: report tool_calls disagrees with trace")
    _require(report.get("bridge_denied") == [],
             f"{name}: bridge denied calls: {report.get('bridge_denied')}")

    return {
        "skill": name,
        "bridge": data["bridge"],
        "levels": {
            "L1_name_description": spec["desc_marker"] in str(data.get("description", "")),
            "L2_skill_md_body": bool(data.get("bodyMarker")),
            "L3_reference_file": bool(data.get("resourceMarker")),
        },
        "tool": spec["tool"],
        "argv": spec["argv"],
        "assertions": {
            "static_no_search_call": True,
            "dynamic_no_search_call": True,
            "zero_search_calls": len(search_calls),
            "one_raw_argv_invoke": len(invokes),
            "result_bytes_under_cap": len(payload),
            "result_truncated": report.get("result_truncated"),
            "tool_calls": len(calls),
            "bridge_calls": report.get("bridge_calls"),
            "bridge_denied": report.get("bridge_denied"),
            "exit_code": report.get("exit_code"),
        },
        "passed": True,
    }


def main() -> int:
    try:
        _require(OMNICLI.is_file(), f"missing {OMNICLI}")
        _require(SKILL_FS.is_file(), f"missing real skills bridge: {SKILL_FS}")

        sources = {}
        for spec in SKILLS:
            source = plan_source(spec)
            static_proof(source, spec["name"])
            sources[spec["name"]] = source

        with tempfile.TemporaryDirectory(prefix="omnicli-hardware-shelf-") as name:
            root = Path(name)
            records = []
            for spec in SKILLS:
                work = root / spec["name"]
                work.mkdir(parents=True, exist_ok=True)
                db = isolate_catalog(work)
                report = run_plan(work, db, sources[spec["name"]], spec["name"])
                records.append(assert_plan(report, work, spec))
            record = {
                "flow": "hardware-shelf-three-skill-bridge",
                "skill_count": len(records),
                "max_result_bytes": MAX_RESULT_BYTES,
                "skills": records,
                "passed": True,
            }
            (root / "hardware_shelf_assertions.json").write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        for rec in records:
            a = rec["assertions"]
            print(f"PASS — {rec['skill']}: bridge L1/L2/L3, "
                  f"{a['zero_search_calls']} search calls, "
                  f"{a['one_raw_argv_invoke']} raw-argv invoke, "
                  f"{a['result_bytes_under_cap']} result bytes < {MAX_RESULT_BYTES}")
        print(f"PASS — {len(records)} hardware skills proven through the real bridge")
        print("assertions: " + json.dumps(record, sort_keys=True))
        return 0
    except FlowFailure as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # fatal / environment problem
        print(f"FATAL — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
