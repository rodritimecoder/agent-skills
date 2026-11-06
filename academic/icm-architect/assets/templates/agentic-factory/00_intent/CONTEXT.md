# 00_intent — The Signed Why and Why-Not

One job: Hold the one document every later stage is judged against.

**Actor:** human
**Step type:** H
**Proof:** output/why.md with `approved_by` and `approved_on` set

## Inputs
- Working: the operator's own words about why this project exists
- Reference: ../_shared/kem-contract.md

## Process
1. Write what this exists to do, in the operator's words, not the model's.
2. Write what it explicitly will not do. A non-goal is a decision, not a gap.
3. Name the constraint that must not be traded away, if there is one.
4. The human signs: `approved_by: <name>`, `approved_on: <date>`.

Do NOT load: any plan, spec, or draft. Intent written after reading the design is not intent.

## Outputs
- `output/why.md` → the constitution. Later stages cite it; none may edit it.

## Human check
Read `why.md` and ask one question: could every non-goal here be proven false at the end? If not, rewrite it until it can.
