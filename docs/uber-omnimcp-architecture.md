# Uber OmniMCP & Code Mode Protocol Architecture

> **Status: first-class since 2026-10-30.** `omnicli` was retired as a front
> line on 2026-10-20, when harnesses moved to plain Agent Skills discovery,
> then restored once the executor landed. It is now discovered like any other
> skill and still becomes the only front line when gateway mode is selected.
> This document records the design; the code lives at
> `orchestration/omnicli/` in this repo and at
> `workstation-clis/orchestration/omnicli/`.

Solving Skill Shadowing, Tool Bloat, and Context Degradation across 50+ Workstation Skills.

---

## 1. The Core Problem: Why Installing More Skills Breaks Agents

Conventional agent harnesses claim that "Progressive Disclosure" (injecting only a 100-token `name` + `description` at turn 0 and deferring the 5,000-token `SKILL.md` body until selected) makes installing dozens or hundreds of skills "free."

Recent empirical research proves this is false—not primarily because of token count, but because of **Selection Failure (Shadowing)** and **Blind Routing**:

| Study / Source | Scale | Key Finding |
| :--- | :--- | :--- |
| **Databricks "Skill Shadowing" Study (May 2026)** | 2,500 runs scaling from Oracle skills $\rightarrow$ 52 $\rightarrow$ 102 $\rightarrow$ 202 skills | Pass rate dropped **21 percentage points**. Context overhead was only ~6 pts; **Shadowing (picking wrong or picking nothing)** accounted for **2/3 of the total failure**. |
| **The "Abandonment" Phenomenon** | Oracle vs. 202-skill library | Correct skill selection dropped from **88% down to 52.6%**. Total abandonment (agent stares at 200 descriptions, recognizes none, and writes from scratch) surged from **12% to 38.5%**. |
| **SkillRouter Attention Analysis (Mar 2026)** | ~80,000 skills | Routing signal lives in: **Name = 7.3%**, **Description = 1.0%**, **Body (`SKILL.md` content) = 91.7%**. Stripping bodies drops routing accuracy by **37–44 points**. |
| **Public GitHub Skill Audit (Jul 2026)** | 3.8M skill files across 282k repos | **26.4%** of public skills ship with **zero routing description**, and ~50% are verbatim duplicates. |
| **GitHub Copilot Tool Trim (Nov 2025)** | Trimmed tools from 40 down to 13 + embedding search | SWE-bench success rates rose **2–5 percentage points**; latency dropped **400ms**. |

> **Core Takeaway:** Retrieval beats installation. A static prompt shelf of >30 tools degrades LLM reasoning. The agent router must search across the **full body content** of skills/tools rather than forcing the model to evaluate 30+ frontmatter descriptions on turn 0.

---

## 2. Uber's Architecture: OmniMCP & `aifx` Code Mode

Uber operates **5,000+ MCP tools across 800+ internal servers**. Exposing them via standard MCP `list_tools` overflows context and triggers immediate shadowing.

Uber resolved this through two complementary patterns implemented on this workstation:
1. **OmniMCP (The 4 Meta-Tools)** for JSON-RPC tool-calling agents.
2. **`aifx` Code Mode (`skills-hub`)** for terminal/shell harnesses (`agy`, Pi Agent).

```
[ AI Agent (Antigravity / Pi / Subagent) ]
        │
        ├── Interface A: OmniMCP (4 Meta-Tools Only)
        └── Interface B: "Code Mode" via `skills-hub` CLI (search | inspect | run)
        │
        ▼
[ skills-hub Gateway (Data Plane) & Catalog Index (Control Plane) ]
   ├── Full-Body BM25 / Vector Search (91.7% signal recovery)
   ├── Dynamic Tool Schema Extraction (1 tool at a time)
   ├── Response Projection (--project / --jq field stripping)
   └── Disk Buffering (--out /tmp/... to keep context lean)
```

---

## 3. Pattern A: The 4 Meta-Tools (`OmniMCP`)

Instead of loading 5,000 tools into the system prompt, the agent receives **only 4 tiny meta-tools** (~400 tokens total):

| Step | Meta-Tool Name | Input Argument | What Enters the Context Window |
| :--- | :--- | :--- | :--- |
| **1** | `discover_server` | Natural language `intent` | Matching skill category names (no schemas). |
| **2** | `discover_tools` | `skill_name` from Step 1 | Tool names + concise descriptions inside that skill. |
| **3** | `get_tool_schema` | `skill_name` + `tool_name` | The exact input contract for **that 1 tool only**. |
| **4** | `invoke_tool` | `tool_name`, `arguments`, `projection` | The projected, filtered execution result. |

### Why This Eliminates Shadowing
- **Zero Startup Freight:** Model starts turn 0 with ~400 tokens instead of 150,000 tokens.
- **Full-Body Search at Step 1:** By indexing the markdown bodies and docstrings, search captures the 91.7% signal that frontmatter descriptions drop.
- **Single Active Schema:** At most 1 tool schema exists in context at any turn.

---

## 4. Pattern B: `aifx` Code Mode & Output Bloat Prevention

Even with small tool definitions, a single tool returning a 100 KB JSON payload will pollute agent reasoning. We pair two architectural defenses:

### 4.1 Response Projection (Pre-Flight Field Filtering)
The caller specifies only the fields the model actually requires before execution:
```bash
# Gateway strips unrequested fields before LLM sees the output
skills-hub run worktree-harness status --project "run_id,active_workers,claims"
```

