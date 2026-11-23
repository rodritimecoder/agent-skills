---
name: omnicli
description: "Unified tool execution gateway and JavaScript Code Mode runner. MUST USE for: (1) multi-step automation in a single turn via one `omnicli exec plan.mjs`, (2) tool discovery by writing that one plan to list/read skills with `lsSkills`/`readSkill`/`readResource` and get a tool's exact input schema with `describe(toolId)` — never call a search tool, (3) executing CLI tools with token shielding and field projection (`omnicli invoke <tool> --omni-project`), and (4) local inference (`omnicli llm|ocr|decide|asr`). Port facts live in CONTEXT.md."
allowed-tools: "Bash(omnicli:*) Read"
---

# `omnicli` — The Uber OmniCLI

One gateway, one tool path, one catalog. Write **one JavaScript `omnicli exec`
plan** to discover skills, read the one tool's exact schema, invoke it, and
emit one bounded result — nothing else enters the context window.

Discovery is the read-only skills window: `lsSkills()` / `readSkill(name)` /
`readResource(name, rel)` from the synthetic `omnicli_skills` module give the
L1/L2/L3 Agent Skills ladder (name + description, full `SKILL.md`, one shelf
file). There is no ranking step, no model in the loop, and no discovery tool
call: the plan reads local files. The tool's exact input schema comes from
`describe(toolId)` in `omnicli_tools` — the same contract the CLI shows — so no
generated artifact is needed. See [skill-discovery.md](references/skill-discovery.md)
for the ladder and the end-to-end proof.

File routing and machine-local facts: [CONTEXT.md](CONTEXT.md). Port/model facts stay in the root [CONTEXT.md](../../CONTEXT.md) — never duplicated here.
Doc-drift gate: `python3 tests/doc_drift_check.py --json` proves the tool surface and docs agree (exit 0 clean, 1 drift).

---

## Available scripts

Bundled CLI scripts, referenced relative to the skill root. Run `<command> --help`
for flags and exit codes; structured data goes to stdout, diagnostics to stderr.

- `scripts/asr.py` — audiocpp-asr - speech-to-text against a local audio.cpp server.
- `scripts/decide.py` — One typed decision from a local Jev-style model. Compact JSON out.
- `scripts/decide.sh` — Shell wrapper for the local typed-decision client.
- `scripts/llm_client.py` — llm-cli — Local Qwen3.6-35B Genesis Client.
- `scripts/ocr.py` — ocr-cli - local OCR for PDFs, slides, and images via local vision models (LightOnOCR-3-0.8B).
- `scripts/route_stats.py` — Bypass metrics for the omnicli-route plugin.
- `scripts/tree_to_md.py` — Convert an OCR'd ASCII directory tree transcript into a Markdown tree.

## ⚡ The one-tool path

### 1. Discover the skill and read the tool schema — all in the plan

The read-only `omnicli_skills` window exposes the Agent Skills ladder as three
helpers. Load only the level the step needs, then stop:

| Level | Helper | Returns |
| :--- | :--- | :--- |
| L1 | `lsSkills()` | `[{ name, description }, …]` for every installed skill |
| L2 | `readSkill(name)` | the complete `SKILL.md` body, path-confined |
| L3 | `readResource(name, rel)` | one `references/`/`assets/`/`scripts/` file by relative path |

Inside one plan, pick the skill by description, read only what the step needs,
then ask `describe(toolId)` for the exact input schema of the tool you will call:

```js
import { lsSkills, readSkill, readResource } from "omnicli_skills";
import { describe } from "omnicli_tools";

const entry = lsSkills().find((s) => s.name === "guard-hooks");
if (!entry) throw new Error("skill not installed");
const body = readSkill("guard-hooks");                 // L2, only when needed
const ref = readResource("guard-hooks", "SKILL.md");   // L3, one file by rel path
const toolId = "guard-hooks/scripts/guard_check";
const { contract } = await describe(toolId);           // exact input schema
if (!contract.inputSchema) throw new Error("no input schema");
```

Window reads are local filesystem reads — no ranking call, no bridge round-trip,
no network. `describe(toolId)` returns the same contract as `omnicli describe
<tool_id> --json` (its `contract.inputSchema` is the authoritative schema) and
runs inside the plan, so the payload never enters the context. The helpers are
also globals (`lsSkills`, `readSkill`, `readResource`) for non-module plans;
`readResource` rejects absolute paths, `..`, and symlinks outside the skill root.
A worked, asserted example lives in `tests/skills_bridge_flow.py`: one strict
exec plan, three skill levels, one tool invocation, zero search calls.

