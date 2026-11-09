# Decide What Good Looks Like Before You Build

**Rule:** Evaluation is the step most people leave far too late. Write the test jobs first — including the awkward ones.

**Why:** You cannot optimise a thing you have not defined, and you cannot tell a fix from a regression without a baseline. You never go live with anything until you have evaluated it.

**In practice:**
- Write the jobs, including the ones you expect to fail and the ones that are awkward to set up.
- Judge with code where the answer is computable; judge with a second model where it takes judgement; and check that judge too.
- Sign off the acceptance criteria before the build so the target is fixed while the work happens.
- For design and knowledge work, do the same with intent: before any worker builds, answer who it is for and what great means, and pull references. Adding more models does not help, because they converge; the differentiator is the intent and taste you bring in up front. Kem calls this alignment phase experimental, so treat it as a method to test, not a result.
- The work is in the evaluations and the training set. You put the work in upfront so you do not need to do it later, and you keep measuring.

**Kem:** *"That's evaluation, the step most people leave far too late. Before you build, decide what good looks like and write test jobs, even awkward ones included."* — Demystifying Orchestration [02:11]

*"More models are never the answer. They all just kind of converge, especially with knowledge and design work."* — Glitch Orchestra: alignment first [00:31]
