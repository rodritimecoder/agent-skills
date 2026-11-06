# In-Flight Coding Disciplines: Applying Lauren Tan's `pstack` inside Kem's ICM Pipeline

A practical architectural and operational guide on integrating **Lauren Tan's (`poteto`)** in-flight coding disciplines directly into **Kem Glitch's** Interpretable Context Methodology (ICM) and 7-Step Kanban Software Factory (`.kanban/`).

---

## 🏛️ Executive Philosophy: "Structure as the Real-Time Harness"

Kem’s architecture posits that **"Folder structure is agent architecture"**—agents follow physical directory boundaries and file-based state machines more reliably than long conversational system prompts.

Lauren Tan’s (`poteto`) work on `pstack` inside Cursor proves that **"Throughput without quality is slop"**, and true agent velocity comes from **in-flight guardrails** that stop mistakes *while code is being typed*, rather than relying solely on post-hoc reviews.

When fused, **Kem’s ICM Kanban provides the physical workflow stages**, while **Poteto’s in-flight tools provide the operational invariants** that govern the builder agent inside each folder.

```
┌────────────────────────────────────────────────────────────────────────┐
│              FUSED ARCHITECTURE: KEM ICM + POTETO IN-FLIGHT            │
├──────────────────────────────┬─────────────────────────────────────────┤
│    Kem ICM Pipeline          │  Poteto In-Flight Coding Invariants     │
├──────────────────────────────┼─────────────────────────────────────────┤
│ 00-backlog/                  │ • Raw requirements & issue triage       │
│ 01-plan/                     │ • 4D Throughput Checkpoint & /architect │
│ 02-in-progress/              │ • Empirical spikes, probes & decisions.tsv│
│ 03-verification/             │ • Grounded app driver & holdout suites  │
│ 04-review/                   │ • /no-comments deslop & Fresh-Context Judge│
│ 05-done/                     │ • Linear git stack ready for merge     │
└──────────────────────────────┴─────────────────────────────────────────┘
```

---

## 📁 The ICM Kanban Folder Blueprint

Here is the concrete target-local folder layout to drop into any project (`.kanban/` or `workspaces/<feature>/`):

```
my-feature/
├── .kanban/
│   ├── 00-backlog/
│   │   └── issue-402-order-retry.md
│   ├── 01-plan/
│   │   ├── task-envelope.md            # Target scope, file paths, acceptance gates
│   │   ├── throughput-checkpoint.md    # [Poteto] 4D concurrency & state gating
│   │   └── sketches/                   # [Poteto] 2 competing typed interface skeletons
│   │       ├── candidate-a.ts
│   │       └── candidate-b.ts
│   ├── 02-in-progress/
│   │   ├── decisions.tsv               # [Poteto] Append-only ledger of wins & reverts
│   │   ├── spikes/                     # [Poteto] Throwaway micro-tests for empirical forks
│   │   │   └── bench-wal-mode/
│   │   └── probes/                     # [Poteto] Standalone Certainty Level-4 scripts
│   │       └── test-session-blast.py
│   ├── 03-verification/
│   │   ├── holdouts/                   # [Kem] Test suites hidden from builder
│   │   └── run-live-proof.sh           # [Kem] Grounded browser / CLI driver
│   ├── 04-review/
│   │   ├── deslop.log                  # [Poteto] Comment Sicko cleanup record
│   │   └── judge-verdict.md            # [Kem] Fresh-Context Unbiased Review
│   └── 05-done/
│       └── pr-briefing.md              # [Poteto] Unslopped conventional PR description
```

---

## 🛠️ The 7 High-Leverage In-Flight Coding Disciplines

### 1. The 4D Throughput Checkpoint (`01-plan/throughput-checkpoint.md`)
**The Problem**: Multiple parallel agents collide by editing the same files, or a single agent writes tangled code that mixes IO, validation, and domain logic.
**The Poteto Solution**: Before moving a task card from `01-plan/` to `02-in-progress/`, the agent must complete a 4-dimensional gate in `throughput-checkpoint.md`:

```markdown
# Throughput Checkpoint: Order Retry Engine

1. Blocking First Steps:
   - Must write failing reproduction script reproducing the duplicate webhook error.
   - Must settle OrderState enum before touching database adapters.

2. Independent Workstreams (Parallelizable):
   - Stream A: Database migration script (`db/migrations/042_idempotency.sql`)
   - Stream B: API route handler (`api/routes/orders.ts`)

3. Shared Mutable State Elimination (Separate Before Serializing):
   - Contention: Both streams touch `types/order.ts`.
   - Resolution: Split `types/order.ts` into `types/order-domain.ts` and `types/order-wire.ts` FIRST. No shared file locks needed.

4. Smallest Safe Decomposition:
   - Worker 1 handles DB migration. Worker 2 handles API handler. Lead handles integration.
```

