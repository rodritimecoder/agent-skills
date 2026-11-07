# Kem Dev Loop Subagent Dispatch Playbook
## How to Run Autonomous Vertical Slices Without Dying or Hanging

> **Glitch Cat Club / Kem Glitch Production Engineering Guide**  
> Synthesized from Reel `DemLMidtxxj` (*"How I Develop with AI (High Level)"*) and operational harness telemetry.

---

## 🚨 The Post-Mortem: Why Did the Subagent "Die"?

When an operator prompts an AI model with *"Run the Kem Dev Loop on this task using subagents"*, the subagent frequently crashes, freezes, times out, or reports that it **"died"**. 

There are **5 distinct root causes** for this failure:

| # | Failure Mode | What Actually Happened | The Fix |
|---|---|---|---|
| **1** | **The "Nested Conductor" Trap** *(Most Common)* | The subagent was handed the *entire* 6-phase loop. In Phase 2 and Phase 6, the subagent tried to ask the human for approval. Because background subagents do not have an interactive user chat modal or stdin, execution blocked indefinitely until the harness watchdog killed it. | **The Parent Agent is the Conductor; the Subagent is ONLY a Builder.** Subagents must never be asked to interact with the human. |
| **2** | **Recursive Spawn Crash** | The subagent tried to call `invoke_subagent` or `delegate_task` to create further subagents for parallel vertical slices. Most agent harnesses explicitly disable nested subagent spawning or lack recursive tooling, throwing an uncaught exception. | **Only the top-level parent agent spawns subagents.** Subagents work on single vertical slices directly. |
| **3** | **Context Bloat & Token Starvation** | The parent agent dumped entire git logs, multiple file contents, or holdout code directly into the subagent's prompt argument, exhausting its context window on Turn 1. | **Pass file paths and concise requirements (`plan.md`).** Let the subagent read target files on demand via its own file tools. |
| **4** | **Git / Worktree Collision** | The subagent attempted to edit files directly in the active working directory while the parent agent was also writing, causing git dirty tree errors, lock collisions, or merge conflicts. | **Always use isolated workspaces or worktrees** (`Workspace: "branch"` in T3 Code or `worktree-harness` in CLI). |
| **5** | **Hanging Interactive Process** | The subagent invoked a long-running process (like `npm start`, a dev server, or a command requiring interactive input like `git push` prompting for credentials or `less` pager), causing execution to hang until timeout. | **Batch commands deterministically; never run long-running daemons in foreground tool calls.** |

---

## 🏛️ The Conductor vs. Builder Separation of Concerns

The single most critical invariant of Kem's methodology when using subagents is:

> **The Parent Agent conducts the lifecycle. The Subagent is strictly a bounded Vertical Slice Builder.**

```
========================================================================================
[ PARENT AGENT: CONDUCTOR ] (Has human chat channel, runs gates, guards intent)
  │
  ├─> Phase 1: Classify & Route (Deterministic regex -> jev decision model)
  ├─> Phase 2: Intent & Holdouts (Talks to HUMAN, gets plan.md approval, creates holdouts)
  │
  ├─> Phase 3: DISPATCH SUBAGENT(S)
  │     │
  │     ▼
  │   [ SUBAGENT: VERTICAL SLICE BUILDER ] (Isolated branch, non-interactive, code-only)
  │     • Reads plan.md and target source files
  │     • Writes implementation code
  │     • Writes internal self-unit tests in tests/
  │     • Emits list of modified files & reports completion
  │     • NEVER sees holdouts; NEVER talks to human
  │     │
  │     ▲ (Completes and returns to Parent)
  │
  ├─> Phase 4: Grounded Validation (Parent executes holdouts via kem-dev-loop validate)
  │     └─ If failed: Parent sends hard error diff back to builder (MAX 2 RETRIES)
  ├─> Phase 5: Decoupled Code Review (Parent runs review-hub on passing code)
  └─> Phase 6: Human Intent Check (Parent presents final diff and evidence to HUMAN)
========================================================================================
```

---

