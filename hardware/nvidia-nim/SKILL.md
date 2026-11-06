---
name: nvidia-nim

description: >
  Direct inference and autonomous subagent execution via NVIDIA NIM / API Catalog (integrate.api.nvidia.com)
  for hosted frontier models including GLM-5.3 (z-ai/glm-5.3-flash), Llama 3.3 70B, DeepSeek R1/V3, and Nemotron.
  Features an autonomous subagent loop with compound bash batching (run_bash_batch), calibrated decision routing (decide),
  batched embeddings (embed), multi-key pooling with automatic failover, and Kem Glitch token reduction.

compatibility: "Requires network access to integrate.api.nvidia.com and an NVIDIA API key (NVIDIA_API_KEY)."
allowed-tools: "Bash(nvidia-nim:*) Bash(python3:*) Read Write"
---

# NVIDIA NIM Multi-Agent & Multimodal Gateway (`nvidia-nim`)

Zero-dependency inference and autonomous subagent execution gateway for **NVIDIA NIM / API Catalog** (`https://integrate.api.nvidia.com/v1`). Built in the same architecture as `openrouter-free`, enabling autonomous subagent workflows, streaming reasoning extraction, calibrated decisions, and vector embeddings without consuming primary frontier tokens.

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

## 📋 Verified Popular Models

| Model ID | Name | Type | Notes |
| :--- | :--- | :--- | :--- |
| `z-ai/glm-5.3-flash` | GLM 5.3 Flash | Chat / Reasoning | Ultra-fast default, subagent tool execution |
| `z-ai/glm-5.3` | GLM 5.3 | Heavy Reasoning | Deep mathematical & logical reasoning |
| `deepseek-ai/deepseek-r1` | DeepSeek R1 | Reasoning | Open reasoning flagship |
| `deepseek-ai/deepseek-v3` | DeepSeek V3 | Chat | High-throughput general instruction |
| `meta/llama-3.3-70b-instruct` | Llama 3.3 70B | Chat | General coding & architectural analysis |
| `nvidia/llama-3.1-nemotron-70b-instruct`| Nemotron 70B | Chat | Precision agentic workflows |
| `qwen/qwen2.5-coder-32b-instruct` | Qwen 2.5 Coder | Code | Specialized coding & refactoring |
| `nvidia/llama-nemotron-embed-vl-1b-v2` | Nemotron Embed | Embed | 2048-dimensional passage/query vectors |
