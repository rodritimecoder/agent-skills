---
name: omnicli

description: "Unified tool execution gateway and Python Code Mode runner. MUST USE for: (1) multi-step automation in a single turn via Code Mode (`omnicli exec plan.py`), (2) executing CLI tools with token shielding and field projection to prevent context flooding (`omnicli invoke <tool> --omni-project`), (3) discovering specific sub-tools and CLI scripts across the 520+ tool catalog by intent (`omnicli search`), and (4) local inference endpoints (Genesis 35B :8080, ASR :8081, decision gating :8083, LightOnOCR :8085)."

compatibility: "Requires the local inference servers it fronts: :8080, :8081, :8083, :8084 and :8085, plus the optional embedding server :8087, which supplies the dense leg of hybrid search (the catalog works without it, on BM25 alone). The decision port speaks either native /v1/systemone or the pplx-decider joint protocol v3; the protocol is auto-detected from the served model."
allowed-tools: "Bash(omnicli:*) Read"
---

# `omnicli` — The Uber OmniCLI

One gateway, two surfaces, one catalog. An agent discovers a tool by *intent*,
pulls the contract for that one tool, invokes it, and gets a bounded response.
Nothing else enters the context window.

```
                  ┌── CLI (shell harnesses) ──────────────────────┐
   agent ────────▶│  omnicli search | describe | invoke | status │
                  ├── Code Mode (one plan, one turn) ────────────┤
                  │  omnicli exec plan.py --sandbox strict       │
                  └──────────────────────────────────────────────┘
                                        │
                        ┌───────────────▼───────────────┐
                        │  catalog.db  (control plane)   │
                        │  FTS5 BM25 + weighted aliases  │
                        │  + bge-small skill vectors     │
                        └───────────────┬───────────────┘
                                        │
                        ┌───────────────▼───────────────┐
                        │  474 tools  (data plane)       │
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

BM25 over the **full body** of every skill, with hand-curated aliases in a
separately weighted column. A curated alias ("podcast" → audio tooling) is
deliberate author intent and outranks incidental prose.

```
🔍 [omnicli] intent: 'transcribe a zoom lecture recording'   tier=bm25(gated)

  1. zoom-recorder   score=0.91  lex=34.25  coord=0.75  chunks=22
       zoom-recorder/scripts/zoom_download
       Download transcripts, audio, and visual keyframe slides from Zoom cloud...
       → omnicli tools zoom-recorder
