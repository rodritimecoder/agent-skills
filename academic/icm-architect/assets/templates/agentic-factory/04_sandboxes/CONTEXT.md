# 04_sandboxes — Parallel Worker Execution

One job: Execute tasks in isolated worktree sandboxes.

**Actor:** agent
**Step type:** P
**Proof:** output/worker_patch.diff

## Inputs
- Working: Active task card from `../03_kanban/doing/`
- Reference: ../_shared/rules.md

## Process
1. Claim target line ranges in `claims.json` before editing.
2. Implement required code in worker branch.
3. Run worker-local test gate.

## Outputs
- `output/worker_patch.diff`

## Human check
Verify no uncommitted files or claim conflicts exist.
