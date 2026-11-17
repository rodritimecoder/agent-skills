---
name: model-layer
description: "The model layer of this machine: every local model server — llm (:8080), audio (:8081), ocr (:8082), decision (:8083/:8089), embed (:8084), llm-aux (:8091) — with its launcher script, weights files, health check, quirks and the skills that consume it, plus the llama-swap rig (:8000) via llama-rig. MUST READ before starting, stopping, swapping or debugging any local model server, or before writing code that calls one. Also the place for capacity questions — whether a candidate or a context size (262k, 16GB card) fits the VRAM budget, what is resident, or what to evict. The roster is generated from ports.json; a model swap edits the manifest and re-renders — never this file."
metadata:
  bins: llama-rig
allowed-tools: "Bash(llama-rig:*) Bash(python3:*) Bash(ports.py:*) Read"
---

# model-layer — the machine's model roster

One fact, one owner. This file is a **view**, not a source: everything between
the markers is generated from `ports.json` and the in-repo launcher copies by
`python3 ports.py render --write`. **Never hand-edit the roster below.** If it
disagrees with the machine, the manifest or a launcher is wrong — fix that and
re-render. `ports.py check` (run by `sync-skills`) fails the push when the
roster drifts from the manifest or when a launcher names weights that are not
on disk.

## How to use this skill

- **Find your server** in the roster table, then read its per-slot section:
  launcher, weights files, API, health check, quirks, and which skills use it.
- **Start it** with the launcher shown (volume `sh/`, in-repo copy
  `launchers/`), or prefer the owning skill's CLI where one exists
  (`ocr server start --engine lighton`, `audiocpp-asr`, …).
- **Health:** trust `omnicli status` over an open port — `tailscale serve`
  holds a listener even when the backend is dead.
- **Read the quirks line before integrating.** Some models answer in
  `reasoning_content` instead of `content`; the embed slot's dimension must
  match the index; decision models are not chat models.
- **Swap a model** — one command, downstream everywhere:
  1. `python3 ports.py swap <slot> --model "NAME" --quant "..." --chat <path.gguf> --mmproj <path.gguf> [--note "quirks"]`
     — supersedes the old record (single-candidate slots rename in place, history
     in the notes; multi-candidate slots retire the old candidate), repoints the
     launcher's weights in `launchers/` and volume `sh/`, re-renders every
     generated surface (this roster, both AGENTS.md, docs tables, the port
     registry), and runs `ports.py check`.
  2. Review the stale-mentions report it prints — prose still naming the old
     model across skills and docs — then re-run with
     `--rename "OLD=NEW"` to rewrite those, or fix them by hand where the old
     name is a historical benchmark attribution.
  3. `sync-skills --push` (refuses to ship if the check failed).

  `--dry-run` prints the whole plan and writes nothing.

## The rig — llama-swap (:8000)

Beyond the slots sits the swapping rig, operated by `llama-rig`
([scripts/llama_rig.py](scripts/llama_rig.py), config in [config/](config/)):

