# 03_kanban — Physical State Machine

One job: Track active task card status across physical folders.

**Actor:** code
**Step type:** D
**Proof:** output/kanban_status.md

## Inputs
- Working: Cards in `todo/`, `doing/`, `done/`, `rejected/`
- Reference: ../_shared/rules.md

## Process
1. Refuse to move any card while `../02_plan_split/output/plan.md` says `approved: false`.
2. Move card from `todo/` to `doing/` when worker claims it.
3. Move card from `doing/` to `done/` when gates pass and judge approves.
4. Move card to `rejected/` if gates or judge fail (with attached evidence).

## Outputs
- `output/kanban_status.md`

## Human check
Inspect cards in `rejected/` to diagnose persistent failures.