---

### 2. Dual-Skeleton Architectural Sketching (`01-plan/sketches/`)
**The Problem**: Agents jump straight into writing implementation details, locking in messy, nested function signatures that are painful to refactor later.
**The Poteto Solution**: Enforce the **"Design it Twice"** rule ([`/architect`](../review-hub/suites/pstack/skills/architect/rubric.md)). 
- The agent drafts **two structurally distinct** candidate interfaces inside `01-plan/sketches/` with empty (`// not implemented`) function bodies.
- It evaluates both against **Interface Depth**: *which candidate hides the most complex state machine behind the simplest, most intuitive public API surface?*

```typescript
// 01-plan/sketches/candidate-a.ts (Shallow: exposes internal retry counters)
export class RetryHandler {
  public attempts: number = 0;
  public checkRetry(err: Error): boolean { /* ... */ }
  public increment(): void { /* ... */ }
}

// 01-plan/sketches/candidate-b.ts (Deep: hides state, caller gets 1 clean idempotent method)
export class IdempotentExecutionGate<T> {
  public execute(idempotencyKey: string, task: () => Promise<T>): Promise<ExecutionResult<T>> {
    // not implemented
  }
}
// WINNER: Candidate B selected for superior interface depth and zero leaked state.
```

---

### 3. The Empirical Forks Protocol (`02-in-progress/spikes/`)
**The Problem**: Standard agents interrupt the developer with annoying questions: *"Do you prefer Option A (regex parsing) or Option B (state-machine tokenizer)?"*
**The Poteto Solution**:
> **"If an answer is a fact observable by running code, it is NOT the human’s job to answer."**

When facing a choice between two implementations, the builder agent:
1. Creates a temporary spike directory: `.kanban/02-in-progress/spikes/<fork-name>/`.
2. Writes a 20-line test script running both options against the real input data.
3. Measures speed, memory, or error rate.
4. Logs the winner to `decisions.tsv` and deletes the spike folder.
5. The human is never interrupted for an empirical question.

---

### 4. The Atomic Discard Habit & Decision Ledger (`02-in-progress/decisions.tsv`)
**The Problem**: Agents hit a compile error or broken test, try to patch it, make another mistake, and end up down an 8-layer rabbit hole of tangled hacks.
**The Poteto Solution**:
- **Discard immediately on failure**: If an edit does not pass verification, the agent runs `git reset` to return to the last green state. It never "fixes a fix".
- **Append-only Decision Ledger**: Every attempt—successful or discarded—is logged to `decisions.tsv`:

```tsv
ts	phase	decision	why	evidence	result
2026-10-19T01:10:00Z	repro	captured duplicate webhook crash	verify defect exists before fixing	repro.sh	reproduced HTTP 500
2026-10-19T01:22:00Z	impl	attempted global mutex on order ID	stop concurrent writes	db/lock.ts	reverted (caused deadlock in test lane)
2026-10-19T01:35:00Z	impl	switched to postgres ON CONFLICT DO NOTHING	atomic db-level idempotency	db/order.sql	tests green, zero deadlocks
```

When Kem’s **Fresh-Context Judge** inspects the card in `04-review/`, it reads `decisions.tsv` and sees exactly which traps were already explored and eliminated.

---

### 5. The Blast-Radius Certainty Probe (`02-in-progress/probes/`)
**The Problem**: Agents change a utility function, run `grep`, and write a hallucinated paragraph claiming: *"This change is completely safe and won't affect other callers."*
**The Poteto Solution**: Write a **Level-4 Certainty Probe** ([`/blast-radius`](../review-hub/suites/pstack/skills/blast-radius/rubric.md)).
The agent must isolate the **"one fact this change is safe because of"** and write an executable script into `probes/` proving it:

```python
# .kanban/02-in-progress/probes/probe_cache_safety.py
from core.cache import SharedCache

cache = SharedCache()
# The One Fact: Clearing tenant A's keys NEVER evicts tenant B's active tokens
cache.set("tenant_a:session_1", "active")
cache.set("tenant_b:session_2", "active")

cache.clear_tenant("tenant_a")

assert cache.get("tenant_b:session_2") == "active", "BLAST RADIUS BREACHED!"
print("PROVEN: Tenant B data completely unaffected.")
```
If the script exits `0`, the task can move to `03-verification/`. If not, the card remains blocked.

