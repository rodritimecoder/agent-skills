# Plan — distill, then embed: question vectors for the dense leg

Status: **built and measured — negative result, shipped off by default.**
Source of the idea: Kem Glitch's Cerebras RAG artefact
(`creator-vault/kem_glitch/artefacts/02_cerebras_rag`), where embeddings over raw
threads underperformed embeddings over *the one question someone would search
for* — "a question meets a question" — and every entry carries a verbatim quote
(no quote, no entry).

## Outcome (2026-11-08)

228 questions across 55 skills, generated in six parallel free-model batches and
gated by code. Routing changed by zero: golden 55→56 auto / 53→52 always,
paraphrase 24→24 and 26→26. Dense-alone paraphrase improved 16→18 while golden
fell 46→42, and **the oracle rescue potential is 0/61 on golden, 3/39 on
paraphrase** — every BM25 top-1 miss is also a dense top-1 miss, so no fusion
weighting can convert the gain. Descriptions already carried the user's
vocabulary; what remains in the misses is proper nouns (`deskforge`, `litellm`),
which belong in the curated alias column.

Acceptance gate was "held-out +3 with golden −1 or better": not met, so the
snapshot ships disabled (`OMNICLI_QUESTIONS=1` opts in) and the default ranking
is untouched.


## Why this and not "a better model"

The dense leg embeds each skill's **description**, and it is the weaker leg:
45/61 golden top-1, 18/30 held-out. The known levers were measured already:
chunk bodies beat descriptions by −9 points and cost 3× the embedding time.
What is left is a *length and register mismatch* — a 60-word author
description compared against a 5-word agent intent. That is the thing
questions fix, and it is orthogonal to the model swap this catalog has already
tuned.

## Decisions taken

| Fork | Decision |
|---|---|
| Which legs see the questions | **Dense only.** BM25 is unchanged so the measured delta is attributable and the golden set stays defensible. |
| Where generation runs | **One hosted-model pass**, snapshot committed. Genesis 35B stays the free fallback for regeneration; no query-time or build-time dependency on either. |

## Shape

```
build time                          query time
──────────                          ──────────
55 skills × 4-5 questions            intent ──► embed (Q_PREFIX)
      │                                   │
      ▼                                   ▼
quote gate (code) ──► embed ──► skill_vectors (kind='question')
                                      │
                          max-pool cosine per skill
                                      │
                          RRF K=60 with BM25 (unchanged)
```

### Schema v4

Derived artifact — migration is a rebuild, no data to preserve.

```sql
CREATE TABLE IF NOT EXISTS skill_vectors (
    skill       TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- 'description' | 'question'
    ord         INTEGER NOT NULL,       -- 0 for the description anchor
    text        TEXT NOT NULL,          -- exactly what was embedded
    quote       TEXT,                   -- verbatim source span; NULL fails the gate
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,          -- sha256(model \x00 text)
    vec         BLOB NOT NULL,
    built_at    TEXT NOT NULL,
    PRIMARY KEY (skill, kind, ord)
);
```

Bump `SCHEMA_VERSION` to `4`. `vectors.ensure()` grows a `kind` axis and keeps
the incremental contract: only skills whose source text changed re-embed.

### Build pipeline

1. **Source text per skill** — description + section headings + first N tool
   summaries. Bounded, so questions describe capability, not internals.
2. **Snapshot generation** — hosted model, temperature 0, one call per skill,
   output `catalog/questions.json` (committed). Four modes per skill:
   find-the-capability, do-the-task, troubleshoot, compare/second-opinion.
   Prompt carries five worked examples and forbids skill-name tokens and
   system jargon; the useful vocabulary is the user's.
3. **Gate (deterministic, never the model's judgement)**
   - must share a verbatim ≥4-gram with its source text → store the span as
     `quote`
   - must not contain the skill name or directory name
   - fail → regenerate once in the same snapshot pass → drop
   - a deliberately wrong control question is injected at build time and the
     build asserts the gate rejects it
4. **Collapse cross-skill collisions** — cosine > 0.97 between questions of two
   skills is an alias/disambiguation signal; log it, do not keep both silently.
5. **Embed** in one batch (:8087), documents only, no query prefix.

### Query side

- `dense_rank` scores each skill by **max** cosine over its question rows,
  optionally `0.85·max_question + 0.15·description`. Max, not sum: summing
  re-introduces the "more text wins" bias `CHUNK_PENALTY_ALPHA` removed for
  BM25.
- RRF `K=60` untouched. `RERANK_GATE_MARGIN` only moves if the ablation earns it.
- `--explain` gains `dense_best: {question, score}`; `found_by` gains
  `dense:question`.
- `OMNICLI_QUESTIONS=0` reverts to description-only at run time, so a bad
  snapshot is one env var away from harmless.

### Surface

| Command | Change |
|---|---|
| `omnicli index --questions` | regenerate/refresh question rows from the committed snapshot |
| `omnicli questions <skill>` | show each question, its quote, and its vector status |
| `omnicli status` | `vectors: 55 desc + 248 q` |
| `omnicli search --explain` | which question matched, and at what score |

## Eval gate

- Commit `tests/paraphrase_eval.json` first: 30–40 blind paraphrases authored
  (or harvested from real session intents) **before** the generated questions
  are seen. The current 30-case held-out number was measured once and never
  committed, so it cannot gate anything.
- A **no-regression proof** for step 1: description-only under schema v4 must
  reproduce the current baseline bit for bit.
- Ablation table: `description-only` / `questions-only` / `both` ×
  `fusion=never|auto|always`, on golden and paraphrase sets.
- **Ship only if** held-out top-1 gains ≥3 cases with golden drop ≤1.
  Otherwise the feature stays behind `--fusion questions` and the default does
  not move.
- Update the `SKILL.md` table either way, negative result included.

## Phases

| # | Step | Gate |
|---|---|---|
| 0 | Commit paraphrase set, re-capture baseline | matches current table |
| 1 | Schema v4 + max-pool, description only | baseline reproduced exactly |
| 2 | Snapshot loader + `questions` command, no vectors yet | snapshot renders, gate rejects the control |
| 3 | Embed questions, dense-only | ablation wired, all three rows run |
| 4 | Decide default / gate threshold | acceptance gate above |
| 5 | Docs, status, rollback flag | `OMNICLI_QUESTIONS=0` restores v3 behaviour |

## Risks carried

- **Register drift** — the model writes system vocabulary ("hybrid retrieval")
  instead of user speech ("find that note I wrote"). Mitigated by worked
  examples and the name/token reject, proven by the blind paraphrase set.
- **Meta-skill hijack** — `icm-architect` and `review-hub` sit near almost any
  query already; cap questions per skill and keep max-pooling.
- **Snapshot staleness** — questions generated from an edited description.
  Fingerprint is per skill, and `index --questions` reports drift rather than
  hiding it.
- **One-off hosted cost** — paid once, committed; regeneration is explicit and
  never on the query path.

## Cost

275 vectors at build time (~2 s); query latency unchanged (max over
275 × 384 floats, sub-ms). Nothing new enters the context window — this only
reorders results.
