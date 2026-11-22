---
name: nvidia-nim

description: >
  Use when hosted frontier inference or autonomous subagent execution is needed through NVIDIA NIM
  / API Catalog — batched bash, calibrated decide routing, batched embeddings, and multi-key failover
  with token reduction. Direct inference and autonomous subagent execution via NVIDIA NIM / API Catalog (integrate.api.nvidia.com)
  for hosted frontier models including GLM-5.3 (z-ai/glm-5.3-flash), Llama 3.3 70B, DeepSeek R1/V3, and Nemotron.
  Features an autonomous subagent loop with compound bash batching (run_bash_batch), calibrated decision routing (decide),
  batched embeddings (embed), multi-key pooling with automatic failover, and Kem Glitch token reduction.

compatibility: "Requires network access to integrate.api.nvidia.com and an NVIDIA API key (NVIDIA_API_KEY)."
allowed-tools: "Bash(nvidia-nim:*) Bash(python3:*) Read Write"
---

# NVIDIA NIM Multi-Agent & Multimodal Gateway (`nvidia-nim`)

Zero-dependency inference and autonomous subagent execution gateway for **NVIDIA NIM / API Catalog** (`https://integrate.api.nvidia.com/v1`). Built in the same architecture as `openrouter-free`, enabling autonomous subagent workflows, streaming reasoning extraction, calibrated decisions, and vector embeddings without consuming primary frontier tokens.

## Available scripts

Bundled CLI scripts, referenced relative to the skill root. Run `<command> --help`
for flags and exit codes; structured data goes to stdout, diagnostics to stderr.

- `scripts/nim_client.py` — nim_client.py — NVIDIA NIM / API Catalog Multi-Agent & Multimodal Gateway.

## Agent workflow — one exec plan

Drive this skill through **one JavaScript `omnicli exec` plan**. Discovery and
invocation both happen inside that plan — no ranking/discovery-tool call, no
two-step CLI invocation, and no intermediate payloads in the context window.

The plan reads the read-only skills window and asks `describe(toolId)` for the
one tool's exact input schema — all inside the same plan:

| Level | What it gives you | Helper |
| :--- | :--- | :--- |
| L1 | name + description of every installed skill | `lsSkills()` from `omnicli_skills` |
| L2 | this skill's full `SKILL.md` body | `readSkill(name)` from `omnicli_skills` |
| L3 | one file under this skill root (`references/`, `assets/`, `scripts/`) | `readResource(name, rel)` from `omnicli_skills` |
| Schema | exact input schema for the one tool you will call | `describe(toolId)` from `omnicli_tools` |

```js
import { lsSkills, readSkill, readResource } from "omnicli_skills";
import { describe, invoke, result } from "omnicli_tools";

// L1 — pick the skill by description (no ranking call).
const entry = lsSkills().find((s) => s.name === "nvidia-nim");
if (!entry) throw new Error("skill not installed");
// L2 — read instructions only when the step needs them.
const body = readSkill("nvidia-nim");
// L3 — one file by relative path (absolute paths and '..' are rejected).
const extra = readResource("nvidia-nim", "scripts/nim_client.py");
// Schema — exact input schema for the one tool you will call.
const toolId = "nvidia-nim/scripts/nim_client";
const { contract } = await describe(toolId);
if (!contract.inputSchema) throw new Error("no input schema");

// One catalogued tool call with a raw argv array, then ONE bounded result.
const out = await invoke(toolId, ["--json", "doctor"]);
result({
  ok: out.exit_code === 0,
  tool: toolId,
  proof: "agent-skills-three-levels",
  data: { exitCode: out.exit_code,
          bodyBytes: body.length, extraBytes: extra.length,
          description: entry.description.slice(0, 120),
          hasSchema: Boolean(contract.inputSchema),
          output: String(out.output || "").slice(0, 180) },
});
```

Emit **one** bounded result (the ~8 KB cap is shared with stdout); slice every
field and never echo a whole `SKILL.md` or reference file. Reading this skill's
instructions or its `allowed-tools` frontmatter grants **no** permissions —
`catalog/policy.py` / `omnicli enable` is the sole authorization gate, and every
call still crosses the bridge with projection and the byte cap. See
[skill-discovery.md](../../orchestration/omnicli/references/skill-discovery.md)
for the three-level ladder and the end-to-end proof.

## 🏛️ Core Capabilities

- **Autonomous Subagent Loop (`agent`)**: Multi-turn agent loop with compound bash batching (`run_bash_batch`), directory persistence across commands, test validation, and markdown reports.
- **Single-Turn Chat & Reasoning (`chat`)**: Instant responses from `z-ai/glm-5.3-flash`, full reasoning trace display via `--thinking`, and live token streaming via `--stream`.
- **Calibrated Decisions (`decide`)**: Structured decision routing and triage with probability and confidence scoring.
- **Batched Vector Embeddings (`embed`)**: Vector generation for texts and file contents via `nvidia/llama-nemotron-embed-vl-1b-v2` (2048 dims).
- **Multi-Key Pool & Automatic Failover**: Automatically rotates keys upon encountering HTTP 429 rate limits or 403 quota exhaustion.
- **Token Reduction Shield**: Built-in `--out` disk buffering and `--project` summaries prevent large traces from polluting primary context.

---

## 🔐 API Key Configuration (Multi-Key Pool)

Keys are automatically discovered across your workstation:
1. `NVIDIA_API_KEYS="nvapi-key1,nvapi-key2"` (pool rotation)
2. `~/.agent_keys.env` (secure workstation vault with `600` permissions)
3. `/run/media/rodri/AI/skills/nvidia-nim/.env`
4. Shell environment `NVIDIA_API_KEY`