```

### Two legs, fused by rank

BM25 plus curated aliases is close to saturated on the golden set, and it is
the leg that matches exact tokens (`:8083`, `canvas-cli`). What it cannot do is
recognise a paraphrase. The second leg embeds each skill's **description** with
`bge-small-en-v1.5` (384d, `-ngl 0` — CPU only, zero VRAM) and the two rankings
are fused with reciprocal rank fusion, `K=60`.

`fusion=auto` fuses only when BM25's own margin is thin (below
`RERANK_GATE_MARGIN`), because fusion buys unseen phrasings and costs tuned
ones:

| mode | golden top-1 | held-out top-1 | median latency |
|---|---|---|---|
| `--fusion never` | 59/61 | 24/30 | 3.8 ms |
| `--fusion auto` (default) | 56/61 | 26/30 | 4.5 ms |
| `--fusion always` | 52/61 | 28/30 | 12.8 ms |

The golden set shares this catalog's vocabulary, so the lexical leg wins it.
The held-out set is paraphrased intent, authored by this catalog's own author —
which means it is **a ceiling, not a forecast**: the descriptions were written
with those 30 queries in view. Read it as "the mechanism responds", not as an
expected accuracy.

### The description field is the cheapest lever

Frontmatter `description` is the only per-skill text both legs see: BM25
indexes it as a `skill`-kind doc row, and the dense leg embeds it. The Agent
Skills spec asks for exactly the two things routing needs — *"when to use it"*
and *"specific keywords that help agents identify relevant tasks"*.

Twelve descriptions rewritten to that pattern (same claims, plus user
vocabulary and one differentiator apiece) moved held-out BM25 from 12/30 to
19/30 before any dense leg was involved, at a cost of one golden case. The
useful vocabulary is the user's ("school portal", "closed source", "second
opinion"), not the system's.

### Distilled questions: built, measured, left off (negative result)

Cerebras' internal RAG found embeddings over raw text insufficient and fixed it
by embedding *the question someone would search for* — "a question meets a
question". That was applied here: 228 questions across 55 skills, generated in
six parallel batches, each carrying a verbatim quote from its own description.
The gate is code (`catalog/questions.py`): the quote must be a real span, the
question may not name the skill, and it must sit within 0.45 cosine of its own
description embedding. A deliberately off-topic question with a valid stolen
quote is rejected, and a test asserts it.

The routing effect is **zero**:

| rows embedded | golden top-1 (auto / always) | paraphrase top-1 (auto / always) |
|---|---|---|
| description only | 55/61 · 53/61 | 24/39 · 26/39 |
| description + questions | 56/61 · 52/61 | 24/39 · 26/39 |

Why it cannot be converted: on this corpus **every BM25 top-1 miss is also a
dense top-1 miss** — the oracle rescue potential is 0/61 on golden and 3/39 on
paraphrase. Fusion has nothing to promote. Questions alone are weaker than
descriptions (dense top-1 34/61 golden, 12/39 paraphrase, versus 46/61 and
16/39), and max-pooling both buys paraphrase recall (16→18) by spending golden
precision (46→42).

Two levers explain it. Descriptions were already rewritten with the user's
vocabulary, which is the same fix questions apply, so the headroom was spent.
What remains in the paraphrase misses is *proper nouns* — `deskforge`,
`litellm`, `navidc` — and those belong in the curated alias column (weight 12),
not in an embedding.

So the snapshot ships, and stays off: `OMNICLI_QUESTIONS=1 omnicli index`.
`omnicli questions <skill>` lists the questions and re-checks each quote against
the current description, so an edited `SKILL.md` cannot leave a stale claim
indexed. The machinery is kept because it is cheap, reversible, and the next
corpus that has not already spent the description lever may not be neutral.

### Body length is a ranking bias

BM25 normalises per chunk (`b=0.75`), but aggregation takes the best chunk per
skill, so a 93-chunk body gets 93 chances at one good chunk while a 1-chunk
skill gets one. `CHUNK_PENALTY_ALPHA` (default `0.2`, env
`OMNICLI_CHUNK_ALPHA`) damps the score by `chunks**-alpha`, which removed the
`icm-architect` hijack of generic queries. Measured: held-out `fusion=always`
top-3 went 29/30 → 30/30 and top-1 26/30 → 28/30 between alpha 0 and 0.2, for
one golden case. Above 0.3 the tuned set starts paying for it.

Every result names the legs that found it (`found_by`) and the fused score is
normalised to 0-1 while `lexical_score` keeps the BM25 value. When :8087 is
down the tier says `bm25 (dense offline)`, `dense.reason` carries the error,
and the result set is exactly what BM25 found — retrieval gets worse, it does
not fail. Vectors are keyed to a fingerprint of each description, so an edited
`SKILL.md` re-embeds on the next `omnicli index` without a full rebuild.

### Discovery does not imply exposure

A tool is catalogued the moment it is discovered, and runnable only once it
has been enabled. `omnicli tools` marks disabled tools, `omnicli describe`
still returns their contract, and `omnicli invoke` refuses them with the exact
command that would open the gate:

```bash
omnicli policy            # 367/474 enabled, plus the recent decisions
omnicli enable <tool_id>  # record the decision against the contract hash
omnicli disable <tool_id>
```

Tools that existed when the gate was introduced were grandfathered; tools new
relative to the previous catalog start disabled. The decision log
(`policy.log.jsonl`) is append-only and survives a rebuild.

### 2. `omnicli describe <tool_id>` — get one contract

```bash
omnicli describe zoom-recorder/scripts/zoom_download
```

Returns the usage line, every flag, positionals and subcommands — extracted
from the tool's own `--help` at index time. **One** tool per call.

Given a **skill name** instead of a tool id, it returns the skill itself: its
frontmatter and a section outline, with a token estimate per section. Add
`--section "<heading>"` to read just that one section.

```bash
omnicli describe canvas-cli
# 📖 [canvas-cli]  ~739 tokens, 13 sections, 22 tools
#    Sections:
#      Canvas LMS (`canvas-cli`)                          60 tok
#        🏛️ The Command Groups                            187 tok
#        🛡️ Token Shielding                               121 tok
#    Read one:  omnicli describe canvas-cli --section "token shield"

