# Start Low, Step Up on Fail

**Rule:** Always begin a task on the cheapest model at lowest effort. Only step up model tier and reasoning effort when the automated test fails.

**Why:** Higher model tiers and maximum reasoning effort frequently burn 30x the cost and 20x the latency for zero additional correctness on routine tasks. Both a $0.07 low-effort model and a $2.10 max-effort model pass the exact same test. Even after paying for the failed cheap runs, optimistic escalation across an entire project is substantially cheaper than defaulting to frontier reasoning.

**In practice:**
- A task is a piece of work with an automated test that decides whether it passed (SWE-bench standard: red to green, existing tests stay green).
- Define the test first. A model cannot self-escalate without an objective test gate.
- Pass 1: Send the task to the cheapest flash model at low effort. Let code decide.
- If the test passes, stop immediately.
- If the test fails, step up the model tier or effort level, supplying the failed test trace and diff.
- The saving is where you start, not when you swap. Swapping to a cheaper model after the first edit saved almost nothing in Kem's runs (8/10 at about Opus's cost); starting cheap and stepping up only on a failed test passed 10/10 for a third less and about a quarter faster.
- Re-test the numbers on your own work with every new model and price; the payoff depends on the price ratio.
- Log every result (prompt attributes, model, effort, latency, cost, pass/fail) and feed that log into a classifier to train a project-specific task router.

**Kem:** *"A simple strategy you can apply is to always begin a task on the cheapest model, run its test to see if it passes and tell your system to only step up the model and effort when it fails. People suggest that even after paying for the runs that fail, it still works out cheaper. So I measured it across all six tasks, and generally that does hold out."* — Which Effort? Which Model? Routing via Automated Tests [00:48]

*"So the big saving isn't the swap. It's starting cheap and only stepping up when the test fails."* — Swap After the First Edit [02:23]
