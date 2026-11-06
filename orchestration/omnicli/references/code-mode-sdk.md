# Python SDK & Code Mode Execution (`omnicli exec`)

## 🏛️ Architectural Provenance

The `omnicli` architecture unifies two foundational production AI patterns:

1. **Uber's MCP Gateway** ([Uber Engineering: Designing an MCP Gateway](https://www.uber.com/au/en/blog/designing-mcp-gateway/)):
   - **Late-Binding Discovery**: Instead of dumping hundreds of tool schemas into turn-0 model context (which triggers the Databricks tool-shadowing degradation), tools are catalogued out-of-band via AutoCrawler/builder into SQLite FTS5 + dense embeddings.
   - **Bounded Meta-Tools**: Agents discover tools by intent (`search`), inspect single contracts on-demand (`describe`), invoke them with strict byte caps and field projections (`invoke`), and monitor service health (`status`).

2. **Cloudflare's Code Mode** ([Cloudflare Blog: Code Mode — Execute Code to Invoke Tools Instead of LLM Function Calling](https://blog.cloudflare.com/code-mode/)):
   - **One Plan, One Turn**: Instead of multiple slow, token-expensive round-trips where intermediate tool outputs flood the prompt context, the agent generates executable code (Python) that imports a generated SDK.
   - **Intermediate Isolation**: Data pipelines, filtering, JSON parsing, loops, and conditional logic execute in local memory. Only the final synthesized result (`print()`) enters the model's context.
   - **Sandboxed Execution**: Code runs in a secure sandbox (Bubblewrap / `bwrap`) with configurable filesystem, network, and capability boundaries.

---

## 📦 The Generated SDK: `omnicli_tools.py`

Running `omnicli bindings` generates `~/.local/share/omnicli/bindings/omnicli_tools.py`. This file provides two layers of functionality:

### 1. The Core Gateway API
- `search(intent: str, limit: int = 6) -> list[dict]`: Full-body BM25 + dense vector search across all registered skills. Returns ranked candidates with scores, evidence, and tool IDs.
- `spec(skill: str = None, grep: str = None, kind: str = None, limit: int = None) -> list[dict]`: Inspect catalog signatures and argument requirements without loading the full catalog database.
- `describe(tool_id: str) -> dict`: Read the full usage contract, flags, parameters, and help text for one specific tool.
- `invoke(tool_id: str, *args, **kwargs) -> dict`: Execute any catalogued tool with strict output bounding, field projection, or disk buffering.
- `skills() -> list[str]`: List all registered skills.
- `tools(skill: str) -> list[str]`: List all tools registered under a skill.

### 2. Typed Surface Functions
Every catalogued tool is automatically exposed as an annotated Python function generated from its CLI `--help`:
```python
from omnicli_tools import search, spec, zoom

# Arguments are validated at import/call time:
# zoom(url: str, format: Literal['md', 'vtt', 'txt', 'all'] = 'all', video: bool = False)
result = zoom(url="https://zoom.us/rec/share/example", format="md")
```

---

## 🔒 Sandboxing & Execution Modes

`omnicli exec <plan.py>` runs the plan in one of three containment tiers:

| Mode | Filesystem | Network | Tool Dispatch | Use Case |
|---|---|---|---|---|
| `write` (default) | `/` is read-only; only current workspace and `/tmp` writable. | Unrestricted. | Direct subprocess execution. | Standard multi-step data pipelines and local tool orchestration. |
| `strict` | Home directory masked (`~/.ssh`, `~/.env` unreadable); only workspace writable. | **Disabled** (no outbound sockets). | Every tool call crosses a UNIX domain socket bridge to the parent process. | Running untrusted code, external scripts, or high-security evaluation suites. |
| `none` | Unconfined host filesystem. | Unrestricted. | Direct subprocess execution. | Tasks requiring broad machine access (system admin, global package installs). |

---

## 💡 Practical Examples

### Example 1: Dynamic Discovery & Chained Execution
Save as `plan_pipeline.py`:
```python
#!/usr/bin/env python3
"""Discover relevant audio tools, transcribe, and output only the snippet."""
import json
from omnicli_tools import search, invoke

# 1. Discover the tool dynamically
candidates = search("transcribe speech audio to text", limit=3)
if not candidates:
    raise SystemExit("No matching transcription tool found.")

tool_id = "audiocpp/scripts/audiocpp_cli"

# 2. Invoke tool with output projection
resp = invoke(tool_id, "asr", "meeting.wav", omni_project="transcript,duration")

# 3. Only the final result is printed back to the model turn
print(f"Transcription complete: {resp.get('transcript', '')[:200]}")
```

Run via:
```bash
omnicli exec plan_pipeline.py
```

### Example 2: In-Memory Filtering Without Context Flooding
```python
#!/usr/bin/env python3
"""Fetch a large dataset, filter in memory, and return a 3-line summary."""
from omnicli_tools import invoke

# Fetch full JSON data without leaking thousands of tokens into prompt context
raw_data = invoke("canvas-cli/scripts/canvas", "assignments", "--json")

# Filter in Python
overdue = [
    item["name"]
    for item in raw_data.get("assignments", [])
    if item.get("status") == "overdue"
]

# Only the concise summary goes to stdout (and into LLM context)
print(f"Found {len(overdue)} overdue assignments:")
for name in overdue:
    print(f"- {name}")
```
