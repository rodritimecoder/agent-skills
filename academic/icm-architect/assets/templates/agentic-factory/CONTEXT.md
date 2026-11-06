# {Workspace Name} — Kem's Six-Phase Loop as Files

Sequential stage execution order. Phases 2 and 6 belong to the human; everything between them is the factory. `holdouts/` is a shelf, not a step: it sits outside the numbering because the builder must never read it.

| Phase (Reel `DemLMidtxxj`) | Folder |
| :--- | :--- |
| 2. Intent, approved by a human | [00_intent](00_intent/CONTEXT.md) |
| — work arrives | [01_inbox](01_inbox/CONTEXT.md) |
| 2. Plan, slices, hidden holdouts | [02_plan_split](02_plan_split/CONTEXT.md) → [holdouts](holdouts/CONTEXT.md) |
| 3. Parallel build | [03_kanban](03_kanban/CONTEXT.md) then [04_sandboxes](04_sandboxes/CONTEXT.md) |
| 4. Grounded validation | [05_gates](05_gates/CONTEXT.md), [06_judge](06_judge/CONTEXT.md) |
| 6. Human intent check | [07_intent_check](07_intent_check/CONTEXT.md) |

1. [00_intent](00_intent/CONTEXT.md) — The signed why and why-not.
2. [01_inbox](01_inbox/CONTEXT.md) — Ingest raw requirements, user stories, and bug prompts into a feature spec.
3. [02_plan_split](02_plan_split/CONTEXT.md) — Decompose work into vertical slices, generate holdout tests, emit the plan for approval.
4. [03_kanban](03_kanban/CONTEXT.md) — Target-local markdown Kanban board state machine (todo, doing, done, rejected).
5. [04_sandboxes](04_sandboxes/CONTEXT.md) — Parallel builder worker slots running in isolated git worktrees.
6. [05_gates](05_gates/CONTEXT.md) — Deterministic quality test gates (unit tests, clippy, playwright-rs).
7. [06_judge](06_judge/CONTEXT.md) — Fresh-context unbiased evaluation audit logs evaluating against spec.
8. [07_intent_check](07_intent_check/CONTEXT.md) — Human verdict against the original why and why-not.

[holdouts](holdouts/CONTEXT.md) — concealed acceptance tests, read only by `06_judge`.