Skills are **never modified**; the read-only skills window and the catalog are
read-only at run time. Newly discovered tools start disabled until opened via the
policy gate:

```bash
omnicli policy            # view enabled/disabled state + audit log
omnicli enable <tool_id>  # allow execution against current contract hash
omnicli disable <tool_id>
```

`omnicli describe <tool_id|skill>` and `omnicli spec --stubs` remain available
for a human reading one contract or a typed signature, but an agent workflow
calls `describe(toolId)` in the plan so intermediate payloads never enter the
context.

### 2. `omnicli invoke <tool_id> [args]` — run the discovered tool, bounded

```bash
omnicli invoke zoom-recorder/scripts/zoom_download -- --url "https://zoom.us/rec/abc"
omnicli invoke local/decide --omni-project "answer,confidence"
omnicli invoke local/llm --omni-buffer /tmp/out.md
```

Every reply is capped (default 8 KB) with a head+tail preview. Gateway flags
are prefixed `--omni-` so they never collide with tool flags (`--` forces the
split explicitly):

| Flag | Effect |
|---|---|
| `--omni-buffer FILE` | Write full, unfiltered stdout to disk and print a bounded preview |
| `--omni-project a,b.c` | Keep only specified JSON fields (dotted paths & arrays supported) |
| `--omni-jq EXPR` | JQ filter expression |
| `--omni-grep RE` | Keep only matching lines |
| `--omni-max-bytes N` | Hard cap on returned bytes (default 8000) |
| `--omni-json` | Wrap output and metadata in JSON |

---

## ⚡ One plan, one turn — `omnicli exec`

For multi-step workflows (≥2 calls or intermediate parsing), write **one**
JavaScript plan inside `node:vm` + `bwrap` that discovers skills via the read-only
skills window, reads the one tool's exact schema with `describe()`, invokes it,
and emits one bounded result. Intermediate payloads stay in JS variables, never
in the context window. (Python plans are retired; `.py` / `--lang py` exits 2.)

```bash
omnicli bindings                                               # writes omnicli_tools.mjs + .d.ts
omnicli exec plan.mjs --sandbox write                          # skills window + describe + invoke + result
omnicli exec plan.mjs --quiet                                  # print only the result
```

```js
import { describe, invoke, result } from "omnicli_tools";
import { lsSkills, readSkill, readResource } from "omnicli_skills";

const entry = lsSkills().find((s) => s.name === "guard-hooks"); // L1
const body = readSkill("guard-hooks");                           // L2
const ref = readResource("guard-hooks", "SKILL.md");            // L3
const toolId = "guard-hooks/scripts/guard_check";
const { contract } = await describe(toolId);                     // exact input schema
if (!contract.inputSchema) throw new Error("no input schema");
const out = await invoke(toolId, ["echo hello"]);                // the one real tool call

result({
  ok: out.exit_code === 0,
  tool: toolId,
  proof: "one-plan-discovery",
  data: { description: entry.description.slice(0, 120),
          bodyBytes: body.length, refBytes: ref.length,
          hasSchema: Boolean(contract.inputSchema),
          exitCode: out.exit_code },
});
```

- **Skills-window discovery:** `lsSkills()` / `readSkill()` / `readResource()`
  from `omnicli_skills` plus `describe(toolId)` for the schema are the discovery
  surface — no discovery-tool call, no ranking, no model in the loop.
  `tests/skills_bridge_flow.py` proves it end to end: one strict exec plan,
  three skill levels, one invocation, and a trace assertion of zero search calls.
- **Zero boilerplate:** `spec`, `describe`, `invoke`, `output`, `parallel`, `emitResult` / `result`, `getState`, `emitState`, and every catalogued tool (`tool({ ... })`) are available inside the VM; imports match `omnicli_tools.d.ts` for editors.
- **Session state:** `getState()` / `emitState(value)` read and replace one JSON object persisted across `omnicli exec --session ID` runs (default: the trace session identity).
- **Pre-flight validation:** Every tool call validates its options object against `inputSchema` (extracted from Python `argparse`, Node `node:util` `parseArgs`, `--omni-schema`, or `--help`) and throws `TypeError` before dispatch on unknown/missing/mistyped args.
- **Sleek call surface:** `tools[id](args)` is a Proxy over the typed surface (`TOOLS` is an alias); calls go through the same validation. `result({ ok, tool, proof, data })` writes one designed result on the `emitResult` channel. `exec --quiet` prints only that result (JSON when present, else stdout) in plain mode and suppresses the ⚡ status line; `--json` reports are untouched.
- **Shell snippets:** `` $`cmd` `` is a lazy tagged template with `.text()` / `.json()` / `.nothrow()` for pasted Claude-style shell snippets. It throws `TypeError` in `strict` **before spawning** — the bridge cannot be bypassed; use `--sandbox write` (network) to run one.
- **Containment & limits:** **`strict` is the default** — use `--sandbox write` to opt out (needed for network plans). `write` binds `/` read-only and keeps only the workspace + `/tmp` writable; `strict` masks `$HOME`, disables network, and routes calls over a UNIX socket bridge (`exec` denied); `--max-calls` (default `100`) and opt-in `--mem-limit MiB` bound execution.

