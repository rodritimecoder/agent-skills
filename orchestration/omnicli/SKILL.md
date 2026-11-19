---
name: omnicli
description: "Unified tool execution gateway and JavaScript Code Mode runner. MUST USE for: (1) multi-step automation in a single turn via Code Mode (`omnicli exec plan.mjs`), (2) executing CLI tools with token shielding and field projection to prevent context flooding (`omnicli invoke <tool> --omni-project`), (3) discovering sub-tools across the 529 tool catalog by intent (`omnicli search`), and (4) local inference (`omnicli llm|ocr|decide|asr`). Port facts live in CONTEXT.md."
allowed-tools: "Bash(omnicli:*) Read"
---

# `omnicli` — The Uber OmniCLI

One gateway, two surfaces, one catalog. Discover a tool by *intent*, pull the
contract for that one tool, and invoke it with a bounded response — nothing
else enters the context window.

One control plane (`catalog.db`: FTS5 BM25, weighted aliases, dense vectors)
over 529 tools, reached through one of two faces: bounded CLI calls
(`search` / `describe` / `invoke`) or a single JavaScript plan (`exec`) that
keeps intermediate payloads out of the context window. Ranking internals:
[references/retrieval-architecture.md](references/retrieval-architecture.md).

File routing and machine-local facts: [CONTEXT.md](CONTEXT.md). Port/model facts stay in the root [CONTEXT.md](../../CONTEXT.md) — never duplicated here.

---

## ⚡ The discovery loop

### 1. `omnicli search "<intent>"` — find the tool

```bash
omnicli search "transcribe a zoom lecture recording"
omnicli search "turn a recorded podcast into readable text"
omnicli search "调研一下这个话题在网上的讨论"
```

`--depth` picks the view (default `brief`):
- `brief` — compact routing view (skill, score, why, top hit); the unchanged default.
- `contract` — the top hit's tool contract, identical to `describe` (`--section`/`--doc` pass through).
- `chunks` — every matching chunk (the former `--chunks` shape).

BM25 over every skill's full body + curated aliases (weight 12) matches exact
tokens; when BM25's margin is thin (`--fusion auto`), `omnicli` fuses a dense
embedding leg over descriptions (`K=60`) and damps multi-chunk bodies
(`OMNICLI_CHUNK_ALPHA=0.2`). The dense leg is `:8084` (bge-small-en-v1.5,
~400 MB VRAM). Unless `--rerank never` / `--no-rerank` is set, `omnicli search`
delegates to model-layer's primitive `llama-rig ensure 8084 --json`: it brings
the slot up if needed and waits for it (bounded timeout), returning `started` /
`waited_ms` / `status` for the audit line. If the index was built with dense
offline (zero vectors), it runs exactly one `omnicli index --rebuild`. The slot
is left warm — `llama-rig down 8084` frees the VRAM manually. Set
`OMNICLI_NO_AUTOSTART=1` to opt out; a failed start degrades to BM25 with a
stderr line naming the manual fix (`llama-rig up local-embed-bge`). The slot
roster, launcher, `ensure` primitive and alias `local-embed-bge` are owned by
the `model-layer` skill.
See [references/retrieval-architecture.md](references/retrieval-architecture.md)
for benchmarks and ranking internals.

### 2. `omnicli describe <tool_id|skill>` — get one contract

```bash
omnicli describe zoom-recorder/scripts/zoom_download   # one tool's usage, flags, inputSchema
omnicli describe canvas-cli                             # skill frontmatter + section outline
omnicli describe canvas-cli --section "token shield"    # load only one section
omnicli spec --grep zoom --stubs                        # typed .d.ts signatures for matching tools
omnicli spec --grep zoom --stubs --plan-header          # + paste-ready header above the stubs
```

Skills are **never modified**; the catalog is a read-only index (`catalog.db`).
Newly discovered tools start disabled until opened via the policy gate:

```bash
omnicli policy            # view enabled/disabled state + audit log
omnicli enable <tool_id>  # allow execution against current contract hash
omnicli disable <tool_id>
```

### 3. `omnicli invoke <tool_id> [args]` — run it, bounded

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