## 📋 The 6-Phase Execution Matrix

| Phase | Responsible Role | Permitted Tools | Forbidden Actions |
|---|---|---|---|
| **1. Classify & Route** | **Parent Agent** | `kem-dev-loop route`, `jev choice` | Spawning subagents before knowing task complexity. |
| **2. Intent & Holdouts** | **Human + Parent** | `ask_question`, `write_to_file` (`.kem-loop/<run>/holdouts/`) | Sharing holdout scenarios with builder prompts. |
| **3. Parallel Build** | **Subagent(s)** | `view_file`, `replace_file_content`, `run_command` (tests only) | Calling `ask_question`, spawning subagents, reading holdouts. |
| **4. Grounded Validation** | **Parent Agent** | `kem-dev-loop validate`, `verify-app run` | Model-based open debate; asking builder to self-validate holdouts. |
| **5. Decoupled Review** | **Parent Agent** | `review-hub` (`ponytail`, `unslop`, `types`) | Running lint/style reviews *before* functional validation passes. |
| **6. Human Intent Gate** | **Human + Parent** | Direct chat, GitHub pull request links | Merging or pushing code without human intent confirmation. |

---

## 🛠️ Operational Guide: How to Run the Subagent Kem Loop

### Step 1: Run Upfront Routing (Parent Agent)
Run the deterministic classifier to check whether this is a `FAST_ROUTE` (routine/small) or `FULL_ROUTE` (complex):
```bash
kem-dev-loop route "Implement token bucket rate limiter in auth middleware"
```
If `FULL_ROUTE`, proceed through all 6 phases. If `FAST_ROUTE`, skip the committee and execute directly.

### Step 2: Human Plan Approval & Scaffolding (Parent Agent)
Initialize the run folder and draft `plan.md`:
```bash
kem-dev-loop init auth-rate-limiter
```
Present the **Why and Why Not** to the human:
1. What are we building?
2. What are we explicitly *not* building (anti-goals)?
3. What is the contract?

Once approved by the human, write 1–3 **hidden holdout tests** in `.kem-loop/auth-rate-limiter/holdouts/`.
> ⚠️ **CRITICAL INVARIANT:** Do NOT mention these holdout files, their file paths, or their assertions in the subagent prompt. This prevents test sycophancy.

