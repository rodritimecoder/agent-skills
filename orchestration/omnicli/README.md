# omnicli

**The Uber OmniCLI** — one late-binding gateway to every tool on this
workstation. Discover by intent, pull one contract, invoke with a bounded
response.

---

## Install

```bash
ln -sfn ~/src/my-agent-skills/orchestration/omnicli/omnicli.py ~/.local/bin/omnicli
```

---

## The loop

```bash
omnicli search "turn a recorded podcast into readable text"
omnicli tools audiocpp
omnicli describe audiocpp/scripts/audiocpp_cli
omnicli invoke audiocpp/scripts/audiocpp_cli asr speech.wav --json
```

When a job has several steps, do not spend a turn per call — write one plan:

```bash
omnicli spec --grep zoom --stubs   # the typed surface for just those tools
omnicli bindings                   # generate omnicli_tools.py
omnicli exec plan.py               # run the whole job in one turn, sandboxed
omnicli exec plan.py --sandbox strict
```

The plan imports `search`, `spec`, `describe`, `invoke`, and one annotated
function per catalogued tool — `zoom(url=..., format="md")` fails at import
time on a misspelled argument instead of at call forty. Intermediate values
stay in variables and only `print()` reaches the model. `exec --json` reports
how many tool calls the plan made, how long it took, and whether bubblewrap
confined it.

Three sandbox modes, and the difference is a capability boundary, not a
convenience flag:

| Mode | Filesystem | Network | Tool calls |
|---|---|---|---|
| `write` (default) | `/` read-only, workspace writable | open | direct subprocess |
| `strict` | home masked, workspace + bindings only | **none** | every call crosses one UNIX socket to the parent, which holds the credentials |
| `none` | unconfined | open | direct subprocess |

In `strict`, the plan cannot read `~/.ssh`, cannot open a socket, and can
only reach the verbs on the bridge allowlist (`search`, `list`, `tools`,
`describe`, `invoke`, `policy`, `spec`). `exec --sandbox strict --json`
reports `bridge_calls` and `bridge_denied`, so a refused verb is evidence
rather than a silence.

Everything takes `--json` for agent consumption. `search --json` returns the
compact routing view (skill, score, matched terms, one line of evidence);
`--chunks` returns every matching chunk when you actually want to read them —
25 KB versus 2.3 KB for the same query.

### Discovery does not imply exposure

A tool is *discoverable* as soon as it is catalogued, and *runnable* only
after it has been enabled:

```bash
omnicli tools zoom-recorder        # lists tools, marks [disabled] ones
omnicli describe <tool_id>         # the contract still works when disabled
omnicli enable <tool_id>           # record the decision, expose the tool
omnicli policy <tool_id>           # state, contract hash, decision history
```

Tools that already existed when the gate was introduced are grandfathered;
a tool that is new relative to the previous catalog starts disabled. Every
decision is appended to `policy.log.jsonl` with the contract hash it was made
against, so an enablement is reviewable and reversible. The policy file
(`policy.json`) is the source of truth and survives a catalog rebuild.

### `invoke` flag names

The gateway's own flags are prefixed `--omni-` so they never collide with the
target tool's flags — `--out`, `--project` and `--json` are all real flags on
real tools in this collection. Everything after the tool id that is not
`--omni-*` is passed to the tool untouched. An unknown `--omni-*` flag is
reported rather than silently dropped.

```bash
omnicli invoke local/decide --omni-project "answer,confidence" --omni-max-bytes 2000
omnicli invoke zoom-recorder/scripts/zoom_download --omni-buffer /tmp/zd.md -- --url "..."
```

| Flag | Effect |
|---|---|
| `--omni-buffer FILE` | write the **full, unfiltered stdout** to a file, print a preview |
| `--omni-project a,b.c` | keep these JSON fields; dotted paths and list elements supported |
| `--omni-jq EXPR` | jq filter expression |
| `--omni-grep RE` | keep only matching lines |
| `--omni-max-bytes N` | hard cap on the returned bytes (default 8000) |
| `--omni-json` | wrap the result in a JSON envelope |

The cap is a guarantee, not a suggestion: the returned payload is never larger
than `--omni-max-bytes`, at any cap size, with or without `--omni-json`. A
small cap fills its budget with head and tail rather than returning only the
elision notice. A projection that cannot be applied says so on stderr; it
never silently returns the unfiltered payload as if it had worked.

---

## Layout

