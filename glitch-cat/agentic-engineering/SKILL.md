---
name: agentic-engineering

description: >
  Autonomous production engineering pipeline implementing Kem's 7-step software factory (Glitch Cat Club;
  Reel DehIT3lNgHC). Operates target-local Markdown Kanban boards (.kanban/), event-driven Listeners,
  Fresh-Context Unbiased Judges, Task Splitters, and multi-model parallel sandboxes.

compatibility: "Requires git. Uses a local model runner for the judge and sandbox tiers."
allowed-tools: "Bash(python3:*) Bash(git:*) Read Write"
---

# `agentic-engineering` (`agentic`)

A production engineering pipeline implementing **Kem's (Glitch Cat Club) 7-Step Architecture**: moving from conversational chatting to an autonomous, multi-model execution factory.

---

## 🏛️ The 7-Step Architecture

```
[1. Inbound Stream] ──> [2. Kanban Board] ──> [3. The Listener] ──> [4. Report Block & Fresh Judge]
                                                                                │
                                                                   [5. Splitter: Task DAG]
                                                                                │
                                  ┌─────────────────────────────┬───────────────┴─────────────┐
                                  ▼                             ▼                             ▼
                        [6a. Sandbox 1 (Opus)]       [6b. Sandbox 2 (Sonnet)]       [6c. Sandbox 3 (Flash)]
                                  │                             │                             │
                                  └─────────────────────────────┼─────────────────────────────┘
                                                                ▼
                                                     [7. Delivery to YOU]
```

1. **Inbound Task**: Issues or requests flow into the target project's `.kanban/01_new/`.
2. **Kanban State Machine**: Cards track status (`01_new` $\rightarrow$ `02_picked_up` $\rightarrow$ `03_review` $\rightarrow$ `04_done`) with explicit acceptance criteria (`[REQ-XX]`).
3. **The Listener**: Event-driven watcher that automatically detects and claims ready cards without prompt babysitting.
4. **Report Block & Unbiased Judge**:
   - Executes deterministic **Blue Diamond Code Gates** (`gate_lint`, `gate_test`, `gate_evidence`) as real commands. A gate that cannot fail is not a gate.
   - `gate_evidence` requires an artifact on disk (`.verify/verify.json`, a transcript, a trace); the artifact must exist and be non-empty, or the gate fails.
   - Invokes a **Fresh-Context Judge** — a separate model call with the diff, the requirements and the gate results, and no conversation history. Ticked checkboxes are claims, not evidence.
   - If a gate or the judge rejects, Kem's pink arrow (`SENT BACK`) returns the card with a structured rejection delta.
5. **The Splitter**: Partitions approved specs into parallel single-writer task lanes.
6. **Multi-Model Sandboxes**: Allocates concurrent lanes across model tiers (Opus, Sonnet, local Genesis 35B) in isolated sandboxes / worktrees.
7. **Delivery to YOU**: The human is the final verifier. `agentic run` stops at `03_review`; only an explicit `agentic kanban move <card> done`, or `--mark-done`, closes the card.

---

## 🚀 CLI Usage

### 1. Initialize Kanban Board in Target Project
```bash
# Initializes .kanban/ with 01_new/, 02_picked_up/, 03_review/, 04_done/
agentic init [target_dir]
```

### 2. Manage Cards on the Board
```bash
# View ASCII Kanban Board
agentic kanban list

# Add a new task card with acceptance criteria
agentic kanban add "Build Authentication Flow" --req "JWT auth endpoint with refresh rotation"

# Move card between columns manually
agentic kanban move CARD-001 done
```

### 3. Run the Event Listener
```bash
# One-shot poll and dispatch
agentic listen --once

# Background daemon listening on .kanban/01_new/
agentic listen --interval 5 --worker "agentic run {CARD_ID}"
```

### 4. Evaluate with Fresh-Context Judge
```bash
# Spawns clean-slate judge evaluating diff against [REQ-XX] criteria
agentic judge CARD-001 --model flash
```

### 5. Run the Full 7-Step Loop End-to-End
```bash
# Real gates: lint, tests and an evidence artifact. Any failure sends the card back.
agentic run CARD-001 --lint "ruff check ." --test "pytest" --evidence .verify/verify.json

# UI work: let the verification skill produce the evidence artifact first
verify-app run --pass .verify/pass.json
agentic run CARD-001 --test "pytest" --evidence .verify/verify.json

# A run with nothing to fail refuses with exit 2. Dry-run labels gates SKIPPED.
agentic run CARD-001 --dry-run --mock-judge PASS

# The default stops in review; --mark-done closes the card yourself
agentic run CARD-001 --test "pytest" --mark-done
```

`--judge-cmd` points the fresh-context judge at any command that reads the prompt
on stdin and prints `VERDICT:` / `SCORE:` / `DELTA:` / `FEEDBACK:`. Without it the
judge calls an OpenAI-compatible endpoint (`--judge-url`, default
`http://127.0.0.1:8080/v1/chat/completions`). A judge that cannot answer rejects
the card; it never falls back to a green tick.

---

---

---

## AGENTS.md rule

## Software factory
Work moves through the board, not through chat:
agentic kanban add "<task>" --req "<requirement>"
agentic kanban move <card-id> done
- One card, one verifiable requirement. No card without a done condition.
- Gates run as commands (`--lint`, `--test`, `--evidence`); a skipped gate is reported, never passed.
- A fresh-context judge decides whether the work is done; the author does not grade itself.
- `agentic run` stops in review. The human moves the card to done.
