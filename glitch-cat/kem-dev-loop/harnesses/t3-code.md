# 🛠️ Hooking Kem Doctrine into T3 Code (`t3-code.md`)

> *"You cannot debug a roulette wheel by nudging it. The harness is what makes two runs comparable, and it is the only part of the system you fully control."*  
> — Kem Glitch, *Fix the Harness Before Anything Runs*

T3 Code is an agentic IDE environment driven by the **Agent Client Protocol (ACP)** and host-managed MCP tools (`t3-code`). When running Kem Glitch workflows in T3 Code, you must align Kem's engineering discipline with T3's specific orchestration and concurrency invariants.

---

## 🏛️ T3 Code Host Invariants (Must Respect)

1. **Ordinary tasks need no T3 tools:** For local code inspection, search, edits, and test runs, use bash and direct file tools. Do not invoke `delegate_task` or T3 thread management for routine, single-agent work.
2. **Subagents vs. Delegates:**
   - **Native Subagent:** Use when the child uses your current provider/model, runs within your workspace, and finishes in the current turn.
   - **`delegate_task`:** Mandatory when delegating across different model providers, when using background execution, or when requiring isolated checkouts (`isolation: "worktree"`).
3. **Capabilities Pre-flight:** Call `orchestrator_capabilities` exactly once per thread before the first `delegate_task`.
4. **Never create shell worktrees for delegates:** When requesting isolated branches for parallel workers, pass `isolation: "worktree"` in `delegate_task`. Never manually run `git worktree add` in shell to prepare a child delegate's checkout — T3 Code manages delegate worktrees natively.
5. **Reactive Wakeup (Zero Polling):** Never run polling loops with `task_status`, `sleep`, or timers. T3 Code automatically resumes your turn when background delegates or tasks complete. Stop calling tools to yield.
6. **Thread Linking:** When mentioning a thread, always use its markdown `link` verbatim. Never use a plain title or raw thread ID.
7. **Visual Rendering:** To present diagrams, dashboards, or validation reports to the user, write the HTML to a file, call `html_preview`, and then call `html_render`. Never start a local web server to display results.

---

## ⚙️ Implementing Kem's 6 Moves in T3 Code

### 1. Tag Every Step (`[D]`, `[P]`, `[H]`) & Write to Disk
In T3 Code, the conversation context rots if raw command output and multi-thousand-line diffs are dumped in chat.
- **[D] Deterministic Code:** Run scripts directly via bash (`python3 tests/gate.py`). Redirect output to disk:
  ```bash
  python3 scripts/run_gate.py > step_01_gate.json
  ```
- **[P] Probabilistic Models:** Confine model work to specific files.
- **Artifact Directory:** Store intermediate step ledgers in `<appDataDir>/brain/<conversation-id>/scratch/` or workspace `.harness/runs/`. Always link created files using absolute markdown links: `[step_01.json](file:///absolute/path/to/step_01.json)`.

### 2. Parallel Vertical Slices (`isolate-before-you-parallelise`)
When breaking a complex feature into independent modules:
1. Call `orchestrator_capabilities` once.
2. Partition the work by strict file ownership: Worker A touches `src/api/`, Worker B touches `src/ui/`.
3. Launch delegates with isolated checkouts:
   ```json
   {
     "task": "Implement OAuth token refresh endpoint according to specs in specs/auth.md. Own only src/auth/refresh.ts.",
     "mode": "async",
     "target": {
       "isolation": "worktree",
       "options": {
         "providerInstanceId": "...",
         "model": "..."
       }
     }
   }
   ```
4. End your turn. Do not sleep or poll `task_status`. T3 Code will wake you up when each delegate completes.

### 3. Fresh-Context Unbiased Judges (`fresh-context-judges`)
A builder agent must **never** judge its own code, and a judge must **never** inherit the builder's chat history (to prevent sycophancy).
- In T3 Code, dispatch the judge as a fresh `delegate_task` or a new native subagent with a lean prompt:
  ```markdown
  You are an unbiased code judge.
  Evaluate the pull request or worktree branch: <PR_LINK_OR_BRANCH>.
  Verification criteria:
  1. All regression tests in tests/unit/ pass.
  2. The hidden holdout case in tests/holdout/edge_case.py passes.
  3. No architectural violations of the domain model.

  Output your evaluation strictly as JSON:
  {
    "verdict": "PASS" | "FAIL",
    "rejection_reasons": [...],
    "mutants_tested": [...]
  }
  ```

### 4. Hands-and-Eyes UI Verification (`give-it-hands-and-eyes`)
Before declaring any UI or user-facing feature complete, run verification like a human user:
1. Check preview status: `preview_status`.
2. Open target page: `preview_open` with target URL.
3. Interact using snapshot locators: `preview_act` (click buttons, type form inputs).
4. Assert screen state: verify visual and DOM state; inspect console errors.
5. Close preview tab: `preview_close` before finishing the turn.
6. Render the verification visual to the operator:
   ```python
   # Call html_preview with verification_report.html, then html_render
   ```

### 5. Always Run the Control & Mutate the Test
Before accepting passing tests:
1. Deliberately break the implementation (e.g. comment out validation logic or change expected fee calculation).
2. Run the test suite and confirm it fails (goes red).
3. Revert the mutant and verify it passes (goes green).
4. Save the mutation ledger to `mutant_verification.json`.

---

## 🚫 T3 Anti-Patterns to Avoid

| Anti-Pattern | Why It Breaks T3 Code | Kem Fix |
| :--- | :--- | :--- |
| Running `git worktree add` in bash before calling `delegate_task` | Conflicts with T3's native worktree management; results in locked index files | Pass `"isolation": "worktree"` directly in `delegate_task` |
| Calling `sleep 10` or looping `task_status` | Freezes the ACP loop and consumes turn execution budget | Call no tools; allow T3's event-driven reactive notification to resume your turn |
| Pasting 500 lines of test output into chat | Triggers context rot; causes downstream hallucinations | Write test output to `step_NN.json` and cite only line ranges |
| Reviewing code in the same session turn as the author | Author model will rationalize its own mistakes (sycophancy) | Spawn a fresh delegate with only the diff and the scorecard schema |
| Claiming UI works without previewing | Violates Kem's "Hands and eyes" doctrine | Drive the browser with `preview_*` tools or fail the verification gate |
