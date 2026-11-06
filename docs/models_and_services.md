# Autonomous Workstation Model Directory & Rankings

Synthesized from local GPU inference configs, launchers, benchmarks, and agent conversation transcripts.

---

## 🏛️ Local Inference Ports

<!-- ports:begin -->
| Port | Slot | Cardinality | Default model | Launcher | Role |
|---|---|---|---|---|---|
| `:8080` | `llm` | many (13) | Qwen3.6-35B-A3B-Uncensored-Genesis-Final | `luffy_nothink.sh` | Primary generative LLM — chat, code, long-form writing, prose projection |
| `:8081` | `audio` | many (3) | nemotron-asr | `run-audiocpp.sh` | Speech-to-text, text-to-speech, forced alignment, voice cloning |
| `:8083` | `decision` | one-of-many (6) | h2o-lightning-4b | `h2o.sh` | The decision engine slot - bool / choice / score primitives |
| `:8082` | `decision-engine` | single (1) | StartLux-Decision-v1.1-4B-Instant | `startlux-decision.sh` | Experimental StartLux backend; not the h2o-lightning-4b JEV endpoint |
| `:8089` | `decision-fallback` | single (1) | Imajev-4B | `imajev-decider.sh` | Secondary decision engine — Imajev-4B chat path, or letter/readout with READOUT=1 |
| `:8084` | `ocr-crispembed` | single (1) | CrispEmbed (PP-OCRv6 small: DB++ det + CTC rec) | `crispembed-ocr.sh` | Documents & scene text — OXR-1.0 layout-aware Markdown, PP-OCRv6 bounding boxes |
| `:8085` | `ocr-lighton` | single (1) | LightOnOCR-3-0.8B | `lighton-ocr.sh` | Documents, PDFs and slides — fast prefill, high-throughput markdown |
| `:8086` | `reranker` | single (1) | jina-reranker-v2-base-multilingual | `jina-reranker.sh` | Cross-encoder reranking for RAG |
| `:8087` | `embed` | one-of-many (2) | bge-small-en-v1.5 | `bge-small.sh` | Vector embeddings for RAG and semantic caching |
| `:8088` | `grounding` | single (1) | WeVisOne-VL-4B | `wevisone-vl.sh` | Word-level OCR boxes, open-vocab detection, referring localization, pointing, counting |
| `:8090` | `ocr-jev` | single (1) | MiniCPM-OCR-Jev | `minicpm-ocr-jev.sh` | OCR consistency gate — scores a candidate transcription against the source image in one forward pass |
| `:8091` | `llm-rp` | single (1) | LFM3-1.7B-Uncensored-AD | `lfm3-1.7b-uncensored.sh` | Secondary generative LLM — uncensored roleplay and short-form creative, runs beside the primary :8080 slot instead of swapping it out |

| Port | Infra | Service | Role |
|---|---|---|---|
| `:8000` | `llama-swap` | llama-swap | Model multiplexer; swaps models in/out of VRAM |
| `:3010` | `kasmvnc` | KasmVNC (podman) | Live interactive web desktop for browser inspection |
| `:9222` | `cdp` | Chromium DevTools | CDP endpoint used by fast-cdp and Playwright |
| `:9224` | `cdp-desktop` | Chromium DevTools (headed agent profile) | Headed Chromium CDP endpoint so a person can see and drive the automated page |
| `:9223` | `cdp-internal` | labwc forwarder | Container-internal forwarder 0.0.0.0:9222 -> 127.0.0.1:9223 |
| `:8761` | `clip-box` | h2o-lightning shim | Standalone h2o shim: box grounding and typed decisions when another model occupies the decision slot |
| `:8621` | `clip-box-backend` | llama-server (private backend) | Pinned stock llama.cpp the h2o-lightning shim drives; one full-context slot, loopback only |
<!-- ports:end -->

---

## 🏆 Model Rankings by Task

### 1. Optical Character Recognition (OCR) & Document Understanding
1. **`LightOnOCR-3-1B` (and `LightOnOCR-3-4B`)** — **#1 Champion**
   - **Why**: Extreme inference throughput (~16,000 t/s prefill, ~330 t/s generation) on dual-GPU Vulkan setup. Flawless on video keyframe extraction, presentation slides, dense code blocks, and terminal recordings.
2. **`SmolDocling-256M` (`cstr/smoldocling-GGUF`)** — **#2 Document & Layout Specialist**
   - **Why**: Ultra-compact 256M model (SigLIP ViT + SmolLM2) running locally. Rather than flat text, generates structured **DocTags** XML markup capturing full page hierarchy, data tables, mathematical formulas, code blocks, and layout bounding boxes.
