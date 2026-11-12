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

## 🧠 Memory cap (`--mem-limit`)

Address space is uncapped by default. `--mem-limit MiB` sets `RLIMIT_AS` on the
sandbox process in MiB (a positive integer); the plan and every process it spawns
inherit it, and soft equals hard, so a plan cannot raise its own ceiling. It works
in `write` and `strict` — in both cases the limit is applied to the bubblewrap
process by `prlimit`, since bwrap itself has no `--rlimit-*` option. `--sandbox
none` rejects the flag instead of ignoring it.

The cap is opt-in because the right number is a property of the plan, not of the
runner: a two-line plan fits in 64 MiB, a 10-call fan-out does not, and a plan
that legitimately allocates 200 MiB would die under any cap chosen for the first.

Measured on this workstation (three runs per cell, `--sandbox write`, `--max-calls 30`):

| Cap | trivial plan | 10 × `asearch` via `parallel` | 200 MiB allocation |
|---|---|---|---|
| none | ok | ok | ok |
| 64 MiB | ok | dies: `RuntimeError: can't start new thread` | dies: `MemoryError` |
| 128 MiB | ok | ok | dies: `MemoryError` |
| 256 MiB | ok | dies: `RuntimeError: can't start new thread` | ok |
| 512 MiB | ok | ok | ok |

The 256 MiB row is not a transcription error, and it is not a threshold either.
A wider sweep by the conductor put 128 MiB at 5/5 pass, 256 MiB at 0/5, 160 and
192 MiB at 1/2, and 320 MiB upward at 2/2 — so the failure does not track the
cap's size. What dies is thread creation (`RuntimeError: can't start new
thread`), not the plan's own allocation, and the address space a thread stack
needs is what the allocator has left rather than the plan's peak RSS. Treat
anything below **512 MiB** as unsupported; 512 passed every plan in every run.

**Recommended floor: 512 MiB** — the smallest measured cap that survives all three
plans in both modes. Below it, treat every failure as the plan telling you what it
needs rather than a runner bug; the plan's traceback names the cap (`MemoryError`,
or a `RuntimeError` from thread creation).

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

---

## Concurrency

Every binding call is one `subprocess.run` of the `omnicli` CLI — around 85 ms
here, almost all of it process spawn and interpreter start, not work. Ten
independent `search()` calls run sequentially measured 800 ms; the same ten
through `parallel()` measured 178 ms at `limit=8` and 127 ms at `limit=10`. The
`a*` twins (`asearch`, `adescribe`, `ainvoke`, `aoutput`, `askills`, `atools`)
build the identical argv as their sync twins and return the identical value, so
a plan can fan out without changing behaviour.

```python
async def parallel(calls, limit=8) -> list
```

`calls` is any iterable of either a zero-arg callable or a `(fn, args, kwargs)`
tuple. At most `limit` calls are in flight (`asyncio.Semaphore`); results come
back from `asyncio.gather`, so they stay in input order even though they finish
out of order. An exception propagates the way `gather` propagates it — one
failure fails the batch. A sync callable still works but runs inline, holding
the loop for its subprocess; pass an `a*` twin when you want overlap.

### Example: ten independent lookups

```python
#!/usr/bin/env python3
"""Fan out ten intent searches and print one row each."""
import asyncio

from omnicli_tools import asearch, parallel

INTENTS = [
    "transcribe audio", "ocr a slide", "search notes", "zoom recording",
    "git worktree", "review a diff", "run tests", "summarize a paper",
    "check model status", "convert pdf",
]


async def main():
    hits = await parallel([(asearch, (intent,), {"limit": 2}) for intent in INTENTS])
    for intent, rows in zip(INTENTS, hits):
        top = rows[0] if rows else {}
        print(f"{intent:22} {top.get('score', 0):>6} {top.get('skill', 'none')}")


asyncio.run(main())
```

Run via:
```bash
omnicli exec plan_fanout.py
```

The zero-arg form is the same thing with closures:

```python
hits = await parallel([lambda i=i: asearch(i, limit=2) for i in INTENTS])
```

Order holds in both forms. `parallel()` does not buffer or reshape results, so
per-call envelopes stay exactly as `invoke()` returns them.
