---
name: local-llm

description: "Query the local LLM: Qwen3.6-35B-A3B Uncensored Genesis on port 8080, a zero-cost, offline, dual-GPU Vulkan coder and writer. Use when the user says \"the local llm\", \"use the local model\", or \"write a python script\" with it, or wants drafting, refactors, long-form text, or any prompt that should not leave the machine — even when they never name the model. Also starts and health-checks the server when it is down. The full endpoint roster is model-layer; this skill is the :8080 coder itself."

compatibility: "Requires dual AMD Radeon RX 9060 XT GPUs with Vulkan and the llama.cpp Vulkan build. The server is NOT started by default: port 8080 is offline until launched with the skill's start command or /run/media/rodri/AI/sh/luffy-hermes-mtp-vulkan.sh. Takes ~15-20s to load 22GB into VRAM."
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

## Available scripts

Bundled CLI scripts, referenced relative to the skill root. Run `<command> --help`
for flags and exit codes; structured data goes to stdout, diagnostics to stderr.

- `scripts/llm_client.py` — local-llm — local LLM client (:8080).

## Agent workflow — one exec plan

Drive this skill through **one JavaScript `omnicli exec` plan**. Discovery and
invocation both happen inside that plan — no ranking/discovery-tool call, no
two-step CLI invocation, and no intermediate payloads in the context window.

The plan reads two read-only surfaces:

| Level | What it gives you | Helper |
| :--- | :--- | :--- |
| L1 | name + description of every installed skill | `lsSkills()` from `omnicli_skills` |
| L2 | this skill's full `SKILL.md` body | `readSkill(name)` from `omnicli_skills` |
| L3 | one file under this skill root (`references/`, `assets/`, `scripts/`) | `readResource(name, rel)` from `omnicli_skills` |
| Contract | generated tool name + schema (`name`, `name+description`, `full`) | `ls()` / `read()` from `catalog/contract_fs.mjs` |

```js
import { lsSkills, readSkill, readResource } from "omnicli_skills";
import { ls, read } from "<file://…/catalog/contract_fs.mjs>"; // sandbox-only
import { invoke, result } from "omnicli_tools";

// L1 — pick the skill by description (no ranking call).
const entry = lsSkills().find((s) => s.name === "local-llm");
if (!entry) throw new Error("skill not installed");
// L2 — read instructions only when the step needs them.
const body = readSkill("local-llm");
// L3 — one file by relative path (absolute paths and '..' are rejected).
const extra = readResource("local-llm", "config.json");
// Contract tree — three detail levels for the one tool you will call.
const file = ls("local-llm").find((n) => n === "scripts_llm_client");
const rel = "local-llm/" + file;
const name = read(rel, "name");              // "local-llm/scripts/llm_client"
const brief = read(rel, "name+description"); // { name, description }
const full = read(rel, "full");              // schema + example + raw argv

// One catalogued tool call with a raw argv array, then ONE bounded result.
const out = await invoke(name, ["--json", "doctor"]);
result({
  ok: out.exit_code === 0,
  tool: name,
  proof: "agent-skills-three-levels",
  data: { exitCode: out.exit_code,
          bodyBytes: body.length, extraBytes: extra.length,
          description: brief.description.slice(0, 120),
          hasSchema: Boolean(full.inputSchema),
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
  VRAM on another slot, start this first or free the other ports.
- **Thinking is disabled** in the launcher's chat template. Prompts expecting
  a visible chain of thought will get a direct answer instead.