```
omnicli/
├── omnicli.py            # CLI entrypoint (Face A)
├── catalog/              # the control plane
│   ├── builder.py        # indexer -> catalog.db (schema v3, enable gate)
│   ├── search.py         # BM25 + coordination + optional re-ranker
│   ├── argspec.py        # contract -> typed parameters -> one function per tool
│   ├── bridge.py         # strict-mode capability socket + sandbox shim
│   ├── bindings.py       # generated omnicli_tools.py (spec + typed surface)
│   ├── invoke.py         # shared projection / cap / execution
│   ├── policy.py         # the enable gate + append-only audit log
│   ├── health.py         # shared service probe (HTTP-first, tailnet-aware)
│   ├── registry.py       # skill & tool discovery, --help contract extraction
│   ├── legacy.py         # the old substring scorer, kept for benchmarking
│   ├── textutil.py       # CJK bigram segmentation
│   ├── aliases.json      # hand-curated synonyms per skill
│   └── schema.sql
├── scripts/              # llm_client.py, ocr.py, decide.py, asr.py
│   └── mcp_server.py     # Face B: JSON-RPC 2.0 over stdio, 4 meta-tools
└── tests/
    ├── golden_eval.json  # 61 intent -> skill routing cases
    ├── eval_runner.py    # measures the catalog against the legacy scorer
    ├── overfit_check.py  # rejects aliases that echo a golden query
    ├── compare_pickers.py # shelf (frontmatter) vs gateway, same model
    ├── test_catalog.py   # 54 unit tests
    ├── test_mcp.py       # 28 stdio conformance checks
    └── sweep.py          # tunes the weight constants
```

The catalog itself is a derived artifact and lives outside the repo:

```
~/.local/share/omnicli/catalog.db
```

Rebuild it with `omnicli index --rebuild`. It is rebuilt automatically
whenever the skill collection changes.

---

## Retrieval

```
BM25 (FTS5)  →  top-200 chunks
   ↓ per-skill aggregation: best chunk × bounded coverage bonus
   ↓ coordination factor: which DISTINCT query terms matched, weighted by
   ↓                      skill-level IDF (rare term ≫ common term)
top-N candidates
   ↓ optional embedding re-ranker (:8087) — reorders only, never recalls
top-K
```

The re-ranker is **optional and additive**. With every inference server down,
search still works: BM25 alone is the baseline, not a degraded mode.

Curated aliases live in their own FTS5 column with a much higher weight than
prose. A curated alias is the skill author stating "this vocabulary routes
here"; incidental body text matching the same word says far less, and must
not out-vote it.

---

## Verify

```bash
omnicli eval              # golden routing evaluation
omnicli eval --verbose    # per-case detail
```

```
BM25 catalog    top1 60/61 (98.4%)   top3 60/61 (98.4%)
legacy scorer   top1 35/61 (57.4%)   top3 46/61 (75.4%)
```

The one miss is a generic-token query — "decide which model should handle
this prompt before answering" — where `pplx-decider` matches all six tokens
and `eval-router` matches four. The re-ranker does not separate them either.
It is recorded rather than papered over.

`tests/overfit_check.py` audits the alias set against the eval set and
fails if any alias is a verbatim echo of a golden query — a router that is
handed the answer key measures nothing. It currently reports **0**; three
echoes were removed, and the case one of them was propping up is the miss
above.

---

## MCP

```bash
omnicli mcp
```

JSON-RPC 2.0 over stdio. Four meta-tools: `omni_discover`, `omni_describe`,
`omni_invoke`, `omni_status`. Hand-rolled stdlib transport — the required
subset is small and stable, and it keeps the control plane dependency-free.

Every reply is bounded by `max_bytes`, not just `omni_invoke`: an oversized
reply is refused with a structured error instead of being truncated into
unparseable JSON. `omni_discover` returns a compact routing view (1.8 KB for
five skills, down from 13 KB) and honours `fusion` and `rerank`. Requests are
handled on a small pool, so a long tool call cannot stall `ping` or another
client request.

---

## 🏛️ References & Provenance

- **Uber's MCP Gateway**: [Designing an MCP Gateway](https://www.uber.com/au/en/blog/designing-mcp-gateway/) — Late-binding discovery, catalog registration, 4 core meta-tools, response bounding and projection.
- **Cloudflare's Code Mode**: [Code Mode: execute code to invoke tools instead of LLM function calling](https://blog.cloudflare.com/code-mode/) — One-plan-one-turn execution via generated Python bindings (`omnicli_tools.py`) inside Bubblewrap sandbox (`omnicli exec`). Full guide: [references/code-mode-sdk.md](references/code-mode-sdk.md).