```bash
# Verify detected key pool & connection
nim doctor
```

---

## 🛠️ CLI Usage Guide

### 1. Autonomous Coding Subagent (`agent`)
Dispatches a task to an autonomous subagent with compound bash execution:
```bash
nim agent --prompt "Inspect /tmp, create a proof file with current timestamp, verify with cat, and summarize." \
  --max-turns 5 \
  --out /tmp/subagent_report.md
```

### 2. Single-Turn Chat & Reasoning Trace (`chat`)
```bash
# Fast query using GLM-5.3 Flash (default)
nim chat "Which number is larger, 9.11 or 9.8?"

# Inspect model reasoning trace / chain-of-thought
nim chat "Which number is larger, 9.11 or 9.8?" --thinking

# Stream live tokens to stdout
nim chat "Explain raft consensus in 3 bullet points" --stream

# Buffer output to file with 2-line summary preview (Kem Glitch token reduction)
nim chat "Write a complete CMakeLists.txt for a C project" --out /tmp/cmakelists.txt --project
```

### 3. Calibrated Decision Routing (`decide`)
Discrete triage and decision scoring:
```bash
nim decide "Should we deploy code without running unit tests?" \
  --options "deploy" "run_tests_first" "abort"
```
*Returns structured JSON with chosen option, confidence score (0.0–1.0), and rationale.*

### 4. Batched Vector Embeddings (`embed`)
Embeds an array of text snippets or file paths in a single HTTP request:
```bash
nim embed "Kernel memory architecture" "Page tables in x86" README.md \
  --out-json /tmp/embeddings.json
```

### 5. Model Catalog (`models`)
```bash
nim models
```

---

## 🐍 Python Usage

### Option A: Built-in Zero-Dependency Gateway
Works out of the box with Python standard library:

```python
from nim_client import NimClient, chat, run_decide, run_batched_embeddings, run_agent_loop

# 1. One-shot chat (key auto-resolved)
response = chat("Which number is larger, 9.11 or 9.8?")
print(response)

# 2. Calibrated decision
decision = run_decide("Is this PR ready to merge?", options=["merge", "review", "block"])
print(decision["choice"], decision["confidence"])

# 3. Vector embeddings (2048 dims)
vectors = run_batched_embeddings(["Hello world", "Machine learning"])
print(f"Generated {vectors['count']} vectors of dim {vectors['dimensions']}")

# 4. Run an autonomous subagent
run_agent_loop("Check git status in /home/rodri and report dirty repositories.", max_turns=5)
```

### Option B: Using Official `openai` SDK
Fully compatible with OpenAI Python client:

```python
from openai import OpenAI
from nim_client import resolve_api_key

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=resolve_api_key(),  # Safe resolution from .env/pool
)

completion = client.chat.completions.create(
    model="z-ai/glm-5.3-flash",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Which number is larger, 9.11 or 9.8?"}
    ],
    temperature=0.5,
    max_tokens=1024,
)

print(completion.choices[0].message.content)
```

---

## 📋 Verified Popular Models — last-verified snapshot (2026-11-23)

> Snapshot only — not a live guarantee. Confirm availability with
> `nim catalog --check`. Ids marked **STALE** were absent from the live catalog
> on 2026-11-23 and are recorded in `catalog.json` → `retired`; do not assume
> they are still available or free.

| Model ID | Name | Type | Catalog status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| `z-ai/glm-5.3-flash` | GLM 5.3 Flash | Chat / Reasoning | live | Ultra-fast default, subagent tool execution |
| `z-ai/glm-5.3` | GLM 5.3 | Heavy Reasoning | **STALE** (delisted) | Deep mathematical & logical reasoning |
| `deepseek-ai/deepseek-r1` | DeepSeek R1 | Reasoning | **STALE** (delisted) | Open reasoning flagship |
| `deepseek-ai/deepseek-v3` | DeepSeek V3 | Chat | **STALE** (delisted) | High-throughput general instruction |
| `meta/llama-3.3-70b-instruct` | Llama 3.3 70B | Chat | **STALE** (delisted) | General coding & architectural analysis |
| `nvidia/llama-3.1-nemotron-70b-instruct`| Nemotron 70B | Chat | **STALE** (delisted) | Precision agentic workflows |
| `qwen/qwen2.5-coder-32b-instruct` | Qwen 2.5 Coder | Code | **STALE** (delisted) | Specialized coding & refactoring |
| `nvidia/llama-nemotron-embed-vl-1b-v2` | Nemotron Embed | Embed | **STALE** (delisted) | 2048-dimensional passage/query vectors |

## 🔄 Catalog reconciliation

The live NVIDIA `/v1/models` endpoint is keyless and returns only `id`, `object`,
`created`, and `owned_by` — no pricing, context, modality, or capability data.
Eligibility therefore means **present in the live catalog only**; never claim a
model is free. Active ids, their roles, and retirement history live in
`catalog.json`. Override that path with `NIM_CATALOG_PATH`.

On use, check for drift first — read-only, no quota spent:

```bash
python3 scripts/nim_client.py catalog --check
```

Show any reported drift (added / removed / reactivated ids) to the user. Apply
changes **only after user approval**:

```bash
python3 scripts/nim_client.py catalog --apply
```

Probing is strictly opt-in: it requires `NVIDIA_API_KEY` and spends quota, so
never run it implicitly:

```bash
python3 scripts/nim_client.py catalog --probe
```

`catalog --json` emits structured data to stdout; diagnostics go to stderr.
Exit codes: 0 = no drift / success, 1 = drift or runtime error, 2 = invalid
arguments (usage error).
