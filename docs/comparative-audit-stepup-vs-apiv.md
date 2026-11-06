# Comparative Audit: StepUp vs. APIV & The 14-Step AI Delivery Lifecycle

This document consolidates the architectural audit and gap analysis of the **StepUp** workstation environment (`/home/rodri` and `/run/media/rodri/AI`) against the **APIV Loop** (Align, Plan, Implement, Verify) and the 14-step AI Delivery Lifecycle.

---

## 1. Executive Verdict

**StepUp matches or exceeds APIV across ~75% of the lifecycle.** APIV introduces no fundamentally new paradigm that StepUp does not already possess. 

StepUp's foundation—anchored by [Interpretable Context Methodology (ICM)](../icm-architect/SKILL.md), [`review-hub`](../review-hub/SKILL.md), [Ponytail](../ponytail/SKILL.md), [Lauren Tan's `pstack`](../pstack/SKILL.md), and the [Grounded Verification Protocol](../../../home/rodri/GEMINI.md)—enforces structural invariants:
- **Folders as state machines** (ICM stage folders, `CONTEXT.md` input/output contracts)
- **Physical single-writer boundaries** (Git worktrees, task briefs, `separate-before-serializing-shared-state`)
- **Executable playbooks** (investigation, feature, prototype, multi-phase plan, orchestrate)
- **The 5-step Grounded Verification Protocol** (`Launch -> Doctor -> Drive -> Evidence -> Cleanup`)

Where APIV often descends into corporate ceremony (mandating separate committee-style markdown artifacts for every micro-phase), StepUp favors compiler-enforced types, automated plan linters, and live runtime drives.

---

## 2. The Two Genuine Gaps & Implemented Upgrades

From the 14 APIV practices, two genuine, high-leverage blind spots were identified and incorporated into StepUp:

### Upgrade 1: Pre-Implementation State Transition Matrix (APIV #5)
- **The Problem**: Discriminated unions prevent illegal states in TypeScript at compile time, but agents can still omit transient real-world states (timeouts, user cancellation, socket disconnects, partial rollbacks) if they were never written into the union.
- **The Fix**: Codified in [`principle-model-the-domain`](../pstack/skills/principle-model-the-domain/SKILL.md) and [`CODING_POWERHOUSE.md`](../docs/coding-powerhouse.md). For stateful async flows or complex UI interactions, agents must write an explicit 2D transition table before coding:

| Current State | Event / Trigger | Guard Condition | Next State | Error / Rollback |
| :--- | :--- | :--- | :--- | :--- |
| `idle` | `SUBMIT` | payload valid | `submitting` | stays `idle`, displays error |
| `submitting` | `SUCCESS` | response ok | `success` | n/a |
| `submitting` | `TIMEOUT` | time > 30s | `failed` | retry count incremented |
| `submitting` | `CANCEL` | user action | `cancelled` | abort controller signal fired |

### Upgrade 2: Numbered Requirement Traceability (`[REQ-XX]`) (APIV #7)
- **The Problem**: Requirements written in issue briefs were disconnected from verification feature maps and PR checklists, creating the risk of silently dropping edge requirements during refactors.
- **The Fix**: Codified in [`create-verification-skill`](../pstack/skills/create-verification-skill/SKILL.md), [`multi-phase-plan`](../pstack/playbooks/multi-phase-plan.md), and validated in [`check-plan.mjs`](../pstack/scripts/check-plan.mjs).
  - Every acceptance criterion carries a `[REQ-XX]` tag.
  - Every PR unit includes `**Traceability.** Satisfies [REQ-XX], [REQ-YY].`
  - Feature verification maps (`features/<feature>.md`) directly link observable end-state proofs to their corresponding `[REQ-XX]` tags.

---

## 3. Capability Matrix Summary

| # | Practice | StepUp Mechanism | Coverage | Verdict |
|:---|:---|:---|:---|:---|
| 1 | Outcome-first brief | Brief schema in `orchestrate`, `feature.md` | **Implemented** | Keep StepUp's concise inline briefs |
| 2 | Shared ontology | Discriminated unions, `model-the-domain`, OKF | **Implemented** | Types beat separate glossary docs |
| 3 | Pattern research | Review Hub API (`review-hub`), `skills-hub`, `agent-reach` | **Implemented** | Pre-indexed skills beat manual spikes |
| 4 | Disposable prototypes | `prototype.md`, isolated scratch workspaces | **Implemented** | Throwaway code behind single switcher |
| 5 | State matrix | Pre-implementation state matrix, Discriminated Unions | **Upgraded (P1)** | Tabulate State x Event -> Next State |
| 6 | Data/module boundaries | ICM single-writer, `separate-before-serializing` | **Implemented** | Physical folder & worktree isolation |
| 7 | Requirement traceability | `[REQ-XX]` tagging, `check-plan.mjs`, feature maps | **Upgraded (P1)** | Numbered tags link briefs to proofs |
| 8 | Execution contract | `multi-phase-plan.md`, `check-plan.mjs` | **Implemented** | Automated linter validates plan |
| 9 | Agent orchestration | `orchestrate.md`, `worktree-audit.sh`, cloud subagents | **Implemented** | Production-grade multi-agent engine |
| 10 | Implementation discipline | Ponytail, Thermo-Nuclear, No-Comments, Unslop | **Implemented** | Minimal diff, 1000-line ceiling |
| 11 | Automated verification | Grounded Verification Protocol (`Prove It Works`) | **Implemented** | Live drives required before completion |
| 12 | Runtime integrity | Grounded Verification `Doctor` step | **Implemented** | Read-only health check before drive |
| 13 | Task closure | ICM filesystem state machine, `orch` CLI | **Implemented** | Filesystem truth beats external tickets |
| 14 | Continuous learning | `graph-memory` (RAG + quote distillation) | **Implemented** | Local RAG + rules in `GEMINI.md` |

---

## 4. Complexity Budget: What Explicitly NOT to Adopt

1. **Dedicated Architecture Spike Documents**: Inline chat briefs avoid context bloat.
2. **Text-Based Glossary/Ontology Documents**: TypeScript types and Zod schemas *are* the ontology.
3. **Formal Committee Sign-Off Gates**: Interactive user grilling via CLI replaces blocking approval ceremonies.
4. **Heavy Traceability Spreadsheets**: Inline `[REQ-XX]` tags in verification maps provide full traceability without overhead.
