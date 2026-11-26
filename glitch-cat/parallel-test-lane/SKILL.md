---
name: parallel-test-lane

description: >
  Use when a regression suite is too slow to run sequentially — partition tests into isolated
  sequential vs independent parallel worker lanes, buffer output cleanly, and aggregate pass/fail
  reporting. AI blast radius containment and parallel test runner. Partitions test suites into sequential-
  isolated vs independent parallel worker lanes across CPU cores, slashing 40-60 minute regression
  suites down to 7-8 minutes with clean non-interleaved output buffering and aggregated pass/fail
  reporting.

compatibility: "Requires Python 3.10+ and a pytest suite to partition."
allowed-tools: "Bash(parallel-test-lane:*) Bash(python3:*) Bash(pytest:*) Read Write"
---

# Parallel Test Lane — AI Blast Radius Containment

```
   Sequential AI Regression Suite (Takes 45 mins):
   [Test 1] ──► [Test 2] ──► [Test 3] ──► ... ──► [Test 200] ──► Slow Agent Loop 🐢

   Kem Glitch Parallel Test Lane (Takes 6-7 mins, 5x-8x Speedup):
   [Serial Reserved Lane] ──► [DB / Stateful Tests]
   [Worker Lane 01]       ──► [Tests 01..25] ┐
   [Worker Lane 02]       ──► [Tests 26..50] ┼──► Aggregated Clean Report ⚡
   [Worker Lane 03..16]   ──► [Parallel...]  ┘
```

---

## Available scripts

Bundled CLI scripts, referenced relative to the skill root. Run `<command> --help`
for flags and exit codes; structured data goes to stdout, diagnostics to stderr.

- `scripts/mutate.py` — Tiny stdlib-only mutation tester: prove a test can fail.
- `scripts/test_lane.py` — Parallel Test Lane — AI Blast Radius Containment.

## ⚡ What It Solves (Reel `DbSgqTXt-3c`)

> *"We spoke about AI blast radius and how to stop it: run regression tests. But when you've got thousands of tests, running them sequentially takes an hour between AI turns... The simple answer: understand which tests need to run in sequence vs parallel, split them across CPU cores in separate lanes. That fits across modern hardware, giving a 5x improvement — what was taking 40 minutes is now 7–8 minutes."*

---

## 🛠️ Usage

```bash
# Set alias or add to PATH
alias parallel-test-lane="python3 /run/media/rodri/AI/skills/parallel-test-lane/parallel_test_lane.py"

# 1. Preview partition plan across CPU threads
parallel-test-lane plan --dir tests/

# 2. Run tests across 8 parallel worker lanes
parallel-test-lane run --dir tests/ --lanes 8

# 3. Specify custom test runner template ({file} placeholder)
parallel-test-lane run --dir tests/ --cmd "pytest -q {file}"

# 4. Buffer full JSON execution report to disk (Uber Protocol)
parallel-test-lane run --dir tests/ --out /tmp/test_report.json
```

---

## 🔒 Serial vs Parallel Partitioning Rule
- Any test file marked with `# serial`, `@serial`, `// serial`, or `@pytest.mark.serial` is automatically placed into the **Serial Reserved Lane** and executed in single-threaded isolation (e.g. tests touching shared databases or fixed local ports).
- All remaining independent unit/integration tests are load-balanced across $N$ CPU worker threads.

---

---

---

## Prove the test can fail

```bash
python3 scripts/mutate.py path/to/module.py --test "python3 -m unittest test_module" --json
```

The helper applies small mutations one at a time — flips a comparison or
`&&`/`||` operator, bumps an integer literal, turns `and` into `or`, deletes a
`raise`/`return`/`throw` line — and reruns the test command after each, restoring
the file in a `finally` block. Comment lines from Python, JS/TS, C-like, SQL, INI
and HTML are skipped, so the helper is language-agnostic.

**Exit codes:** a **killed** mutant makes the test command exit non-zero. A
**survivor** means the tests still passed, so nothing exercised the mutated
behaviour: the suite is weaker than it looks, and `mutate.py` exits **1**. It
exits **0** only when every mutant died. An empty mutation plan exits **1** and
`--limit < 1` is a usage error (**2**): a run with zero mutants never reports
success. `--allow-survivors` restores the old reporting-only behaviour (exit 0)
for exploratory runs.

---

## 🔴 Red on purpose — tests first

Tests first: red, then green, then red on purpose. Every lane must include at
least one mutant deliberately made to fail — prove the gate can fail. A test
that stays green when the code is wrong has no teeth.

---

## AGENTS.md rule

## Test lanes
Run the suite through the lane planner:
parallel-test-lane run --dir tests/ --lanes 8
- Tests marked serial run alone, in isolation, one at a time.
- Output is buffered per lane; read the aggregated report, not interleaved streams.
- A lane failure is a failure. Do not re-run until it passes.
- A surviving mutant is a failure: `mutate.py` exits 1, and the worktree-harness `--mutate` gate fails.
