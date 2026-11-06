# 🚀 Hooking Kem Doctrine into Gemini & Antigravity CLI (`gemini-antigravity.md`)

> *"A skill is instructions the model may follow; a hook is code that ALWAYS runs."*  
> — Kem Glitch, *Rules in Code, Not Context*

Antigravity (Google DeepMind's agentic CLI engine powering Gemini agents) provides high-performance orchestration primitives: native Python workflow graphs (`run_workflow`), dynamic subagent provisioning (`define_subagent`, `invoke_subagent`), isolated git workspaces (`branch` / `share`), surgical file replacement, and reactive messaging.

---

## 🏛️ Antigravity Host Invariants

1. **Native Python Workflow Execution (`run_workflow`):** Antigravity injects Python primitives (`pipeline`, `parallel`, `agent`, `phase`, `log`) into inline workflow scripts. This is the optimal execution environment for Kem's multi-step pipelines.
2. **Dynamic Subagent Definition:** Custom roles can be registered on-the-fly with `define_subagent` (specifying tool permissions and system prompts) and invoked via `invoke_subagent`.
3. **Workspace Isolation (`Workspace` parameter):**
   - `"inherit"` (default): uses parent workspace.
   - `"branch"`: creates an isolated git clone branched from parent.
   - `"share"`: shares underlying object storage like a git worktree (`hg share` / `git worktree`).
4. **Surgical File Edits:** Use `replace_file_content` for single contiguous edits. Avoid full-file rewrites on existing codebases.
5. **Reactive Resumption:** The system resumes execution when background subagents report back or background commands finish. Never poll `manage_task` or run `sleep` commands.
6. **Artifact Storage:** Conversation-scoped persistent artifacts belong in `<appDataDir>/brain/<conversation-id>/`, with scratch data in `.../scratch/`.

---

## ⚙️ Implementing Kem's 6 Moves in Antigravity

### 1. Start with a Workflow (`start-with-a-workflow`)
Kem's Fourth Principle states: *"The workflow graph, the roots, the gates, and the stop condition get written in code before the first agent starts."*

In Antigravity, write the execution graph directly in Python using `run_workflow`:

```python
# kem_pipeline.py executed via run_workflow
phase("scaffold_and_gates")
# Step 1 [D]: Deterministic gate creation
log("Writing holdout assertions...")

phase("parallel_slices")
# Step 2 [P]: Parallel builder workers in isolated workspaces
workers = [
    {"role": "auth_slice", "task": "Build token refresh in src/auth/"},
    {"role": "db_slice", "task": "Add user token table migration in src/db/"}
]

async def build_slice(item):
    worker = agent(
        prompt=item["task"],
        role=item["role"],
        workspace="branch"  # Isolated git branch
    )
    return await worker

results = await parallel(workers, build_slice)

phase("verification_and_judge")
# Step 3 [D]: Run deterministic test runner
log("Running test lane...")

# Step 4 [P]: Fresh-context judge evaluating results
scorecard_schema = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
        "rejection_reasons": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["verdict"]
}

judge = agent(
    prompt=f"Evaluate worker outputs against holdout criteria. Results: {results}",
    schema=scorecard_schema,
    role="Fresh-Context Judge"
)
verdict = await judge
log(f"Judge verdict: {verdict}")
```

### 2. Spawning Fresh-Context Judges (`fresh-context-judges`)
When not using `run_workflow`, invoke a fresh judge via `invoke_subagent`:
1. Use `define_subagent` if custom tools are needed, or call `invoke_subagent` with `TypeName: "research"` or `"self"`.
2. **Never** include previous chat turns, builder apologies, or conversation rationalizations in the judge prompt.
3. Pass **only**:
   - The diff path or commit SHA
   - The test ledger path (`step_02_tests.json`)
   - The holdout criteria and scorecard schema
4. Require typed JSON output: `{"verdict": "PASS"|"FAIL", "failed_checks": [...]}`.

### 3. Isolated Parallel Coding (`isolate-before-you-parallelise`)
When invoking parallel subagents via `invoke_subagent`:
```json
{
  "Subagents": [
    {
      "TypeName": "self",
      "Role": "Auth Backend Slice",
      "Workspace": "branch",
      "Prompt": "Implement refresh token logic in src/auth/. Do not touch other directories."
    },
    {
      "TypeName": "self",
      "Role": "UI Modal Slice",
      "Workspace": "branch",
      "Prompt": "Implement token expired modal in src/components/. Do not touch other directories."
    }
  ]
}
```
Setting `Workspace: "branch"` guarantees neither worker corrupts the other's uncommitted edits.

### 4. Context Rot Shield & Compaction (`state-compactor`)
Long Antigravity sessions can compact automatically. To ensure zero loss of critical engineering facts:
1. Maintain `.agent_state.json` and `STATE.md` at root for every milestone.
2. Store intermediate test results and gate proofs in `<appDataDir>/brain/<conversation-id>/scratch/`.
3. When inspecting large files, use `cgate` (from `state-compactor`) to AST-slice definitions instead of viewing 2,000 lines into context.

### 5. Deterministic Guard-Hooks (`guard-hooks`)
Before running destructive shell commands in `run_command`, invoke the guard check:
```bash
python3 /home/rodri/src/my-agent-skills/glitch-cat/guard-hooks/scripts/guard_check.py --command "$CMD"
```
If the command matches forbidden patterns (`rm -rf /`, `git push --force`, mutation of `.env` or `STATE.md`), halt immediately in code.

---

## 🚫 Antigravity Anti-Patterns to Avoid

| Anti-Pattern | Why It Breaks Antigravity | Kem Fix |
| :--- | :--- | :--- |
| Overwriting entire files with `write_to_file` on existing modules | High token cost; prone to wiping unrelated functions | Use `replace_file_content` targeting exact contiguous line ranges |
| Setting `Workspace: "inherit"` for concurrent coding workers | Both workers edit the same working tree simultaneously, producing merge collisions | Set `Workspace: "branch"` or `"share"` |
| Polling `manage_task` or running `sleep` commands in background | Wastes tool turns and exhausts timeouts | Rely on Antigravity's automatic reactive resumption |
| Slurping entire 100k-token logs into `view_file` | Context poisoning and rapid context window exhaustion | Pipe commands to disk (`> step_NN.log`) and read summaries or grep targets |
| Omitting the stop condition in `run_workflow` | Agents can run recursive loops without bounding criteria | Set strict schemas and step boundaries |
