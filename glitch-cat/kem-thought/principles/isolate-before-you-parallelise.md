# Isolate Before You Parallelise

**Rule:** One worktree per agent, a claim before every write, and an explicit merge step. Then, and only then, fan out.

**Why:** Two agents editing the same file overwrite each other's work. That is not a race condition you can retry — it is a silent loss.

**In practice:**
- Worktree per agent, branch per agent.
- Claim the section before writing it. A claim is the deterministic record of ownership, not an etiquette.
- The merge is a step with a decision in it: keep both versions, let a fresh-context agent check them against the spec, then let code test the answer.

**Kem:** *"Two agents editing the same files at once overwrite each other's work, so each gets its own copy, a Git work tree, plus a system around it, claims. So no two agents take the same task and merge that bring the work back and settle the conflicts."* — Demystifying Orchestration [01:31]