omnicli describe canvas-cli --section "token shield"
# 📖 [canvas-cli] section: 🛡️ Token Shielding  (~121 tokens)
```

This is the spec's progressive disclosure, routed through the gateway: the
outline first, then one section. A skill's body is never fetched whole unless
that is what you ask for.

`omnicli spec --grep <re> --stubs` is the wide-angle version: annotated
signatures for every matching tool, in one bounded reply. It is what an agent
reads before writing a plan, and `spec(grep=...)` returns the same thing
*inside* the plan.

The skills themselves are **never modified**. The catalog is an index over
them: it reads the files, it does not own them. Delete `catalog.db` and every
skill still works exactly as before.

### 3. `omnicli invoke <tool_id> [args]` — run it, bounded

```bash
omnicli invoke zoom-recorder/scripts/zoom_download -- --url "https://zoom.us/rec/abc"

# keep only the fields you need
omnicli invoke local/decide --omni-project "answer,confidence"

# keep the full payload on disk, read only what matters
omnicli invoke local/llm --omni-buffer /tmp/out.md
```

**Every response is capped** (default 8 KB) with a head+tail preview and a
pointer to the full output. An agent cannot flood its context window by
forgetting a flag.

**Flag names are prefixed `--omni-`** so they never collide with the target
tool's own flags (`--out`, `--project` and `--json` are all real flags on
real tools here). Anything after the tool id that is *not* `--omni-*` is
passed to the tool untouched; `--` forces that split explicitly.

| Flag | Effect |
|---|---|
| `--omni-buffer FILE` | write the full, **unfiltered** stdout to a file, print a preview |
| `--omni-project a,b.c` | keep these JSON fields; dotted paths and list elements supported |
| `--omni-jq EXPR` | JQ filter expression |
| `--omni-grep RE` | keep only matching lines |
| `--omni-max-bytes N` | hard cap on returned bytes (default 8000) |
| `--omni-json` | wrap the result in JSON |

A cap is a budget to fill, not a reason to return only a banner: at 250 bytes
the reply is 250 bytes of head, banner and tail. A projection that cannot be
applied says so; it never returns the unfiltered payload as though it worked.
Unknown `--omni-*` flags are reported instead of silently dropped.

---

## 🐍 One plan, one turn — `omnicli exec`

Step 3 is one tool call per turn. When a job has several steps, write one
Python plan instead: the intermediates stay in variables and only what you
print comes back.

```bash
omnicli spec --grep zoom --stubs   # the typed surface for just those tools
omnicli bindings                   # writes ~/.local/share/omnicli/bindings/omnicli_tools.py
omnicli exec -c 'from omnicli_tools import search; print(search("audio", limit=2))'  # inline
cat plan.py | omnicli exec -       # piped stdin
omnicli exec plan.py               # runs file in bubblewrap; prints only the plan's stdout
omnicli exec plan.py --sandbox strict
```

```python
from omnicli_tools import search, spec, zoom, invoke

print(len(spec(grep="zoom")))            # query 481 contracts without loading them
zoom(url="https://zoom.us/rec/share/x", format="md")   # one annotated function per tool

