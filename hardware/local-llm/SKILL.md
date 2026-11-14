---
name: local-llm

description: "Query the local Qwen3.6-35B-A3B Uncensored Genesis model on port 8080 — a zero-cost, offline, dual-GPU Vulkan coder and writer. Use for drafting code, long-form text, refactors, or any prompt that should not leave the machine. Also starts and health-checks the server when it is down."

compatibility: "Requires dual AMD Radeon RX 9060 XT GPUs with Vulkan and the llama.cpp Vulkan build. The server is NOT started by default: port 8080 is offline until launched with the skill's start command or /run/media/rodri/AI/sh/luffy_nothink.sh. Takes ~15-20s to load 22GB into VRAM."
allowed-tools: "Bash(python3:*) Bash(local-llm:*) Bash(curl:*) Read"
---

> **Model layer:** the server behind this skill is registered in the `model-layer` skill (slot `:8080`) — launcher, weights files, health and quirks. Read it before starting, swapping or debugging the model. If it is down, the client starts it via `llama-rig up 8080` (`--no-autostart` skips).

# Local LLM — Qwen3.6-35B Genesis (`local-llm`)

An OpenAI-compatible `llama-server` on `:8080`, serving
**Qwen3.6-35B-A3B Uncensored Genesis Final** (Q4_0 ROCMFP4, layer-split
45/55 across two RX 9060 XT cards, 131k context, thinking disabled).

Use it when a task should cost nothing and stay offline. Pass `--fallback` to
route to OpenRouter Free or Gemini when the local server is down.

```
agent ──▶ scripts/llm_client.py ──▶ http://127.0.0.1:8080/v1/chat/completions
                                        └── llama-server (22 GB VRAM)
```

---

## Quickstart

```bash
# Is it up?
python3 scripts/llm_client.py doctor

# Ask something
python3 scripts/llm_client.py "write a bash function that retries a command"

# Bring it up first (loads 22 GB into VRAM, ~15-20s)
python3 scripts/llm_client.py start

# Offline? Borrow a cloud model for this call only
python3 scripts/llm_client.py "refactor this" --fallback
```

`chat` is the default subcommand — the bare form above is equivalent to
`python3 scripts/llm_client.py chat "…"`.

---

## Keeping output out of the context window

Long generations are where a context window goes to die. Every call can be
buffered and projected:

| Flag | Effect |
| :--- | :--- |
| `--out FILE` | write the full reply to disk; stdout gets a one-line confirmation |
| `--json` | wrap the reply as `{"content": …, "model": …}` |
| `--project content` | emit only the listed JSON fields (implies `--json`) |
| `--stream` | stream tokens to stdout as they arrive |

```bash
# full essay on disk, nothing in context
python3 scripts/llm_client.py "explain ROCm FP4 quantization" --out /tmp/essay.md

# machine-readable, one field
python3 scripts/llm_client.py "return a JSON list of 5 test names" --json --project content
```

Prefer `--out` for anything longer than a paragraph: you can `grep` the file
afterwards and read only the lines that matter.

---

## Quick reference

| Subcommand | Purpose |
| :--- | :--- |
| `chat PROMPT` | send a prompt (default when the first arg is not a subcommand) |
| `doctor` | report endpoint, process state, and how to start the server |
| `start` | launch the server in the background via the configured launcher |

| `chat` flag | Default | Meaning |
| :--- | :--- | :--- |
| `--system TEXT` | — | system instruction prepended to the prompt |
| `--temp FLOAT` | `0.7` | sampling temperature |
| `--stream` | off | stream tokens |
| `--out FILE` | — | buffer the reply to disk |
| `--json` / `--project` | off | structured output, selective fields |
| `--fallback` | off | use a cloud model if `:8080` is offline |

---

## Files

| Path | Purpose |
| :--- | :--- |
| `scripts/llm_client.py` | the client — chat, doctor, start |
| `config.json` | endpoint, model name, launcher path, sampling defaults |

`config.json` is read from the skill root (`SKILL_DIR/config.json`), so the
server can be moved to another port by editing one file.

---

## Gotchas

- **`:8080` is not running by default.** `doctor` is the cheap way to find out;
  a failed call costs nothing but a wasted process spawn.
- **`tailscale serve` also binds `:8080`** on the tailscale interface
  (`100.x.y.z%tailscale0:8080`). That listener does not block the local bind,
  but when the mesh is published and this server is down, tailnet clients get a
  dead port. Check `doctor` before assuming the mesh is healthy.
- **The `start` command detaches.** It returns before the model is loaded;
  poll `doctor` rather than the first request.
- **`--fallback` is per call.** It does not start the local server, and the
  reply comes from a remote model — say so if the caller needs provenance.
- **OOM.** The server wants ~22 GB across both cards. If something else holds
  VRAM on `:8083`–`:8085`, start this first or free the other ports.
- **Thinking is disabled** in the launcher's chat template. Prompts expecting
  a visible chain of thought will get a direct answer instead.
