# Fix the Measuring, Not the Result

**Rule:** When your own inspection catches a flaw that the automated numbers missed, never just patch the code. Fix the measuring harness.

**Why:** If you manually patch the result, you fix one symptom while leaving the blind spot intact. The loop will gladly make the exact same regression next round. If you harden the scoring harness or checklist instead, the system can never silently regress that failure mode again.

**The Four-Tier Scoring Hierarchy (Anthropic Guidance):**
Most people lean on the model to judge its own work, but an uncalibrated scalar (e.g. "rate this 1 to 10") is meaningless. Start with the simplest evaluator that can measure the criterion:
1. **Deterministic program (code):** Unit tests, frame-rate profilers, bundle sizes, latency assertions. Deterministic, instant, and free—but blind to taste.
2. **Blind pairwise A/B:** Present candidates A and B in randomized order to an LLM judge. Models excel at comparative ranking over isolated scalar scoring.
3. **Pointwise binary checklist:** Small calibrated models (e.g., Jev / `h2o-lightning-4b`) evaluating atomic yes/no assertions (*"Does it look on brand?"*) in milliseconds.
4. **Human in the loop:** The ultimate quality and taste anchor, reserved for the final gate.

**In practice:**
- **Describe the outcome, never the solution:** Write what good looks like as checkable properties (e.g., *"responds within two frames"*), not implementation steps, or you will only ever get your own preconceptions back.
- **Give the model sensory tools:** The model needs to experience the work as you would. Give it browser automation tools (e.g. Playwright / CDP) for visuals and telemetry/profilers for performance.
- **Run the Wobble Test:** Before releasing an autonomous optimization loop, score the same baseline candidate multiple times. If answers wobble on identical input, calibrate the judge before running the loop—otherwise you are climbing noise.
- **Enforce strict monotonic improvement:** Keep changes only if the target metric improves and no existing metric or regression test gets worse.
- **Watch competing objectives:** Goals pull each other in opposite directions (e.g. richer animation vs slower load times). Declare tradeoffs explicitly and cap iterations with a hard stopping rule.

**Kem:** *"And when your own hand catches something that the numbers missed, fix the measuring, not the result, right? Most of the real work happens up front, deciding what good looks like and how you'll score it, get that right and the loop does the rest."* — Hill-Climbing Loops: How to Set Them Up Properly [02:23 – 02:40]