3. **`CrispEmbed Suite` (`cstr/` GGUF models: DBNet-IC15 + TrOCR / PP-OCRv6 / PARSeq / GLM-OCR)** — **#3 Scene-Text & Crops**
   - **Why**: Ultra-lightweight CPU/GPU graph pipelines (DBNet detector at 13 MB, PP-OCRv6 at 5 MB, PARSeq at 25 MB). Ideal for line crops, scene photos, and noisy screenshots.
4. **Additional / Specialized Models in `/run/media/rodri/AI/models/`**:
   - `Xiaomi-OCR-0`: High accuracy alternative vision-language OCR.
   - `OvisOCR2` (`Abiray/OvisOCR2-GGUF`): High-fidelity ROCmFPX/BF16 VLM.
   - `Trocr-small-printed` (`cstr/`): Fast printed line OCR.

### 2. Calibrated Decision & Gating Models
1. **`h2o-lightning-4b` (`:8083`)** — the JEV decision model
   - **Native Decision API**: `jev-decision` sends typed bool, choice and score requests through `/v1/systemone`; it verifies the served model ID before sending and will not use another local JEV model.
   - **Vision**: `mmproj-lightning-f16` is loaded alongside the model, so every primitive accepts images for screenshot gating, diagram checks and visual UAT.
   - **Not a chat model**: it emits typed decisions, not prose. Free-form projection belongs to the generative LLM on `:8080` (see the `local-llm` skill).
   - **Legacy candidates**: vllm-d3 and pplx-decider checkpoints remain documented for historical benchmarks only; they are not JEV targets. `Imajev-4B` on `:8089` remains a separate A/B endpoint.

### 3. Desktop GUI & Browser Grounding
- **Archived (`:8088`)**: `DeskForge-Qwen3.5-4B` was the visual grounding fallback for `hybrid-browser`. It is no longer a live slot — see **Archived Slots** below. The weights remain on disk and the code path is preserved behind `HYBRID_BROWSER_VISION=1`.
- **Alternative**: `DeskForge-Gemma4-E4B` (`mradermacher/`).

### 4. Speech-to-Text & Voice Synthesis
- **ASR**: `Nemotron-3.5-ASR-Streaming-0.6B` on `:8081` (RNNT architecture, 40 languages, streaming dictation).
- **TTS**: `Kokoro-82m` on `:8081` (instant local TTS) + `Omnivoice` / `Index-TTS-2.5` for multi-speaker synthesis.
- **Word Timestamps**: `Qwen3-Forced-Aligner-0.6B` (66× realtime forced alignment).

---

## 🗄️ Archived Slots

Slots are retired in `ports.json` (the `retired` list) rather than deleted, so
the decision, its evidence and the route back are all recorded. `ports.py check`
fails if a retired launcher reappears outside `launchers/archived/`.

| Port | Model | Why it was retired | To restore |
|---|---|---|---|
| `:8088` | `DeskForge-Qwen3.5-4B` | Selector-based automation strictly dominates visual grounding wherever the DOM exposes a selector: exact text, single-digit-millisecond locators, no 4.3 GB resident model, no sampling. The fallback only earns its keep on `<canvas>`/WebGL, closed shadow roots and text baked into images — which was not the workload. | Re-add the slot to `ports.json`, move `launchers/archived/deskforge-qwen.sh` back, then run `ports.py render --write`. Weights are still on disk (`Q4_K_M` 2.58 GB + `mmproj` bf16 644 MB). Until then `hybrid-browser` uses it only under `HYBRID_BROWSER_VISION=1`. |
| `:8082` | `NaviDC-OCR` | Outperformed by LightOnOCR-3-1B (`:8085`) on every measured case: dense digital page F1 0.970 vs 0.953, cleaner layout on a scanned form, and handwritten dense math (5.7 s clean stop vs 14.7 s of dash filler hitting the token cap). It had no server consumers either — the `ocr` skill routes to `:8085`/`:8084`, and `zoom-recorder` called `llama-mtmd-cli` directly. | Re-add the slot, move `launchers/archived/navidc-ocr.sh` back, render. Weights are still at `models/nandraj/NaviDC-OCR-GGUF` (4.2 GB). |
| `:8090` | `JPT-4B` | Decision engines consolidated onto the H2O JEV endpoint at `:8083`; `:8089` remains a separate Imajev A/B endpoint. | Not planned; `/v1/systemone` on `:8083` is the JEV decision API. |
| — | `Jev-Style-Qwen3.5-2B-Decision` | Same consolidation. It had been squatting on the single-model LightOnOCR slot at `:8085`. | Not planned. |

### The rule this encodes

Before adding an inference slot, ask whether a deterministic tool already does
the job. A vision model over a rendered page is strictly worse than reading the
DOM when a selector exists; OCR of a screenshot is strictly worse than the text
layer when the PDF has one. Models are the answer to "there is no other way in",
not to "this would be convenient".
