---
name: model-layer
description: "The model layer of this machine: every local model server — llm (:8080), audio (:8081), decision (:8083/:8089), ocr (:8084/:8085), rerank + embed (:8086/:8087), grounding (:8088), ocr-jev (:8090) — with its launcher script, weights files, health check, quirks and the skills that consume it, plus the llama-swap rig (:8000) via vram-rig-ctl. MUST READ before starting, stopping, swapping or debugging any local model server, or before writing code that calls one. The roster is generated from ports.json; a model swap edits the manifest and re-renders — never this file."
allowed-tools: "Bash(vram-rig-ctl:*) Bash(python3:*) Bash(ports.py:*) Read"
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

Beyond the slots sits the swapping rig, operated by `vram-rig-ctl`
([scripts/vram_rig_ctl.py](scripts/vram_rig_ctl.py), config in [config/](config/)):

- **`:8000` llama-swap** — a Go model-swapping proxy. One model is pinned (the
  llm slot's king holds the VRAM); auxiliary models are evicted and restored on
  demand. Start/inspect/stop with `vram-rig-ctl llama-swap-up | llama-swap-status
  | llama-swap-down`; it watches [config/llama-swap.yaml](config/llama-swap.yaml).
- **Headroom:** `vram-rig-ctl status` (VRAM + every slot's state),
  `evict-all` (free every non-pinned port), `kill --port N`, `swap --port N`.

The rig is `infra` in `ports.json` (owned by this skill); the slots above are
the models it swaps. Note: the rig config's `qwen3.6-35b` entry names the
deleted Genesis Q4_K_M — calls to the default model 500 until it is repointed
(`ports.py swap` covers the slots; `llama-swap.yaml` needs a matching edit).

## Rules

- The roster is generated; the manifest is the truth and the disk is the floor.
- A skill that uses a model points here via a `Model layer:` line in its
  SKILL.md, and names the slot in its `compatibility` string.
- Adding a consumer or a slot is a `ports.json` edit (`consumers` map), not a
  prose edit.

<!-- ports:begin -->
| Slot | Port | Alias | Default launcher | Model | Weights | Used by |
|---|---|---|---|---|---|---|
| `llm` | `:8080` | `local-coder-genesis` | `luffy_nothink.sh` | Qwen3.6-35B-A3B-Uncensored-Genesis-Final (Q4_K_M) **(retired)** | `models/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Final-GGUF/Qwen3.6-35B-A3B-Uncensored-Genesis-Final-Q4_K_M.gguf` | local-llm, omnicli |
| `audio` | `:8081` | `local-audio-audiocpp` | `run-audiocpp.sh` | nemotron-asr | — | audiocpp, companion, video-miner |
| `decision` | `:8083` | `local-decide` | `h2o.sh` | h2o-lightning-4b (Q4_K_M + mmproj F16) | — | jev-decision, decision-model, clip-box, frontend-uat, eval-router |
| `decision-engine` | `:8082` | `local-decide-engine` | `startlux-decision.sh` | StartLux-Decision-v1.1-4B-Instant (Q4_K_M + mmproj F16) **(candidate)** | `models/startlux-models/StartLux-Decision-v1.1-4B-Instant-GGUF/StartLux-Decision-v1.1-4B-Instant-Q4_K_M.gguf`<br>`models/startlux-models/StartLux-Decision-v1.1-4B-Instant-GGUF/mmproj-StartLux-Decision-v1.1-4B-Instant-F16.gguf` | jev-decision |
| `decision-fallback` | `:8089` | `local-decide-fallback` | `imajev-decider.sh` | Imajev-4B (Q4_K_M + mmproj f16) | `models/mindchain/imajev-4b-GGUF/imajev-4b-Q4_K_M.gguf`<br>`models/mindchain/imajev-4b-GGUF/imajev-4b-mmproj-f16.gguf` | jev-decision |
| `ocr-crispembed` | `:8084` | `local-ocr-crispembed` | `crispembed-ocr.sh` | CrispEmbed (PP-OCRv6 small: DB++ det + CTC rec) | `models/cstr/PP-OCRv6-small-det-GGUF/PP-OCRv6_small_det-f16.gguf`<br>`models/cstr/PP-OCRv6_small_rec-GGUF/PP-OCRv6_small_rec-q8-head.gguf`<br>`models/cstr/dbnet-ic15-GGUF/dbnet-ic15-f16.gguf`<br>`models/cstr/parseq-GGUF/parseq-q8_0.gguf` | ocr |
| `ocr-lighton` | `:8085` | `local-ocr-lighton` | `lighton-ocr.sh` | LightOnOCR-3-0.8B (Q4_K_M + mmproj q8_0) | `models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.Q4_K_M.gguf`<br>`models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.mmproj-q8_0.gguf` | ocr, video-miner, doc-layout, canvas-cli |
| `reranker` | `:8086` | `local-rerank-jina` | `jina-reranker.sh` | jina-reranker-v2-base-multilingual (Q8_0) | `models/gpustack/jina-reranker-v2-base-multilingual-GGUF/jina-reranker-v2-base-multilingual-Q8_0.gguf` | graph-memory |
| `embed` | `:8087` | `local-embed-bge` | `bge-small.sh` | bge-small-en-v1.5 (f16) | `models/unsloth/bge-small-en-v1.5-GGUF/bge-small-en-v1.5-f16.gguf` | graph-memory, semantic-cache |
| `grounding` | `:8088` | `local-grounding-wevisone` | `wevisone-vl.sh` | WeVisOne-VL-4B (Q4_K_M + mmproj Q8_0) **(retired)** | `models/mradermacher/WeVisOne-VL-4B-GGUF/WeVisOne-VL-4B.Q4_K_M.gguf`<br>`models/mradermacher/WeVisOne-VL-4B-GGUF/WeVisOne-VL-4B.mmproj-Q8_0.gguf` | — |
| `ocr-jev` | `:8090` | `local-ocr-jev` | `minicpm-ocr-jev.sh` | MiniCPM-OCR-Jev (Q6_K + mmproj f16) | `models/openbmb/MiniCPM-OCR-Jev-gguf/MiniCPM-OCR-Jev-Q6_K.gguf`<br>`models/openbmb/MiniCPM-OCR-Jev-gguf/mmproj-model-f16.gguf` | kem-ocr |
| `llm-rp` | `:8091` | `local-rp-lfm3` | `lfm3-1.7b-uncensored.sh` | LFM3-1.7B-Uncensored-AD (Q4_K_M) | `models/AtomicChat/LFM3-1.7B-Uncensored-GGUF/LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf` | — |

### `:8080` llm — `local-coder-genesis`

- **Role:** Primary generative LLM — chat, code, long-form writing, prose projection
- **Service:** llama-server (Vulkan)
- **Start:** `luffy_nothink.sh` (volume `sh/`; in-repo copy `launchers/luffy_nothink.sh`)
- **Health:** `curl -s http://127.0.0.1:8080/health`
- **API:** `/v1/chat/completions`
- **Owner:** `local-llm` · **Used by:** local-llm, omnicli
- **Weights:** `models/LuffyTheFox/Qwen3.6-35B-A3B-Uncensored-Genesis-Final-GGUF/Qwen3.6-35B-A3B-Uncensored-Genesis-Final-Q4_K_M.gguf`
- **Quirks:** WEIGHTS DELETED by owner 2026-11-01 — deliberate, not coming back; only the Q8_K_P build remains on the volume.
- **Candidates:** `Qwen3.6-35B-A3B-Uncensored-Genesis-Hermes-MTP` (MXFP4 experts (FFN 1-38) + Q8_0, MTP draft, candidate) · `Qwen3.8-27B-GSQ-RCO + DFlash2 draft` (IQ3_XXS target, Q4_K_M draft, candidate) · `Swift-1.5-Qwen3.8-27B-heretic` (IQ3_XXS + MTP draft, candidate) · `Qwen3.8-27B-Uncensored-HauhauCS-Aggressive` (Q4_K_P, candidate) · `Qwen3.6-35B-A3B-Uncensored-Genesis-Final` (Q4_K_M, retired) · `Qwen3.6-35B-A3B-Uncensored-Genesis-Final` (Q4_K_M + mmproj F16, retired) · `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-TTQ` (4.51bpw IQ4_NL, legacy) · `Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced` (Q4_K_M, legacy) · `Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced` (Q4_K_M, legacy) · `Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced` (Q4_K_M, legacy) · `Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced` (Q4_K_M, legacy) · `Qwen3.6-35B-A3B-Uncensored-Genesis-Final` (Q4_K_M, candidate) · `Qwen3.6-35B-A3B-MTP` (UD-Q3_K_M, candidate) · `ThinkingCap-Qwen3.6-27B` (Q4_K_M + f16 mmproj, candidate)

### `:8081` audio — `local-audio-audiocpp`

- **Role:** Speech-to-text, text-to-speech, forced alignment, voice cloning
- **Service:** audio.cpp 0.9.4 (Vulkan)
- **Start:** `run-audiocpp.sh` (volume `sh/`; in-repo copy `launchers/run-audiocpp.sh`)
- **Health:** `curl -s http://127.0.0.1:8081/health`
- **API:** `/v1/audio/*`
- **Owner:** `audiocpp` · **Used by:** audiocpp, companion, video-miner
- **Quirks:** server.json registers 14 GGUFs; models load lazily, max_loaded_models keeps 3 warm 40 locales; streaming live transcription endpoint.
- **Candidates:** `nemotron-asr` (, current) · `kokoro-v1.0` (, current) · `qwen3-forced-aligner` (, current)

### `:8083` decision — `local-decide`

- **Role:** The decision engine slot - bool / choice / score primitives
- **Service:** llama-server b11736+ (Vulkan), optionally behind a package server
- **Start:** `h2o.sh` (volume `sh/`; in-repo copy `launchers/h2o.sh`)
- **Health:** `curl -s http://127.0.0.1:8083/health`
- **API:** `/v1/systemone (native, calibrated); vision via mmproj`
- **Owner:** `jev-decision` · **Used by:** jev-decision, decision-model, clip-box, frontend-uat, eval-router
- **Quirks:** Native /v1/systemone (Q4_K_M) + visual box locator via h2o-serve shim (:8761). vision projector attached
- **Candidates:** `h2o-lightning-4b` (Q4_K_M + mmproj F16, current) · `gliclass-v4-edge` (Q8_ONNX (617 MB) / FP32_ONNX (1.68 GB), candidate) · `pplx-decider-flash-v1.2` (Q4_K_M + mmproj F16, retired) · `vllm-d3-mini` (Q4_K_M + mmproj Q8_0, candidate) · `vllm-d3-nano` (Q4_K_M (local) + mmproj Q8_0, legacy) · `StartLux-Decision-v1.1-4B-Instant` (Q4_K_M (text decoder) + mmproj F16, candidate)

### `:8082` decision-engine — `local-decide-engine`

- **Role:** Experimental StartLux backend; not the h2o-lightning-4b JEV endpoint
- **Service:** llama-server b11736+ (Vulkan)
- **Start:** `startlux-decision.sh` (volume `sh/`; in-repo copy `launchers/startlux-decision.sh`)
- **Health:** `curl -s http://127.0.0.1:8082/health`
- **API:** `llama.cpp native (/health, /props, /completion)`
- **Owner:** `jev-decision` · **Used by:** jev-decision
- **Weights:** `models/startlux-models/StartLux-Decision-v1.1-4B-Instant-GGUF/StartLux-Decision-v1.1-4B-Instant-Q4_K_M.gguf` · `models/startlux-models/StartLux-Decision-v1.1-4B-Instant-GGUF/mmproj-StartLux-Decision-v1.1-4B-Instant-F16.gguf`
- **Quirks:** Started and stopped by the :8083 launcher, never independently - switching it alone starts the whole decision slot. vision projector attached

### `:8089` decision-fallback — `local-decide-fallback`

- **Role:** Secondary decision engine — Imajev-4B chat path, or letter/readout with READOUT=1
- **Service:** llama-server (Vulkan)
- **Start:** `imajev-decider.sh` (volume `sh/`; in-repo copy `launchers/imajev-decider.sh`)
- **Health:** `curl -s http://127.0.0.1:8089/health`
- **API:** `/v1/chat/completions (readout driven by the pplx-decider client)`
- **Owner:** `jev-decision` · **Used by:** jev-decision
- **Weights:** `models/mindchain/imajev-4b-GGUF/imajev-4b-Q4_K_M.gguf` · `models/mindchain/imajev-4b-GGUF/imajev-4b-mmproj-f16.gguf`
- **Quirks:** Supersedes the OneJev1.5-4B occupancy of this port. Not the primary decision API — :8083 remains the one clients should call; this slot exists for A/B work and for a second opinion while :8083 is held by another candidate. Qwen3.5-4B with a merged LoRA decision adapter, restored to the :8089 fallback slot it occupied during the ImageJevBench A/B against pplx on :8083. vision projector attached

### `:8084` ocr-crispembed — `local-ocr-crispembed`

- **Role:** Documents & scene text — OXR-1.0 layout-aware Markdown, PP-OCRv6 bounding boxes
- **Service:** crispembed-server
- **Start:** `crispembed-ocr.sh` (volume `sh/`; in-repo copy `launchers/crispembed-ocr.sh`)
- **Health:** `curl -s http://127.0.0.1:8084/health`
- **API:** `/ocr/pipeline, /oxr/document`
- **Owner:** `ocr` · **Used by:** ocr
- **Weights:** `models/cstr/PP-OCRv6-small-det-GGUF/PP-OCRv6_small_det-f16.gguf` · `models/cstr/PP-OCRv6_small_rec-GGUF/PP-OCRv6_small_rec-q8-head.gguf` · `models/cstr/dbnet-ic15-GGUF/dbnet-ic15-f16.gguf` · `models/cstr/parseq-GGUF/parseq-q8_0.gguf`
- **Quirks:** Default engine ppocrv6.

### `:8085` ocr-lighton — `local-ocr-lighton`

- **Role:** Documents, PDFs and slides — fast prefill, high-throughput markdown
- **Service:** llama-server (Vulkan)
- **Start:** `lighton-ocr.sh` (volume `sh/`; in-repo copy `launchers/lighton-ocr.sh`)
- **Health:** `curl -s http://127.0.0.1:8085/health`
- **API:** `/v1/chat/completions`
- **Owner:** `ocr` · **Used by:** ocr, video-miner, doc-layout, canvas-cli
- **Weights:** `models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.Q4_K_M.gguf` · `models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.mmproj-q8_0.gguf`
- **Quirks:** thinking variant — OCR output arrives in reasoning_content.

### `:8086` reranker — `local-rerank-jina`

- **Role:** Cross-encoder reranking for RAG
- **Service:** llama-server (Vulkan)
- **Start:** `jina-reranker.sh` (volume `sh/`; in-repo copy `launchers/jina-reranker.sh`)
- **Health:** `curl -s http://127.0.0.1:8086/health`
- **API:** `/v1/rerank`
- **Owner:** `graph-memory` · **Used by:** graph-memory
- **Weights:** `models/gpustack/jina-reranker-v2-base-multilingual-GGUF/jina-reranker-v2-base-multilingual-Q8_0.gguf`

### `:8087` embed — `local-embed-bge`

- **Role:** Vector embeddings for RAG and semantic caching
- **Service:** llama-server (Vulkan)
- **Start:** `bge-small.sh` (volume `sh/`; in-repo copy `launchers/bge-small.sh`)
- **Health:** `curl -s http://127.0.0.1:8087/health`
- **API:** `/v1/embeddings`
- **Owner:** `graph-memory` · **Used by:** graph-memory, semantic-cache
- **Weights:** `models/unsloth/bge-small-en-v1.5-GGUF/bge-small-en-v1.5-f16.gguf`
- **Quirks:** THE ONE SLOT WHERE DIMENSION MATTERS. Indexes must record which candidate built them; see rag.db meta table. DEFAULT.
- **Candidates:** `bge-small-en-v1.5` (f16, current) · `embeddinggemma-2` (Q8_0 + mmproj Q8_0, alternate)

### `:8088` grounding — `local-grounding-wevisone`

- **Role:** Word-level OCR boxes, open-vocab detection, referring localization, pointing, counting
- **Service:** llama-server (Vulkan)
- **Start:** `wevisone-vl.sh` (volume `sh/`; in-repo copy `launchers/wevisone-vl.sh`)
- **Health:** `curl -s http://127.0.0.1:8088/health`
- **API:** `/v1/chat/completions (structured <ref>/<box>/<point>, 0-1000 normalized)`
- **Owner:** `unowned` · **Used by:** —
- **Weights:** `models/mradermacher/WeVisOne-VL-4B-GGUF/WeVisOne-VL-4B.Q4_K_M.gguf` · `models/mradermacher/WeVisOne-VL-4B-GGUF/WeVisOne-VL-4B.mmproj-Q8_0.gguf`
- **Quirks:** Reuses :8088, freed when DeskForge-Qwen was archived; tailscale serve already holds the tailnet listener. No skill drives this slot yet - call it directly or add it to a consumer. WEIGHTS DELETED by owner 2026-11-01 — deliberate, not coming back (the empty prithivMLmods/tencent-WeVisOne-VL-4B-GGUF dir is a half-finished swap the owner abandoned). vision projector attached

### `:8090` ocr-jev — `local-ocr-jev`

- **Role:** OCR consistency gate — scores a candidate transcription against the source image in one forward pass
- **Service:** llama-server (Vulkan)
- **Start:** `minicpm-ocr-jev.sh` (volume `sh/`; in-repo copy `launchers/minicpm-ocr-jev.sh`)
- **Health:** `curl -s http://127.0.0.1:8090/health`
- **API:** `/v1/systemone (fixed question: state = OCR text, images = [original, rendered]; choice or noul)`
- **Owner:** `unowned` · **Used by:** kem-ocr
- **Weights:** `models/openbmb/MiniCPM-OCR-Jev-gguf/MiniCPM-OCR-Jev-Q6_K.gguf` · `models/openbmb/MiniCPM-OCR-Jev-gguf/mmproj-model-f16.gguf`
- **Quirks:** Reuses :8090, freed when JPT-4B was archived. Not a general decision engine: the question is baked into the model, so this slot cannot answer the jev-decision query types - :8083 remains the decision API. No skill drives this slot yet - call it directly or add it to a consumer. 2B Qwen3.5-VL trunk with a 2-class value head read at the pooled last token; no LM head, text generation is rejected. vision projector attached

### `:8091` llm-rp — `local-rp-lfm3`

- **Role:** Secondary generative LLM — uncensored roleplay and short-form creative, runs beside the primary :8080 slot instead of swapping it out
- **Service:** llama-server (Vulkan)
- **Start:** `lfm3-1.7b-uncensored.sh` (volume `sh/`; in-repo copy `launchers/lfm3-1.7b-uncensored.sh`)
- **Health:** `curl -s http://127.0.0.1:8091/health`
- **API:** `/v1/chat/completions`
- **Owner:** `unowned` · **Used by:** —
- **Weights:** `models/AtomicChat/LFM3-1.7B-Uncensored-GGUF/LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf`
- **Quirks:** No skill drives this slot; call it directly. The launcher honours PORT=, but any other port needs a manifest slot first or ports.py check fails. LiquidAI LFM3 1.7B, uncensored AD tune, RP workload.
<!-- ports:end -->
