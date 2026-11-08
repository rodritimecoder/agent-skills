---
name: kem-dev-loop
description: >
  Kem Glitch's 6-phase autonomous AI development lifecycle (Glitch Cat Club; Reel DemLMidtxxj).
  The CLI holds the order: a builder cannot be dispatched before hidden holdouts exist,
  and validation refuses a gate that postdates the dispatch or a builder that exited
  non-zero. Use for FULL_ROUTE work that needs plan approval, anti-sycophancy holdouts,
  and grounded evidence.
compatibility: "Requires python3 and git. The decision model on :8083 is optional."
allowed-tools: "Bash(kem-dev-loop:*) Bash(jev:*) Bash(review-hub:*) Bash(git:*) Read Write"
---

# Kem Dev Loop

Six phases. The CLI holds the order so the prose does not have to be trusted.

## The loop

```bash
# 1. Route (deterministic pre-screen, then the model on :8083 if it is up)
kem-dev-loop route "Add --json to the okf-architect validate subcommand"

# 2. The human approves the plan, then the gates -- BEFORE any builder exists
kem-dev-loop init okf-json
$EDITOR .kem-loop/okf-json/plan.md      # Why / Why Not
kem-dev-loop approve okf-json           # he reads it on serious work; MVPs pass --skip-plan-review
kem-dev-loop holdout add okf-json .kem-loop/okf-json/holdouts/test_validate.py

# 3. One builder, one task file, all output on disk
kem-dev-loop dispatch okf-json --task /tmp/task_okf.txt
#   DISPATCH ok exit=0 62.4s log=.kem-loop/okf-json/dispatch/builder_....log

# 4. Validate: holdouts, plus the app as a user for UI slices
kem-dev-loop validate okf-json --test "python3 academic/okf-architect/scripts/okf_architect.py validate . --json"
verify-app run --pass .verify/pass.json      # click, type, see the screens -- not a screenshot claim

# 5. Review the passing code, then hand the diff to the human
kem-dev-loop review okf-json --suite ponytail src/
```

## A holdout is a script, and it carries its own control

One file, exit 0 or fail. The positive case and the negative control live in the
same script, so nobody can register a gate that cannot fail:

```python
# .kem-loop/<run>/holdouts/test_validate.py
import subprocess, sys

script = "academic/okf-architect/scripts/okf_architect.py"

# positive: valid input must succeed
p = subprocess.run([sys.executable, script, "validate", ".", "--json"], capture_output=True)
assert p.returncode == 0, p.stderr
assert p.stdout.startswith(b"{"), "stdout is not pure JSON"

# control: the gate must be able to fail
bad = subprocess.run([sys.executable, script, "--invalid-flag-xyz"], capture_output=True)
assert bad.returncode != 0, "control failed: invalid input was accepted"

print("PASS: validate holdout + control")
```

`.py` runs as a script, `.sh` via bash, `.js` via node, from the project root, with
`KEM_RUN_DIR` pointing at the run folder. Evidence per gate lands in
`.kem-loop/<run>/evidence/`.

## What refuses what

| Command | Refuses when | Why |
| :--- | :--- | :--- |
| `holdout add` | file is outside `.kem-loop/<run>/holdouts/` | a builder must not read the gate |
| `holdout add` | `.py` is pytest-style with no `__main__` | it would pass vacuously |
| `dispatch` | the plan was not approved (`--skip-plan-review` for an MVP) | the human approves before anything is built |
| `dispatch` | no holdout registered, or one changed since registration | the gate predates the build |
| `dispatch` | `--task` is a directory or missing | one bounded slice per dispatch |
| `validate` | holdout registered or modified **after** dispatch | this is the sycophancy breach |
| `validate` | holdout hash changed since registration | a gate edited to fit the code is not a gate |
| `validate` | builder exited non-zero | the slice never landed; prints `tail -n 25` |
| `validate` | no dispatch (`--local` if you wrote it yourself) | Phase 3 happened, or it did not |
| `review` | validation has not passed | review is about clean, not about working |

A refusal is a bug in the process, not an obstacle.

## Rules

1. **Approve, then holdouts, then build.** The human reads `plan.md` before
   anything is built; on a quick MVP it is skipped unread, and `dispatch` records
   which one happened. Holdouts are written and registered next. Ordering is
   checked by timestamp and hash; you cannot backfill.
2. **One Conductor, bounded builders.** You run gates. The builder never talks to
   the human, never spawns subagents, never sees `holdouts/`.
3. **One task file.** Exact target file, arguments, return schema. Not "audit the
   codebase". `dispatch` copies it and hands the builder the copy.
4. **Disk owns the logs.** The builder's output never enters chat; read
   `tail -n 25` only when it failed.
5. **Validate, then review.** Functional proof precedes style.
6. **Two attempts, then stop.** The cap lives in `meta.json`; a third needs `--force`.
7. **The human keeps the Why and Why Not.** Phase 6 shows evidence and the diff.

## State

`.kem-loop/<run>/meta.json` holds `holdouts` (name → hash + timestamp) and
`dispatch` (timestamp, exit code, log). Nothing else gates the loop.

## References

- [`references/subagent-dispatch-playbook.md`](references/subagent-dispatch-playbook.md) —
  conductor/builder separation, the "dead subagent" post-mortem, prompt templates.
- [`references/architecture.md`](references/architecture.md) — blueprint and reel notes.
