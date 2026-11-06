# Workstation Hardware & Local Inference Matrix

Hardware Topology, Dual GPU VRAM Budget, and Local Serving Endpoints.

---

## 1. Hardware Substrate Overview

- **CPU**: AMD Ryzen Processor (16 Threads: 4 Host Reserved, 12 Worker Dedicated)
- **Primary GPUs**: Dual AMD Radeon RX 9060 XT (32 GB Combined VRAM)
- **Acceleration Drivers**: ROCm (Primary FP4/FP8 compute) + Vulkan (DeskForge visual GUI grounding)
- **Local Proxy Gateway**: llama-swap (`:8000`)

---

## 2. Port-by-Port Local Services Registry

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

## 3. Dual GPU VRAM Allocation Policy

To prevent Out-Of-Memory (OOM) crashes while running heavy local coder models, the workstation enforces a **20 GB Primary Floor + Dynamic Auxiliary Headroom** invariant:

```
[ GPU 0: 16 GB ]                       [ GPU 1: 16 GB ]
┌──────────────────────────────┐       ┌──────────────────────────────┐
│  Genesis 35B Slice 1 (9 GB)  │       │  Genesis 35B Slice 2 (11 GB) │
├──────────────────────────────┤       ├──────────────────────────────┤
│  LightOnOCR-3-0.8B (0.7 GB)    │       │  h2o-lightning-4b (3.2 GB)  │
├──────────────────────────────┤       ├──────────────────────────────┤
│  audio.cpp Nemotron (1.8 GB) │       │  bge-small Embeddings (0.5GB)│
├──────────────────────────────┤       ├──────────────────────────────┤
│  VRAM Buffer (2.0 GB Headroom)       │  DeskForge Vulkan (1.0 GB)   │
└──────────────────────────────┘       └──────────────────────────────┘
```

1. **20 GB Primary Reserved**: Genesis 35B (`:8080`, Q4_K_M) remains permanently resident across both GPUs.
2. **Auxiliary Services Headroom**: Auxiliary models (OCR, Decision, STT, Embeddings) consume $\le$ 7.5 GB combined across remaining memory.
3. **Dynamic Swap via `:8000`**: If a heavy compile or vision task requires extra memory, `vram-rig-ctl swap` unloads inactive auxiliary instances automatically.

---

## 4. Workstation Health & Verification Command

To check the operational status of all local ports and services:
```bash
# Check all inference endpoints
vram-rig-ctl status

# Or check dual GPU VRAM utilization via ROCm
rocm-smi
```