rows = search("audio transcription", limit=3)          # discovery inside the plan
print(invoke(f"{rows[0]['skill']}/scripts/audiocpp_cli", "asr", "talk.wav")["output"][:200])
```

Every catalogued tool is generated as a function with the flags, metavars and
choices recovered from its own `--help`: `url: str` is required, `format` is
`Literal["md","vtt","txt","all"]`, `video` is a bool. A wrong argument fails
at import time, not at call forty.

| Property | Behaviour |
|---|---|
| **Policy** | every call shells out to `omnicli invoke`, so the enable gate, projection and 8 KB cap still apply |
| **Surface** | one annotated function per tool, plus `spec()` to filter the catalog in-plan |
| **Discovery** | `search()`, `spec()` and `describe()` are callable *inside* the plan — definitions never enter the window |
| **Isolation (`write`)** | bubblewrap: writes land only in the workspace and an ephemeral `/tmp`; `/` is read-only |
| **Isolation (`strict`)** | no network, home masked, and every tool call crosses one UNIX socket to the parent; the plan holds no credentials and cannot open a socket |
| **Isolation (memory)** | `--mem-limit MiB` is opt-in: unset is no cap at all. Because the right number belongs to the plan (a 64 MiB one-liner and a 200 MiB allocation cannot share a default), setting it caps `RLIMIT_AS` for the plan and every child it spawns |
| **Allowlist** | a strict plan can reach `search`, `list`, `tools`, `describe`, `invoke`, `policy`, `spec` — `exec` is refused with rc 126 and recorded in `bridge_denied` |
| **Concurrency** | sync calls are serial; `parallel()` runs the `a*` twins at once (default fan-out 8), so ten independent calls cost about one call's latency |
| **Call budget** | `--max-calls` (default 100, `0` = unlimited) reserves each slot *before* dispatch; over budget raises `RuntimeError` at the call site naming the count and the calls just made |
| **Result** | `emit_result(value)` sends one value back on its own channel: `exec --json` reports it under `result`, while `stdout` stays the plan's printed text |
| **Trace** | each call appends a `kind=call` row (with `t`) and then a `kind=done` row (with `ms`, `rc`) to `.omnicli_trace.jsonl`; `exec --json` reports `tool_calls`, `bridge_calls`, seconds and bytes |
| **Escape hatch** | `--no-sandbox` runs unsandboxed; `--workspace DIR` chooses the writable root |

Token arithmetic: a 9-step job becomes **one** model turn. The plan's own
reads and writes never cross the boundary.

See [references/code-mode-sdk.md](references/code-mode-sdk.md) for the full SDK API reference, and inspect runnable scripts in [examples/](examples/). The run that added budgets, fan-out and the memory cap is recorded in [references/plan-code-mode-limits.md](references/plan-code-mode-limits.md).

---

## 🌐 First-party harness adapters

`omnicli` ships first-party adapter specifications and verification gates for every
workstation harness in the `harnesses/` directory:

| Harness | Guide | Primary Face | Key Primitives |
|---|---|---|---|
| **T3 Code** | [`harnesses/t3-code.md`](harnesses/t3-code.md) | Native tools + Code Mode | `omnicli_*` tools, `omnicli exec` plans, `html_preview` visuals, reactive wakeups |
| **Antigravity CLI (`agy`)** | [`harnesses/agy.md`](harnesses/agy.md) | Hooks + Python Bindings | `PreToolUse` gate, `PreInvocation` routing, `run_workflow`, subagents |
| **OpenCode** | [`harnesses/opencode.md`](harnesses/opencode.md) | Native tools + Code Mode | `omnicli_*` plugin tools, skills path, local daemons (:8080-:8085) |
| **Pi Agent** | [`harnesses/pi.md`](harnesses/pi.md) | Direct CLI | Fast sub-10ms terminal tool calls, strict 8KB token budget cap |
| **Boxxy Claw** | [`harnesses/boxxy.md`](harnesses/boxxy.md) | Direct CLI + Sandbox | Bubblewrap sandboxing (`--sandbox strict`), hot-reloading, WAL safety |

### Native tools in OpenCode and T3 Code

Both harnesses reach the catalogue as native tools, not as a shell hop. The
plugin registers `omnicli_search`, `omnicli_describe`, `omnicli_invoke`, and
`omnicli_exec` with `codemode: true` (so Code Mode sees `tools.omnicli.*`),
injects the routing rule, and denies skill-directory discovery until a
catalogue call has run.

```bash
ln -sf ~/src/my-agent-skills/orchestration/omnicli/plugin/omnicli-route.js \
  ~/.config/opencode/plugins/omnicli-route.js
