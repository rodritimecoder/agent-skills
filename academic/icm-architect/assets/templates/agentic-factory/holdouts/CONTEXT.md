# holdouts — Anti-Sycophancy Test Suite

One job: Hold acceptance tests the builder never reads, executed only at validation.

**Actor:** agent (planner, at `02_plan_split`) — never the builder
**Step type:** D — the suite runs as code and returns exit codes
**Proof:** `holdout_pass.log`, written here by `06_judge`

## Inputs
- Working: acceptance criteria from ../01_inbox/output/feature_spec.md
- Working: scenarios written during ../02_plan_split/
- Reference: ../_shared/rules.md

## Process
1. Store holdout test scripts and edge case fixtures.
2. Keep them out of every builder's context. `04_sandboxes/` must never list this folder.
3. Nothing here is editable after `02_plan_split` signs the plan. A holdout changed mid-build is not a holdout.

Do NOT load: this folder into a builder's context, ever.

## Outputs
- `holdout_pass.log` — written by `06_judge`, one line per scenario.

## Human check
Confirm the holdouts test what the user asked for, not how the code happens to be written.