### Step 3: Launching the Builder Subagent (Parent Agent)
When calling `invoke_subagent` (or your harness equivalent):
- **Role:** `"Vertical Slice Builder"`
- **TypeName:** `"self"` (or your platform's coding subagent type)
- **Model:** `"inherit"`
- **Workspace:** `"branch"` (or an isolated git worktree via `worktree-harness`)

Use **Template B** below for the prompt. The subagent will work quietly in the background, run its own self-unit tests, and notify the parent when finished.

### Step 4: Grounded Validation (Parent Agent)
When the subagent completes, the parent agent executes the validation gate:
```bash
kem-dev-loop validate auth-rate-limiter --test "pytest tests/test_rate_limit.py"
```
- If the app has a frontend/UI, run hands-and-eyes acceptance:
  ```bash
  verify-app run --pass .verify/pass.json
  ```
- **If validation FAILS:**
  Do **NOT** start an open-ended debate. Collect the exact exit code, stdout/stderr traceback, or failed assertion, and send **Template C** back to the subagent.
  > 🛑 **Cap:** Maximum **2 validation retries**. If it fails a second time, halt and escalate to the human operator. Never permit infinite loops.

### Step 5: Decoupled Code Review (Parent Agent)
Only *after* Phase 4 produces a verifiable PASS artifact:
```bash
kem-dev-loop review auth-rate-limiter --suite ponytail src/middleware/
kem-dev-loop review auth-rate-limiter --suite unslop src/middleware/
```
Clean up styling, remove AI tells/comments, and enforce type discipline.

### Step 6: Final Human Intent Check (Parent Agent)
Present the final diff and validation proof to the user:
```markdown
### Verification Evidence
- ✅ Unit Suite: 8 passed
- ✅ Hidden Holdout Suite: 3 passed (zero sycophancy)
- ✅ Ponytail Minimal Diff Audit: 0 unnecessary abstractions
```
Await human confirmation before pushing or merging.

---

## 📝 Production Prompt Templates

### Template A: Prompting the Conductor (What the Operator tells the Parent Agent)
Use this prompt when instructing the main agent to orchestrate the loop:

```text
Please execute this task using the Kem Dev Loop methodology:
Task: "<DESCRIPTION OF TASK>"

Operating Rules:
1. You are the Conductor. Run Phase 1 (Route) and Phase 2 (Plan Approval) with me.
2. Once I approve the plan and you write the hidden holdouts in .kem-loop/<run>/holdouts/, DISPATCH a background builder subagent for Phase 3.
3. The subagent must be given ONLY the slice specification and plan.md. Do NOT give the subagent access or references to the holdout tests.
4. When the subagent finishes, YOU (the conductor) will run `kem-dev-loop validate` in Phase 4.
5. If validation fails, pass only the serialized error logs to the subagent (max 2 iterations).
6. Run decoupled code review (Phase 5) only after validation passes, then present the final result to me (Phase 6).
```

---

### Template B: The Subagent Builder Prompt (What the Conductor gives the Subagent)
Use this bounded, non-hanging prompt when launching the child subagent:

```text
You are a Vertical Slice Builder for task: <TASK_NAME>.

Context & Contract:
- Specification: Read <ABSOLUTE_PATH_TO_PLAN_MD>
- Target files to modify/create:
  - <FILE_1>
  - <FILE_2>
- Test file to author: <TEST_FILE_PATH>

Your Mandate:
1. Implement the required functionality adhering strictly to the contract in plan.md.
2. Author your own unit tests in <TEST_FILE_PATH> to verify your implementation.
3. Run your unit tests using: `pytest <TEST_FILE_PATH>` (or equivalent test command). Ensure all tests pass.
4. Maintain minimal diff footprint (YAGNI). Do not add unrequested helper frameworks or dead abstractions.

Strict Operational Constraints:
- DO NOT attempt to interact with the user or ask interactive questions (you are running non-interactively).
- DO NOT spawn further subagents.
- DO NOT search for or inspect any holdout directories or external validation suites.
- DO NOT start persistent background services or daemons in the foreground.

When complete, output a clear summary containing:
- List of files modified/created
- Test execution output showing all self-tests passing
- Confirmation that the slice is ready for validation
```

---

### Template C: The Validation Failure Envelope (Adversarial Error Feedback)
If Phase 4 validation fails, send this deterministic feedback envelope back to the subagent:

```text
Validation Gate FAILED (Attempt <N> of 2).

Failure Reason:
<SUMMARY OF THE FAILURE>

Serialized Evidence:
```
<EXACT STDOUT / STDERR / FAILED ASSERTION / STACK TRACE>
```

Instructions:
1. Analyze the exact failure evidence above.
2. Apply the necessary corrective patch to resolve the failure without breaking existing unit tests.
3. Re-run your internal unit tests.
4. Return your updated summary and modified file list.
```

---

## 🛡️ Harness-Specific Safeguards

### In T3 Code / Antigravity Harness:
- **Launching:** Use `invoke_subagent` with `TypeName: "self"`, `Role: "Vertical Slice Builder"`, `Model: "inherit"`, `Workspace: "branch"`.
- **Waiting:** After calling `invoke_subagent`, **do NOT poll** `manage_task` or loop. Simply end your turn or proceed with independent work. The T3 harness will wake you when the subagent message arrives.
- **Never Call:** `ask_question` from inside a subagent; it will hang or error out.

### In Claude Code / Terminal Conductors:
- Launch worker panes using `glitch-orchestra` or dispatch into dedicated git worktrees using `worktree-harness add <branch>`.
- Keep the conductor pane clean: feed child panes through file descriptors or discrete task prompts.

### In Cursor / OpenCode:
- Set up isolated branches so that model edits do not cause file flickering or language server churn in the active editor pane.
