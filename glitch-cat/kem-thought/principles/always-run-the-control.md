# Always Run the Control

**Rule:** Run the simplest version side by side with your system, on the same jobs. If you never run the control, you never learn whether your agents were decoration.

**Why:** On simple jobs, a single call to the model can beat a whole team in a fraction of the tokens. Also: if the strongest model gives the same wrong answer every time, your prompt is the bug, not the model.

**In practice:**
- The control is one model call, or one session, on the same worktree and the same jobs.
- Route by complexity: easy → local and free, moderate → mid-tier, hard → frontier. Train the classifier on your own labelled prompts, not someone else's.
- Shadow-verify the cheap answers behind the response; when the cheap answer fails, the expensive one replaces it before anyone notices, and the failure becomes training data.
- Every request therefore becomes an evaluation.

**Kem:** *"Always run the simplest version side by side with a single call to the model, because on simple jobs it can beat out a whole team in a fraction of the tokens."* — Demystifying Orchestration [02:28]