### 4.2 Disk Buffering (Keeping Large Payloads on Disk)
For shell agents, outputs write to disk buffers, and the agent uses `grep` or `jq` to pull only matching lines into context:
```bash
# Output stays on disk; context takes 0 tokens
skills-hub run cdp-browser --url "http://localhost:3000" --out /tmp/trace.json

# Read only relevant errors into context
jq '{errors: .console_errors, status: .http_status}' /tmp/trace.json
```
*Anthropic's benchmark of this pattern demonstrated a **98.7% context token reduction** (from 150,000 down to 2,000 tokens).*

---

## 5. Workstation CLI Mapping

| Command | Action |
| :--- | :--- |
| `omnicli search "<intent>"` | Full-body BM25 search across all 50+ workstation skills |
| `omnicli tools <skill>` | List executable tools and scripts within winning skill |
| `omnicli describe <tool_id>` | View the exact input contract for that 1 tool |
| `omnicli invoke <tool_id> [args]` | Execute with response projection, disk buffering and a hard byte cap |
| `omnicli eval` | Measure routing accuracy against the legacy scorer |
| `omnicli mcp` | Serve the four meta-tools over JSON-RPC stdio |

---

## 6. As Built: `omnicli`

The design above is implemented as **`omnicli`**, in
`/run/media/rodri/AI/workstation-clis/omnicli/`. `uber`, `local-hub` and
`skills-hub` remain as deprecated aliases.

### What the naive implementation got wrong

The first implementation of the "Code Mode" face inherited a substring
scorer straight from `local-hub`:

```python
score += min(md_content.count(t), 10)   # no length normalisation
```

Measured against a 53-case golden routing set, it scored **64.2% top-1**.
The failure was systematic, not incidental: a large, generic meta-document
(`icm-architect`) accumulated score on nearly every query purely by having
more text to match in. "turn a recorded podcast into readable text" routed
to `icm-architect`, and the actual answer (`audiocpp`) did not appear in the
top four.

### The four fixes

1. **Chunking + BM25.** Documents are chunked by heading and scored with
   SQLite FTS5's `bm25()`. Length normalisation inside a chunk removes the
   size advantage that generic meta-documents had.

2. **A separately weighted alias column.** Curated synonyms live in their own
   FTS5 column at ~12x the weight of prose. A curated alias ("podcast" ->
   audio tooling) is the skill author stating *this vocabulary routes here*;
   incidental body text matching the same word says far less. This is the
   only thing that makes the podcast case work, and it needs no model.

3. **Coordination as a tie-breaker, not a global multiplier.** Among the top
   three candidates by lexical score, a skill that matched *more distinct
   query terms* (weighted by skill-level IDF) is preferred. Applied only
   within that head, because applying it globally let a skill whose docs
   merely *contain* a Python example outrank the one that actually provides
   the local LLM.

4. **The router's own body is not indexed.** The catalog's documentation is
   *about* routing; indexing its example queries as routing text made the
   router compete with the skills it routes to.

The optional embedding re-ranker is deliberately **not** a parallel leg. A
parallel semantic leg competes with the lexical one, and this corpus is full
of generic meta-documents that are semantically close to almost any question.
Embeddings are chained as a *re-ranker over the lexical top-K*: they can
only reorder what BM25 already surfaced, so with every inference server down
the search still works.

### Measured

```
BM25 catalog    top1 60/61 (98.4%)   top3 61/61 (100.0%)
legacy scorer   top1 37/61 (60.7%)   top3 48/61 (78.7%)
```

One top-1 miss remains, and it is a lexical artifact rather than a routing
gap: "make sure no secrets get committed" pulls `playwright` to #1 because its
docs contain the words "make" and "sure", while `github-architect` — the skill
that actually scans for secrets — lands at #2 (27.3 vs 31.9). The curated
aliases were checked against the answer key (`tests/overfit_check.py`) and
deliberately not made to echo it, so the miss is recorded rather than papered
over. The retired `hybrid-browser` case was repointed at `playwright`, its
browser-control successor.

### Guarding the measurement

`tests/overfit_check.py` audits the curated alias set against the golden
queries and fails if any alias is a verbatim echo of one. Without that
guard the same configuration reported a meaningless 100%: several aliases
had been written as copies of the test questions. The reported numbers come
from an alias set with **zero** query echoes, and the checker stays in the
tree to keep it that way.

### Other things the build surfaced

- **CJK needs segmentation.** Chinese has no word delimiters, so a query like
  `调研一下这个话题在网上的讨论` is one token and matched nothing. Both the
  indexer and the retriever now expand CJK runs into character bigrams.
- **`argparse.REMAINDER` swallows the gateway's own flags.** `omnicli invoke
  <tool> --out FILE` silently lost `--out`. The gateway's flags are now
  prefixed `--omni-` and parsed manually, so they cannot collide with the
  target tool's flags (`--out`, `--project` and `--json` are all real flags
  on real tools here).
- **Running `--help` during indexing is not free.** `decide.sh --help` ran a
  model. Scripts are now inspected before being executed, and output without
  a `usage:` line is rejected rather than stored as a contract.
- **A virtual skill with an empty path walks the current directory.** The
  `local` endpoint skill was silently registering whatever happened to be in
  the working directory.
