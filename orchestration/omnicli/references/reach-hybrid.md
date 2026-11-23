# Hybrid audit — Google skill-reach beside the omnicli catalog

> **Status: the head-to-head below is historical research.** It compared
> skill-reach with omnicli's *retired* lexical router, which no longer ships.
> omnicli's current discovery path is one `omnicli exec` plan using
> `omnicli_skills` (`lsSkills` / `readSkill` / `readResource`) plus `describe()`,
> then `invoke()` — never a search tool. The advisory audit use of skill-reach
> described below still applies; the routing comparison does not.

Historical decision (2026-11-21, head-to-head on 120 harvested queries): **keep
omnicli as the router.** skill-reach's offline keyword scorer scored 85/120
top-1 (70.8%); omnicli's then-current router scored 109/120 (90.8%) on the same
queries. A pivot would have been a regression.

skill-reach measures **LLM frontmatter triggering** ("shelf" mode). This
workstation runs **gateway** mode: `opencode.json` points at `surface/`, which
contains only the `omnicli` skill, and `~/.config/skills-frontline` is `gateway`.
Agent Skills progressive disclosure is not the active selection path, so
skill-reach's live probes target a mode we do not run. It also has no OpenCode
adapter.

## What we use it for

An **advisory, offline** audit only — never a gate:

- `reach lint --format json` — frontmatter schema, name collisions, description
  bounds. Warnings are recorded, not enforced: they reflect shelf conventions.
- `reach overlap --format json` — lexical competition across skill names and
  descriptions. Useful for spotting a future keyword-style collision.

`tests/reach_audit.py --repo <checkout>` runs both and writes a timestamped
artifact under `~/.local/share/omnicli/reach-audit/`. It always exits 0. The
managed pre-push hook calls it non-blockingly, after `git-sync check-messages`;
that gate still fails on a subject-only commit (verified by negative control).

## Never

- `reach check` Stage 2 (wrong harness, spends tokens)
- `reach optimize --auto-apply` (would rewrite descriptions for shelf mode)
- treating a reach warning as a failed push

The authoritative gates are the four hard legs of `tests/routing_gate.py`:
`exec_only_flow`, `skills_bridge_flow`, `overfit_check.py`, and
`doc_drift_check.py`, each with a real mutant in `tests/discovery_mutant.py` or
`tests/leg_mutants.py`.
