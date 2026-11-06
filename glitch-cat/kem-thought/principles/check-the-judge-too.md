# Check the Judge Too

**Rule:** The judge is a model, so the judge needs a check. Never let the last word be an unverified opinion.

**Why:** A model can write all these checks, but it is still a model. You only know the judge is right if something independent confirms it.

**In practice:**
- Code judges where the answer is computable; a second model judges where it takes judgement.
- Where the judge's verdict is expensive, sample it against code on a known-answer set.
- Calibrate it: a decision engine with a known error rate beats a confident paragraph.

**Kem:** *"Check answers with code or a second model as the judge where it takes judgment — and check the judge too."* — Demystifying Orchestration [02:20]
