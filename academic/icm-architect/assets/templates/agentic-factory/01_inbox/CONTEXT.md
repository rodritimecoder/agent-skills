# 01_inbox — Requirements Ingestion

One job: Ingest raw user prompt or issue into a structured feature specification.

**Actor:** agent
**Step type:** P
**Proof:** output/feature_spec.md

## Inputs
- Working: User issue description, bug report, or feature request
- Reference: ../_shared/rules.md

## Process
1. Extract target outcomes and non-goals.
2. Define user acceptance criteria.
3. Emit `output/feature_spec.md`.

## Outputs
- `output/feature_spec.md`

## Human check
Verify scope before plan decomposition starts.
