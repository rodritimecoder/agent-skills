# Kem's Engineering Invariants & Glitch Cat Club Architectural Laws

A unified reference and architectural codex synthesizing the foundational engineering principles, failure mode defenses, and autonomous system designs from Kem (`kem_glitch` / Glitch Cat Club).

---

## 🏛️ The Core Axiom: Kem's Law

> **"Code decides wherever it can; LLMs only decide where code cannot."**

Every failure in modern agentic systems stems from violating this boundary: delegating deterministic invariants (compilation, syntax, regex, schema validation, state transitions) to probabilistic language models.

---

## 🎯 The 9 Glitch Cat Architectural Pillars

### 1. The Tripartite Actor Model & "Loop Ego"
There are only three actors capable of performing work in AI software systems:
- **Human**: Knows high-level intent, best subjective taste, but is a severe throughput **bottleneck**.
- **Model**: High reasoning ability and semantic agility, but **probabilistic, stochastic, and unreliable**.
- **Code**: **Deterministic, instantaneous, repeatable, and free**.

```
  Primitive Loop ("Loop Ego" / Roulette Wheel):
  Human ──(prompt)──> Model ──(read output)──> Human ──(prompt)──> Model
  * Slow, expensive, non-scalable. Developer is trapped as a manual babysitter.

  Agentic Software Factory:
  Trigger (Event) ──> Taskboard ──> Listener ──> Parallel Workers ──> Deterministic Gates
                                                                               │
                                                                               ▼
                                                                  Fresh-Context Judge
                                                                               │
                                                                               ▼
                                                                Human Verifier (Only at End)
```
**The Invariant**: Shift the human operator from the *beginning* of the loop to the *end* of the loop as the final verification gate.

---

### 2. Context Hygiene: Rot vs. Poisoning
Long-running agent loops degrade through two distinct phenomena:
- **Context Rot**: As conversation history swells past 50k–100k tokens, attention dilution causes instruction neglect, hallucinated parameters, and runaway costs.
- **Context Poisoning**: When an agent hallucinates or makes a broken assumption, standard harness autocompaction summarizes the error into the conversation history. Downstream turns accept the falsehood as established ground truth.

**The Fix: Active State File Compaction**:
- The agent continuously writes verified facts and milestones to a single structured state file (`.agent_state.json` or `STATE.md`) *while its context is small and sharp*.
- Never rely on lossy, late autocompaction or multi-document handover bloat.
- When token limits are reached, trigger a **hard session reset** and rehydrate the fresh context with **only the state file injected**. Preserves 100% of facts across 660,000+ token sessions.

---

### 3. The Knowledge Graph Trap vs. Disciplined Structure
> *"Do you need a graph?! Short answer: probably not."*

- **The Fallacy**: Outsourcing graph generation to automated tools (Graphify, Obsidian plugins, naive LLM entity extractors). Without rigorous ontological data modeling, they produce noisy, disconnected edges and hallucinated multi-hop traversals.
- **The Reality**: Coding models default to literal lookup (`grep` / `ripgrep`). If forced to traverse an unmodeled graph, the agent burns tokens on raw JSON dumps before falling back to grep anyway.
- **The Glitch Cat Architecture**:
  1. **Strict Folder Hierarchy (ICM)**: Deterministic directories where paths encode types, domains, and boundaries.
  2. **Deterministic Literal Search**: Fast ripgrep across clean files.
  3. **Late-Binding Hybrid RAG**: BM25 keyword matching + BGE dense vector embeddings with Reciprocal Rank Fusion (RRF) and exact-quote distillation.
  4. **JEV De-Duplication**: Pairwise chronological audits to prune stale and contradictory claims before retrieval.

---

### 4. Calibrated Decision Routing: JEV & The 3 Primitives
Decouple perception and decision-making from verbose text generation. Generative models waste seconds and dollars typing open-ended tokens for simple decisions.

**The 3 Universal Decision Primitives**:
1. **`Bool` (Binary / Null)**: Yes / No condition assertion (*"Is there a merge conflict?"*).
2. **`Choice` (Discrete Enum)**: Selection from a constrained, finite set (*"Which worker lane: A, B, or C?"*).
3. **`Score` (Scalar Magnitude)**: Quantitative evaluation on a normalized scale (*"Urgency severity from 0.0 to 1.0"*).

Using the specialized decision model (`h2o-lightning-4b` on port `:8083`, with vision):
- Run 41,000 judgments in 7 minutes for $0.37 (vs. 12 hours and $60.00 on Sonnet).
- Execute frontend UAT clicks in <500ms for $0.00024 per test suite.

