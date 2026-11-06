# 🎛️ Kem Glitch Harness Adapters (`harnesses/`)

> *"It begins with a harness, a workflow graph designed before anything runs. The roots and the gates are fixed in the code."*  
> — Kem Glitch, *5 Agents Writing the Same File* [00:12]

Kem's Law states: **a skill is instructions the model may follow; a hook is code that ALWAYS runs.**  
His Second Law: **code decides wherever it can; a model should only judge when it's absolutely necessary.**

This directory provides concrete, harness-specific hooking instructions for running the **Glitch Cat Suite** and Kem's development methodology across modern agent environments.

---

## 🧭 Why Harness Adaptation Matters

Kem doctrine is **invariant**:
- Step-level risk mitigation (`[D]`/`[P]`/`[H]` tagging)
- Fresh-context judges (never evaluating with the author's memory)
- Parallel vertical slices in isolated workspaces
- Handoffs via disk serialization (`step_NN.json`, `verify.json`, diffs), never conversational summaries
- Gates written as executable code that can fail
- Hands-and-eyes verification before code review

However, **host harnesses have radically different primitives, concurrency models, and constraints**:
- **T3 Code** uses ACP/MCP orchestration (`delegate_task`, `preview_*`, `task_cancel`, worktree thread isolation) with strict host invariants (no manual git checkouts for child delegates, reactive wakeups instead of polling loops).
- **Gemini / Antigravity CLI** provides Python workflow graph execution (`run_workflow` with `parallel`, `pipeline`, `agent` primitives), dynamic agent definitions (`define_subagent`), surgical diff tools (`replace_file_content`), and native branch/share workspace isolation.
- **OpenCode** operates terminal-first with pure CLI tools, local GGUF models (`:8080`, `:8081`, `:8083`), compound bash batching, and `step_NN.json` stdout redirection.
- **Claude Code** relies on `CLAUDE.md`, `.claude/hooks/` pre-execution guards, slash commands, and the native `Agent` tool with prompt caching discipline.
- **Pi Agent & Boxxy Claw** hot-reload skills from disk, executing bash scripts with tight terminal feedback loops.

An agent that ignores the host harness will fight its own runtime: it will busy-poll when the harness is event-driven, leak context when the harness supports isolation, or corrupt git trees by spawning ad-hoc checkouts where the IDE manages worktrees.

---

## 🔎 Auto-Detecting Your Host Harness

At session startup, identify your host environment in turn 1:

| Indicator | Detected Harness | Guide |
| :--- | :--- | :--- |
| MCP tools `preview_*`, `delegate_task`, `t3_thread_*` present; `<t3_code_instructions>` in prompt | **T3 Code** | [`t3-code.md`](./t3-code.md) |
| Native tools `invoke_subagent`, `define_subagent`, `run_workflow`, `replace_file_content` present | **Gemini / Antigravity CLI** | [`gemini-antigravity.md`](./gemini-antigravity.md) |
| Running under `opencode` CLI; `surface/` skills discovery configured in `opencode.json` | **OpenCode** | [`opencode.md`](./opencode.md) |
| Tools include `Agent`, `Bash`, `Read`, `Write`; reads `CLAUDE.md`; `.claude/` directory present | **Claude Code** | [`claude-code.md`](./claude-code.md) |
| Running in Boxxy terminal or Pi environment (`~/.pi/agent/skills`, `~/.config/boxxy-terminal`) | **Pi Agent / Boxxy Claw** | [`pi-boxxy.md`](./pi-boxxy.md) |

---

## ⚡ The 7 Universal Kem Primitives Translation Matrix

| Kem Glitch Primitive | T3 Code | Gemini / Antigravity CLI | OpenCode | Claude Code |
| :--- | :--- | :--- | :--- | :--- |
| **1. Deterministic Hooks** ("Code that ALWAYS runs") | Native bash scripts / `guard-hooks` wrapped in tool calls | Pre-execution verification in `run_command` / `guard-hooks` | Bash aliases or pre-exec traps (`guard-hooks/scripts/guard.sh`) | `.claude/hooks/` pre-tool interception |
| **2. Fresh-Context Judge** (Zero author memory) | `delegate_task` or native subagent with fresh prompt & artifact link | `invoke_subagent` with clean prompt or `define_subagent` | `opencode run "<lean judge prompt>"` | `Agent` tool (`Explore` or clean prompt) |
| **3. Workspace Isolation** (No git collision) | `isolation: "worktree"` in `delegate_task` | `Workspace: "branch"` or `"share"` in `invoke_subagent` | `git worktree add ../wt-worker-N` | `isolation: "worktree"` or git worktree |
| **4. Structured Handoff** (No summary handoffs) | File artifacts in `<appDataDir>/brain/<id>/` | Disk files (`step_NN.json`) in workspace or `brain/` | Disk files (`step_NN.json`) + assertion scripts | `.agent_state.json` + `STATE.md` + file diffs |
| **5. Non-Blocking Flow** (Never sleep in a loop) | Reactive wakeup via ACP notifications; stop turn | Reactive wakeup via message/task notifications; stop turn | Background processes (`&`) + wait / exit code check | Event-driven subagent notifications |
| **6. Hands & Eyes** (Verify before review) | `preview_status` → `preview_open` → `html_preview` / `html_render` | Headless Chrome CDP / `frontend-uat` / Playwright | Fast CDP (`:9222`) or Playwright CLI | Playwright or CDP scripts |
| **7. Workflow Graph** (Code before agent) | Orchestrator graph / script driving delegates | `run_workflow` (`pipeline()`, `parallel()`, `agent()`) | Deterministic Python script calling sub-agents | Multi-agent script or conductor pane |

---

## 📖 Harness Guides

1. [**T3 Code Adapter Guide**](t3-code.md) — How to orchestrate Kem pipelines inside T3 Code (ACP tools, preview management, delegates, worktree threads).
2. [**Gemini & Antigravity Adapter Guide**](gemini-antigravity.md) — How to leverage `run_workflow`, subagent workspaces, surgical diffs, and context compactor.
3. [**OpenCode Adapter Guide**](opencode.md) — Running Kem pipelines with zero-cost models, local model daemons (`:8080`, `:8083`), and bash compounding.
4. [**Claude Code Adapter Guide**](claude-code.md) — Using `.claude/hooks`, `CLAUDE.md` 200-line memory budgets, and subagent review lanes.
5. [**Pi Agent & Boxxy Claw Guide**](pi-boxxy.md) — Fast terminal loops, hot-reloading skills, and direct CLI model access.
