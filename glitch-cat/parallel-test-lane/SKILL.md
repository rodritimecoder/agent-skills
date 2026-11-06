---
name: parallel-test-lane

description: >
  AI blast radius containment and parallel test runner (Glitch Cat Club; Reel DbSgqTXt-3c).
  Partitions test suites into sequential-isolated vs independent parallel worker lanes across CPU cores,
  slashing 40-60 minute regression suites down to 7-8 minutes with clean non-interleaved output buffering
  and aggregated pass/fail reporting.

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

The helper applies small mutations one at a time — flips a comparison operator,
bumps an integer literal, turns `and` into `or`, deletes a `raise`/`return`
line — and reruns the test command after each, restoring the file in a
`finally` block. A **killed** mutant makes the test command exit non-zero. A
**survivor** means the tests still passed, so nothing exercised the mutated
behaviour: the suite is weaker than it looks. Zero survivors means the test
can fail.

---

## AGENTS.md rule

## Test lanes
Run the suite through the lane planner:
parallel-test-lane run --dir tests/ --lanes 8
- Tests marked serial run alone, in isolation, one at a time.
- Output is buffered per lane; read the aggregated report, not interleaved streams.
- A lane failure is a failure. Do not re-run until it passes.
