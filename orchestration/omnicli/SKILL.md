---
name: omnicli
description: "Unified tool execution gateway and JavaScript Code Mode runner. MUST USE for: (1) multi-step automation in a single turn via Code Mode (`omnicli exec plan.mjs`), (2) executing CLI tools with token shielding and field projection to prevent context flooding (`omnicli invoke <tool> --omni-project`), (3) discovering sub-tools across the 580+ tool catalog by intent (`omnicli search`), and (4) local inference (`omnicli llm|ocr|decide|asr`). Port facts live in CONTEXT.md."
allowed-tools: "Bash(omnicli:*) Read"
---

# `omnicli` — The Uber OmniCLI

One gateway, two surfaces, one catalog. Discover a tool by *intent*, pull the
contract for that one tool, and invoke it with a bounded response — nothing
else enters the context window.

One control plane (`catalog.db`: FTS5 BM25, weighted aliases, dense vectors)
over 580+ tools, reached through one of two faces: bounded CLI calls
(`search` / `describe` / `invoke`) or a single JavaScript plan (`exec`) that
keeps intermediate payloads out of the context window. Ranking internals:
[references/retrieval-architecture.md](references/retrieval-architecture.md).

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
embedding leg over descriptions (`K=60`) and damps multi-chunk bodies
(`OMNICLI_CHUNK_ALPHA=0.2`). Falls back cleanly to BM25 when the embedding endpoint is offline.
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
import { search, invoke, parallel, emitResult } from "omnicli_tools";
const [hits, asr] = await parallel([
  () => search("audio transcription", 3),
  () => invoke("audiocpp/scripts/audiocpp_cli", ["asr", "talk.wav"]),
]);
emitResult({ hits: hits.length, exit: asr.exit_code }); // project; never dump raw
```

- **Zero boilerplate:** `search`, `spec`, `describe`, `invoke`, `output`, `parallel`, `emitResult`, and every catalogued tool (`tool({ ... })`) are globals inside the VM; imports match `omnicli_tools.d.ts` for editors.
- **Pre-flight validation:** Every tool call validates its options object against `inputSchema` (extracted from Python `argparse`, Node `node:util` `parseArgs`, `--omni-schema`, or `--help`) and throws `TypeError` before dispatch on unknown/missing/mistyped args.
- **Containment & limits:** `write` binds `/` read-only and keeps only the workspace + `/tmp` writable; `strict` masks `$HOME`, disables network, and routes calls over a UNIX socket bridge (`exec` denied); `--max-calls` (default `100`) and opt-in `--mem-limit MiB` bound execution.

Full SDK API and authoring guidelines:
- [references/code-mode-sdk.md](references/code-mode-sdk.md) (API, sandbox modes, `--mem-limit`, examples in [examples/](examples/))
- [references/agent-skills-checklist.md](references/agent-skills-checklist.md) (Agent Skills spec, Python/JS script contract, `scripts/verify_agent_skills.py`)

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
