---
id: "{CARD_ID}"
title: "{CARD_TITLE}"
status: "new"
priority: "P1"
model: "flash"
created: "{TIMESTAMP}"
assigned_sandbox: "sandbox-1"
---

# {CARD_ID}: {CARD_TITLE}

## Objective
{OBJECTIVE}

## Acceptance Criteria (`[REQ-XX]`)
- [ ] `[REQ-01]`: Core implementation meets specifications.
- [ ] `[REQ-02]`: Zero regressions across existing test lanes.

## Deterministic Code Gates (Blue Diamonds)
- [ ] `gate_lint`: Lint and typecheck pass with exit code 0
- [ ] `gate_test`: Automated test lane passes
- [ ] `gate_evidence`: Observable proof (exit codes, transcript, logs) recorded

## Unbiased Judge Evaluation
- Status: PENDING
- Evaluator Model: flash
- Verdict: UNREVIEWED
- Rejection Delta: NONE
