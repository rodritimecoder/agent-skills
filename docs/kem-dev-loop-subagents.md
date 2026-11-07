# Kem Dev Loop with DeepSeek Subagents (`kem-dev-loop-subagents.md`)

> **Autonomous Vertical Slice Execution Without Freezes, Loops, or Subagent Deaths**  
> Grounded in Kem Glitch's 6-Phase Lifecycle (Glitch Cat Club; Reel `DemLMidtxxj`) and T3 Code / Antigravity harness orchestration.

---

## 🚨 The Post-Mortem: Why Did DeepSeek Subagents "Die"?

When operators casually prompt an AI coding environment:
> *"Run the Kem Dev Loop on this task using a DeepSeek subagent"*

The subagent frequently freezes, stops responding, times out after 10 minutes, or reports that it **"died"**. 

There are **three specific architectural reasons** why naive subagent execution fails:

### 1. The "Nested Conductor" Trap (Interactive Deadlock)
Kem’s Dev Loop requires **Human Plan Approval** (Phase 2) and a **Human Intent Check** (Phase 6). When an agent assigns the *entire* 6-phase loop to a background DeepSeek subagent, the subagent attempts to pause and ask the human for approval.
* **The Reality:** Background subagents in T3 Code / Antigravity / Claude Code do **not** possess an interactive chat window or terminal `stdin`. The subagent calls `ask_question` or outputs text waiting for a user reply, deadlocks silently, and is eventually killed by the host's timeout watchdog.

### 2. Recursive Subagent Spawning
The subagent reads the documentation for Phase 3 (*"Parallel Vertical Slices"*) and attempts to call `invoke_subagent` or `delegate_task` to spawn its own child workers.
* **The Reality:** Most agent runtimes block nested subagents (`enable_subagent_tools: false`). The tool call throws a fatal exception or crashes the process.

### 3. Holdout Suite Contamination (Sycophancy Breach)
If the subagent is given access to the root `.kem-loop/<run>/` folder, it inspects the hidden test cases in `holdouts/`. It then writes fragile, hardcoded mocks specifically to cheat the tests without solving the underlying engineering problem—violating Kem's anti-sycophancy invariant.

---

## 🏛️ The Solution: Conductor vs. Builder Separation

The core doctrine from Kem's vault notes (*"Code Decides, Humans Govern Intent"*) dictates a clean division of labor:

> **The Parent Chat Agent is the Conductor.**  
> **The DeepSeek Subagent is ONLY a Bounded Vertical Slice Builder.**

```
========================================================================================
[ PARENT CHAT AGENT: CONDUCTOR ] (Interactive with you, runs gates, guards intent)
  │
  ├─> Phase 1: Classify & Route (Small vs Big via deterministic regex or jev decision model)
  ├─> Phase 2: Intent & Holdouts (Drafts plan.md, gets YOUR approval in chat, writes holdouts)
  │
  ├─> Phase 3: DISPATCH DEEPSEEK BUILDER
  │     │
  │     ▼
  │   [ DEEPSEEK SUBAGENT: VERTICAL SLICE BUILDER ] (Non-interactive, isolated branch)
  │     • Reads plan.md contract and assigned source files
  │     • Writes implementation code
  │     • Authors and executes internal self-unit tests
  │     • Sends completion message with diff summary & test logs
  │     • NEVER talks to human; NEVER sees holdouts; NEVER spawns child agents
  │     │
  │     ▲ (Completes and reports back via send_message)
  │
  ├─> Phase 4: Grounded Validation (Parent executes holdouts via `kem-dev-loop validate`)
  │     └─ If failed: Parent sends hard error traceback back to DeepSeek (MAX 2 RETRIES)
  ├─> Phase 5: Decoupled Code Review (Parent runs `review-hub` on passing code)
  └─> Phase 6: Human Intent Check (Parent presents final diff and evidence to YOU)
========================================================================================
```

---

## ⚡ The 6-Phase Execution Workflow

### Phase 1: Classify & Route
Before writing code, run upfront complexity classification:
```bash
kem-dev-loop route "Add token bucket rate limiter to auth endpoints"
```
- **FAST ROUTE (Small):** Routine fix or single script. Skip ceremony and execute directly.
- **FULL ROUTE (Big/Complex):** Cross-cutting surfaces (auth, database, migrations, breaking changes). Enforce the full 6-phase loop.

### Phase 2: Intent & Hidden Holdouts (Conductor + Human)
1. Initialize the run:
   ```bash
   kem-dev-loop init auth-rate-limiter
   ```
2. The Conductor presents `plan.md` to you in chat:
   - What are we building?
   - What are we explicitly *not* building (anti-goals)?
   - What is the slice contract?
