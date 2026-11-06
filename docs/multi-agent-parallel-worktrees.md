# Multi-Agent Parallel Git Worktrees & Swarm Compiler Architecture

The Glitch Cat Club / Kem & Anthropic Parallel Subagent Compiler Pattern on a Local Ryzen Substrate.

---

## 1. The Multi-Agent Concurrency Dilemma

When multiple autonomous coding agents work on the same repository, naive architectures fail in one of three ways:
1. **Directory Clobbering**: Two subagents write to `src/app.py` in the same directory concurrently, producing race conditions, partial writes, and broken git status trees.
2. **Context Degeneration**: Forcing a single model to hold 50 files and 20 test iterations degrades its effective reasoning and context window.
3. **Fictitious Completion**: Agents self-report "I have fixed the issue!" without executing real tests.

---

## 2. The 6 Core Invariants of `worktree-harness`

The `worktree-harness` architecture solves these failure modes through 6 strict invariants:

```
                          [ Main Frontier / Lead Agent ]
                                         │
                                         ▼
                            tasks.json Plan Decomposition
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   │               swarm-dispatch              │
                   ▼                                           ▼
      .harness/.../wt-auth                        .harness/.../wt-db
       (Isolated Worktree)                         (Isolated Worktree)
        Branch: harness/.../wt-auth                 Branch: harness/.../wt-db
        Model: gemini-3.5-flash-lite                Model: nemotron-3-ultra
                   │                                           │
                   ├─ Claim: src/auth.py                       ├─ Claim: src/db.py
                   ├─ Write Code & Tests                       ├─ Write Migrations & Tests
                   └─ $HARNESS gate (green)                    └─ $HARNESS gate (green)
                   │                                           │
                   └─────────────────────┬─────────────────────┘
                                         ▼
                            $HARNESS integrate
                         (Automated Merge & Arbitration)
                                         │
                                         ▼
                           harness/.../integration
```

### 1. Git Worktree Isolation
Never let multiple agents share a disk directory. Each worker runs in an isolated worktree (`.harness/runs/<run_id>/worktrees/<worker>/`) on a dedicated branch (`harness/<run_id>/<worker>`). Worktrees share underlying Git object storage without duplicating repo history.

### 2. Pre-Write Section Claiming (`claims.json`)
Before modifying files or line ranges, agents declare intent via `claim`:
```bash
python3 $HARNESS claim --run-id run_01 --worker wt-auth --file "src/auth.py" --lines "1-60"
```
If two workers declare overlapping files, the harness emits a conflict warning and registers the overlap in `claims.json`.

### 3. Deterministic Quality Gates ("Code Decides")
Models are forbidden from judging their own completion. Unit/integration tests (`pytest`, `vitest`, `cargo test`) and an optional app-proof command decide whether work passes:
```bash
python3 $HARNESS gate --run-id run_01 --worker wt-auth \
  --test "pytest tests/test_auth.py" \
  --verify "verify-app run --pass .verify/pass.json"
```
Gate status (`GATE_PASSED` / `GATE_FAILED`), duration, each check's exit code, and output are immutably recorded. `--test` proves the code; `--verify` proves the app.

### 4. Gated Integration
`integrate` reads the manifest and refuses to merge a worker whose gate status is not `GATE_PASSED`; `--allow-untested` is the explicit override. A branch that was never gated is not "verified" by being merged.

### 5. Automated Merge Conflict Arbitration
When merging worker branches into `harness/<run_id>/integration`, adjacent hunk collisions are automatically arbitrated using:
- **Calibrated Synthesizer (Fast Path)**: Preserves sequential imports, additive function declarations, and non-overlapping block unions.
- **Decision Engine (Fallback)**: Leverages `inception/mercury-decide:free` or local `h2o-lightning-4b` through `jev-decision` (`:8083`) to arbitrate semantic conflicts.
- **Post-Merge Verification**: Runs global integration tests immediately following merge.

### 6. Append-Only Event Log (`events.jsonl`)
Every lifecycle state transition is logged with ISO timestamps:
```json
{"timestamp": "2026-10-15T04:58:10Z", "event": "HARNESS_INITIALIZED", "data": {"goal": "..."}}
{"timestamp": "2026-10-15T04:58:10Z", "event": "WORKER_SPAWNED", "data": {"worker": "wt-add"}}
{"timestamp": "2026-10-15T04:58:10Z", "event": "SECTION_CLAIMED", "data": {"worker": "wt-add", "file": "adder.py"}}
{"timestamp": "2026-10-15T04:58:16Z", "event": "WORKER_COMPLETED", "data": {"worker": "wt-add", "exit_code": 0}}
{"timestamp": "2026-10-15T04:58:34Z", "event": "WORKER_INTEGRATED", "data": {"worker": "wt-add"}}
```

---

## 3. The 1-Command Autonomous Compiler: `swarm-dispatch`

`swarm-dispatch` connects `worktree-harness` with `openrouter-free` to turn task plans into executable parallel compiles.

### Input Specification (`tasks.json`)
```json
[
  {
    "worker": "wt-auth",
    "task": "Implement OAuth2 / JWT authentication in src/auth.py",
    "files": ["src/auth.py"],
    "test": "pytest tests/test_auth.py",
    "model": "gemini-3.5-flash-lite"
  },
  {
    "worker": "wt-db",
    "task": "Add user migration schema and pool logic in src/db.py",
    "files": ["src/db.py"],
    "test": "pytest tests/test_db.py",
    "model": "nvidia/nemotron-3-ultra-550b-a55b:free"
  }
]
```

### Execution
```bash
# Execute autonomous parallel run
swarm-dispatch --tasks tasks.json --max-turns 6 --timeout 300

# Inspect live claims and worker dashboard
worktree-harness status

# Inspect consolidated output on integration branch
git checkout harness/<run_id>/integration
```
