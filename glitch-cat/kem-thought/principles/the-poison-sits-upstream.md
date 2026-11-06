# The Poison Sits Upstream

**Rule:** When the output is wrong, do not debug the output. Find the earliest step that was already wrong.

**Why:** A problem in one step carries through — propagation risk to every step after it. The loudest failure is rarely the first one, and the part that works fine when it is already magic is the part you should not be optimising.

**In practice:**
- Every step saves what it did into its own file, so there is something to check. No artifact, no verification.
- Test each step in isolation, then run the whole thing multiple times and measure the variance.
- If the strongest model fails the same way every time, the bug is in your instructions, not the model: find the sentence that left something unsaid.

**Kem:** *"Checking every step shows you which step causes the problem, and a problem in one step carries through. This is propagation risk to every step after it."* — Eval Pipeline [01:54]
