# 🌐 omnicli Harness Integration Matrix

> *"One gateway, two faces, one catalog — across every agent harness on this workstation."*

`omnicli` acts as the universal late-binding gateway across all five agent harnesses deployed on this workstation:
1. **T3 Code** (IDE / Agent Client Protocol host)
2. **Antigravity CLI (`agy`)** (Google DeepMind workflow engine)
3. **OpenCode** (Terminal-native local model harness)
4. **Pi Agent** (Terminal agent with hot-reloaded rsync skills)
5. **Boxxy Claw & Terminal** (Terminal companion with hot-reload and bubblewrap sandboxing)

---

## 📊 Universal Harness Capability Matrix

| Feature / Primitive | T3 Code | Antigravity (`agy`) | OpenCode | Pi Agent | Boxxy Claw |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Primary Interaction Face** | Code Mode + CLI | JS Bindings + CLI | Code Mode + CLI | Direct CLI | Direct CLI + Sandbox |
| **Discovery Protocol** | Preloaded skill metadata; fallback `lsSkills` / `readSkill` via `omnicli exec` | Preloaded metadata; fallback `lsSkills` / `readSkill` | Preloaded metadata; fallback `lsSkills` / `readSkill` | Preloaded metadata; fallback `lsSkills` / `readSkill` | Preloaded metadata; fallback `lsSkills` / `readSkill` |
| **Invocation Protocol** | `invoke()` / bash tool | `invoke()` in a `plan.mjs` | Compound bash / `omnicli invoke` | Direct bash / CLI | `omnicli invoke` / `exec` |
| **Code Mode SDK** | `omnicli exec plan.mjs` | `omnicli exec plan.mjs` from `run_workflow` | `omnicli exec plan.mjs` | Script invocation | `omnicli exec --sandbox` |
| **Output Capping** | Strict 8KB (`--omni-max-bytes`) | Strict 8KB / envelope `output` | Strict 8KB / `step_NN.json` | Strict 8KB cap | Strict 8KB cap |
| **JSON Projection** | `--omni-project` / `invoke()` | `project` option / `--omni-project` | `--omni-project` / jq | `--omni-project` | `--omni-project` |
| **Concurrency Model** | Reactive wakeups (ACP) | `await parallel([...])` | Git worktrees (`worktree-harness`)| Sequential CLI | `await parallel([...])` |
| **Config Location** | `~/.config/t3code-v2/` | `~/.gemini/antigravity-cli/` | `~/.config/opencode/opencode.json` | `~/.pi/agent/` | `~/.config/boxxy-terminal/` |
| **Verification Gate** | `omnicli harness verify t3-code` | `omnicli harness verify agy` | `omnicli harness verify opencode` | `omnicli harness verify pi` | `omnicli harness verify boxxy` |

---

## 🔍 Runtime Auto-Detection

`omnicli harness detect` inspects environment variables, parent processes, and workstation filesystem markers in priority order:

```
                  ┌── T3CODE_CLI_PATH / ARGV0 ~ T3-Code ──▶  T3 Code
                  ├── ANTIGRAVITY_AGENT / GEMINI_HOME   ──▶  Antigravity (agy)
Process & Env ────┼── OPENCODE_CONFIG / OPENCODE_ROOT   ──▶  OpenCode
                  ├── PI_AGENT_HOME / ~/.pi/agent/bin   ──▶  Pi Agent
                  └── BOXXY_HARNESS / boxxy-terminal    ──▶  Boxxy Claw
```

---

## 🛠️ CLI Operations

```bash
# List all harnesses and their detection status
omnicli harness list

# Auto-detect the current active harness environment
omnicli harness detect

# Show detailed integration guide and configuration snippet
omnicli harness info t3-code
omnicli harness info agy

# Output raw configuration snippet for a harness
omnicli harness config opencode

# Verify integration and readiness across all harnesses
omnicli harness verify
```

---

## 📖 Harness Guides

- [**T3 Code Adapter Guide**](t3-code.md) — Code Mode plans, ACP tool calls, visual rendering, reactive wakeups.
- [**Antigravity (`agy`) Guide**](agy.md) — lifecycle hooks, `run_workflow` graphs, dynamic subagents, workspace isolation.
- [**OpenCode Guide**](opencode.md) — `opencode.json` skills path, compound bash batching, local model daemon routing.
- [**Pi Agent Guide**](pi.md) — Interactive terminal usage, rsync sync, tight token budgeting.
- [**Boxxy Claw Guide**](boxxy.md) — Bubblewrap sandboxing, hot-reload sync, SQLite WAL safety.

**Visual guides:** [Code Mode Showcase](code-mode-showcase.html) — self-contained walkthrough of the exec tool, direct known-tool invocation, discovery fallback, plan globals, paste-ready `spec --plan-header`, and the strict boundary · [Verification Report](verification_report.html) — first-party harness check matrix and evidence.
