---
name: semantic-cache

description: >
  Sub-10ms repeat query bypass and verified response cache for RAG and agent systems.
  Intercepts recurring queries via dense vector cosine similarity before invoking heavy RAG
  pipelines or frontier LLMs, delivering instant answers at zero token cost for 40-70% of
  inbound queries. Use when the same question keeps coming back, to avoid paying twice for an
  answer already given, to memoise or deduplicate repeated lookups, or to cut prompt cost
  across near-identical requests. It caches answers to questions; it does not index or search
  a notes folder — use notes-index for that.

compatibility: "Requires the local embedding endpoint on :8087 for the semantic leg."
allowed-tools: "Bash(python3:*) Read Write"
---

# Semantic Cache (`semantic-cache`)

A zero-token sub-10ms query bypass layer derived from **Kem Glitch (Glitch Cat Club)**'s architecture in Reel [`DdbQeb5t2u0`](https://www.instagram.com/reel/DdbQeb5t2u0/).

---

## 🏛️ Why Semantic Caching Matters

In production agent and RAG workflows, **40% to 70% of inbound user queries are semantic variations of recurring questions**. 
- Traditional RAG slurps documents, parses vectors, and calls an LLM every turn (3–10s, $$$).
- A **Semantic Cache** intercepts questions via vector cosine similarity and returns the verified ground-truth answer in **<10ms at $0 cost**.

---

## 🛠️ CLI Quickstart

```bash
CACHE="python3 /run/media/rodri/AI/skills/semantic-cache/semantic_cache.py"

# 1. Store a verified answer
$CACHE store "How do I configure git worktrees for parallel agents?" \
             "Run 'git worktree add <path> -b <branch>' and pre-claim file lines."

# 2. Query with paraphrase (Sub-10ms bypass)
$CACHE query "How to set up git worktrees for parallel subagents?"
# Output:
# ⚡ [CACHE HIT] Similarity: 89.2% (Hits: 1)
# Matched: "How do I configure git worktrees for parallel agents?"
# Answer: Run 'git worktree add <path> -b <branch>' and pre-claim file lines.

# 3. Check cache hit metrics
$CACHE stats
```

---

---

---

## AGENTS.md rule

## Semantic cache: ask it first
Before sending a question that resembles one already answered, run:
semantic-cache query "<question>"
- On a hit, use the cached answer as-is and say it came from the cache.
- On a miss, answer normally, then `semantic-cache store "<question>" "<verified answer>"`.
- Only store answers you have verified, never a guess.
