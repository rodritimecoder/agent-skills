---
name: local-llm

description: "Query the local LLM: Inkling-2-Mini-Unbound-v2 on port 8080, a zero-cost, offline coder and writer served by the maya-ik2 engine on one RX 9060 XT. Use when the user says \"the local llm\", \"use the local model\", or \"write a python script\" with it, or wants drafting, refactors, long-form text, or any prompt that should not leave the machine — even when they never name the model. Also starts and health-checks the server when it is down. The full endpoint roster is model-layer; this skill is the :8080 coder itself."

compatibility: "Requires an AMD Radeon RX 9060 XT (gfx1200) with ROCm 10 and the maya-ik2 HIP build in /home/rodri/build/maya-ik2, driven by serve/server.py. The server is NOT started by default: port 8080 is offline until launched with the skill's start command or /run/media/rodri/AI/sh/inkling-2-mini-unbound.sh. Takes ~10-25 s to open the model; 14.7 GiB of experts then stay in a pinned host-RAM pool."
allowed-tools: "Bash(python3:*) Bash(local-llm:*) Bash(curl:*) Read"
---

> **Model layer:** the server behind this skill is registered in the `model-layer` skill (slot `:8080`) — launcher, weights files, health and quirks. Read it before starting, swapping or debugging the model. If it is down, the client starts it via `llama-rig up 8080` (`--no-autostart` skips).

# Local LLM — Inkling-2-Mini-Unbound-v2 (`local-llm`)

An OpenAI- and Anthropic-compatible `serve/server.py` on `:8080`, serving
**Inkling-2-Mini-Unbound-v2** (UD-Q4_K_XL, the Unbound finetune of Thinking
Machines' 26B looped MoE) through the **maya-ik2** engine: one RX 9060 XT,
65,536-token context, FP8 KV, 10 GiB expert cache over a 14.7 GiB pinned host
pool, ~33 tok/s decode. Text only — no image tower is built.

Use it when a task should cost nothing and stay offline. Pass `--fallback` to
route to OpenRouter Free or Gemini when the local server is down.

```
agent ──▶ scripts/llm_client.py ──▶ http://127.0.0.1:8080/v1/chat/completions
                                        └── serve/server.py ──▶ maya-ik2 (HIP, GPU 0)
```

---

## Available scripts

Bundled CLI scripts, referenced relative to the skill root. Run `<command> --help`
for flags and exit codes; structured data goes to stdout, diagnostics to stderr.

- `scripts/llm_client.py` — local-llm — local LLM client (:8080).

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
const entry = lsSkills().find((s) => s.name === "local-llm");
if (!entry) throw new Error("skill not installed");
// L2 — read instructions only when the step needs them.
const body = readSkill("local-llm");
// L3 — one file by relative path (absolute paths and '..' are rejected).
const extra = readResource("local-llm", "config.json");
// Schema — exact input schema for the one tool you will call.
const toolId = "local-llm/scripts/llm_client";
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

## Quickstart

```bash
# Is it up?
python3 scripts/llm_client.py doctor

# Ask something
python3 scripts/llm_client.py "write a bash function that retries a command"

# Bring it up first (opens the engine in ~10-25s)
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
- **RAM is the binding limit, not VRAM.** The server holds one whole 16 GB card
  (~15.5 GiB: dense weights, FP8 KV cache, 10 GiB expert cache) plus 14.7 GiB of
  **pinned host RAM** for the expert pool, out of this box's 30 GB. That leaves
  room for one chat model only: starting `llm-aux` (`:8091`) beside it drove free
  RAM to zero, swap to 7/7 and decode from 33 to 0.8 tok/s (measured 2026-11-29).
  Swap chat models, never stack them; GPU 1 is free for the small aux slots but
  the RAM is not.
- **Thinking follows the model's own default.** With no level named the server
  reports `auto` (the template's 0.9, "high"); send
  `chat_template_kwargs: {"enable_thinking": false}` or `reasoning_effort:
  "none"` when you want the answer with no reasoning segment.
- **Stopping takes 30-60 s.** SIGTERM makes the engine release the pinned
  expert pool; a 3-second SIGKILL fallback (`llama-rig down`) can cut that
  short, so prefer a plain SIGTERM when you have the time.
- **Sampling profiles.** The launcher picks a set with `PROFILE`: `agent` (default — temperature 0.7,
  top_p 0.95, top_k 20, thinking at the model's default), `rp` (1.05 / 0.98, no top_k, thinking **off**)
  or `raw` (1.0 / 1.0, thinking off). RP and raw think off because this model spends its whole budget in
  the reasoning segment at any effort level (effort `low`, 700 tokens → 2 364 chars of reasoning, 0 of
  answer). `TEMP`, `TOP_P` and
  `TOP_K` override any profile. Only those three reach maya-ik2: `min_p` and the repetition /
  frequency / presence penalties are forwarded by the server and dropped by the engine, so setting
  them here changes nothing (use `:8091`, a llama.cpp server, when penalties matter).
- **Text only.** The image tower (`maya-vision`) is not built here, so
  `/health` reports `images: false` and picture inputs are refused.
