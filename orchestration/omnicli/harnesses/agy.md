# 🚀 Antigravity CLI (`agy`) Harness Guide for omnicli

> *"Antigravity is Google DeepMind's agentic CLI engine powering Gemini models with native Python workflow graphs."*

This guide specifies how `omnicli` integrates with **Antigravity CLI (`agy`)** as a native tool execution engine and Python binding provider.

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

1. **`PreInvocation` Hook:** Injects `[omnicli route]` into the prompt context, directing the agent to use `omnicli search` / `exec` instead of manual discovery.
2. **`PreToolUse` Gate:** Automatically intercepts `view_file` and shell read commands (`cat`, `grep`, `rg`, `find`, etc.) targeting `~/src/my-agent-skills/**`. If an unprimed agent attempts to read skill directories directly without calling `omnicli search`, the hook rejects the call with `{"decision": "deny"}`.
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

## 🐍 Native Python Workflow Execution (`run_workflow`)

`omnicli bindings` produces typed Python modules (`omnicli_tools.py`) directly importable by Antigravity workflow scripts.

### Pattern: Multi-Agent Pipeline with omnicli Tools

```python
# Workflow script passed to run_workflow
from omnicli_tools import search, invoke, describe

phase("discovery")
log("Finding candidate tools for video transcription...")
tools = search("transcribe lecture video", limit=3)

phase("parallel_execution")
# Process multiple items in parallel using Antigravity's native primitives
items = [
    {"url": "https://zoom.us/rec/session1", "dest": "notes/session1.md"},
    {"url": "https://zoom.us/rec/session2", "dest": "notes/session2.md"}
]

async def transcribe_job(item):
    # Call omnicli tool with strict output bounding
    res = invoke(
        "zoom-recorder/scripts/zoom_download",
        "--url", item["url"],
        "--omni-project", "status,markdown_path"
    )
    return res

results = await parallel(items, transcribe_job)

phase("summary_agent")
# Launch subagent to evaluate transcribed notes
evaluator = agent(
    prompt=f"Summarize transcribed lectures: {results}",
    role="Lecture Summarizer",
    workspace="inherit"
)
summary = await evaluator
log(f"Finished pipeline: {summary}")
```

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
      "Prompt": "Run `omnicli search 'transcribe audio'` to locate audio.cpp tooling, then transcribe input.wav with `omnicli invoke`."
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
