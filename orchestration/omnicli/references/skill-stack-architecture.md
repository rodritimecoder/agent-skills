# Skill Stack Architecture — agentskills.io × ICM × omnicli

Three systems describe the same ladder: the [Agent Skills specification](https://agentskills.io/specification), Interpretable Context Methodology (ICM, the folder structure behind `AGENTS.md` / `CONTEXT.md`), and `omnicli` itself. They are not competing designs. They are one idea of **progressive disclosure**, encoded at three different layers.

- The **Agent Skills spec** defines the tiers *statically on disk* (what a skill folder contains).
- **ICM** defines the tiers *for a workspace* (what an agent reads, in what order, and where state lives).
- **`omnicli`** makes the tiers *dynamic and measurable* — and enforces them at runtime.

This document is the architecture-level counterpart to [agent-skills-checklist.md](agent-skills-checklist.md), which covers authoring and verification mechanics. The one-paragraph version of this argument lives in [CONTEXT.md](../../../CONTEXT.md) ("Discovery is the harness's job, not a router's"); here is the long form.

---

## 1. One ladder, three encodings

| Tier | agentskills.io | ICM / workspace | omnicli runtime | Budget |
| :--- | :--- | :--- | :--- | :--- |
| Metadata | `name` + `description` frontmatter | L0 `AGENTS.md` — *where am I?* | `omnicli search` brief line | ~100 tok metadata; 300–800 tok L0 |
| Instructions | `SKILL.md` core workflow | L1 root / L2 stage `CONTEXT.md` — *where do I go / what do I do?* | `describe <skill> --section` | <5,000 tok / <500 lines |
| Resources | `references/`, `assets/` | L3 `_shared/`, `references/` — *what rules apply?* | `invoke`, `--omni-buffer`, Code Mode variables | on demand |
| State | output files | L4 `output/`, `check.md` — *what am I working with?* | `emitState` session JSON, `check.md` | varies |

The upper tiers of each column are a **catalog**: small, stable, and holding no content payload. The lower tiers are **shelves**: the actual material. Every layer reads down until it has enough, then stops. ICM's ~8,000-token step budget and omnicli's 8 KB bounded reply are the same *discipline* — load/prevent only what the step needs — but they are an **analogy, not an equivalence**: one is a token budget on context, the other a byte cap on a single reply, enforced by different mechanisms.

Consequences that hold across all three encodings:

- **One home per fact.** A link beats a copy. Duplicated entry files drift.
- **Routing files carry no content.** When a router grows, move the payload to a shelf and leave a pointer.
- **Generated indexes are never hand-edited.** `_index.md` and `catalog.db` are rebuilt by script.
- **A pointer is not a second copy.** `GEMINI.md` holds `@./AGENTS.md`; it does not restate the routing table.

---

## 2. `description` is the L0 catalog of the skill world

Every retrieval leg sees the frontmatter `description` — and essentially nothing else at selection time. BM25 indexes it as a `skill`-kind doc row; the dense leg embeds it. It is the direct analogue of a small `AGENTS.md`: the minimum text that answers *"where do I go for task X"* while storing no content.

That makes it the cheapest lever in the whole system. Rewriting twelve descriptions in user vocabulary ("school portal", "closed source", "second opinion") moved held-out BM25 top-1 from **12/30 to 19/30** before the dense leg was involved at all ([retrieval-architecture.md](retrieval-architecture.md)).

Write it as an instruction to the agent, in user intent, with both *what* and *when*:

```yaml
description: >
  Use this skill when <user-facing intent>, even if the user does not name
  <domain keyword> explicitly.
```

Two ICM rules apply verbatim:

- **One home per fact.** Proper nouns (`deskforge`, `litellm`, `navidc`) belong in `catalog/aliases.json`, not in descriptions. `tests/overfit_check.py` reports 0 verbatim alias echoes across 389 aliases — the routing text stays clean.
- **One way in.** A tool that looks for another name gets a one-line pointer (`metadata.bins` for `~/.local/bin` aliases), never a duplicated instruction set.

Body length is a ranking bias: BM25 aggregates the best chunk per skill, so a 93-chunk body gets 93 chances against a short skill's one. `CHUNK_PENALTY_ALPHA=0.2` damps this (`chunks**-alpha`). Thick `SKILL.md` files do not just cost tokens — they distort routing.

---

## 3. `search` → `describe --section` → `invoke` is the ICM read-down

The bounded-invoke loop is a runtime implementation of "load only what the step needs":

| ICM move | omnicli call | What it keeps out of context |
| :--- | :--- | :--- |
| Read L0, route | `omnicli search "<intent>"` (brief) | the prompt shelf of every skill's full text |
| Read L2 contract | `omnicli describe <skill> --section "<heading>"` | the rest of `SKILL.md` |
| Load L3/L4 selectively | `omnicli invoke ... --omni-project a,b` | unrequested fields and full stdout |
| Run the step | `omnicli exec plan.mjs` | intermediate tool outputs |

Measured 2026-11-14 across 59 skills ([retrieval-architecture.md](retrieval-architecture.md)):

| | prompt shelf | omnicli | saving |
| :--- | ---: | ---: | ---: |
| selection phase | 10,827 tok | 1,274 tok | **88.2% smaller** |
| to invoke one tool | 13,209 tok | 4,265 tok | **67.7% smaller** |

The selection-phase number is paid on *every turn*, whether or not a tool is used. The second saving comes from the 8 KB cap. BM25 top-1 is 56/61 (91.8%) and top-3 is 61/61 on the golden set; on the paraphrase set BM25 alone is 21/39 top-1 (53.8%). The golden set shares this catalog's vocabulary — read it as a routing benchmark, not an answer-quality benchmark.

This is **prevention, not compression**. A monolithic everything-prompt loads 30k–50k tokens and then summarizes them; omnicli never loads them. The reason is operational, not aesthetic: tool selection degrades as prompt shelves grow (the Databricks study measured 88% → 52.6% past ~30 skills).

---

## 4. Code Mode is Sequence + Shelf at runtime

ICM's structural primitives — Sequence (numbered folders, one stage's output feeding the next), Shelf (same-shaped files from a template), and Catalog (a pointer file) — reappear in `omnicli exec`:

