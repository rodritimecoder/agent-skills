# `omnicli` Retrieval Architecture

Deep-dive notes on the two-leg hybrid retrieval pipeline and ranking normalization behind `omnicli search`. Live routing numbers come from `omnicli eval` over the committed `golden`, `paraphrase`, and `fresh` query sets in `tests/`.

---

## Two Legs, Fused by Rank

BM25 over every skill's full body plus hand-curated aliases (weight 12) matches exact tokens (`:8083`, `canvas-cli`). To recognize paraphrases, the second leg embeds each skill's `description` with `bge-small-en-v1.5` (384d, `-ngl 0` — CPU only, zero VRAM) and fuses the two rankings via Reciprocal Rank Fusion (`K = 60`).

`fusion=auto` fuses only when BM25's own margin is thin (below `RERANK_GATE_MARGIN`), because fusion buys unseen phrasings and costs tuned ones. Modes are exercised by `--fusion auto|always|never` and `--rerank auto|always|never` when the dense/rerank servers are online.

---

## The Description Field Is the Cheapest Lever

Frontmatter `description` is the only per-skill text both legs see: BM25 indexes it as a `skill`-kind doc row, and the dense leg embeds it. Following the Agent Skills spec (*"when to use it"* + *"specific keywords that help agents identify relevant tasks"*), rewriting twelve descriptions with user vocabulary ("school portal", "closed source", "second opinion") moved held-out BM25 from 12/30 to 19/30 before any dense leg was involved, at a cost of one golden case.

---

## Distilled Questions: Built, Measured, Left Off (Negative Result)

Embedding *the question someone would search for* was tested across 228 generated questions for 55 skills, gated by verbatim quote checks and a cosine threshold (`catalog/questions.py`). The routing effect was **zero**, and every BM25 top-1 miss was also a dense top-1 miss. Remaining paraphrase misses were proper nouns, which belong in `catalog/aliases.json`, not embeddings. The machinery remains opt-in via `OMNICLI_QUESTIONS=1 omnicli index` and `omnicli questions <skill>`.

---

## Body Length Is a Ranking Bias

BM25 normalizes per chunk (`b=0.75`), but aggregation takes the best chunk per skill, giving a long body many chances at one good chunk vs one for a short skill. `CHUNK_PENALTY_ALPHA` (default `0.2`, env `OMNICLI_CHUNK_ALPHA`) damps the score by `chunks**-alpha` to remove multi-chunk hijacks.

Fused rankings set `found_by` and preserve `lexical_score` on full results; `--depth brief` (the default) compacts each result to skill/score/matched/why/top/chunk_count and drops those fields. Falls back cleanly to BM25 when `:8084` is offline.

---

## Result Views

`search --depth {brief,contract,chunks}` selects the view: the compact routing line (default), the top hit's tool contract (same shape as `describe`, with `--section`/`--doc` passthrough), or the full chunk body (the legacy `--chunks` shape). The 8 KB cap applies to all three.

---

## Why This Exists & Provenance

Moving selection off the turn-0 prompt shelf onto SQLite FTS5 BM25 plus curated aliases keeps per-turn context cost flat as the catalog grows. Live accuracy is measured by `omnicli eval` over the committed query sets, not by archived snapshots.

- **Architectural lineage:**
  1. [Uber's MCP Gateway](https://www.uber.com/au/en/blog/designing-mcp-gateway/): late-binding catalog discovery, single-contract `describe`, bounded `invoke`.
  2. [Cloudflare's Code Mode](https://blog.cloudflare.com/code-mode/): sandboxed JS plans (`omnicli exec`) keeping intermediates in variables rather than round-trip prompt turns.
  3. **Retired stdio MCP server:** Built, conformance-tested (28 checks), and retired to `archived/omnicli-mcp/` because JSON-RPC tool round-trips burn prompt tokens while JS variables in `node:vm` cost nothing.

