---
name: omnicli
description: "Unified tool execution gateway and JavaScript Code Mode runner. MUST USE for: (1) multi-step automation in a single turn via Code Mode (`omnicli exec plan.mjs`), (2) executing CLI tools with token shielding and field projection to prevent context flooding (`omnicli invoke <tool> --omni-project`), (3) discovering specific sub-tools and CLI scripts across the 520+ tool catalog by intent (`omnicli search`), and (4) local inference endpoints (Genesis 35B :8080, ASR :8081, decision gating :8083, LightOnOCR :8085)."
allowed-tools: "Bash(omnicli:*) Read"
---

# `omnicli` — The Uber OmniCLI

One gateway, two surfaces, one catalog. Discover a tool by *intent*, pull the
contract for that one tool, and invoke it with a bounded response — nothing
else enters the context window.

```
                  ┌── CLI (shell harnesses) ──────────────────────┐
   agent ────────▶│  omnicli search | describe | invoke | status │
                  ├── Code Mode (one plan, one turn) ────────────┤
                  │  omnicli exec plan.mjs --sandbox strict      │
                  └──────────────────────────────────────────────┘
                                        │
                        ┌───────────────▼───────────────┐
                        │  catalog.db  (control plane)   │
                        │  FTS5 BM25 + weighted aliases  │
                        │  + bge-small skill vectors     │
                        └───────────────┬───────────────┘
                                        │
                        ┌───────────────▼───────────────┐
                        │  580+ tools  (data plane)      │
                        │  scripts · CLIs · endpoints    │
                        └───────────────────────────────┘
```

---

## ⚡ The discovery loop

### 1. `omnicli search "<intent>"` — find the tool

```bash
omnicli search "transcribe a zoom lecture recording"
omnicli search "turn a recorded podcast into readable text"
omnicli search "调研一下这个话题在网上的讨论"
```

BM25 over every skill's full body + curated aliases (weight 12) matches exact
tokens; when BM25's margin is thin (`--fusion auto`), `omnicli` fuses a dense
`bge-small-en-v1.5` leg over descriptions (`K=60`) and damps multi-chunk bodies
(`OMNICLI_CHUNK_ALPHA=0.2`). Falls back cleanly to BM25 when `:8087` is offline.
See [references/retrieval-architecture.md](references/retrieval-architecture.md)
for benchmarks and ranking internals.

### 2. `omnicli describe <tool_id|skill>` — get one contract

```bash
omnicli describe zoom-recorder/scripts/zoom_download   # one tool's usage, flags, inputSchema
omnicli describe canvas-cli                             # skill frontmatter + section outline
omnicli describe canvas-cli --section "token shield"    # load only one section
omnicli spec --grep zoom --stubs                        # typed .d.ts signatures for matching tools
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
omnicli spec --grep zoom --stubs
omnicli bindings                                                      # writes omnicli_tools.mjs + .d.ts
omnicli exec -c 'const rows = await search("audio", 2); console.log(rows)'
omnicli exec plan.mjs --sandbox strict                                # write (default) | strict | none
```

```js
import { search, spec, zoom, invoke, parallel, emitResult } from "omnicli_tools";

const [notes, hits] = await parallel([
  () => zoom({ url: "https://zoom.us/rec/share/x", format: "md" }),
  () => search("audio transcription", 3),
]);
const asr = await invoke("audiocpp/scripts/audiocpp_cli", ["asr", "talk.wav"]);
emitResult({ notes: notes.output.slice(0, 200), hits: hits.length, asr: asr.exit_code });
```

- **Zero boilerplate:** `search`, `spec`, `describe`, `invoke`, `output`, `parallel`, `emitResult`, and every catalogued tool (`tool({ ... })`) are globals inside the VM; imports match `omnicli_tools.d.ts` for editors.
- **Pre-flight validation:** Every tool call validates its options object against `inputSchema` (extracted from Python `argparse`, Node `node:util` `parseArgs`, `--omni-schema`, or `--help`) and throws `TypeError` before dispatch on unknown/missing/mistyped args.
- **Containment & limits:** `write` binds `/` read-only and keeps only the workspace + `/tmp` writable; `strict` masks `$HOME`, disables network, and routes calls over a UNIX socket bridge (`exec` denied); `--max-calls` (default `100`) and opt-in `--mem-limit MiB` bound execution.

Full SDK API and authoring guidelines:
- [references/code-mode-sdk.md](references/code-mode-sdk.md) (API, sandbox modes, `--mem-limit`, examples in [examples/](examples/))
- [references/agent-skills-checklist.md](references/agent-skills-checklist.md) (Agent Skills spec, Python/JS script contract, `scripts/verify_agent_skills.py`)

---

## 🌐 Harnesses & Telemetry

| Harness | Guide | Face / Integration |
|---|---|---|
| **T3 Code** | [`harnesses/t3-code.md`](harnesses/t3-code.md) | OpenCode plugin (`omnicli_*` tools + `tools.omnicli.*`) + Code Mode |
| **Antigravity (`agy`)** | [`harnesses/agy.md`](harnesses/agy.md) | [`hooks/agy_omnicli_hook.py`](hooks/agy_omnicli_hook.py) (`PreInvocation` + `PreToolUse`) + JS bindings |
| **OpenCode** | [`harnesses/opencode.md`](harnesses/opencode.md) | [`plugin/omnicli-route.js`](plugin/omnicli-route.js) + `skills` path |
| **Pi Agent** | [`harnesses/pi.md`](harnesses/pi.md) | Direct CLI with strict 8 KB caps |
| **Boxxy Claw** | [`harnesses/boxxy.md`](harnesses/boxxy.md) | Sandboxed plans (`--sandbox strict`) + WAL-safe catalog |

```bash
omnicli harness list|detect|verify     # inspect active harnesses & run verification matrix
omnicli harness info|config <id>       # read adapter guide or ready-to-paste setup snippet
omnicli usage --since 24h --json       # per-harness telemetry from ~/.local/share/omnicli/trace.jsonl
```

---

## 🧠 Native local inference & Catalog maintenance

| Command | Tool id | Model |
|---|---|---|
| `omnicli llm "<prompt>"` | `local/llm` | Qwen3.6-35B Genesis, dual-GPU (:8080) |
| `omnicli ocr <file>` | `local/ocr` | LightOnOCR-3-0.8B (:8085) |
| `omnicli decide "<state>" "<q>"` | `local/decide` | Decision model on :8083 (auto-detects protocol) |
| `omnicli asr transcribe <audio>` | `local/asr` | Nemotron-3.5 ASR (:8081) |

```bash
omnicli status            # ports, catalog freshness, retrieval tier
omnicli index --rebuild   # rebuild catalog.db + re-extract contracts
omnicli eval              # golden routing evaluation (61 cases)
```
