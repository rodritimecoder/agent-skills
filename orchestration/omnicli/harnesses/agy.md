# 🚀 Antigravity CLI (`agy`) Harness Guide for omnicli

> *"Antigravity is Google DeepMind's agentic CLI engine powering Gemini models with native Python workflow graphs."*

This guide specifies how `omnicli` integrates with **Antigravity CLI (`agy`)** as a native tool execution engine and JavaScript binding provider.

---

## ⚡ Integration Faces in Antigravity

Antigravity provides first-class primitives for agent execution:
- `run_workflow`: Inline Python workflow graphs with `parallel()`, `pipeline()`, and `agent()`.
- `define_subagent` & `invoke_subagent`: Dynamic subagent orchestration with isolated workspaces.
- `replace_file_content`: Surgical, contiguous file editing.
- `run_command`: Sandboxed command execution with background task notifications.
- `hooks.json`: Deterministic lifecycle hooks (`PreInvocation`, `PreToolUse`, `PostToolUse`).

---

## 🪝 Lifecycle Hook Integration (`omnicli-route`)

Antigravity enforces Kem's Law: *"A skill is instructions the model may ignore; a hook is code that ALWAYS runs."*

`orchestration/omnicli/hooks/agy_omnicli_hook.py` wires into `~/.gemini/config/hooks.json` under `"omnicli-route"`:

1. **`PreInvocation` Hook:** Injects `[omnicli route]` into the prompt context, directing the agent to use `omnicli exec (filesystem discovery)` / `exec` instead of manual discovery.
2. **`PreToolUse` Gate:** Automatically intercepts `view_file` and shell read commands (`cat`, `grep`, `rg`, `find`, etc.) targeting `~/src/my-agent-skills/**`. If an unprimed agent attempts to read skill directories directly without calling `omnicli exec (filesystem discovery)`, the hook rejects the call with `{"decision": "deny"}`.
3. **Observability:** Logs all allows, denials, and exemptions to `~/.local/share/omnicli/route.jsonl`.

```json
{
  "omnicli-route": {
    "PreInvocation": [
      {
        "type": "command",
        "command": "/bin/sh -c 'if [ -f \"/home/rodri/src/my-agent-skills/orchestration/omnicli/hooks/agy_omnicli_hook.py\" ]; then /usr/bin/python3 \"/home/rodri/src/my-agent-skills/orchestration/omnicli/hooks/agy_omnicli_hook.py\" PreInvocation; else printf \"{}\"; fi'",
        "timeout": 5
      }
    ],
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/bin/sh -c 'if [ -f \"/home/rodri/src/my-agent-skills/orchestration/omnicli/hooks/agy_omnicli_hook.py\" ]; then /usr/bin/python3 \"/home/rodri/src/my-agent-skills/orchestration/omnicli/hooks/agy_omnicli_hook.py\" PreToolUse; else printf \"{\\\"decision\\\":\\\"allow\\\"}\"; fi'",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

---

## 🐍 Code Mode inside a workflow (`run_workflow`)

`run_workflow` is Python, so a workflow orchestrates and the tool work happens in
one JavaScript plan: `omnicli bindings` generates `omnicli_tools.mjs` (plus
`omnicli_tools.d.ts`) and a workflow step runs it through `omnicli exec`.

### Pattern: Multi-Agent Pipeline with omnicli Tools

```python
# Workflow script passed to run_workflow
phase("discovery")
log("Downloading candidate lecture recordings...")
run_command("omnicli exec plans/fetch_sessions.mjs --sandbox strict")

phase("summary_agent")
# Launch subagent to evaluate transcribed notes
evaluator = agent(
    prompt="Summarize the transcribed lectures in notes/",
    role="Lecture Summarizer",
    workspace="inherit"
)
summary = await evaluator
log(f"Finished pipeline: {summary}")
```

`plans/fetch_sessions.mjs` keeps the fan-out inside one turn:

```js
import { invoke, parallel, emitResult } from "omnicli_tools";

const ITEMS = [
  { url: "https://zoom.us/rec/session1", dest: "notes/session1" },
  { url: "https://zoom.us/rec/session2", dest: "notes/session2" },
];

const results = await parallel(
  ITEMS.map((item) => () => invoke(
    "zoom-recorder/scripts/zoom_download",
    { url: item.url, out_dir: item.dest, project: "status,markdown_path" },
  )),
  4,
);

emitResult(results.map((res) => ({ tool: res.tool, exit: res.exit_code, bytes: res.bytes })));
```

---

## 💻 JavaScript Code Mode in Shell (`omnicli exec`)

When an agent needs to perform multi-step data exploration, inspect binary formats/archives (like `app.asar`), or chain multiple tool calls, **never run serial `python3 -c` commands**. Instead, run sandboxed JavaScript Code Mode in a single turn via `omnicli exec`:

```bash
# Inline execution (zero file staging overhead; globals need no import)
omnicli exec -c 'const rows = await search("audio", 2); console.log(rows)'

# Piped stdin execution
cat << 'EOF' | omnicli exec -
import { search } from "omnicli_tools";
const results = await search("ocr text extraction", 3);
console.log(results.map((r) => r.skill));
EOF

# File-based execution
omnicli exec plan.mjs --sandbox write
```

Inside `omnicli exec`, `node:vm` runs the plan under bubblewrap, enforces
`--max-calls` (default 100), and exposes `search`, `spec`, `describe`, `invoke`,
`output`, `parallel`, `emitResult` and one async function per catalogued tool as
globals. Optional `--mem-limit MiB` caps Node's heap
(`--max-old-space-size`) and sets a floored `RLIMIT_AS` of `max(MiB, 2048)` MiB.
Python plans are retired: `omnicli exec plan.py` exits 2 with the migration text.

---

## 👥 Dynamic Subagent Delegation

When dispatching parallel workers with `invoke_subagent`, equip subagents with `omnicli` CLI tools:

```json
{
  "Subagents": [
    {
      "TypeName": "self",
      "Role": "Audio Transcription Worker",
      "Workspace": "branch",
      "Prompt": "Run `omnicli exec (filesystem discovery) 'transcribe audio'` to locate audio.cpp tooling, then transcribe input.wav with `omnicli invoke`."
    }
  ]
}
```

---

## 🛡️ Context Protection & Surgical Edits

1. **Output Capping (`--omni-max-bytes`):** Antigravity sessions maintain context sharpness over long horizons. Always cap CLI tool output (default 8KB) to prevent context pollution.
2. **Buffer to Disk (`--omni-buffer`):** For large outputs, use `--omni-buffer /tmp/out.json` and project only the critical fields back into the agent conversation.
3. **Surgical Diff Tooling:** When editing codebases, combine `omnicli spec --grep ...` with Antigravity's `replace_file_content` rather than rewriting whole files.

---

## 🏛️ Antigravity Host Invariants

1. **Workspace Modes:**
   - `"inherit"`: Same workspace as parent.
   - `"branch"`: Isolated git clone branched from parent.
   - `"share"`: Shared git worktree repository directory.
2. **Reactive Messaging:** The harness resumes automatically when background subagents finish or commands complete. Never execute `sleep` loops.
3. **Artifact Directory:** Persistent artifacts belong in `<appDataDir>/brain/<conversation-id>/`.

---

## 🔍 Verification

Run the automated verification suite to confirm Antigravity integration:

```bash
omnicli harness verify agy
```
