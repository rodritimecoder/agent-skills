# 06_judge — Fresh-Context Unbiased Evaluation

One job: Audit completed work against spec in a fresh context.

**Actor:** agent
**Step type:** P
**Proof:** output/judge_verdict.md

## Inputs
- Working: ../01_inbox/output/feature_spec.md
- Working: ../04_sandboxes/output/worker_patch.diff
- Working: ../holdouts/
- Reference: ../_shared/rules.md

## Process
1. Judge evaluates deliverables without seeing worker's trial-and-error thoughts.
2. Execute holdout test suite.
3. Emit final verdict.

## Outputs
- `output/judge_verdict.md`

## Human check
Final sign-off before merging into main branch.