---

### 5. Multi-Agent Git Worktree Concurrency
When multiple agents write to the same codebase or file simultaneously:
- **Never share working directories**: Cloned directories cause race conditions and index corruption.
- **Isolate in Git Worktrees**: Every worker runs on an independent branch in an isolated `git worktree` backed by common Git object storage.
- **Pre-Write Section Claiming**: Before writing, workers formally claim target functions or line ranges in code (`claims.json`).
- **Conflict Arbitration**:
  - Keep both conflicting versions.
  - Spawn an unbiased judge in a *fresh context* to evaluate both against the specification.
  - Run deterministic test suites to prove the merged result works.

---

### 6. Step-Level Propagation Risk & The 3-Step Eval Pipeline
A skill is a multi-step chain. An unverified ambiguity in Step 1 compounds exponentially into catastrophic failure in Step 5 (**Propagation Risk**).

**The 3-Step Eval Pipeline**:
1. **Map and Tag**: Label every step explicitly as `[D]` (Deterministic Code), `[P]` (Probabilistic Model), or `[H]` (Human).
2. **Intermediate Artifact Ledger**: Force each step to serialize its intermediate input/output to disk (e.g., `step_01.json`, `step_02.json`).
3. **Automated Assertion Suite**: Write automated verification checks against the disk artifacts, running 5–10 iterations across model tiers to catch drift.

---

### 7. AI Blast Radius Containment: Hardware-Parallel Test Lanes
High-velocity AI coding generates thousands of regression tests, causing full test suite runs to inflate to 40–60 minutes.
- **Don't over-engineer mocks or skip tests**: Real regression test suites are the only grounded boundary that stops the AI blast radius.
- **Hardware-Parallel Partitioning**:
  - Audit tests for shared database or filesystem mutations.
  - Isolate state-mutating tests into a single sequential lane (Lane 0).
  - Fan out stateless unit and integration tests across all available CPU hardware cores (e.g., 16 worker lanes).
  - Slashes test latency from 60 minutes down to **7–8 minutes** (5x–8x acceleration).

---

### 8. Dynamic Swarm Governance: The Tripartite Contract
When orchestrating dynamic swarms (where 1 lead coordinator spawns dozens of parallel subagents):
The lead orchestrator must be bound by **3 non-negotiable constraints**:
1. **The Goal**: Explicit hit list, deliverables, and search expansion boundaries.
2. **The Contract**: A strict, standardized scorecard schema that every worker must populate upon completion (preventing vague markdown summaries).
3. **The Hard Budget**: An immutable financial/token ceiling enforced strictly in code.

---

### 9. Semantic Caching & Asynchronous Shadow Verification
In real-world agent and RAG systems, 40%–70% of inbound queries are variations of recurring questions.
- **Semantic Caching**: Intercept questions via dense vector cosine similarity *before* touching RAG indexes or calling LLMs. Return verified answers in **<10ms at $0 token cost**.
- **Shadow Verification & Failure Harvesting**:
  - Cheap local models answer first.
  - A frontier model audits the response asynchronously in the background.
  - If the cheap answer fails, the frontier output seamlessly replaces it, and the failure is **harvested into the training set** as a new evaluation sample.
  - Delivers a sustained **30%–40% token cost reduction** while self-improving over time.

---

## 🛠️ Workstation CLI Mapping

| Glitch Cat Concept | Canonical Workstation Implementation | Primary Tool / Script |
| :--- | :--- | :--- |
| **Kem's Law Enforcement** | `guard-hooks` | Pre-execution safety hooks & immutable file shields |
| **Git Worktree Orchestration** | `worktree-harness` | `worktree-harness claim / gate / integrate` |
| **Autonomous State Compaction** | `state-compactor` | `state-compactor record / compact` |
| **Universal Task Router & Eval** | `eval-router` | Fast proxy, shadow verifier & failure harvester |
| **Calibrated Decision Engine** | `jev-decision` | `jev` (`:8083` h2o-lightning-4b) |
| **Hardware Parallel Testing** | `parallel-test-lane` | `parallel-test-lane run --cores 16` |
| **Hybrid RAG & Knowledge Memory** | `graph-memory` | BM25 + BGE-small RRF & deterministic k-hop graph |
| **Code Review & Audits** | `review-hub` | `review-hub review [suite] [target]` |
| **Fast Video & Knowledge Mining** | `video-miner` | `vault-mine add <url>` |
