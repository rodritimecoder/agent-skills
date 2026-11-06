# 02_plan_split — Plan Approval & Task Splitter

One job: Break feature spec into vertical slices and create holdout tests.

**Actor:** agent
**Step type:** P
**Proof:** output/plan.md with `approved: true`

## Inputs
- Working: ../01_inbox/output/feature_spec.md
- Reference: ../_shared/rules.md

## Process
1. Decompose into independent vertical slices (frontend, backend, schema).
2. Write holdout verification tests into `../holdouts/`.
3. Create task cards in `../03_kanban/todo/`.
4. Emit `output/plan.md` with frontmatter `approved: false`.

## Outputs
- `output/plan.md` — starts unapproved; the human flips it
- Task cards in `../03_kanban/todo/`

## Human check
Read the plan and the hidden holdouts. Set `approved: true` in `output/plan.md`, or send it back. Builders do not spawn while it is false.
