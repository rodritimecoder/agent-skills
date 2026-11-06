# Mutate the Test (Break the Code on Purpose)

**Rule:** Before you call code or a test done, break the code on purpose and show me it go red. If it stays green, the test is useless.

**Why:** A passing test doesn't prove the code works. When an AI writes tests for its own code, it defaults to vacuous inputs that mirror its implementation rather than testing the specification boundary. Mutation testing is running the negative control on the test itself.

**The Three Invariants for AI Testing:**
1. Work out the expected answer from what I ask for, never from the code.
2. Before you call it done, break the code and show me it go red.
3. Never weaken a test to make it pass.

**In practice:**
- Never accept a green test suite without seeing at least one injected mutant fail.
- Watch for four false-green failure modes:
  1. *Boundary-blind inputs:* inputs never stress the actual decision threshold (e.g. discount never crosses the threshold).
  2. *Loose assertions:* checking existence instead of value (e.g. checking that a delivery fee exists rather than verifying the exact £3.50 amount).
  3. *Tautological mocks:* fake payment system with hardcoded `paid: true` that always succeeds.
  4. *Runtime flakiness:* non-deterministic execution passing or failing due to ambient race conditions.
- High-trust autonomy requires tests that build into a reliable regression suite (`parallel-test-lane`); that is how you manage blast radius with confidence.

**Kem:** *"There's a proper name for checking a test is correct. It's called mutation testing. It's what I showed you. You break the code on purpose and watch the test go red. If it stays green, the test is useless. It's the same idea behind test driven development. So how do you get your AI to do this? Well, you put it somewhere it's read every time, like its rules or a skill, or maybe your planning sequence, and you tell it three things..."* — Do You Even Mutate Tests Bro? [01:55 – 02:40]