- **Sequence:** a JS plan calls tools in order and passes results as variables. The folder-numbering handoff becomes `const research = ...; const script = ...`.
- **Shelf:** typed surface functions generated from each tool's `inputSchema`; one shape, many calls.
- **Intermediate isolation:** parsing, filtering and loops run in `node:vm`, not in the prompt. Only `emitResult()` / the final `console.log()` enters context. This is the runtime form of ICM's "state is files, not conversation".
- **State on disk:** `getState()` / `emitState()` persist one JSON object across `--session ID` runs — the equivalent of a `check.md` verdict or a status line in the file it describes.
- **Typed contracts before dispatch:** unknown, missing or mistyped args throw `TypeError` at the call site. Same discipline as an ICM stage contract naming exact input paths.
- **Containment:** `strict` (default) masks `$HOME`, disables network, and bridges tool calls over a UNIX socket; `write` keeps only the workspace + `/tmp` writable; `--max-calls` (100) and `--mem-limit` bound execution.

One plan, one turn. The retired stdio MCP server exists in `archived/omnicli-mcp/` precisely because JSON-RPC round-trips burn prompt tokens while JS variables cost nothing.

### Batch multiple intents with parallel()

When you already know the batch, don't spend one CLI call per intent. `parallel()`
fans independent async thunks out inside the same one-plan/one-turn shape and
returns results **in input order**, even though the calls finish out of order.
The default concurrency limit is **8** (`parallel(calls, limit = 8)`); the call
budget is `--max-calls`, which defaults to **100**; and `strict` is the default
sandbox (network disabled, `$HOME` masked, tool calls bridged over a UNIX
socket). One failure rejects the batch as `parallel[<index>]: <message>`, so
keep intents distinguishable.

```js
import { search, parallel, emitResult } from "omnicli_tools";

const INTENTS = [
  "transcribe a zoom lecture",
  "ocr a slide",
  "route a calibrated decision",
];

const hits = await parallel(INTENTS.map((intent) => () => search(intent, 2)));
for (const [i, rows] of hits.entries()) {
  const top = rows[0] ?? {};
  console.log(`${INTENTS[i]} -> ${top.skill ?? "none"} (${top.score ?? 0})`);
}
emitResult({
  intents: INTENTS.length,
  hits: hits.map((rows, i) => ({ intent: INTENTS[i], top: rows[0]?.skill ?? null })),
});
```