- **`:8000` llama-swap** — a Go model-swapping proxy. One model is pinned (the
  llm slot's king holds the VRAM); auxiliary models are evicted and restored on
  demand. Start/inspect/stop with `llama-rig llama-swap-up | llama-swap-status
  | llama-swap-down`; it watches [config/llama-swap.yaml](config/llama-swap.yaml).
  It fronts **chat-completions models only** — `/v1/embeddings`, `/v1/rerank`,
  `/v1/audio/*`, `/ocr/pipeline` and `/v1/systemone` stay direct slots, because a
  router fits a uniform contract with many candidates, not a "type".
  `llama-swap -validate` only proves the file parses; `ports.py check` proves every
  model's weights exist and the swap matrix resolves.
- **Headroom & Dynamic Swapping:** `llama-rig status` (VRAM + every slot's state),
  `llama-rig up <slot|port> [candidate]` (or `swap`), `llama-rig down <slot|port>` (or `kill`),
  and `llama-rig evict-all` (free every non-pinned port to reclaim headroom). Target
  can be a slot id (`ocr`, `asr`, `decision`, `llm`), an alias, a numeric port, or any
  registered candidate by model or launcher name (`up valen`,
  `up embed embeddinggemma-2`). `--dry-run` prints the resolved launch plan and
  starts nothing.
- **Manifest first:** the tool reads `ports.json` (every candidate) and treats
  `port_registry.json` as a rendered cache. Starting a non-default candidate never
  rewrites the manifest: it prints the divergence and the `ports.py swap` command
  that would persist it.

The rig is `infra` in `ports.json` (owned by this skill); the slots above are
the models it swaps. Note: `qwen3.6-35b` is backed by the Hermes MTP MXFP4 weights on the AI volume.

## Rules

- The roster is generated; the manifest is the truth and the disk is the floor.
- A skill that uses a model points here via a `Model layer:` line in its
  SKILL.md, and names the slot in its `compatibility` string.
- Adding a consumer or a slot is a `ports.json` edit (`consumers` map), not a
  prose edit.

<!-- ports:begin -->
| Slot | Port | Alias | Default launcher | Model | Weights | Used by |
|---|---|---|---|---|---|---|
| `llm` | `:8080` | `local-coder-genesis` | `luffy-hermes-mtp-vulkan.sh` | Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-MTP (MXFP4 experts (FFN 1-38) + Q8_0, MTP draft) **(candidate)** | `models/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-MTP-GGUF/Hermes3.6-35B-A3B-Uncensored-Genesis-MTP-MXFP4.gguf`<br>`models/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-MTP-GGUF/mmproj-Hermes3.6-35B-A3B-Uncensored-Genesis-F16.gguf` | local-llm, omnicli |
| `audio` | `:8081` | `local-audio-audiocpp` | `run-audiocpp.sh` | nemotron-asr | — | audiocpp, video-miner |
| `decision` | `:8083` | `local-decide` | `h2o.sh` | h2o-lightning-4b (Q4_K_M + mmproj F16) | — | jev-decision, decision-model, frontend-uat, eval-router |
| `decision-aux` | `:8089` | `local-decide-aux` | `imajev-decider.sh` | Imajev-4B (Q4_K_M + mmproj f16) | `models/mindchain/imajev-4b-GGUF/imajev-4b-Q4_K_M.gguf`<br>`models/mindchain/imajev-4b-GGUF/imajev-4b-mmproj-f16.gguf` | jev-decision |
| `ocr` | `:8082` | `local-ocr` | `lighton-ocr.sh` | LightOnOCR-3-0.8B (Q4_K_M + mmproj q8_0) | `models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.Q4_K_M.gguf`<br>`models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.mmproj-q8_0.gguf` | ocr, video-miner, doc-layout, canvas-cli |
| `embed` | `:8084` | `local-embed-bge` | `bge-small.sh` | bge-small-en-v1.5 (f16) | `models/unsloth/bge-small-en-v1.5-GGUF/bge-small-en-v1.5-f16.gguf` | graph-memory, semantic-cache |
| `llm-aux` | `:8091` | `local-llm-aux` | `lfm3-1.7b-uncensored.sh` | LFM3-1.7B-Uncensored-AD (Q4_K_M) | `models/AtomicChat/LFM3-1.7B-Uncensored-GGUF/LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf` | — |

### `:8080` llm — `local-coder-genesis`

- **Role:** Primary generative LLM — chat, code, long-form writing, prose projection
- **Service:** llama-server (Vulkan)
- **Start:** `luffy-hermes-mtp-vulkan.sh` (volume `sh/`; in-repo copy `launchers/luffy-hermes-mtp-vulkan.sh`)
- **Health:** `curl -s http://127.0.0.1:8080/health`
- **API:** `/v1/chat/completions`
- **Owner:** `local-llm` · **Used by:** local-llm, omnicli
- **Weights:** `models/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-MTP-GGUF/Hermes3.6-35B-A3B-Uncensored-Genesis-MTP-MXFP4.gguf` · `models/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-MTP-GGUF/mmproj-Hermes3.6-35B-A3B-Uncensored-Genesis-F16.gguf`
- **Quirks:** 131072 context, nextn head, --spec-type draft-mtp (n-max 4), dual-GPU 50/50 on the upstream Vulkan build.
- **Candidates:** `Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-MTP` (MXFP4 experts (FFN 1-38) + Q8_0, MTP draft, candidate) · `Qwen3.8-27B-GSQ-RCO + DFlash2 draft` (IQ3_XXS target, Q4_K_M draft, candidate) · `Swift-1.5-Qwen3.8-27B-heretic` (IQ3_XXS + MTP draft, candidate) · `Qwen3.8-27B-Uncensored-HauhauCS-Aggressive` (Q4_K_P, candidate) · `Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced` (Q4_K_M, legacy) · `Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced` (Q4_K_M, legacy) · `Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced` (Q4_K_M, legacy) · `Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced` (Q4_K_M, legacy) · `Qwen3.6-35B-A3B-MTP` (UD-Q3_K_M, candidate) · `ThinkingCap-Qwen3.6-27B` (Q4_K_M + f16 mmproj, candidate) · `llama-router (multi-model multiplexer)` (n/a — presets live in hardware/model-layer/config/llama-router.ini, candidate)

### `:8081` audio — `local-audio-audiocpp`

- **Role:** Speech-to-text, text-to-speech, forced alignment, voice cloning
- **Service:** audio.cpp 0.9.4 (Vulkan)
- **Start:** `run-audiocpp.sh` (volume `sh/`; in-repo copy `launchers/run-audiocpp.sh`)
- **Health:** `curl -s http://127.0.0.1:8081/health`
- **API:** `/v1/audio/*`
- **Owner:** `audiocpp` · **Used by:** audiocpp, video-miner
- **Quirks:** server.json registers 14 GGUFs; models load lazily, max_loaded_models keeps 3 warm 40 locales; streaming live transcription endpoint.
- **Candidates:** `nemotron-asr` (, current) · `kokoro-v1.0` (, current) · `qwen3-forced-aligner` (, current)

### `:8083` decision — `local-decide`

- **Role:** The decision engine slot - bool / choice / score primitives
- **Service:** llama-server b11736+ (Vulkan), optionally behind a package server
- **Start:** `h2o.sh` (volume `sh/`; in-repo copy `launchers/h2o.sh`)
- **Health:** `curl -s http://127.0.0.1:8083/health`
- **API:** `/v1/systemone (native, calibrated); vision via mmproj`
- **Owner:** `jev-decision` · **Used by:** jev-decision, decision-model, frontend-uat, eval-router
- **Quirks:** Native /v1/systemone (Q4_K_M) + visual box locator via h2o-serve shim (:8761). vision projector attached
- **Candidates:** `h2o-lightning-4b` (Q4_K_M + mmproj F16, current) · `Valen-Decision-1.5-0.8B` (Q5_K_M + vision Q8_0, candidate) · `gliclass-v4-edge` (Q8_ONNX (617 MB) / FP32_ONNX (1.68 GB), candidate) · `GLiDE-0.4B` (Q8_0 (421 MB) + readout bf16 (522 KB), candidate) · `pplx-decider-flash-v1.2` (Q4_K_M + mmproj F16, retired) · `vllm-d3-mini` (Q4_K_M + mmproj Q8_0, candidate)

### `:8089` decision-aux — `local-decide-aux`

- **Role:** Secondary decision engine — Imajev-4B chat path, or letter/readout with READOUT=1
- **Service:** llama-server (Vulkan)
- **Start:** `imajev-decider.sh` (volume `sh/`; in-repo copy `launchers/imajev-decider.sh`)
- **Health:** `curl -s http://127.0.0.1:8089/health`
- **API:** `/v1/chat/completions (readout driven by the pplx-decider client)`
- **Owner:** `jev-decision` · **Used by:** jev-decision
- **Weights:** `models/mindchain/imajev-4b-GGUF/imajev-4b-Q4_K_M.gguf` · `models/mindchain/imajev-4b-GGUF/imajev-4b-mmproj-f16.gguf`
- **Quirks:** Supersedes the OneJev1.5-4B occupancy of this port. Not the primary decision API — :8083 remains the one clients should call; this slot exists for A/B work and for a second opinion while :8083 is held by another candidate. Qwen3.5-4B with a merged LoRA decision adapter, restored to the :8089 fallback slot it occupied during the ImageJevBench A/B against pplx on :8083. vision projector attached

### `:8082` ocr — `local-ocr`

- **Role:** Documents, PDFs and slides — fast prefill, high-throughput markdown
- **Service:** llama-server (Vulkan)
- **Start:** `lighton-ocr.sh` (volume `sh/`; in-repo copy `launchers/lighton-ocr.sh`)
- **Health:** `curl -s http://127.0.0.1:8082/health`
- **API:** `/v1/chat/completions`
- **Owner:** `ocr` · **Used by:** ocr, video-miner, doc-layout, canvas-cli
- **Weights:** `models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.Q4_K_M.gguf` · `models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.mmproj-q8_0.gguf`
- **Quirks:** thinking variant — OCR output arrives in reasoning_content.

### `:8084` embed — `local-embed-bge`

- **Role:** Vector embeddings for RAG and semantic caching
- **Service:** llama-server (Vulkan)
- **Start:** `bge-small.sh` (volume `sh/`; in-repo copy `launchers/bge-small.sh`)
- **Health:** `curl -s http://127.0.0.1:8084/health`
- **API:** `/v1/embeddings`
- **Owner:** `graph-memory` · **Used by:** graph-memory, semantic-cache
- **Weights:** `models/unsloth/bge-small-en-v1.5-GGUF/bge-small-en-v1.5-f16.gguf`
- **Quirks:** THE ONE SLOT WHERE DIMENSION MATTERS. Indexes must record which candidate built them; see rag.db meta table. DEFAULT.
- **Candidates:** `bge-small-en-v1.5` (f16, current) · `embeddinggemma-2` (Q8_0 + mmproj Q8_0, alternate)

### `:8091` llm-aux — `local-llm-aux`

- **Role:** Secondary generative LLM — uncensored roleplay and short-form creative, runs beside the primary :8080 slot instead of swapping it out
- **Service:** llama-server (Vulkan)
- **Start:** `lfm3-1.7b-uncensored.sh` (volume `sh/`; in-repo copy `launchers/lfm3-1.7b-uncensored.sh`)
- **Health:** `curl -s http://127.0.0.1:8091/health`
- **API:** `/v1/chat/completions`
- **Owner:** `local-llm` · **Used by:** —
- **Weights:** `models/AtomicChat/LFM3-1.7B-Uncensored-GGUF/LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf`
- **Quirks:** No skill drives this slot; call it directly. The launcher honours PORT=, but any other port needs a manifest slot first or ports.py check fails. LiquidAI LFM3 1.7B, uncensored AD tune, RP workload.
<!-- ports:end -->