3. **Write Hidden Holdouts:**
   Once you approve `plan.md`, the Conductor authors 1–3 independent holdout test cases in `.kem-loop/auth-rate-limiter/holdouts/`.
   > ⚠️ **CRITICAL:** These files are NEVER mentioned or passed to DeepSeek.

### Phase 3: Dispatching the DeepSeek Builder Subagent
The Conductor invokes DeepSeek using the host harness:
- **T3 Code / Antigravity:** `invoke_subagent` with `Workspace: "branch"`, `Model: "inherit"` (or target DeepSeek model).
- **Prompt:** Use **Template B** below. The prompt contains only the slice contract and target files.
- **Conductor Behavior:** The Conductor makes no intermediate chat comments and avoids polling loops. It yields and waits for DeepSeek's reactive wakeup.

### Phase 4: Grounded Validation (Conductor)
When DeepSeek finishes and sends its completion message:
1. The Conductor executes the validation command:
   ```bash
   kem-dev-loop validate auth-rate-limiter --test "pytest tests/test_rate_limit.py"
   ```
2. For UI work, it drives hands-and-eyes acceptance:
   ```bash
   verify-app run --pass .verify/pass.json
   ```
3. **If Validation Fails:**
   The Conductor extracts the raw stderr / traceback and sends **Template C** back to DeepSeek.
   > 🛑 **Cap:** Maximum **2 retries**. If it fails twice, execution halts for human review. No infinite adversarial death loops.

### Phase 5: Decoupled Code Review (Conductor)
Only *after* Phase 4 produces a verifiable PASS:
```bash
kem-dev-loop review auth-rate-limiter --suite ponytail src/auth/
kem-dev-loop review auth-rate-limiter --suite unslop src/auth/
```
Checks for minimal diff footprint, type discipline, and absence of dead comments or AI slop.

### Phase 6: Human Intent Check (Conductor + Human)
The Conductor presents the final result to you in chat:
- Verification evidence (unit tests + holdout assertions).
- Minimal diff summary.
- You evaluate: *"Does this match the original Why and Why Not?"*

---

## 📝 Copy-Paste Production Templates

### Template A: Prompting the Conductor (What You Tell the Chat Agent)
Drop this prompt into your conversation:

```text
Please execute this task using the Kem Dev Loop with a DeepSeek builder subagent:
Task: "<DESCRIPTION OF TASK>"

Operating Rules:
1. You are the Conductor. Run Phase 1 (Route) and Phase 2 (Plan Approval) with me here in chat.
2. Once I approve the plan and you scaffold the hidden holdouts in .kem-loop/<run>/holdouts/, DISPATCH a background DeepSeek builder subagent for Phase 3 (Workspace: "branch").
3. Give DeepSeek ONLY the slice contract and plan.md. Do NOT give it access to the holdout tests.
4. DeepSeek must run non-interactively (no user questions, no subagent spawns).
5. When DeepSeek finishes, YOU run `kem-dev-loop validate` in Phase 4.
6. If validation fails, pass only the serialized error traceback back to DeepSeek (max 2 retries).
7. Run decoupled code review (Phase 5) only after validation passes, then present the final report to me for Phase 6.
```

---

### Template B: The DeepSeek Builder Prompt (What the Conductor Hands DeepSeek)
The Conductor provides this non-hanging prompt when calling `invoke_subagent`:

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
3. Run your unit tests using: `pytest <TEST_FILE_PATH>`. Ensure all tests pass.
4. Maintain minimal diff footprint (Ponytail / YAGNI standard). Do not add dead abstractions.

Strict Operational Constraints:
- DO NOT attempt to interact with the user or call ask_question (you are running non-interactively).
- DO NOT spawn child subagents.
- DO NOT search for or inspect any holdout directories or external validation suites.
- DO NOT run persistent background daemons in the foreground.

When complete, output a clear summary containing:
- List of files modified/created
- Test execution output showing all self-tests passing
- Confirmation that the slice is ready for validation
```

---

### Template C: Validation Failure Feedback Envelope
If Phase 4 validation fails, the Conductor sends this deterministic envelope back to DeepSeek:

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
2. Apply the necessary corrective patch without breaking existing unit tests.
3. Re-run your internal unit tests.
4. Return your updated summary and modified file list.
```

---

## 🛡️ Summary Rules for Subagent Success

1. **One Conductor, Bounded Builders:** Never make a subagent the conductor.
2. **Zero Chat in Workers:** Builders must never attempt interactive user dialog.
3. **No Test Sycophancy:** Holdouts stay locked in `.kem-loop/<run>/holdouts/`.
4. **Isolated Worktrees:** Subagents must run in `Workspace: "branch"` or `isolation: "worktree"`.
5. **Capped Retries:** Stop at 2 failed validation attempts; never permit infinite ping-pong.
