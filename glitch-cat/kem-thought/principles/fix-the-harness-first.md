# Fix the Harness Before Anything Runs

**Rule:** The workflow graph, the roots, the gates, and the stop condition get written in code before the first agent starts.

**Why:** You cannot debug a roulette wheel by nudging it. The harness is what makes two runs comparable, and it is the only part of the system you fully control.

**In practice:**
- The lead orchestrator gets three things: a goal, how well it is done, and when to stop.
- The graph is code; the agents are interchangeable parts.
- A harness you rewrite after every incident was never a harness.
- Never fight the host runtime. Hook Kem primitives into your active harness using the adapter in `../harnesses/`:
  - **T3 Code**: see `../harnesses/t3-code.md` (ACP delegates, `isolation: "worktree"`, preview tools, reactive wakeups).
  - **Gemini / Antigravity**: see `../harnesses/gemini-antigravity.md` (Python `run_workflow`, `invoke_subagent` branch workspaces).
  - **OpenCode**: see `../harnesses/opencode.md` (local daemons, bash compounding, git worktrees).
  - **Claude Code**: see `../harnesses/claude-code.md` (`.claude/hooks`, `CLAUDE.md` memory budget).
  - **Pi Agent / Boxxy Claw**: see `../harnesses/pi-boxxy.md` (hot-reloaded skills, direct CLI tools).

**Kem:** *"It begins with a harness, a workflow graph designed before anything runs. The roots and the gates are fixed in the code."* — 5 Agents Writing the Same File [00:12]