`search(intent, 2)` returns ranked `SearchResult[]` rows with `.skill` and
`.score`. Check `omnicli spec --stubs` for the typed surface rather than guessing
result shapes. That matters when you chain into `describe`: a skill-level
describe returns `{ skill, kind, path, frontmatter, body_tokens, outline, tools }`,
and its outline items use `.heading` (not `.title`) — there is no `.sections` key.
Project those fields only; a projection built on `d.sections` / `s.title` would
silently emit `undefined`.

**Which face?** Use the CLI `omnicli search "<intent>"` for **one** exploratory
intent where you want to *see the ranking* and read the evidence before
deciding. Use an `omnicli exec` plan for a **known batch**, or when search is a
chain into `describe`/`invoke` whose results you filter and project in JS. Same
router, two faces: the CLI shows you the ranking; the plan keeps intermediates
out of your prompt.

---

## 5. Capability retrieval is not content retrieval

This is the boundary most likely to be misread. `omnicli search` retrieves **capabilities** — which skill or tool can do the job. It does not answer questions from your notes. Content retrieval is a different catalog with a different contract:

| Question | Correct mechanism | Why |
| :--- | :--- | :--- |
| "which tool transcribes audio?" | `omnicli search` | routing over capabilities |
| "what did Kem say about knowledge graphs?" | `python3 /run/media/rodri/AI/creator-vault/vault_index.py search --folder .../creator-vault "knowledge graphs"` | FTS5 over note bodies |
| "what superseded claim X?" | `graph-memory recall --hops 2` | k-hop entity traversal |

Kem's benchmark reel (`creator-vault/kem_glitch/2026-10-30_karpathy_llm_wikis/notes.md`) is about the *content* column: wikis cost 2×–3.35× the tokens with mostly flat accuracy, organized folders + grep matched the best at 0.97×, and a one-line citation hook moved verified answers from 70% to 92.5%. The conclusion — *"a visualizer is not a retrieval mechanism"* — does not apply to omnicli's catalog. `omnicli search` is a router over tools, not a wiki over knowledge. Conflating the two either expects graph answers from a router or expects routing from a note index.

> **Caveat — not every Kem figure is equally grounded.** The `0.97×` / `2.05×`
> ICM-vs-NVK token multipliers and the `70% → 92.5%` citation-hook figures are
> flagged **UNVERIFIED** in the vault note
> (`creator-vault/kem_glitch/2026-10-30_karpathy_llm_wikis/notes.md`, "Unverified"
> section) because they are not spoken in the reel and rest on the reel's OCR
> timeline. By contrast, the `2×–3.35×` cost range and the "only NVK improved"
> conclusion **are** grounded in the transcript — NVK "got more right ... but it
> cost about twice as much", while the other two "did no better" and one "spent
> more than three times as many tokens". Cite the transcript-backed half; flag
> the OCR-backed half.

Both are catalogs, but over different things. Keep them distinct.

One exception proves the rule: the router itself opts out of body indexing
(`index_body: false` in `catalog/aliases.json`). Its documentation is full of
example queries like `omnicli search "transcribe a zoom lecture recording"`;
indexed as routing text, the router would compete with the very skills it
routes to. This reference is therefore reachable through the SKILL.md link and
by path, not through `omnicli search`. That is deliberate, not a missing feature.

---

## 6. Authoring consequences

When adding or changing a skill, each file has one job:

1. **Frontmatter** — routing only. User intent, imperative phrasing, no content payload. Proper nouns go to `catalog/aliases.json`.
2. **`SKILL.md`** — workflow, defaults, quickstart. Under 5,000 tokens / 500 lines. Deep tables and rubrics go to `references/`, loaded via `describe --section`.
3. **`scripts/`** — runnable CLI entrypoints only. Shared helpers in `modules/` or `assets/`, tests in `tests/`, so the catalog indexes tools, not libraries.
4. **`references/`** — the factory (stable across runs). Inputs that change per run belong on disk as artifacts, not inlined here.
5. **Generated indexes** — rebuilt, never hand-edited. `catalog.db`, `_index.md`, `viz.html`.

Verification, after any skill change:

```bash
omnicli index --rebuild
omnicli spec --skill <skill-name> --stubs
python3 tests/verify_agent_skills.py --skill <skill-name> --strict
python3 tests/verify_code_mode.py --skill <skill-name>
python3 tests/skillcheck.py all
for cli in <affected entrypoints>; do python3 "$cli" --help >/dev/null || echo "BROKEN: $cli"; done
```

