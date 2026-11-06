# 07_intent_check — Human Intent Gate

One job: Decide whether what was built still serves the why it was built for.

**Actor:** human
**Step type:** H
**Proof:** output/intent_check.md with one verdict per non-goal in `00_intent`

## Inputs
- Working: ../00_intent/output/why.md (frozen; never edit it here)
- Working: ../06_judge/output/judge_verdict.md
- Working: ../05_gates/output/gate_results.json
- Reference: ../_shared/kem-contract.md

## Process
1. Walk the change the way the user would: click, type, read the screens.
2. Answer, per non-goal in `why.md`: `HELD`, `BROKEN`, or `NOT EXERCISED`.
3. Answer once: does this still do what we said, and only that?
4. Cite the evidence behind every line.
5. A "no" returns the work to `03_kanban`. It does not get a nicer summary.

Do NOT load: the builders' scratchpads. Do not accept a summary where evidence was asked for.

## Outputs
- `output/intent_check.md`

## Human check
Every line cites something observable: a screenshot, a test log, a URL. "Looks good" is not a verdict.

## When the project runs

For someone who cannot read the diff, the readable artifact is a walk: `glitch-walk` renders the flow with the real screens and the code behind each step. A person who can see the walk can hold this gate. A person who can only read a summary is ratifying it.
