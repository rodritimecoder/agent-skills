# 🌐 Glitch Cat Suite: Complete Cross-Harness Matrix (`skills-matrix.md`)

This matrix details how every skill in the **Glitch Cat Suite** hooks into each major host harness: **T3 Code**, **Gemini / Antigravity CLI**, **OpenCode**, **Claude Code**, and **Pi Agent / Boxxy Claw**.

---

## 👥 1. Multi-Agent & Orchestration Skills

### `worktree-harness`
*Multi-agent parallel Git worktree orchestration & quality gate claims.*
- **T3 Code:** Do **not** run `git worktree add` in shell. Pass `isolation: "worktree"` directly in `delegate_task`. T3 Code binds the worktree to the delegate thread natively.
- **Gemini / Antigravity:** Set `Workspace: "branch"` (isolated clone) or `"share"` (git worktree / hg share) in `invoke_subagent`.
- **OpenCode:** Direct terminal management via `git worktree add ../wt-worker-N`. Workers run parallel `opencode run` processes, merging only after passing tests.
- **Claude Code:** Pass `isolation: "worktree"` to the `Agent` tool, or manage worktrees via `Bash` tool with file range locks.
- **Pi / Boxxy:** Standard git worktree CLI calls in split terminal panes.

### `projects-harness`
*Autonomous multi-agent CLI coordination, 3-way message routing, dual provenance envelope, 200-line memory cap.*
- **T3 Code:** Dual provenance maps to T3 Code instructions: user brief vs coordinator instructions. Envelope hooks format thread-to-thread messages.
- **Gemini / Antigravity:** Direct mapping to `send_message` between subagent conversation IDs. Enforces 200-line memory cap in `.agent_state.json`.
- **OpenCode:** Headless coordination via FIFO queue files in `.harness/queue/`. Max 2 concurrent tasks throttled in bash.
- **Claude Code:** Governs `CLAUDE.md` line count and inter-subagent task routing.
- **Pi / Boxxy:** Local process FIFO messaging and terminal status badges.

### `glitch-orchestra`
*Terminal conductor architecture for multi-session agent supervision.*
- **T3 Code:** T3 IDE takes the place of tmux conductor panes; subagent threads represent specialist panes.
- **Gemini / Antigravity:** Emulated via `run_workflow` pipeline script driving child subagents with reactive wakeups.
- **OpenCode:** Native `tmux` or `zellij` multi-pane conductor running parallel OpenCode sessions.
- **Claude Code:** Terminal conductor supervising multiple Claude Code CLI processes.
- **Pi / Boxxy:** Boxxy terminal multi-session tabs supervised by the lead conductor.

### `agentic-engineering`
*7-step software factory: Target-local Kanban (.kanban/), Listeners, Fresh Judges, Splitters.*
- **T3 Code:** Kanban stored in `.kanban/`; steps advance via delegates. Done-checks render via `html_render`.
- **Gemini / Antigravity:** Automated via Python script in `run_workflow`. Splitter partitions items into `parallel()`.
- **OpenCode:** Pure filesystem-driven: watcher scripts monitor `.kanban/todo/` and trigger `opencode run`.
- **Claude Code:** Managed via `CLAUDE.md` task checklists; fresh judge spawned via `Agent` tool.
- **Pi / Boxxy:** Interactive CLI menu reading and updating `.kanban/`.

### `swarm-contract`
*Tripartite contract: Goal, Scorecard Schema, and Hard Budget ceiling.*
- **T3 Code:** Hard budget mapped to delegate turn limits and timeout options; scorecard passed in delegate brief.
- **Gemini / Antigravity:** Enforced via `run_workflow` JSON schemas and `agent(schema=scorecard_schema)`.
- **OpenCode:** Shell wrapper checks token/time spend and halts with non-zero exit code if ceiling exceeded.
- **Claude Code:** Enforced via subagent system prompt and JSON assertion script.
- **Pi / Boxxy:** Local budget counter script monitoring daemon tokens.

---

## ⚖️ 2. Judgement, Classification & Gating Skills

### `jev-decision`
*Calibrated decision engine on port `:8083` (bool, choice, score, composite).*
- **Universal across all harnesses:** The `jev` CLI tool runs locally on `http://127.0.0.1:8083`.
- **T3 Code:** Call `jev bool "..."` in bash to evaluate assertions or gate progress without generating text tokens.
- **Gemini / Antigravity:** Invoked in `run_command` or imported directly in `run_workflow` scripts.
- **OpenCode:** High-frequency routing in bash scripts; sub-150ms latency.
- **Claude Code:** Used in bash tool calls to make non-generative binary and classification decisions.
- **Pi / Boxxy:** Direct shell evaluation.

### `eval-router`
*Speculative shadow evaluation, h2o-lightning-4b complexity classification, failure harvesting.*
- **T3 Code:** Routes simple tasks to fast local models (`local-llm` on `:8080`) vs frontier models via `delegate_task`.
- **Gemini / Antigravity:** Routes `agent(model="flash")` for easy tasks vs `agent(model="pro")` for hard tasks.
- **OpenCode:** Routes prompts between local Qwen 35B (`:8080`) and OpenRouter free tiers based on calibrated complexity.
- **Claude Code:** Classifies whether a task needs Haiku vs Sonnet vs Opus.
- **Pi / Boxxy:** Local decision before dispatching terminal jobs.