---

### 6. Subagent Division of Labor (Lead Conductor vs. Fast Worker)
**The Problem**: Frontier reasoning models (Opus 5.5, Gemini Pro) are slow and expensive for typing out repetitive CRUD code, while fast coding models (Grok, Gemini Flash) lack high-level architectural judgment.
**The Poteto Solution**:
- **Conductor / Lead Agent (Claude Opus 5.5 / Frontier)**: Resides in the parent session. Owns the `.kanban/` cards, writes `task-envelope.md`, verifies the diff, and runs the final verification harness.
- **Worker Delegate (Grok `grok-4.7-xhigh-fast`)**: Spawned as an isolated subagent inside `.kanban/02-in-progress/`. Receives strict boundary instructions:
  ```text
  "Modify only src/services/billing.ts. Implement the IdempotentExecutionGate interface. 
   Do not add any dependencies. Do not edit tests. Stop when npm run build exits 0."
  ```
- Result: 5x faster coding iterations without sacrificing architectural discipline.

---

### 7. Pre-Judge Deslopping & Comment Stripping (`04-review/deslop.log`)
**The Problem**: AI code is littered with redundant self-narrating comments (`// set loading to false`, `// loop through items`), while critical constraints are hidden inside informal text (`// PLEASE DO NOT REMOVE THIS TIMEOUT`).
**The Poteto Solution**: Before Kem’s Fresh-Context Judge reads the diff, run the **Comment Sicko** protocol ([`/no-comments`](../review-hub/suites/pstack/skills/no-comments/rubric.md)):
1. **Strip all narrating comments**: Code should be self-documenting through clear symbol names and small functions.
2. **Convert text constraints to code**:
   - Instead of `// do not pass null here`: Convert the TypeScript argument type to `NonNullable<T>`.
   - Instead of `// must run after DB flush`: Assert `isFlushed()` at runtime.
3. Record the cleaned items in `04-review/deslop.log` so the Judge sees the clean code directly.

---

## 🧭 In-Flight Steering Cheat Sheet for the Human Operator

When watching an agent work in Kem's ICM environment, you don't need to write long paragraphs to correct drift. Use Poteto's **Principle Shorthand**:

| What the Agent is Doing Wrong in Flight | Type This 2-4 Word Steering Prompt | What the Harness Forces |
| :--- | :--- | :--- |
| Writing nested boolean checks (`if status == 'P' and retry < 3`) | **`model the domain`** | Refactors logic into an explicit algebraic enum or state machine. |
| Bolting new wrappers onto deprecated legacy functions | **`subtract before you add`** | Deletes the dead code first; builds clean addition on the simplified base. |
| Overcomplicating classes and adding generic interfaces | **`laziness protocol`** | Strips out the fluff; writes the minimal readable diff. |
| Two subagents trying to write to the same file | **`separate before serializing`** | Splits the file into two independent modules so both can write without locks. |
| Claiming success because "the unit tests pass" | **`prove it works`** | Spawns a real browser/CLI process and captures observable output. |
| Getting stuck in an infinite fix-the-fix loop | **`attack the premise`** | Drops the current line of thought; questions the underlying assumption shared by both failed fixes. |
| Wondering how to prove a change won't break production | **`blast radius`** | Climbs the Certainty Ladder; writes an executable probe in `probes/`. |

---

## 📋 Ready-to-Use File Templates

### Template A: `01-plan/throughput-checkpoint.md`
```markdown
# Throughput Checkpoint: [Task Name]

## 1. Blocking First Steps (Run before any fan-out)
- [ ] Reproduce defect with live output (`repro.sh`)
- [ ] Lock core data types in `sketches/`

## 2. Independent Workstreams (Safe to parallelize)
- [ ] Stream 1: [Files / Scope]
- [ ] Stream 2: [Files / Scope]

## 3. Shared Mutable State (Eliminate contention first)
- Contended Resource: [File or DB table]
- Structural Separation: [How the resource is split]

## 4. Decomposition Rationale
- [Why this split minimizes coordination overhead]
```

### Template B: `02-in-progress/decisions.tsv` Header
```tsv
ts	phase	decision	why	evidence	result
```

### Template C: `02-in-progress/probes/probe_template.py`
```python
"""
Level-4 Certainty Probe
Fact to prove: [State the single safety invariant]
"""
import sys

def main():
    # 1. Setup real imported modules
    # 2. Execute boundary condition
    # 3. Assert invariant
    print("PROVEN: Invariant verified on real runtime code.")
    sys.exit(0)

if __name__ == "__main__":
    main()
```
