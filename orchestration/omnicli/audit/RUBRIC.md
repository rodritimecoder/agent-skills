# Audit rubric — Agent Skills spec + omnicli exec-readiness

Ground truth:
- https://agentskills.io/specification (dossier: /run/media/rodri/AI/creator-vault/synthesis/omnicli-sources/07_agentskills-spec-file-references/source.md)
- /home/rodri/src/my-agent-skills/orchestration/omnicli/references/agent-skills-checklist.md
- the code-mode design now in omnicli (strict default, bridge gate, 7 KB caps, session state).

For EACH skill in your batch, check and score these 10 points. Mark PASS / FAIL / N-A with evidence (file:line).

## Spec compliance (agentskills.io)
1. `name` present, `^[a-z0-9]+(-[a-z0-9]+)*$`, 1–64 chars, MATCHES parent dir name.
2. `description` present, 1–1024 chars, states BOTH what and when, imperative/intent-first ("Use when…", "MUST USE for…"), not passive.
3. `SKILL.md` under 500 lines and ~5,000 tokens; exhaustive tables/rubrics moved to `references/`.
4. File references relative to skill root, ONE level deep; no deep chains.
5. `scripts/` contains only runnable CLI entrypoints; helpers/tests kept out (`modules/`, `assets/`, `tests/`).

## Exec-readiness (omnicli Code Mode)
6. Scripts expose exact typed contracts: Python `argparse`, JS `node:util parseArgs`, or `--omni-schema`. No hand-rolled unparseable flags.
7. Non-interactive: no stdin prompts; missing args → actionable stderr + non-zero exit.
8. `--help` prints a `Usage:` line with flags/positionals/subcommands, zero side effects.
9. Structured `--json` on clean stdout; progress/errors on stderr.
10. Bounded output + safe defaults: `--limit`/`--offset`/`--fields`/`--output FILE`; `--dry-run` for destructive ops; no default 50 KB dump.

## Output format per batch
Write to your assigned findings file:

```
# Batch N — findings
## Per-skill table
| Skill | Lines | Spec (1-5) | Exec (6-10) | Blockers | Quick wins |
| :--- | :---: | :--- | :--- | :--- | :--- |

## Top 5 cross-cutting fixes (ranked, with exact file:line and the minimal change)
## Skills that are already exec-ready (name them — do not pad)
```

Return a COMPACT summary to the conductor: counts (PASS/FAIL per point), the top 5 fixes, and the exec-ready list. Do NOT paste the full table into your reply. Edit NOTHING in the skills repo.
