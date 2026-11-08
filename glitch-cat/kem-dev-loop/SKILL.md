---
name: kem-dev-loop
description: >
  Kem Glitch's 6-phase autonomous AI development lifecycle (Glitch Cat Club; Reel DemLMidtxxj).
  The CLI is the state machine: it refuses to dispatch a builder before hidden holdouts
  exist, refuses to validate an undispatched or tampered run, and refuses code review
  before a passing validation. Use for FULL_ROUTE work that needs plan approval,
  anti-sycophancy holdouts, and grounded evidence.
compatibility: "Requires python3, git, and local decision model (:8083)."
allowed-tools: "Bash(kem-dev-loop:*) Bash(jev:*) Bash(review-hub:*) Bash(git:*) Read Write"
---

# Kem Dev Loop

Six phases. **The CLI enforces the order; the prose below does not.** There are five
commands and you run them in sequence. Each one refuses if you skipped the one before.

## The whole loop

```bash
# 1. Route: deterministic pre-screen, then the calibrated model on :8083
kem-dev-loop route "Add --json to the okf-architect validate subcommand"

# 2. Plan, approve, gate -- BEFORE any builder exists
kem-dev-loop init okf-json
$EDITOR .kem-loop/okf-json/plan.md                      # fill in Why / Why Not
kem-dev-loop approve okf-json --by human
kem-dev-loop holdout add okf-json .kem-loop/okf-json/holdouts/test_pass.py    --kind pass
kem-dev-loop holdout add okf-json .kem-loop/okf-json/holdouts/test_control.py --kind control

# 3. Dispatch ONE builder from ONE task file. All output goes to disk.
kem-dev-loop dispatch okf-json --task /tmp/task_okf.txt
#   DISPATCH ok exit=0 62.4s log=.kem-loop/okf-json/dispatch/builder_....log

# 4. Validate: the only place assertions run
kem-dev-loop validate okf-json --test "python3 academic/okf-architect/scripts/okf_architect.py validate . --json"

# 5. Review the passing code, then hand the diff to the human
kem-dev-loop review okf-json --suite ponytail src/
```

Holdouts run from the invocation directory (the project root), with `KEM_RUN_DIR`
pointing at `.kem-loop/<run>/` for fixtures. `.py` runs under pytest when it is
installed, otherwise as a plain script (so give it an `if __name__ == "__main__"`
block); `.sh` runs via bash, `.js` via node. Each gate's stdout, stderr and exit
code lands in `.kem-loop/<run>/evidence/`.

A missing runner is an environment fault, not a failed build: `validate` says so
and does not spend a retry.

`route` prints `FAST_ROUTE` or `FULL_ROUTE`. Only `FULL_ROUTE` uses this loop; a
`FAST_ROUTE` change is executed directly with normal verification.

## What the CLI refuses

| Command | Refuses when | Because |
| :--- | :--- | :--- |
| `approve` | `plan.md` still has empty **Why** / **Why Not** | A plan with no stated intent approves nothing. |
| `holdout add` | the file is not inside `.kem-loop/<run>/holdouts/` | Holdouts must stay where a builder cannot see them in-tree. |
| `dispatch` | plan not approved | Phase 2 is a human gate, not a formality. |
| `dispatch` | no holdouts registered | A builder with no gate can only be graded on its own opinion. |
| `dispatch` | no `--kind control` holdout (`--allow-no-control` records a waiver) | A gate that cannot fail is not a gate. |
| `dispatch` | a registered holdout's hash changed | The gate was edited after being written. |
| `dispatch` | already dispatched successfully (`--redispatch` to override) | Stops accidental double builds. |
| `validate` | no dispatch recorded (`--local` if you wrote it yourself) | Phase 3 happened, or it did not. |
| `validate` | the builder exited non-zero | The slice never landed; it prints `tail -n 25` of the log. |
| `validate` | a holdout was registered or modified **after** dispatch | This is the sycophancy breach the loop exists to prevent. |
| `validate` | a holdout hash changed after registration | A gate edited to fit the code is not a gate. |
| `validate` | an unregistered file sits in `holdouts/` | Every gate must be declared before the build. |
| `validate` | no control was registered (`--allow-no-control` records a waiver) | Proves the gate can fail. |
| `review` | `validation_passed` is false | Review checks whether code is clean, not whether it works. |

Every refusal exits non-zero and says what to run next. A refusal is a bug in the
process, not an obstacle to route around.

## Rules that make it work

1. **Holdouts first.** Write the positive gate *and* the negative control before
   dispatch. `validate` compares timestamps and hashes; you cannot backfill.
2. **One Conductor, bounded builders.** You orchestrate and run gates. The builder
   never talks to the human, never spawns subagents, never sees `holdouts/`.
3. **One task file.** `dispatch --task` takes a single file with the contract: exact
   target file, exact arguments, exact return schema. No "audit the codebase".
4. **Disk owns the logs.** `dispatch` already buffers to
   `.kem-loop/<run>/dispatch/*.log` and prints one receipt line. Never stream raw
   builder output into chat; read `tail -n 25` only when it failed.
5. **Validate, then review.** Functional proof precedes style and type review.
6. **Two attempts, then stop.** The retry cap is enforced in `meta.json`; a third
   validation needs `--force` and a human decision.
7. **The human keeps the Why and Why Not.** Phase 6 shows evidence and the minimal
   diff; the human decides whether it still matches the original intent.

## Phase map

| Phase | Owner | Command | Artifact |
| :--- | :--- | :--- | :--- |
| 1. Classify | Conductor | `route` | route + source + confidence |
| 2. Intent & holdouts | Human + Conductor | `init`, `approve`, `holdout add` | `plan.md`, registered holdouts |
| 3. Build | Builder (dispatched) | `dispatch` | `dispatch/task_*.md`, `dispatch/builder_*.log` |
| 4. Validate | Conductor | `validate`, `verify-app run` for UI | `evidence/validation_*.json` |
| 5. Review | Conductor | `review` | `review-hub` suite output |
| 6. Intent check | Human | — | approved diff |

Run state lives in `.kem-loop/<run>/meta.json`:

```json
{
  "plan_approved": true,
  "holdouts": {"test_pass.py": {"kind": "pass", "sha256": "…"},
               "test_control.py": {"kind": "control", "sha256": "…"}},
  "dispatch": {"started_at_epoch": 1762…, "exit_code": 0, "log": ".kem-loop/…/builder_….log"},
  "validation_passed": true,
  "validation_attempts": 0,
  "waivers": []
}
```

## References

- [`references/subagent-dispatch-playbook.md`](references/subagent-dispatch-playbook.md) —
  conductor/builder separation, the "dead subagent" post-mortem, and prompt templates.
- [`references/architecture.md`](references/architecture.md) — full blueprint and reel notes.
