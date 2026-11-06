# Agentic factory — a pipeline specialised for software

A local sixth form, not in upstream. Read it when the repeating unit is **a change to software**, built by parallel agents and gated by code.

It is a Pipeline over the three primitives, with three additions: a shelf outside the numbering, a state machine beside the mtimes, and two human gates that are files. Derived from Kem Glitch's six-phase development loop (Reel `DemLMidtxxj`) expressed as ICM folders, on the seven-step factory (Reel `DehIT3lNgHC`).

Scaffold it with:

```bash
icm-architect init ./my-app --name "My App" --template agentic-factory
```

## Target tree

```
workspace/
├─ entry.md             copied to the root as AGENTS.md: routing, and where the two human gates are
├─ CONTEXT.md           the loop in one screen
├─ 00_intent/           signed why and why-not                 human
├─ 01_inbox/            request -> feature_spec.md
├─ 02_plan_split/       slices, holdouts, plan.md (approved: false)
├─ 03_kanban/           todo/ doing/ done/ rejected/
├─ 04_sandboxes/        isolated workers (worktrees, claims.json)
├─ 05_gates/            tests, linters, UI checks              code decides
├─ 06_judge/            fresh-context audit, runs the holdouts
├─ 07_intent_check/     verdict per non-goal                   human
├─ holdouts/            concealed acceptance tests, outside the numbering
├─ _shared/             rules.md, kem-contract.md
└─ _memory/             entity graph + hybrid search (optional)
```

## What it adds to Pipeline

- **A concealed shelf** (`holdouts/`) outside the numbering. A builder that can read the tests builds to pass the tests; anti-sycophancy is a layout decision, not a rule in a prompt.
- **A physical state machine** (`03_kanban/`) beside the mtimes: cards move, and a rejected card carries its evidence with it.
- **Two human gates that are files.** Intent is signed once up front; a verdict per non-goal closes the run. Approval that lives only in the conversation is not approval.
- **The three contract fields** from `_shared/kem-contract.md` on every stage: `Actor`, `Step type` (D/P/H), `Proof`. `icm-architect validate . --kem` fails on a gap.

## Take it when

- The repeating unit is a feature or a change, and the repo is the product.
- Some automated check can go red — a test, a linter, a UI assertion. That is the spine.
- The work splits into independent vertical slices worth running in parallel.
- Someone will read `why.md` at the end and answer for each non-goal.

## Do not take it when

- **There is no gate.** `05_gates` then holds opinions, and the judge's verdict is a model's taste dressed as a result. Use Pipeline and let a person check each handoff instead.
- **The work is one fix.** The folder ceremony is bigger than the change; route it down the fast lane and skip the plan gate.
- **The deliverable is not software** — a deck, a video, a vault. That is Pipeline or Knowledge bundle.
- **Nobody will sign twice.** Then this is a build script wearing folders.

## Tooling it assumes

`05_gates` names `pytest` / `cargo test` / `playwright-rs`, and `04_sandboxes` assumes worktree isolation with `claims.json` line ranges. Both are contract text: edit them to match the repo. A JavaScript factory is the same shape with `vitest`.

## Every check still ends at a check

The pipeline's own checks are `check.md` verdicts like any other stage. A gate that cannot fail is not a gate, and a check that shares the author's context is not a judge — `06_judge` runs in a fresh context and reads only the holdouts and the diff.
