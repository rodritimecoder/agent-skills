# 💻 Hooking Kem Doctrine into OpenCode (`opencode.md`)

> *"Code decides wherever it can; a model should only judge when it's absolutely necessary."*  
> — Kem Glitch, *Code Decides*

OpenCode is an open-source, terminal-native AI agent environment. In this workstation setup, OpenCode connects directly to the local model layer (Genesis 35B coder on `:8080`, Nemotron ASR on `:8081`, Jev decision engine on `:8083`) and free OpenRouter tiers, reading skills directly from `~/src/my-agent-skills/surface`.

---

## 🏛️ OpenCode Host Invariants

1. **Zero-Copy Surface Discovery:** OpenCode reads skills directly from `~/src/my-agent-skills/surface` as configured in `~/.config/opencode/opencode.json`. Any skill symlinked into `surface/` is discovered instantly.
2. **Local Model Affinity:** OpenCode can route sub-tasks directly to local daemon ports without spending API tokens:
   - `:8080` — Genesis Qwen 35B coder (`local-llm`)
   - `:8083` — Jev calibrated decision engine (`jev-decision`)
   - `:8085` / `:8084` — Document & slide OCR (`ocr`)
3. **Compound Bash Batching:** OpenCode supports running multiple commands in structured batch sequences. Scripts should be written to fail-fast (`set -e` or `&&`).
4. **Direct File System Worktrees:** Unlike hosted environments, OpenCode operates directly on local git worktrees. Multi-agent parallelism uses standard git worktrees managed via `worktree-harness`.
5. **Disk Ledgers (`step_NN.json`):** Intermediate outputs should be written directly to workspace files and validated with deterministic Python assertions.

---

## ⚙️ Implementing Kem's 6 Moves in OpenCode

### 1. Step-Level Risk Mitigation (`eval-pipeline`)
In OpenCode, execute tasks as discrete pipeline steps, tagging each step explicitly:
- **`[D]` Step 1: Scaffold & Classify**
  ```bash
  python3 scripts/classify_task.py --task "Implement payment gateway" > step_01_classify.json
  ```
- **`[P]` Step 2: Implement Vertical Slice**
  Run code generation using local Genesis or OpenRouter:
  ```bash
  python3 hardware/local-llm/scripts/llm_client.py "Implement payment provider interface in src/payment/provider.ts" > step_02_patch.diff
  patch -p1 < step_02_patch.diff
  ```
- **`[D]` Step 3: Run Deterministic Assertion Gate**
  Never ask the LLM if the code works. Run the test suite:
  ```bash
  pytest tests/test_payment.py --json-report --json-report-file=step_03_tests.json
  python3 -c "import json; data=json.load(open('step_03_tests.json')); assert data['summary']['failed'] == 0, 'Tests failed!'"
  ```

### 2. Parallel Workers via Git Worktrees (`worktree-harness`)
When handling large refactors or multi-module builds:
1. Create isolated worktrees:
   ```bash
   git worktree add -b slice-backend ../wt-backend main
   git worktree add -b slice-frontend ../wt-frontend main
   ```
2. Spawn worker tasks in the background:
   ```bash
   opencode run --dir ../wt-backend "Implement backend endpoint in src/api/" &
   opencode run --dir ../wt-frontend "Implement frontend view in src/views/" &
   wait
   ```
3. Run the regression gate before merging:
   ```bash
   git -C ../wt-backend diff --name-only main
   pytest tests/
   ```
4. Merge clean worktrees and clean up:
   ```bash
   git merge slice-backend
   git worktree remove ../wt-backend
   ```

### 3. Non-Generative Decision Routing with JEV (`jev-decision`)
When the pipeline needs a judgment (triage, categorization, or holdout scoring), **do not generate prose**. Use the local calibrated decision engine on `:8083`:
```bash
jev bool "Does this patch implement all requirements in specs/payment.md?" \
  --context "$(git diff HEAD~1)"
```
This returns a calibrated probability `p(true)` in under 150ms without consuming context tokens with explanations.

### 4. Fast Retrieval with Notes Index (`notes-index`)
Never grep through thousands of markdown files or vault folders. Use the SQLite FTS5 index:
```bash
notes-index search "payment webhook signature verification" --limit 3 --cite
```
Every citation is verified to exist on disk before it enters the prompt.

### 5. Deterministic Guard-Hooks (`guard-hooks`)
Install guard rails into your shell session to prevent destructive accidents:
```bash
# Add to shell wrapper or task script
python3 /home/rodri/src/my-agent-skills/glitch-cat/guard-hooks/scripts/guard_check.py --command "$USER_OR_AGENT_COMMAND"
```
Rejects `rm -rf`, force pushes, or modifications to protected state files with a non-zero exit code.

---

## 🚫 OpenCode Anti-Patterns to Avoid

| Anti-Pattern | Why It Breaks OpenCode | Kem Fix |
| :--- | :--- | :--- |
| Asking the LLM "Did the tests pass?" | Models hallucinate pass verdicts on broken logs | Use `python3 -c "assert..."` on the raw test exit code or JSON output |
| Spawning agents into the same git directory concurrently | Git index locks and uncommitted file overwrite collisions | Use `git worktree add` to give each agent an isolated filesystem tree |
| Running expensive cloud models for simple bool decisions | Wastes token budget and introduces latency | Use `jev bool` on local port `:8083` |
| Dumping 5,000-line diffs to stdout | Floods terminal scrollback and exhausts context | Redirect to disk (`step_NN.diff`) and inspect line ranges |
| Skipping the control run | Code passes tests that never actually exercised the boundary | Break the implementation on purpose (`mutate-the-test`) and verify failure |
