# Upstream sync

Base: [RinDig/icm-architect](https://github.com/RinDig/icm-architect) commit `8bc2f56` (merge of `any-harness`, 2026-10-23).
Synced: 2026-11-05.

Upstream files are copied verbatim. Everything below is local and must be re-applied (or deliberately dropped) after the next upstream merge.

## Local files

| Path | What it is |
|---|---|
| `references/agentic-factory.md` | Local sixth form: Kem Glitch's six-phase loop as folders. Upstream has five forms. |
| `references/examples/` | Five worked workspaces (course decks, script-to-animation, voice-driven animation, workspace-builder, system-map of a code project). Never in upstream. |
| `references/method-paper.md` | Long-form notes on arXiv:2603.16021. |
| `references/reference-integrity.md` | Move-safety checklist. Upstream folded the short version into Restructure mode; the examples still link this file. |
| `assets/templates/agentic-factory/` | Whole workspace starter for the Agentic factory. `entry.md` is copied to `AGENTS.md` by the CLI. |
| `assets/templates/kem-contract.md` | `Actor` / `Step type` / `Proof`, plus the Kem rules around gates. |
| `scripts/icm_architect.py` | `init` / `validate` / `doctor` / `map`, plus optional graph memory. |
| `tests/test_icm_architect.py` | CLI tests. |

## Edits inside upstream files

- `SKILL.md`
  - Forms table: one extra row for the Agentic factory.
  - Restructure step 4: pointer to `references/reference-integrity.md`.
  - Walk test: one extra check — a `check.md` older than its input marks the stage `STALE`.
  - Guardrails: one extra bullet, anti-patterns seen in the wild.
  - `## Local extensions` section at the end.
- `README.md`: rewritten; upstream install table kept, local extensions documented.
- `scripts/icm_architect.py`: accepts both `## Check` and the older `## Human check`; scaffolds `## Check`; copies the factory's `entry.md` to `AGENTS.md`.

## Deliberately dropped

- `references/build-mode.md`, `restructure-mode.md`, `walk-test.md`, `guardrails.md`: upstream moved this prose into `SKILL.md` and `references/core.md`.
- `assets/templates/AGENTS.md`, `node.md`, `schema.md`: replaced by upstream's `entry.md`, `context-map-node.md`, `context-map-schema.md`. `entry.md` also stops a harness auto-loading a template as instructions.
