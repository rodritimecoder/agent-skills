---
name: worktree-harness

description: >
  Spawn parallel coding subagents into isolated git worktrees, reserve the
  file ranges they will write, gate each branch on the project's own tests,
  and merge the passing ones with automated conflict arbitration. Use when
  several agents will edit the same repository at once.

compatibility: "Requires git and Python 3.10+."
allowed-tools: "Bash(worktree-harness:*) Bash(git:*) Bash(python3:*) Read Write"
---

# Worktree Harness (`worktree-harness`)

An autonomous multi-agent orchestration harness for high-concurrency coding
tasks, without file-clobbering. It implements the architecture detailed by
Kem (Glitch Cat Club) and Anthropic's parallel subagent compiler workflows.

---

## 🏛️ The 6 Core Invariants

1. **Git Worktree Isolation**: Never let multiple subagents write to the same disk directory concurrently. Each worker runs in its own isolated worktree (`.harness/runs/<run_id>/worktrees/<worker>/`) on a dedicated branch.
2. **Pre-Write Section Claiming**: Agents declare and reserve file or line ranges in `claims.json` before writing, preventing overlapping collision.
3. **Deterministic Quality Gates ("Code Decides")**: Code and test suites decide whether work passes — models only judge when strictly necessary. A gate takes `--test` (the project's suite) and/or `--verify` (an app-proof command such as `verify-app run --pass .verify/pass.json`); both must exit 0.
4. **Gated Integration Only**: `integrate` refuses to merge a worker whose gate status is not `GATE_PASSED`. `--allow-untested` is the explicit override, not the default.
5. **Automated Merge Conflict Arbitration**: If two worker branches touch conflicting lines, an arbitrator agent (or local Jev decision model) synthesizes an additive resolution, followed immediately by the post-merge gate.
6. **Immutable Time-Indexed Event Log**: Every spawn, claim, gate pass/fail, and merge is recorded in `.harness/runs/<run_id>/events.jsonl`, enabling deterministic state replays.

---

## 🛠️ CLI Quickstart

```bash
# 1. Initialize a run and spawn isolated worktrees
worktree-harness start \
  --goal "Refactor API error handling and write integration tests" \
  --workers agent-auth agent-db agent-api \
  --run-name run_v1

# 2. Reserve a file or line range before writing
worktree-harness claim --run-id run_v1 --worker agent-auth --file "src/auth.py" --lines "1-50"

# 3. Run the quality gate inside the worker worktree: tests first, app proof second
worktree-harness gate --run-id run_v1 --worker agent-auth --test "pytest tests/test_auth.py"
worktree-harness gate --run-id run_v1 --worker agent-auth \
  --test "pytest" \
  --verify "verify-app run --pass .verify/pass.json"

# 4. Integrate GATE_PASSED branches only, arbitrating conflicts and re-gating the result
worktree-harness integrate --run-id run_v1 --test "pytest" \
  --verify "verify-app run --pass .verify/pass.json"

# 5. Check live status and the claims dashboard
worktree-harness status --run-id run_v1
worktree-harness status --run-id run_v1 --json

# 6. Tear down the worktrees, keeping the integration branch and event log
worktree-harness teardown --run-id run_v1 --delete-branches

# 7. The one-command swarm compiler — same tool, pairs with openrouter-free
swarm-dispatch --tasks tasks.json
swarm-dispatch \
  --goal "Refactor user authentication and database models" \
  --workers wt-auth wt-db wt-api \
  --test "pytest" \
  --verify "verify-app run --pass .verify/pass.json" \
  --model "gemini-3.5-flash-lite"
```

`--test` proves the code; `--verify` proves the app. A branch can pass a unit
suite and still ship a cut-off button, so the second command is how the
`verification` gate joins this harness.

---

## Reference

- `references/architecture.md` — how the run directory, worktrees and event log fit together

---

## AGENTS.md rule

## Parallel edits: worktrees and file ranges
When more than one agent will edit this repository, run:
worktree-harness start ...
worktree-harness claim --run-id <run> --worker <agent> --file "<path>" --lines "<range>"
- Two agents never write the same file range. Claims are enforced, not trusted.
- Every branch is gated on the project's own tests before it is integrated.
- `integrate` only merges `GATE_PASSED` workers; `--verify` adds app proof beside `--test`.