opencode reload
omnicli harness verify t3-code   # includes native_tool_plugin
```

Source: [`plugin/omnicli-route.js`](plugin/omnicli-route.js). Bypass metrics:
`python3 scripts/route_stats.py` over `~/.local/share/omnicli/route.jsonl`.

### Deterministic hooks in Antigravity (`agy`)

Antigravity uses native lifecycle hooks in `~/.gemini/config/hooks.json` under
`omnicli-route` to enforce Kem's Law (*"a skill is instructions; a hook is code
that ALWAYS runs"*):
- `PreInvocation`: Injects `[omnicli route]` into prompt context.
- `PreToolUse`: Intercepts `view_file` and shell commands reading `my-agent-skills`
  and denies them until `omnicli search` has been called.

```bash
omnicli harness verify agy   # includes agy_route_hook
```

Source: [`hooks/agy_omnicli_hook.py`](hooks/agy_omnicli_hook.py).

### Harness operations

```bash
omnicli harness list       # overview of harnesses, detection status, and config paths
omnicli harness detect     # inspect active environment variables and process trees
omnicli harness info <id>  # display guide, protocol details, and config snippet
omnicli harness config <id># emit raw ready-to-paste configuration snippet
omnicli harness verify     # run automated verification across all 5 harnesses
```

---

## 🧠 Native local inference

Available both as subcommands and as tools in the catalog:

| Command | Tool id | Model |
|---|---|---|
| `omnicli llm "<prompt>"` | `local/llm` | Qwen3.6-35B Genesis, dual-GPU (:8080) |
| `omnicli ocr <file>` | `local/ocr` | LightOnOCR-3-0.8B (:8085) |
| `omnicli decide "<state>" "<q>"` | `local/decide` | the decision model on :8083, protocol auto-detected (pplx-decider-flash v1.2 or vllm-d3-mini) |
| `omnicli asr transcribe <audio>` | `local/asr` | Nemotron-3.5 ASR (:8081) |

```bash
omnicli status            # ports, catalog freshness, retrieval tier
omnicli index --rebuild   # rebuild the catalog
omnicli eval              # golden routing evaluation
```

---

## 🧭 Why this exists

Thirty-plus skills, each with its own `SKILL.md`, used to be a prompt shelf.
The Databricks skill-shadowing study measured the cost: correct skill
selection fell from 88% to 52.6% as the library grew, with **two thirds of
the failures caused by picking wrong or picking nothing** — not by token
count. The router had to evaluate dozens of frontmatter descriptions on turn 0.

Retrieval beats installation. The catalog moves selection off the model's
shoulders and onto a BM25 index, and the golden evaluation in `tests/` is the
falsifiable claim that it works:

```
BM25 catalog    top1 59/61 (96.7%)   top3 61/61 (100%)
legacy scorer   top1 35/61 (57.4%)   top3 46/61 (75.4%)
```

The miss is a generic-token query ("decide which model should handle this
prompt before answering") where the decision skill matches all six tokens and
the router matches four; neither leg separates them. It is recorded, not
excluded.

The alias set is audited against the eval set (`tests/overfit_check.py`) so a
router handed the answer key cannot be mistaken for a router that works. It
currently reports **0** echoes; three verbatim-echo aliases were removed, and
the case one of them propped up is the miss above.

**That 96.7% is a tuned-set number and should be quoted as one.** 32 of the 61
queries share a curated alias string, so the set measures whether the
vocabulary was written down, not whether a stranger's phrasing lands. The
held-out set scores 24/30 on BM25 alone — and that number is itself optimistic,
because the descriptions were written with those queries in view. Both are
true; neither predicts a stranger's results. `omnicli eval --fusion
auto|always|never` and `--rerank auto|always|never` re-run the set under either
semantic mode.

### Token cost (measured)

`tests/measure_tokens.py` counts what actually lands in the model's context,
using the local Qwen3.5 tokenizer against the 45-skill library:

| | prompt shelf | omnicli | |
|---|---|---|---|
| selection phase | 8,208 tok | 691 tok | **91.6% smaller** |
| to invoke one tool | 9,326 tok | 2,890 tok | **69.0% smaller** |

The second row's saving comes from the 8 KB response cap, not from the
discovery itself. The selection-phase number is the one that matters, because
it is paid on every turn whether or not a tool gets used.

---

## 🔌 Compatibility

`uber`, `local-hub` and `skills-hub` are **not** installed any more; they were
deprecated aliases and have been removed from `PATH`. `omnicli` is the name.
The legacy `search` / `tools` / `inspect` / `run` verbs still work; `search`
uses the BM25 catalog instead of the old substring scorer.

---

## 🏛️ Architectural References & Provenance

1. **Uber's MCP Gateway**: [Designing an MCP Gateway](https://www.uber.com/au/en/blog/designing-mcp-gateway/)  
   *Architecture*: AutoCrawler catalog ingestion → SQLite FTS registry → 4 core meta-tools (`discover`, `describe`, `invoke`, `status`) → bounded responses with byte caps and JSON projections. Eliminates catalog bloat and context poisoning across large fleets of tools.
2. **Cloudflare's Code Mode**: [Code Mode: execute code to invoke tools instead of LLM function calling](https://blog.cloudflare.com/code-mode/)  
   *Architecture*: Replaces multi-step JSON function calling roundtrips with sandboxed code execution (`omnicli exec`) against typed SDK bindings (`omnicli_tools.py`). Intermediates stay in memory; only synthesized results enter context.
3. **MCP, evaluated and removed.** A stdio JSON-RPC server was built, tested (28
   conformance checks) and retired: routing intermediate data across round-trips
   burns prompt tokens and causes quadratic context decay, while Python variables
   cost nothing. The code is preserved at `archived/omnicli-mcp/` for reference,
   not wired to any verb.

