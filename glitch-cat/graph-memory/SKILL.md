---
name: graph-memory

description: >
  Unified Glitch Cat Club Knowledge Graph & Hybrid RAG Engine (Glitch Cat Club; Reel DcTIPKyt7Am):
  deterministic SQLite k-hop graph traversal (<2ms), entity deduplication via UUID5 & aliases,
  and hybrid BM25 + bge-small-en-v1.5 (384d) RRF search with exact-quote distillation.

compatibility: "Requires the local embedding endpoint on :8087 for the hybrid BM25 and vector leg. The slot also hosts EmbeddingGemma-2 (768d); an index built with one is not comparable with the other, so rag.db records which model built it."
allowed-tools: "Bash(graph-memory:*) Bash(python3:*) Read Write"
---

> **Model layer:** the server behind this skill is registered in the `model-layer` skill (slot `:8086 + :8087`) — launcher, weights files, health and quirks. Read it before starting, swapping or debugging the model. If `:8087` is down, `search` starts the index's own candidate (`llama-rig up embed <model>`; `--no-autostart` skips) — the prompt hook never starts a model.

# `graph-memory` — Unified Knowledge Graph & Hybrid RAG (Glitch Cat Club Architecture)

A dual-legged local memory system derived directly from **Kem Glitch (Glitch Cat Club)**'s `graph-memory-starter`. Solves the fundamental flaw of autonomous agent memory: **eliminates upstream ontological drift and duplicate entity pollution while delivering sub-2ms deterministic graph traversals**.

---

## 🏛️ Architecture: The Two Legs of Memory

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          GLITCH CAT HYBRID MEMORY                            │
├──────────────────────────────────────┬──────────────────────────────────────┤
│               LEG 1: GRAPH           │               LEG 2: RAG             │
│   Deterministic Typed Relationships  │    Lexical + Semantic Discovery      │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ • SQLite tables (entities, relations,│ • SQLite FTS5 (BM25 keyword search)  │
│   aliases)                           │ • bge-small-en-v1.5 (384d)           │
│ • Deterministic UUID5 entity IDs     │ • Reciprocal Rank Fusion (K=60)      │
│   uuid5(type + normalised(name))     │ • Exact-quote LLM distillation       │
│ • Recursive CTE k-hop SQL traversal  │ • Zero-hallucination verbatim check  │
│ • Sub-2ms execution, pure SQLite     │ • Token-shielded Markdown tables     │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

---

## ⚠️ Upstream Ontology & Anti-Duplicate Discipline

As ranted by Kem, *"The poison sits upstream. Underneath every graph, there's basically a table... Before anyone fills it in, someone has to pick the columns (ontology) and schema."*

1. **Deterministic Entity IDs**: Every entity ID is `uuid5(NAMESPACE_OID, f"{type}:{normalise(name)}")`. "Ops Manager" in doc 1 and doc 4 resolves to the exact same node without ML or lookup ambiguity.
2. **Aliases Table**: Prevents duplicate entities ("Dave", "David", "Dave Smith" map to one canonical entity ID).
3. **Closed Extraction Vocabulary** (`extract-prompt.md`):
   - **Entity Types**: `PERSON`, `ROLE`, `POLICY`, `PROCESS`, `DOCUMENT`
   - **Predicates**: `approved_by`, `held_by`, `delegates_to`, `part_of`, `references`
   - Conditions (amounts, dates, time windows) are stored in entity `description`, keeping graph edges clean.

---

## 🛠️ CLI Quickstart

The entrypoint is `graph-memory` (or `python3 /run/media/rodri/AI/skills/glitch-cat/graph-memory/graph_memory.py`).

### 1. Knowledge Graph Traversal (Leg 1)
```bash
# Build the deterministic SQLite graph from extraction JSONs
graph-memory build-graph

# Walk the graph: seed entities from query, traverse k hops, return facts in <2ms
graph-memory recall "Who approves refunds?"

# Custom depth and top-k facts:
graph-memory recall "Who does Sarah delegate to?" --hops 3 --top-k 8

# Run the UserPromptSubmit injection hook (JSON in/out for agent harnesses)
echo '{"prompt": "Can Marcus approve the invoice?"}' | graph-memory hook
```

### 2. Hybrid RAG & Distillation (Leg 2)
```bash
# Search notes index via hybrid BM25 + BGE vector RRF (table output):
graph-memory search "propagation delay" --table

# Project specific fields and limit hits:
graph-memory search "dynamic power" --table -p file,section,snippet -n 5

# Buffer full text hits to disk with receipt preview:
graph-memory search "cmos inverters" -o /tmp/hits.json

# Rebuild the RAG index over notes corpus:
graph-memory index --corpus "/run/media/rodri/AI/University/notes"

# Distil raw markdown notes into verified question-rule-quote triplets:
graph-memory distil "/run/media/rodri/AI/University/notes" --limit 10
```

---

## 📁 Repository Structure
```
glitch-cat/graph-memory/
├── SKILL.md                 # This canonical contract
├── graph_memory.py          # Unified CLI entrypoint
├── extract-prompt.md        # Strict closed-world extraction prompt
├── graph.db                 # Compiled SQLite knowledge graph
├── graph/
│   ├── schema.sql           # 3 tables: entities, relations, aliases
│   ├── build_graph.py       # Deterministic compiler with UUID5 addressing
│   ├── recall.py            # Recursive CTE k-hop SQL walk (<2ms)
│   └── recall_hook.py       # UserPromptSubmit prompt injection hook
├── extraction/              # Staged ground-truth extraction JSONs
├── corpus/                  # Reference corpus documents
├── digest/                  # Session start/end auto-digest hooks
└── rag/                     # Hybrid BM25 + Vector reciprocal rank fusion
    ├── build_index.py       # RAG indexer
    ├── search.py            # RRF searcher
    ├── distil.py            # Verbatim quote extractor
    └── test_search.py       # Test suite
```

---

---

---

## AGENTS.md rule

## Memory: query the graph before you search
When a question is about people, owners, decisions or relationships in this repo's knowledge graph, run:
graph-memory recall "<question>" --hops 2 --top-k 8
- The answer is a pointer to a source line. Quote it exactly, do not paraphrase it.
- If the recall returns nothing, fall back to `graph-memory search "<words>" --table`.
