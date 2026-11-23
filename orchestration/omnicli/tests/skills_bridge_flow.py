#!/usr/bin/env python3
"""End-to-end proof of Agent Skills discovery through the strict-mode skill window.

One ``omnicli exec`` plan (strict sandbox) DISCOVERS its target skill from a
real natural-language intent using only the exec-only flow: L1 ``lsSkills()``
name+description, then L2 ``readSkill()`` / L3 ``readResource()``. It resolves
the tool for that discovered skill with the in-memory catalog index (``spec``),
describes it, invokes it with a raw argv array, and emits ONE bounded result.

The plan never calls ``search()``; this driver proves that statically in the
plan source and dynamically in the exec trace, then records every assertion as
JSON. Neither the skill name nor the tool id is hardcoded: the intent is the
only selector.

Discovery goes through the generated ``omnicli_skills`` synthetic module
(read-only skills window, built by ``catalog/skill_fs.mjs``). A tiny in-workspace
fallback module is used only when that bridge is not installed yet, so the
driver can be executed before the slices are merged. The recorded ``mode`` says
which surface was used; once ``catalog/skill_fs.mjs`` exists, ``fixture`` mode
is refused and the real bridge is required.

The catalog and HOME are isolated before the run, so no shared bindings,
traces, session state or catalog rows are touched.

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
LLAMA_BUILD = REPO / "hardware" / "llama-build"
SKILL_FS = SKILL / "catalog" / "skill_fs.mjs"

sys.path.insert(0, str(SKILL))
from catalog import builder, registry  # noqa: E402

# A real routing intent, phrased the way a user would ask. The discovery terms
# are derived from it; the skill and tool ids are never named here.
INTENT = (
    "Is my llama build stale and which binary is the rig using? "
    "Check the upstream llama.cpp checkout and rebuild it if needed."
)
DISCOVERY_TERMS = ("llama.cpp", "checkout")
TARGET_RESOURCE = "CONTEXT.md"
ARGV = ["--json", "--help"]
DESC_MARKER = "upstream llama.cpp checkout"   # L1: frontmatter description
BODY_MARKER = "## Available scripts"          # L2: SKILL.md body
RESOURCE_MARKER = "llama.cpp Builds & Forks"  # L3: CONTEXT.md reference
BOUND = 180                                   # per-field synthesis bound
MAX_RESULT_BYTES = 8 * 1024                   # the exec reply cap
PROOF = "agent-skills-intent-discovery"


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


def plan_source() -> str:
    """One plan: L1 -> L2 -> L3 -> discover tool -> describe -> invoke -> result."""
    # Static import of omnicli_tools; the skills window is imported dynamically
    # so the plan still runs before the bridge is installed. Neither path uses
    # a ranking call or a discovery tool call.
    return f'''import {{ spec, describe, invoke, result }} from "omnicli_tools";

const INTENT = {json.dumps(INTENT)};
const TERMS = {json.dumps(list(DISCOVERY_TERMS))};
const RESOURCE = {json.dumps(TARGET_RESOURCE)};
const ARGV = {json.dumps(ARGV)};
const BOUND = {BOUND};

// The real window is the synthetic `omnicli_skills` module, whose helpers are
// injected as globals. Fall back to the in-workspace fixture only when the
// bridge is not installed yet. Neither path calls the ranking service.
let skills, mode;
if (typeof globalThis.lsSkills === "function"
    && typeof globalThis.readSkill === "function"
    && typeof globalThis.readResource === "function") {{
  skills = globalThis;
  mode = "bridge";
}} else {{
  skills = await import("file:///tmp/omnicli/work/.skills_fixture.mjs");
  mode = "fixture";
}}
const {{ lsSkills, readSkill, readResource }} = skills;

// DISCOVERY — L1: name + description for every skill. This is a filesystem
// read, not a ranking call: the generated index IS the catalog. The skill is
// selected by the intent terms found in its description, never by a literal
// name baked into the plan.
const listed = lsSkills();
const entry = listed.find((s) => {{
  const description = String(s.description || "").toLowerCase();
  return TERMS.every((term) => description.includes(String(term).toLowerCase()));
}});
if (!entry) throw new Error("L1: no skill matches the intent: " + INTENT);
const SKILL = String(entry.name || "");
const description = String(entry.description || "");
if (!description.includes({json.dumps(DESC_MARKER)})) throw new Error("L1: description marker missing");

// L2 — the complete SKILL.md body for the discovered skill.
const body = String(readSkill(SKILL));
if (!body.includes({json.dumps(BODY_MARKER)})) throw new Error("L2: SKILL.md body marker missing");

// L3 — one reference file beneath the discovered skill root, by relative path.
const resource = String(readResource(SKILL, RESOURCE));
if (!resource.includes({json.dumps(RESOURCE_MARKER)})) throw new Error("L3: CONTEXT.md marker missing");

// TOOL DISCOVERY — the in-memory catalog index resolves the base command for
// the discovered skill; the tool id is read from the catalog, not hardcoded.
const rows = spec({{ skill: SKILL }});
const base = rows.find((r) => !String(r.id).includes(":"));
if (!base) throw new Error("catalog: no base tool for skill " + SKILL);
const TOOL = base.id;

// describe() confirms the exact runtime contract for the discovered tool.
const schema = await describe(TOOL);
if (!schema || schema.id !== TOOL) throw new Error("describe returned wrong tool: " + (schema && schema.id));
const contract = schema.contract || {{}};
if (!contract.inputSchema) throw new Error("describe returned no input schema");

// Exactly one catalogued tool call, with a raw argv array.
const envelope = await invoke(TOOL, ARGV);

result({{
  ok: envelope.exit_code === 0,
  tool: TOOL,
  proof: {json.dumps(PROOF)},
  data: {{
    intent: INTENT,
    terms: TERMS,
    mode,
    levels: ["L1", "L2", "L3"],
    skillsListed: listed.length,
    skill: SKILL,
    description: description.slice(0, BOUND),
    bodyMarker: body.includes({json.dumps(BODY_MARKER)}),
    bodyBytes: body.length,
    resource: RESOURCE,
    resourceMarker: resource.includes({json.dumps(RESOURCE_MARKER)}),
    resourceBytes: resource.length,
    discoveredTool: TOOL,
    hasSchema: Boolean(contract.inputSchema),
    argv: ARGV,
    exitCode: envelope.exit_code,
    output: String(envelope.output || "").slice(0, BOUND),
  }},
}});
'''


# vm_runner links dynamic imports but does not evaluate their top level, so the
# fallback declares only hoisted functions and acquires modules inside them.
FIXTURE_MJS = '''export function lsSkills() {
  return [{ name: "llama-build", description: __DESC__ }];
}
export function readSkill(name) {
  if (String(name) !== "llama-build") throw new Error("unknown skill: " + name);
  const fs = require("node:fs");
  const path = require("node:path");
  const base = path.join("/tmp/omnicli/work/.skills_fixture_root", "llama-build");
  return fs.readFileSync(path.join(base, "SKILL.md"), "utf8");
}
export function readResource(name, rel) {
  if (String(name) !== "llama-build") throw new Error("unknown skill: " + name);
  const fs = require("node:fs");
  const path = require("node:path");
  const base = path.join("/tmp/omnicli/work/.skills_fixture_root", "llama-build");
  const target = path.resolve(base, String(rel));
  if (target !== base && !target.startsWith(base + path.sep)) throw new Error("resource escapes skill root");
  return fs.readFileSync(target, "utf8");
}
'''


def write_fixture(tmp: Path) -> None:
    """Materialize the fallback window from the real llama-build files."""
    _require((LLAMA_BUILD / "SKILL.md").is_file(), f"missing {LLAMA_BUILD / 'SKILL.md'}")
    _require((LLAMA_BUILD / "CONTEXT.md").is_file(), f"missing {LLAMA_BUILD / 'CONTEXT.md'}")
    base = tmp / ".skills_fixture_root" / "llama-build"
    base.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LLAMA_BUILD / "SKILL.md", base / "SKILL.md")
    shutil.copy2(LLAMA_BUILD / "CONTEXT.md", base / "CONTEXT.md")
    text = (LLAMA_BUILD / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    _, description = registry.parse_frontmatter(text)
    _require(bool(description), "llama-build has no frontmatter description")
    fixture = FIXTURE_MJS.replace("__DESC__", json.dumps(description, ensure_ascii=False))
    (tmp / ".skills_fixture.mjs").write_text(fixture, encoding="utf-8")


def static_proof(source: str) -> None:
    """Prove, in the plan source, that no ranking call is possible."""
    _require(re.search(r"\bsearch\s*\(", source) is None,
             "plan source contains a discovery-tool call")
    for helper in ("lsSkills", "readSkill", "readResource"):
        _require(helper in source, f"plan source never uses {helper}")
    _require("omnicli_skills" in source, "plan never names the skills window")
    _require("globalThis.lsSkills" in source, "plan never uses the real window helpers")
    _require("spec(" in source, "plan never queries the catalog index")
    _require("await describe(" in source, "plan never describes the discovered tool")
    _require(source.count("await invoke(") == 1, "plan must make exactly one invoke call")
    _require(source.count("result({") == 1, "plan must emit exactly one result")


def run_plan(tmp: Path, db: Path, source: str) -> dict:
    plan = tmp / "plan.mjs"
    plan.write_text(source, encoding="utf-8")
    write_fixture(tmp)

    env = os.environ.copy()
    env.pop("OMNICLI_DB_RO", None)
    env["HOME"] = str(tmp)
    env["OMNICLI_DB"] = str(db)
    env["OMNICLI_SESSION"] = "skills-bridge-flow-test"
    env["OMNICLI_USER_TRACE"] = str(tmp / "user_trace.jsonl")

    proc = subprocess.run(
        [sys.executable, str(OMNICLI), "exec", str(plan), "--json",
         "--workspace", str(tmp), "--sandbox", "strict", "--max-calls", "10"],
        capture_output=True, text=True, timeout=300, cwd=str(tmp), env=env,
    )
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise FlowFailure(
            f"exec produced no JSON report (rc={proc.returncode}): {proc.stderr[-800:]}"
        ) from exc


def assert_flow(report: dict, tmp: Path) -> dict:
    """Prove the three levels, intent-driven discovery, zero search calls, a bounded result."""
    _require(report.get("exit_code") == 0,
             f"exec failed: {str(report.get('stderr'))[-800:]}")
    _require(report.get("sandbox") == "strict", "plan did not run in strict sandbox")
    result = report.get("result")
    _require(isinstance(result, dict), "no bounded emitResult recorded")
    _require(result.get("ok") is True, f"result not ok: {result}")
    _require(result.get("proof") == PROOF, "wrong proof marker")

    data = result.get("data") or {}
    skill = str(data.get("skill") or "")
    discovered_tool = str(data.get("discoveredTool") or "")
    _require(bool(skill), "no skill was discovered from the intent")
    _require(list(data.get("terms") or []) == list(DISCOVERY_TERMS),
             "intent terms were not carried into the result")
    _require(data.get("intent") == INTENT, "intent was not carried into the result")
    description = str(data.get("description") or "")
    lowered = description.lower()
    _require(all(term.lower() in lowered for term in DISCOVERY_TERMS),
             "discovered skill description does not match the intent terms")
    _require(bool(discovered_tool)
             and discovered_tool.startswith(skill + "/"),
             f"tool {discovered_tool!r} does not belong to discovered skill {skill!r}")
    _require(result.get("tool") == discovered_tool, "result tool is not the discovered tool")
    _require(data.get("hasSchema") is True, "discovered tool has no input schema")

    _require(data.get("levels") == ["L1", "L2", "L3"], "not all three levels exercised")
    expected_mode = "bridge" if SKILL_FS.is_file() else "fixture"
    _require(data.get("mode") == expected_mode,
             f"expected {expected_mode} discovery surface, got {data.get('mode')!r}")
    _require(data.get("skillsListed", 0) > 0, "L1: empty skills index")
    _require(DESC_MARKER in description, "L1: description marker not surfaced")
    _require(data.get("bodyMarker") is True and data.get("bodyBytes", 0) > 0,
             "L2: SKILL.md body not read")
    _require(data.get("resource") == TARGET_RESOURCE and data.get("resourceMarker") is True
             and data.get("resourceBytes", 0) > 0, "L3: CONTEXT.md reference not read")
    _require(data.get("argv") == ARGV, "tool was not invoked with the raw argv array")
    _require(data.get("exitCode") == 0, f"tool invocation failed: {data.get('exitCode')}")

    # ONE bounded result: both the field slices and the whole payload stay under
    # the cap, and the exec runner did not have to truncate.
    payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
    _require(report.get("result_truncated") is False, "result was truncated by exec")
    _require(len(payload) < MAX_RESULT_BYTES,
             f"result payload {len(payload)} bytes >= {MAX_RESULT_BYTES}")
    for key in ("description", "output"):
        _require(len(str(data.get(key, ""))) <= BOUND, f"{key} is not bounded")

    # Dynamic proof: the trace records every real tool call. Discovery through
    # the skills window and the in-memory catalog query leave no trace row.
    trace = tmp / ".omnicli_trace.jsonl"
    _require(trace.is_file(), "no exec trace recorded")
    rows = [json.loads(line) for line in trace.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    calls = [row for row in rows if row.get("kind") in (None, "call")]
    search_calls = [row for row in calls if row.get("call") == "search"]
    _require(not search_calls, f"discovery-tool calls found in trace: {search_calls[:3]}")
    describes = [row for row in calls if row.get("call") == "describe"]
    _require(len(describes) == 1 and describes[0].get("tool") == discovered_tool,
             f"expected exactly one describe call for {discovered_tool}, got: "
             f"{[(r.get('call'), r.get('tool')) for r in calls]}")
    invokes = [row for row in calls if row.get("call") == "invoke"]
    _require(len(invokes) == 1 and invokes[0].get("tool") == discovered_tool,
             f"expected exactly one invoke of {discovered_tool}, got: "
             f"{[(r.get('call'), r.get('tool')) for r in calls]}")
    _require(len(calls) == 2,
             f"expected describe + invoke calls only, got: "
             f"{[row.get('call') for row in calls]}")
    _require(report.get("tool_calls") == len(calls),
             "report tool_calls disagrees with trace")
    _require(report.get("bridge_denied") == [],
             f"bridge denied calls: {report.get('bridge_denied')}")

    return {
        "flow": "agent-skills-intent-discovery",
        "skill": skill,
        "tool": discovered_tool,
        "mode": data["mode"],
        "levels": {
            "L1_name_description": bool(DESC_MARKER in description),
            "L2_skill_md_body": bool(data.get("bodyMarker")),
            "L3_reference_file": bool(data.get("resourceMarker")),
        },
        "assertions": {
            "static_no_search_call": True,
            "dynamic_no_search_call": True,
            "zero_search_calls": len(search_calls),
            "one_describe": len(describes),
            "one_raw_argv_invoke": len(invokes),
            "result_bytes_under_cap": len(payload),
            "result_truncated": report.get("result_truncated"),
            "tool_calls": len(calls),
            "bridge_calls": report.get("bridge_calls"),
            "exit_code": report.get("exit_code"),
        },
        "passed": True,
    }


def main() -> int:
    try:
        _require(OMNICLI.is_file(), f"missing {OMNICLI}")
        source = plan_source()
        static_proof(source)
        with tempfile.TemporaryDirectory(prefix="omnicli-skills-bridge-") as name:
            tmp = Path(name)
            db = isolate_catalog(tmp)
            report = run_plan(tmp, db, source)
            record = assert_flow(report, tmp)
            (tmp / "skills_bridge_assertions.json").write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        a = record["assertions"]
        print(f"PASS — strict plan, {record['mode']} window, "
              f"intent discovered {record['skill']!r} -> {record['tool']!r}, "
              f"L1/L2/L3 proven, {a['zero_search_calls']} search calls, "
              f"{a['one_raw_argv_invoke']} raw-argv invoke, "
              f"{a['result_bytes_under_cap']} result bytes < {MAX_RESULT_BYTES}")
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
