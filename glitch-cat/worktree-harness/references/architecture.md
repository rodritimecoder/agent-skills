# Run Directory Architecture

Everything a run writes lives under `.harness/runs/<run_id>/` in the target
repository, so a run is inspectable and replayable after the fact.

```
.harness/runs/run_v1/
├── worktrees/
│   ├── agent-auth/          # isolated git worktree for one worker
│   ├── agent-db/
│   └── agent-api/
├── claims.json             # reserved file and line ranges, per worker
├── events.jsonl            # immutable, time-indexed event log
└── integration/            # the branch verified branches are merged into
```

## The event log

`events.jsonl` is append-only. Every spawn, claim, gate pass or fail, and
merge is one JSON object per line, timestamped. Nothing rewrites it, so the
history of a run is a replay rather than a summary.

```json
{"ts": "2026-03-30T14:02:11Z", "event": "spawn", "run_id": "run_v1", "worker": "agent-auth", "branch": "agent/agent-auth"}
{"ts": "2026-03-30T14:04:52Z", "event": "claim", "run_id": "run_v1", "worker": "agent-auth", "file": "src/auth.py", "lines": "1-50"}
{"ts": "2026-03-30T14:07:03Z", "event": "gate", "run_id": "run_v1", "worker": "agent-auth", "status": "pass", "test": "pytest tests/test_auth.py"}
```

## Claims

`claims.json` holds the reservations agents make *before* writing. A claim
names a file, and optionally a line range within it. A second agent claiming
an overlapping range is the collision the harness exists to prevent, and the
arbitrator is what resolves it if the ranges do overlap in practice.

## Why a worktree, not a branch

A branch alone does not isolate the *disk*. Two agents on two branches still
share one checkout, so an agent that runs `git checkout` or writes a build
artifact breaks the other. A worktree gives each agent its own directory on
its own branch, so the only shared state is the object database — and every
write is explicit.

## Teardown

`teardown` removes the worktrees but keeps the consolidated integration
branch and the event log. The log is the record of what happened; deleting
it with the worktrees would throw away the only durable evidence of the run.
