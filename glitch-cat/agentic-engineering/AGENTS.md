# AGENTS.md — agentic-engineering

Autonomous production pipeline implementing Kem's (Glitch Cat Club) 7-step loop.

## Where Everything Lives
- `scripts/kanban.py`: Target-local file-based Kanban board engine (`.kanban/`).
- `scripts/listener.py`: Event listener monitoring and auto-claiming inbound cards.
- `scripts/judge.py`: Fresh-context unbiased evaluator applying Kem's rejection delta (`SENT BACK`).
- `scripts/splitter.py`: Multi-model sandbox allocator and task partitioner.
- `_templates/`: Kanban directory template and canonical task card template.
- `agentic.py`: Unified CLI entrypoint.

## Routing
| Intent / Task | Go To |
|---|---|
| Initialize Kanban in a project | `agentic init [path]` |
| Add or move cards on board | `agentic kanban add <title>` / `agentic kanban list` |
| Run event listener | `agentic listen [--once]` |
| Run unbiased judge evaluation | `agentic judge <card-id> [--model flash]` |
| Split task into parallel lanes | `agentic split <title>` |
| Run full 7-step loop | `agentic run <card-id> --test "<cmd>" [--lint "<cmd>"] [--evidence <artifact>]` |
| Prove the UI before evidence | `verify-app run --pass .verify/pass.json` (`verification` skill) |
| Run test suite | `python3 scripts/test_agentic.py` |

## Not This Workspace
- Individual code changes: Performed in target project workspaces or worktrees.
- Local inference port management: Handled by the `local-llm`, `jev-decision` and `ocr` skills.
- Code review rubrics: Handled in `review-hub`.

## Status Rules
- `REVIEW`: Gates passed and the judge approved; the card is in `03_review/` waiting for the human.
- `COMPLETE`: The human moved the card to `04_done/`. A card is never completed by the pipeline alone.
- `REJECTED`: A gate failed or the judge fired the pink arrow; card returned to `02_picked_up/` with delta.
- `UNVERIFIED`: A mock judge or `--dry-run` was used; never counts as a verdict.
- `STALE`: Upstream task brief was modified after card was created.
