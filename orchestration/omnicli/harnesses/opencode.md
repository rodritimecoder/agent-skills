# 💻 OpenCode Harness Guide for omnicli

> *"OpenCode is an open-source, terminal-native AI agent environment with native support for local model daemons and compound bash batching."*

This guide specifies how `omnicli` integrates with **OpenCode** as a first-party tool discovery gateway, MCP provider, and local model router.

---

## ⚡ Integration Faces in OpenCode

OpenCode interacts with `omnicli` through two complementary channels:

### 1. Configuration in `~/.config/opencode/opencode.json`

Register `omnicli` both as an MCP server and via zero-copy surface skill discovery:

```json
{
  "skills": [
    "/home/rodri/src/my-agent-skills/surface"
  ],
  "mcp": {
    "omnicli": {
      "type": "local",
      "command": ["omnicli", "mcp"]
    }
  }
}
```

- **MCP Face:** OpenCode accesses `omni_discover`, `omni_describe`, `omni_invoke`, and `omni_status` as native tool functions.
- **Surface Discovery:** Any skill symlinked in `surface/` is discovered instantly by OpenCode's internal skill crawler.

---

## 🧱 Compound Bash Batching

OpenCode executes multi-command sequences in single turns. `omnicli` enables fail-fast pipeline compounding without polluting terminal context:

```bash
# Compound task execution
set -e
TOOL_ID=$(omnicli search "generate cornell notes from markdown" --json | jq -r '.results[0].top.id // .results[0].skill')
omnicli describe "$TOOL_ID" --section "Usage"
omnicli invoke "$TOOL_ID" --omni-buffer /tmp/notes_step.json -- input.md
python3 -c "import json; data=json.load(open('/tmp/notes_step.json')); print('Summary:', data.get('summary', 'done'))"
```

---

## 🧠 Local Model Daemon Routing

OpenCode routes sub-tasks directly to local inference ports without consuming external API tokens. `omnicli` provides standardized CLI interfaces to all local daemons:

| Task | omnicli Subcommand | Daemon Port | Underlying Engine |
| :--- | :--- | :--- | :--- |
| **Code & Text Generation** | `omnicli llm "<prompt>"` | `:8080` | Qwen3.6-35B Genesis (dual-GPU) |
| **Calibrated Decision / Gating** | `omnicli decide "<context>" "<q>"` | `:8083` | Jev / h2o-lightning-4b |
| **Speech-to-Text (ASR)** | `omnicli asr transcribe <audio>` | `:8081` | audio.cpp / Nemotron-3.5 |
| **Visual Document OCR** | `omnicli ocr <image_or_pdf>` | `:8085` | LightOnOCR-3-0.8B |
| **Scene Text & UI Bounding** | `omnicli invoke ocr/crispembed` | `:8084` | CrispEmbed spatial model |

---

## 🌿 Parallel Workers via Git Worktrees (`worktree-harness`)

When OpenCode orchestrates multiple parallel sub-agents:
1. Isolate each agent into a separate git worktree (`git worktree add -b slice-1 ../wt-1 main`).
2. Each agent executes `omnicli invoke` independently against the read-only catalog database (`catalog.db`).
3. Intermediates are serialized to disk (`step_NN.json`) in the worktree.
4. Merge passing worktrees once assertions pass.

---

## 🔍 Verification

Run the automated verification suite to confirm OpenCode integration:

```bash
omnicli harness verify opencode
```
