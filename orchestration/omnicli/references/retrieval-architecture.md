# `omnicli` Retrieval Architecture & Benchmarks

Deep-dive notes on the two-leg hybrid retrieval pipeline, ranking normalization, and empirical evaluations behind `omnicli search`.

---

## Two Legs, Fused by Rank

BM25 over every skill's full body plus hand-curated aliases (weight 12) matches exact tokens (`:8083`, `canvas-cli`). To recognize paraphrases, the second leg embeds each skill's `description` with `bge-small-en-v1.5` (384d, `-ngl 0` — CPU only, zero VRAM) and fuses the two rankings via Reciprocal Rank Fusion (`K = 60`).

`fusion=auto` fuses only when BM25's own margin is thin (below `RERANK_GATE_MARGIN`), because fusion buys unseen phrasings and costs tuned ones:

| mode | golden top-1 | held-out top-1 | median latency |
|---|---|---|---|
| `--fusion never` | 59/61 | 24/30 | 3.8 ms |
| `--fusion auto` (default) | 56/61 | 26/30 | 4.5 ms |
| `--fusion always` | 52/61 | 28/30 | 12.8 ms |

The golden set shares this catalog's vocabulary, so the lexical leg wins it. The held-out set is paraphrased intent authored with the descriptions in view — read it as *"the mechanism responds"*, not as an expected accuracy ceiling.

---

## The Description Field Is the Cheapest Lever

Frontmatter `description` is the only per-skill text both legs see: BM25 indexes it as a `skill`-kind doc row, and the dense leg embeds it. Following the Agent Skills spec (*"when to use it"* + *"specific keywords that help agents identify relevant tasks"*), rewriting twelve descriptions with user vocabulary ("school portal", "closed source", "second opinion") moved held-out BM25 from 12/30 to 19/30 before any dense leg was involved, at a cost of one golden case.

---

## Distilled Questions: Built, Measured, Left Off (Negative Result)

Embedding *the question someone would search for* was tested across 228 generated questions for 55 skills, gated by verbatim quote checks and a 0.45 cosine threshold (`catalog/questions.py`). The routing effect was **zero**:

| rows embedded | golden top-1 (auto / always) | paraphrase top-1 (auto / always) |
|---|---|---|
| description only | 55/61 · 53/61 | 24/39 · 26/39 |
| description + questions | 56/61 · 52/61 | 24/39 · 26/39 |

On this corpus, every BM25 top-1 miss was also a dense top-1 miss (oracle rescue potential: 0/61 golden, 3/39 paraphrase). Remaining paraphrase misses are proper nouns (`deskforge`, `litellm`, `navidc`), which belong in `catalog/aliases.json`, not embeddings. The machinery remains opt-in via `OMNICLI_QUESTIONS=1 omnicli index` and `omnicli questions <skill>`.

---

## Body Length Is a Ranking Bias

BM25 normalizes per chunk (`b=0.75`), but aggregation takes the best chunk per skill, giving a 93-chunk body 93 chances at one good chunk vs 1 for a short skill. `CHUNK_PENALTY_ALPHA` (default `0.2`, env `OMNICLI_CHUNK_ALPHA`) damps the score by `chunks**-alpha`, removing multi-chunk hijacks and moving held-out `fusion=always` top-3 from 29/30 → 30/30 and top-1 from 26/30 → 28/30.

Every result names the legs that found it (`found_by`), normalizes fused scores to 0–1 while preserving `lexical_score`, and falls back cleanly to BM25 when `:8084` is offline.

---

## Empirical Routing & Token Cost Measurements

Measured 2026-11-14 across the 59-skill catalog (`:8084` offline):

```
BM25 catalog    top1  56/61 (91.8%)   top3  61/61 (100.0%)
legacy scorer   top1  41/61 (67.2%)   top3  49/61 ( 80.3%)
```

- `tests/overfit_check.py` audits `catalog/aliases.json` against eval queries (**0** echoes across 389 aliases).
- On the 39-case paraphrase set (`tests/paraphrase_eval.json`), BM25 alone scores 21/39 (53.8%) top-1 and 24/39 (61.5%) top-3 (`legacy`: 19/39).
- `tests/measure_tokens.py` counts context landing on the model via Qwen3.5 tokenizer across 58 non-archived skills:

| | prompt shelf | omnicli | |
|---|---|---|---|
| selection phase | 10,827 tok | 1,274 tok | **88.2% smaller** |
| to invoke one tool | 13,209 tok | 4,265 tok | **67.7% smaller** |

The second row's saving comes from the 8 KB response cap; the selection-phase number is paid on every turn whether or not a tool gets used.

---

## Why This Exists & Provenance

- **Skill-shadowing decay:** The Databricks study measured tool selection dropping from 88% to 52.6% as prompt shelves grew past ~30 skills, with two thirds of failures caused by picking wrong or picking nothing. Moving selection off turn-0 context onto SQLite FTS5 BM25 + curated aliases keeps selection flat.
- **Eval caveats:** In the 2026-11-14 snapshot (`91.8%` golden top-1), 32 of 61 golden queries share a curated alias string (`overfit_check.py` reports 0 verbatim echoes across 389 aliases). On the 39-case paraphrase set (`tests/paraphrase_eval.json`), BM25 alone scores 21/39 (53.8%) top-1 and 24/39 (61.5%) top-3 (`legacy`: 19/39); `--fusion auto|always|never` and `--rerank auto|always|never` exercise the dense/reranker legs when `:8084` / reranker are online.
- **Architectural lineage:**
  1. [Uber's MCP Gateway](https://www.uber.com/au/en/blog/designing-mcp-gateway/): late-binding catalog discovery, single-contract `describe`, bounded `invoke`.
  2. [Cloudflare's Code Mode](https://blog.cloudflare.com/code-mode/): sandboxed JS plans (`omnicli exec`) keeping intermediates in variables rather than round-trip prompt turns.
  3. **Retired stdio MCP server:** Built, conformance-tested (28 checks), and retired to `archived/omnicli-mcp/` because JSON-RPC tool round-trips burn prompt tokens while JS variables in `node:vm` cost nothing.