For multi-step workflows (≥2 calls or intermediate parsing), run one JavaScript
plan inside `node:vm` + `bwrap` instead of round-tripping intermediate payloads
through context. (Python plans are retired; `.py` / `--lang py` exits 2.)

```bash
omnicli spec --grep zoom --stubs --plan-header                         # paste-ready header + stubs
omnicli bindings                                                      # writes omnicli_tools.mjs + .d.ts
omnicli exec -c 'const rows = await search("audio", 2); console.log(rows)'
omnicli exec plan.mjs                                                 # strict (default); --sandbox write opts out
omnicli exec plan.mjs --quiet                                         # print only the result; no ⚡ status line
```

```js
import { search, invoke, parallel, emitResult } from "omnicli_tools";
const [hits, asr] = await parallel([
  () => search("audio transcription", 3),
  () => invoke("audiocpp/scripts/audiocpp_cli", ["asr", "talk.wav"]),
]);
emitResult({ hits: hits.length, exit: asr.exit_code }); // project; never dump raw
```

- **Zero boilerplate:** `search`, `spec`, `describe`, `invoke`, `output`, `parallel`, `emitResult`, `getState`, `emitState`, and every catalogued tool (`tool({ ... })`) are globals inside the VM; imports match `omnicli_tools.d.ts` for editors.
- **Session state:** `getState()` / `emitState(value)` read and replace one JSON object persisted across `omnicli exec --session ID` runs (default: the trace session identity).
- **Pre-flight validation:** Every tool call validates its options object against `inputSchema` (extracted from Python `argparse`, Node `node:util` `parseArgs`, `--omni-schema`, or `--help`) and throws `TypeError` before dispatch on unknown/missing/mistyped args.
- **Sleek call surface:** `tools[id](args)` is a Proxy over the typed surface (`TOOLS` is an alias); calls go through the same validation. `result({ ok, tool, proof, data })` writes one designed result on the `emitResult` channel. `exec --quiet` prints only that result (JSON when present, else stdout) in plain mode and suppresses the ⚡ status line; `--json` reports are untouched.
- **Shell snippets:** `` $`cmd` `` is a lazy tagged template with `.text()` / `.json()` / `.nothrow()` for pasted Claude-style shell snippets. It throws `TypeError` in `strict` **before spawning** — the bridge cannot be bypassed; use `--sandbox write` (network) to run one.
- **Containment & limits:** **`strict` is the default** — use `--sandbox write` to opt out (needed for network plans). `write` binds `/` read-only and keeps only the workspace + `/tmp` writable; `strict` masks `$HOME`, disables network, and routes calls over a UNIX socket bridge (`exec` denied); `--max-calls` (default `100`) and opt-in `--mem-limit MiB` bound execution.

Architecture, full SDK API and authoring guidelines:
- [references/skill-stack-architecture.md](references/skill-stack-architecture.md) (how agentskills.io, ICM's `AGENTS.md`/`CONTEXT.md`, and omnicli compose into one progressive-disclosure ladder)
- [references/code-mode-sdk.md](references/code-mode-sdk.md) (API, sandbox modes, `--mem-limit`, examples in [examples/](examples/))
- [examples/recipes.mjs](examples/recipes.mjs) (five canonical recipes: discovery → contract → project, in-memory `spec()`, `parallel()` fan-out, a caught typed-validation error, and session state)
- [harnesses/code-mode-showcase.html](harnesses/code-mode-showcase.html) (self-contained visual walkthrough of the three native tools, plan surface, and strict boundary)
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
| `omni_search` | intent → routing; `depth: "contract"` adds the top hit's exact contract in one call (no separate describe tool) |
| `omni_invoke` | run one tool, bounded + projected |
| `omni_exec` | one JavaScript Code Mode plan that emits one bounded result |

`depth: "contract"` is byte-identical to `omnicli describe`, so discovery and
contract pull are a single call. `omni_exec` runs with `--sandbox strict` by
default and is **OFF unless `OMNICLI_MCP_ALLOW_EXEC=1`**; `--no-exec` is an
extra kill switch (hides it from `tools/list` and refuses calls).

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
omnicli status            # ports, catalog freshness, retrieval tier
omnicli index --rebuild   # rebuild catalog.db + re-extract contracts
omnicli eval              # golden routing evaluation (61 cases)
```