### `eval-pipeline`
*Step-level propagation risk mitigation with `[D]`/`[P]`/`[H]` tagging and intermediate disk ledgers (`step_NN.json`).*
- **T3 Code:** Intermediate ledgers written to `<appDataDir>/brain/<id>/scratch/` and linked with absolute paths.
- **Gemini / Antigravity:** Direct mapping to `run_workflow` phases (`phase("step_01")`) and assertion gates.
- **OpenCode:** Bash pipeline writing `step_01.json`, halted immediately by `python3 -c "assert..."`.
- **Claude Code:** Each tool call writes `step_NN.json`; verified before moving to next step.
- **Pi / Boxxy:** Local run directories `.harness/runs/run_NN/`.

---

## 🔍 3. Retrieval & Memory Skills

### `notes-index`
*SQLite FTS5 ranked search over Markdown notes + fingerprint refresh + verbatim cite verification.*
- **Universal across all harnesses:** Replaces greedy `grep` and massive prompt loading with `notes-index search "..." --cite`.
- **T3 Code:** Agent queries `notes-index` via bash instead of reading dozens of files.
- **Gemini / Antigravity:** Runs inside `run_command`; returns line-accurate verified citations.
- **OpenCode:** Standard retrieval tool for local docs and project notes.
- **Claude Code:** Configured in `CLAUDE.md` as the mandatory search tool over notes.
- **Pi / Boxxy:** Instant terminal search with highlighted excerpts.

### `graph-memory`
*Hybrid Knowledge Graph (<2ms SQLite k-hop walk) + BM25/BGE RAG & exact-quote distillation.*
- **T3 Code:** Traverses relationships and dependencies across packages via CLI before planning.
- **Gemini / Antigravity:** Traversal results injected into workflow context.
- **OpenCode:** Local graph queries on SQLite database.
- **Claude Code:** Fast entity and relationship lookup.
- **Pi / Boxxy:** Direct SQLite traversal.

### `semantic-cache`
*Sub-10ms repeat query bypass and verified response cache using vector cosine similarity.*
- **All harnesses:** Intercepts repeated questions, returning cached answers from disk without calling LLM endpoints.

---

## 🧪 4. Testing, UI & Blast Radius Containment

### `frontend-uat`
*Sub-second model-backed frontend UAT loop: DOM targets $\rightarrow$ decision model clicks $\rightarrow$ screen verification.*
- **T3 Code:** Drives CDP or works alongside `preview_*` snapshot locators.
- **Gemini / Antigravity:** Automated journey driver in headless browser scripts.
- **OpenCode:** CDP driver interacting with KasmVNC desktop (`:3010`) or headless Chrome (`:9222`).
- **Claude Code:** Fast journey execution via Playwright/CDP.
- **Pi / Boxxy:** Headless browser journey runner.

### `parallel-test-lane`
*Blast radius containment: partitions test suites into sequential-isolated vs parallel worker lanes.*
- **T3 Code:** Runs in bash; slashes 40-minute test suites to minutes; output summarized for chat.
- **Gemini / Antigravity:** Invoked as a deterministic gate in `run_workflow` or `run_command`.
- **OpenCode:** Multi-core parallel CPU test runner across 16 threads.
- **Claude Code:** Standard test runner called by `Bash`.
- **Pi / Boxxy:** High-throughput local test execution.

### `kem-dev-loop`
*Kem's 6-phase lifecycle: Classifier $\rightarrow$ Fast/Full Route $\rightarrow$ Parallel Slices $\rightarrow$ Holdouts $\rightarrow$ Validate $\rightarrow$ Review.*
- **T3 Code:** Orchestrates the 6 phases using T3 delegates, hidden holdouts, and `html_render` validation.
- **Gemini / Antigravity:** Structured as a Python workflow graph using `run_workflow`.
- **OpenCode:** Controlled via `.kem-loop/` state files and step scripts.
- **Claude Code:** Guided by `kem-dev-loop.py` script and `CLAUDE.md` checkpoints.
- **Pi / Boxxy:** Terminal interactive development runner.

### `kem-ocr`
*MiniCPM-OCR-1.0 parsing + MiniCPM-OCR-Jev consistency scoring with corrupted holdouts.*
- **All harnesses:** Parses images/PDFs on local GPUs (`:8084/:8090`) and asserts transcription fidelity in one forward pass.

---

## 🛡️ 5. Safety & Invariants

### `guard-hooks`
*Pre-execution deterministic guardrails ("Code that ALWAYS runs") blocking `rm -rf`, force push, and file mutations.*
- **T3 Code:** Wrapped around tool calls or executed as a pre-command assertion script.
- **Gemini / Antigravity:** Checked before executing destructive shell commands in `run_command`.
- **OpenCode:** Bash trap / alias in shell session.
- **Claude Code:** Configured natively in `.claude/hooks/pre-tool-use`.
- **Pi / Boxxy:** Shell wrapper script halting dangerous execution.