Architecture, full SDK API and authoring guidelines:
- [references/skill-stack-architecture.md](references/skill-stack-architecture.md) (how agentskills.io, ICM's `AGENTS.md`/`CONTEXT.md`, and omnicli compose into one progressive-disclosure ladder)
- [references/code-mode-sdk.md](references/code-mode-sdk.md) (API, sandbox modes, `--mem-limit`, examples in [examples/](examples/))
- [examples/recipes.mjs](examples/recipes.mjs) (five canonical recipes: discovery → schema → projection, in-memory `spec()`, `parallel()` fan-out, a caught typed-validation error, and session state)
- [harnesses/code-mode-showcase.html](harnesses/code-mode-showcase.html) (self-contained visual walkthrough of the exec-only tool surface, plan surface, and strict boundary)
- [references/agent-skills-checklist.md](references/agent-skills-checklist.md) (Agent Skills spec, Python/JS script contract, `tests/verify_agent_skills.py`)

---

## 🔌 MCP face

`omnicli mcp` exposes the same three-tool surface as the native CLI over
JSON-RPC 2.0 — a JSON-RPC client sees the surface, not the agent:

```bash
omnicli mcp                       # stdio NDJSON (default)
omnicli mcp --http --port 8790    # Streamable HTTP on 127.0.0.1:8790
```

| Tool | Does |
|---|---|
| `omni_exec` | one JavaScript Code Mode plan that discovers skills with `omnicli_skills`, reads the tool schema with `describe()`, invokes the tool, and emits one bounded result — the only MCP tool and the sole discovery path |

`omni_exec` is the agent discovery path: it runs the same plan as the CLI with
`--sandbox strict` by default and is **OFF unless `OMNICLI_MCP_ALLOW_EXEC=1`**;
`--no-exec` is an extra kill switch (hides it from `tools/list` and refuses calls).

HTTP **refuses to start unless `OMNICLI_MCP_TOKEN` is set** (a deliberate
negative-control gate); every request needs `Authorization: Bearer <token>`.
`GET /health` is the plain liveness probe (same token, not an MCP tool). The
loopback bridge is surfaced on the tailnet as `https://host/omni` via
`ports.json` + `tailscale-ops sync`. Discovery is not exposure — `omni_invoke`
is gated by `omnicli enable`, runs the same CLI in one bounded subprocess, and
every `tools/call` is appended to `~/.local/share/omnicli/mcp-audit.jsonl`
(no arguments or tokens logged).

---

## 🌐 Harnesses & Telemetry

Adapters for **T3 Code**, **Antigravity**, **OpenCode**, **Pi** and **Boxxy Claw** live in [harnesses/index.md](harnesses/index.md); each maps the same bounded-invoke contract onto its host primitives.

```bash
omnicli harness list|detect|verify     # inspect active harnesses & run verification matrix
omnicli harness info|config <id>       # read adapter guide or ready-to-paste setup snippet
omnicli usage --since 24h --json       # per-harness telemetry from ~/.local/share/omnicli/trace.jsonl
```

---

## 🧠 Native local inference & Catalog maintenance

`omnicli llm` · `ocr` · `decide` · `asr` map to `local/llm`, `local/ocr`, `local/decide`, `local/asr`. Ports, models and slot rules are in `CONTEXT.md` — not duplicated here.

```bash
omnicli status            # ports, catalog freshness, service health
omnicli index --rebuild   # rebuild the skill/tool index + tool schemas
```

The routing gate has three hard legs — `exec_only_flow`, `skills_bridge_flow`,
`doc_drift` — each with a real mutant that must turn it red:

```bash
python3 tests/routing_gate.py --json   # run all three legs
python3 tests/discovery_mutant.py      # mutant for exec_only_flow
python3 tests/leg_mutants.py           # mutants for the other two legs
```

`tests/overfit_check.py` remains a standalone diagnostic of the curated routing
metadata, not a gate leg.
