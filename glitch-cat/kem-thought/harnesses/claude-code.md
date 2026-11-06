# 🎭 Hooking Kem Doctrine into Claude Code (`claude-code.md`)

> *"A skill is instructions the model may follow; a hook is code that ALWAYS runs."*  
> — Kem Glitch, *Kem's Law*

Anthropic's Claude Code CLI is a terminal agent environment built around `CLAUDE.md`, prompt caching, subagents (`Agent`), and bash execution. When running Kem Glitch workflows in Claude Code, anchor your workflow to Claude Code's native hooks, memory limits, and subagent isolation.

---

## 🏛️ Claude Code Host Invariants

1. **`CLAUDE.md` 200-Line Memory Cap:** As established in Kem's `projects-harness`, long context files decay. Keep `CLAUDE.md` strictly below 200 lines: one line per fact, delete superseded history in-place.
2. **Deterministic Pre-Execution Hooks:** Claude Code supports hooks (e.g. `.claude/hooks/pre-tool-use`). This is the ideal native hook location for Kem's `guard-hooks` ("code that ALWAYS runs").
3. **Subagent Types:**
   - `subagent_type: "Explore"` (Read-only, cannot edit files; ideal for research and initial code surveys).
   - `subagent_type: "general-purpose"` (Full read/write permissions for building vertical slices).
4. **Prompt Caching Discipline:** Put static rules, invariants, and schemas at the very beginning of briefs and instructions so Claude Code caches them across turns.
5. **Worktree Support:** Claude Code supports `isolation: "worktree"` for parallel subagents.

---

## ⚙️ Implementing Kem's 6 Moves in Claude Code

### 1. Deterministic Pre-Tool Hooks (`guard-hooks`)
Never rely on prompt instructions to stop destructive commands. Configure `.claude/hooks/pre-tool-use`:
```bash
#!/usr/bin/env bash
# .claude/hooks/pre-tool-use
COMMAND="$1"
python3 /home/rodri/src/my-agent-skills/glitch-cat/guard-hooks/scripts/guard_check.py --command "$COMMAND"
if [ $? -ne 0 ]; then
  echo "❌ [guard-hooks] Blocked dangerous command: $COMMAND" >&2
  exit 1
fi
```
This halts `rm -rf`, `git push --force`, or modification of `.env` before Claude can execute it.

### 2. Spawning Fresh-Context Judges (`fresh-context-judges`)
When reviewing work, spawn a new subagent using `Agent`:
```markdown
Use the Agent tool:
- subagent_type: "general-purpose"
- prompt: |
    You are an unbiased code judge. Evaluate the changes on branch 'feature/oauth'.
    Check:
    1. Run tests: `pytest tests/unit`
    2. Run hidden holdout: `pytest tests/holdout/test_token_replay.py`
    3. Verify no mutations to protected core domain models.
    Output only JSON:
    {"verdict": "PASS" | "FAIL", "issues": [...]}
```
Because the subagent launches with a fresh context window, it cannot be swayed by the parent agent's confirmation bias.

### 3. Worktree Parallelism (`worktree-harness`)
For parallel vertical slices, tell Claude Code to isolate the subagent's checkout:
- Specify `isolation: "worktree"` in the subagent options.
- Assign non-overlapping file scopes (Worker 1 owns `src/auth/`, Worker 2 owns `src/db/`).
- Merge only after each worktree passes the regression gate.

### 4. Continuous State Compaction (`state-compactor`)
Before Claude Code automatically prompts for context compaction (`/compact`):
1. Run `python3 glitch-cat/state-compactor/scripts/compact.py --out .agent_state.json`.
2. Update `STATE.md` with verified facts, current blockers, and completed steps.
3. Keep facts atomic: one bullet per fact, timestamped.

---

## 🚫 Claude Code Anti-Patterns to Avoid

| Anti-Pattern | Why It Breaks Claude Code | Kem Fix |
| :--- | :--- | :--- |
| Bloating `CLAUDE.md` past 200 lines | Model ignores later instructions due to context degradation | Enforce single-line facts; prune stale rules |
| Asking the main session to review its own changes | High risk of sycophancy (model agrees with its prior output) | Launch a fresh subagent with the `Agent` tool |
| Putting security rules only in prompt text | Models can be jailbroken or distracted by complex tasks | Enforce rules in `.claude/hooks/` executable code |
| Reading 3,000-line logs directly into the window | Consumes expensive cache budget | Direct output to `step_NN.log` and use `grep` or `cgate` |