Then `sync-skills propagate` to refresh `surface/`, `~/.local/bin`, harnesses and the catalog, and `sync-skills publish` once the change is verified.

---

## 7. Kem lenses on Code Mode and search

Kem's ideas are about where judgment lives and how a run proves itself; they
attach at the routing/plan boundary, not inside the gateway. None of them
require framework code — they are conventions over the same one-plan/one-turn
shape.

| Kem idea | omnicli seam | What to do |
| :--- | :--- | :--- |
| Evidence before invoke | Code Mode `search()` hit | Name `why`/`matched`/`top` in the plan and project them into `emitResult` before invoking. |
| Actor / Step type / Proof | every plan call | Comment Actor, `D`/`P`/`H` and Proof above each call; emit a `proof` field per step. |
| Negative controls | `omnicli eval` sets | Pair each positive routing case with a must-not-trigger prompt; require a failing gate. |
| Fail → align | routing failure | Re-ask which skill owns the phrasing and re-plan; never add a one-off alias. |
| Concealed holdouts | plan read scope | Keep expected results outside the plan; compare only at verify time. |
| Factory vs product | aliases/descriptions vs per-run intents | Curate the factory across runs; never mutate it to fit one run. |

### Evidence before invoke

A Code Mode `search()` hit has exactly these keys (verified live): `skill`,
`score`, `matched`, `why`, `top`, `chunk_count`. Do not invoke on a hit until
you have named `why`, `matched` and `top` in the plan and projected them into
`emitResult` — that makes the routing decision auditable. Call this the citation
hook: provenance enforcement is cheaper than knowledge synthesis. One drift to
note, not fix here: `retrieval-architecture.md:46` claims every result names
`found_by`, but the Code Mode result has no such key; rely on
`why`/`matched`/`top` and treat `found_by` as stale doc text (do not edit that
file). Do not re-state `70% → 92.5%` as verified — section 5 flags it OCR-backed.

### Actor / Step type / Proof

The local Kem contract (`icm-architect`): every step names its Actor (code,
agent or human), its Step type (`D` deterministic, `P` probabilistic, `H` human)
and its Proof. In a plan, write these as short comments above each call and emit
a `proof` field per step in the result envelope. A `[D]` step names its command;
a `[P]` step names the model call; an `[H]` step names what a person signs off.
Nothing moves on without the proof its step declares.

### A gate that can fail

`omnicli eval` ships golden and paraphrase sets, but neither declares an
explicit should-not-trigger negative control (grep finds "control" only in an
unrelated browser note). A gate that cannot fail is not a gate: pair every
positive routing case with a prompt that must NOT select the same skill, run
both in one harness, and require a non-zero exit when the negative control
mutates. This is `kem-dev-loop`'s positive-and-negative-in-one-script pattern.

### Fail to align, never patch

When routing fails, do not add a one-off alias to make that single query pass —
that is the overfitting `tests/overfit_check.py` exists to catch (0 verbatim
alias echoes across 389 aliases). Go back to intent: which skill *should* own
this phrasing? Then re-plan. The same rule protects the factory/product split:
curated aliases and descriptions are the factory, per-run intents the product;
mutating the factory to fit one product run is decay.

### Concealed holdouts

A plan that can read its own acceptance tests builds to pass them. Keep the
expected result outside the plan's read scope and compare only at verify time.
This is `icm-architect`'s agentic-factory holdouts shelf, applied to a plan
rather than a workspace.

What this does NOT mean: these are plan-time disciplines, not a new runtime layer — the gateway stays one catalog, two faces.

---

## Read next

- [agent-skills-checklist.md](agent-skills-checklist.md) — frontmatter rules, script contract, verification gates
- [retrieval-architecture.md](retrieval-architecture.md) — BM25/dense fusion, benchmarks, provenance
- [code-mode-sdk.md](code-mode-sdk.md) — the generated SDK, sandbox modes, `parallel`, state
- [discovery_and_invoke.mjs](../examples/discovery_and_invoke.mjs) — search + spec in one plan
- [in_memory_filter.mjs](../examples/in_memory_filter.mjs) — project in JS, emit one result
- [harnesses/index.md](../harnesses/index.md) — how the same contract maps onto each host harness
- `icm-architect` skill — `references/core.md` for the five-layer hierarchy and contract format
