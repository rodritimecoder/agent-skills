# agentic-engineering

Autonomous production pipeline implementing **Kem's (Glitch Cat Club) 7-Step Architecture**: moving from conversational chatting to an autonomous, multi-model execution factory.

## The 7-Step Blueprint
1. **Inbound Stream**: Issues or briefs enter `.kanban/01_new/`.
2. **Task Board**: Local Markdown Kanban state machine (`new` -> `picked_up` -> `review` -> `done`).
3. **The Listener**: Event-driven watcher that automatically claims ready cards.
4. **Report Block & Unbiased Judge**: Real deterministic gate commands (`--lint`, `--test`, `--evidence`) plus a fresh-context judge call (Kem's pink arrow `SENT BACK` on failure).
5. **The Splitter**: Partitions approved specs into parallel single-writer lanes.
6. **Multi-Model Sandboxes**: Allocates tasks across Opus, Sonnet, and local models in isolated sandboxes or worktrees; the worker executes.
7. **Delivery to YOU**: The pipeline stops in `03_review`. The human is the final verifier and moves the card to `done`.

## Quickstart
```bash
# 1. Initialize Kanban in any project
agentic init /path/to/project

# 2. View board
agentic kanban list

# 3. Add a task card
agentic kanban add "Build User Authentication" --req "JWT auth endpoint"

# 4. Run full loop with real gates
agentic run CARD-001 --lint "ruff check ." --test "pytest" --evidence .verify/verify.json
```
