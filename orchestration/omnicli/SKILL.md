---
name: omnicli
description: "Unified tool execution gateway and JavaScript Code Mode runner. Use for: (1) a known tool call (`omnicli invoke <tool>`), (2) multi-step automation in one `omnicli exec plan.mjs`, (3) unknown-tool discovery via `lsSkills`/`readSkill`/`readResource` plus optional `describe(toolId)` — never call a search tool, and (4) local inference (`omnicli llm|ocr|decide|asr`). Known tools need no discovery round-trip. Port facts live in CONTEXT.md."
allowed-tools: "Bash(omnicli:*) Read"
---

# `omnicli` — The Uber OmniCLI

One gateway, one tool path, one catalog. **Known tool ID? Invoke it directly.**
Use one JavaScript `omnicli exec` plan when a task needs multiple calls, intermediate
filtering, or a bounded final result. Discover a skill only when the tool is not
already known.

Harnesses following the Agent Skills model already preload each skill's `name` and
`description`; the full `SKILL.md` loads when relevant. Code Mode orchestrates tool
calls — it does not require rediscovering skills on every call. See Anthropic's
[Code Mode](https://docs.anthropic.com/en/docs/claude-code/code-mode) and
[Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
for that model.

When discovery is needed, the read-only `omnicli_skills` window provides
`lsSkills()` / `readSkill(name)` / `readResource(name, rel)`. `describe(toolId)`
is optional introspection for an unknown or unfamiliar contract. See
[skill-discovery.md](references/skill-discovery.md) for the fallback ladder.

`omnicli` itself holds no search or embedding runtime: routing is harness L1
metadata plus those `omnicli_skills` Code Mode reads. The optional live
shortlist — `hs-embed-1` vectors, FTS5, and `skill_expansions.json` doc2query —
belongs to `glitch-cat/apiv-loop/scripts/skill_discovery.py` and is used by APIV
only after Align sign-off.

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

### Known tool — invoke directly

If the tool ID is already known, do not discover or describe it first:

```bash
omnicli invoke guard-hooks/scripts/guard:check -- 'echo hello' --json
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

### Unknown tool — discover only as needed

Use the read-only `omnicli_skills` window only when the harness's already-loaded
skill metadata is not enough. Load the smallest level that answers the question:

| Level | Helper | Returns |
| :--- | :--- | :--- |
| L1 | `lsSkills()` | `[{ name, description }, …]` for every installed skill |
| L2 | `readSkill(name)` | the complete `SKILL.md` body, path-confined |
| L3 | `readResource(name, rel)` | one `references/`/`assets/`/`scripts/` file by relative path |

```js
import { lsSkills, readSkill } from "omnicli_skills";
import { describe, invoke, result } from "omnicli_tools";

const entry = lsSkills().find((s) => s.name === "guard-hooks");
if (!entry) throw new Error("skill not installed");
const body = readSkill("guard-hooks");                 // only if its guidance is needed

const toolId = "guard-hooks/scripts/guard:check";
const { contract } = await describe(toolId);           // optional schema check
if (!contract.inputSchema) throw new Error("no input schema");
const out = await invoke(toolId, ["echo hello", "--json"]);

result({ ok: out.exit_code === 0, tool: toolId, data: JSON.parse(out.output) });
```

Window reads are local filesystem reads — no ranking call, no bridge round-trip,
no network. `describe(toolId)` returns the same contract as `omnicli describe
<tool_id> --json`; it is useful when the exact schema is unclear, but ordinary
`invoke()` calls already validate arguments before dispatch. The helpers are also
globals (`lsSkills`, `readSkill`, `readResource`) for non-module plans;
`readResource` rejects absolute paths, `..`, and symlinks outside the skill root.

Skills are **never modified**; the read-only skills window and the catalog are
read-only at run time. Newly discovered tools start disabled until opened via the
policy gate:

```bash
omnicli policy            # view enabled/disabled state + audit log
omnicli enable <tool_id>  # allow execution against current contract hash
omnicli disable <tool_id>
```

`omnicli describe <tool_id|skill>` and `omnicli spec --stubs` remain available
for human inspection or typed signatures.

---

## ⚡ One plan, one turn — `omnicli exec`

For multi-step workflows (multiple calls, intermediate parsing, or parallel
work), write **one** JavaScript plan. Known tools are called directly; discovery
helpers appear only if a tool is unknown. Intermediate payloads stay in JS
variables, never in the context window. (Python plans are retired; `.py` /
`--lang py` exits 2.)

```bash
omnicli bindings                       # writes omnicli_tools.mjs + .d.ts
omnicli exec plan.mjs --quiet          # print only the synthesized result
```

```js
import { invoke, result } from "omnicli_tools";

const out = await invoke(
  "guard-hooks/scripts/guard:check",
  ["echo hello", "--json"]
);
const payload = JSON.parse(String(out.output || "{}"));

result({
  ok: out.exit_code === 0 && payload.allowed === true,
  data: payload,
});
```

- **Known-tool fast path:** `invoke(toolId, args)` is the normal Code Mode call.
  No `lsSkills()`, `readSkill()`, or `describe()` round-trip is required.
- **Discovery fallback:** `lsSkills()` / `readSkill()` / `readResource()` are for
  unknown skills; `describe(toolId)` is optional contract introspection. There is
  no ranking call and no model in the loop. `tests/skills_bridge_flow.py` proves
  the fallback with zero search calls.
- **Zero boilerplate:** `spec`, `describe`, `invoke`, `output`, `parallel`, `emitResult` / `result`, `getState`, `emitState`, `store` / `load`, `text`, `exit`, `models`, and every catalogued tool (`tool({ ... })`) are available inside the VM; imports match `omnicli_tools.d.ts` for editors.
- **Session state:** `getState()` / `emitState(value)` read and replace one JSON object persisted across `omnicli exec --session ID` runs (default: the trace session identity). `store(key, value)` / `load(key)` keep named values beside it and commit only when the plan exits 0.
- **Output:** `text(value)` emits one item, strings as is and everything else as JSON; a top-level `return` is emitted the same way, so a plan can print several results in order. `exit()` ends a plan successfully from anywhere.
- **Pre-flight validation:** Every tool call validates its options object against `inputSchema` (extracted from Python `argparse`, Node `node:util` `parseArgs`, `--omni-schema`, or `--help`) and throws `TypeError` before dispatch on unknown/missing/mistyped args.
- **Sleek call surface:** `tools[id](args)` and `tools.<fn>(args)` are a Proxy over the typed surface (`TOOLS` is an alias); ids carry `/` and `:`, so `tools.local_asr({...})` is the ergonomic spelling and `spec()` prints the same `fn`. Calls go through the same validation. `models.classify(model, { state, questions })` asks typed `bool`/`choice`/`score` questions of the local decision backend and returns answers keyed by question id. `result({ ok, tool, proof, data })` writes one designed result on the `emitResult` channel. `exec --quiet` prints only that result (JSON when present, else stdout) in plain mode and suppresses the ⚡ status line; `--json` reports are untouched.
- **Shell snippets:** `` $`cmd` `` is a lazy tagged template with `.text()` / `.json()` / `.nothrow()` for pasted Claude-style shell snippets. It throws `TypeError` in `strict` **before spawning** — the bridge cannot be bypassed; use `--sandbox write` (network) to run one.
- **Containment & limits:** **`strict` is the default** — use `--sandbox write` to opt out (needed for network plans). `write` binds `/` read-only and keeps only the workspace + `/tmp` writable; `strict` masks `$HOME`, disables network, and routes calls over a UNIX socket bridge (`exec` denied); `--max-calls` (default `100`) and opt-in `--mem-limit MiB` bound execution.

Architecture, full SDK API and authoring guidelines:
- [references/skill-stack-architecture.md](references/skill-stack-architecture.md) (how agentskills.io, ICM's `AGENTS.md`/`CONTEXT.md`, and omnicli compose into one progressive-disclosure ladder)
- [references/code-mode-sdk.md](references/code-mode-sdk.md) (API, sandbox modes, `--mem-limit`, examples in [examples/](examples/))
- [examples/recipes.mjs](examples/recipes.mjs) (five canonical recipes: known-tool invocation, in-memory `spec()` dedupe, `parallel()` fan-out, a caught typed-validation error, and session state)
- [harnesses/code-mode-showcase.html](harnesses/code-mode-showcase.html) (self-contained visual walkthrough of the exec-only tool surface, plan surface, and strict boundary)
- [references/agent-skills-checklist.md](references/agent-skills-checklist.md) (Agent Skills spec, Python/JS script contract, `tests/verify_agent_skills.py`)

---

## 🔌 MCP face

`omnicli mcp` exposes one tool over JSON-RPC 2.0 — a JSON-RPC client sees the
surface, not the agent:

```bash
omnicli mcp                       # stdio NDJSON (default)
omnicli mcp --http --port 8790    # Streamable HTTP on 127.0.0.1:8790
```

| Tool | Does |
|---|---|
| `omni_exec` | one JavaScript Code Mode plan: call known tools directly, discover unknown skills only when needed, and emit one bounded result |

`omni_exec` runs the same plan as the CLI with `--sandbox strict` by default and
is **OFF unless `OMNICLI_MCP_ALLOW_EXEC=1`**; `--no-exec` is an extra kill switch
(hides it from `tools/list` and refuses calls).

HTTP **refuses to start unless `OMNICLI_MCP_TOKEN` is set** (a deliberate
negative-control gate); every request needs `Authorization: Bearer <token>`.
`GET /health` is the plain liveness probe (same token, not an MCP tool). The
loopback bridge is surfaced on the tailnet as `https://host/omni` via
`ports.json` + `tailscale-ops sync`. Every `tools/call` is appended to
`~/.local/share/omnicli/mcp-audit.jsonl` (no arguments or tokens logged).

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
