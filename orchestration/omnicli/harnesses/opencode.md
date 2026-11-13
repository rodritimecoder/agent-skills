# 💻 OpenCode Harness Guide for omnicli

> *"OpenCode is an open-source, terminal-native AI agent environment with native support for local model daemons and compound bash batching."*

This guide specifies how `omnicli` integrates with **OpenCode** as a first-party tool discovery gateway, Code Mode runner, and local model router.

---

## ⚡ Integration Surfaces in OpenCode

OpenCode reaches `omnicli` through three complementary channels:

### 1. Native tools (the plugin)

`plugin/omnicli-route.js` registers `omnicli_search`, `omnicli_describe`,
`omnicli_invoke`, and `omnicli_exec` with `codemode: true`, so they appear in
the tool list and inside Code Mode as `tools.omnicli.*`. It also injects the
routing rule and denies skill-directory discovery until a catalogue call has
run.

```bash
ln -sf ~/src/my-agent-skills/orchestration/omnicli/plugin/omnicli-route.js \
  ~/.config/opencode/plugins/omnicli-route.js
opencode reload
omnicli harness verify opencode   # includes native_tool_plugin
```

Metrics: `python3 scripts/route_stats.py` reads `~/.local/share/omnicli/route.jsonl`.

### 2. Configuration in `~/.config/opencode/opencode.json`

Register the zero-copy surface path. Nothing else is needed — omnicli ships no
server to attach:

```json
{
  "skills": [
    "/home/rodri/src/my-agent-skills/surface"
  ]
}
```

- **Surface Discovery:** Any skill symlinked in `surface/` is discovered instantly by OpenCode's internal skill crawler.
- **Code Mode:** That skill teaches `omnicli search` / `describe` / `invoke` / `exec`, which OpenCode reaches through its bash tool. Multi-step jobs go in one `omnicli exec plan.py`.

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
