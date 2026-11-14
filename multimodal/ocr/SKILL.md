---
name: ocr

description: >
  Unified OCR hub on dual AMD Radeon GPUs: OXR-1.0 (:8084) parses full documents,
  PDFs and scans into layout-aware Markdown/JSON with tables, formulas and reading
  order; LightOnOCR-3-0.8B (:8085) transcribes slides and screenshots fast;
  CrispEmbed (:8084) returns 2D spatial coordinates and text tokens for scene text
  and UI elements. Use to read text out of an image, screenshot or scanned page, to
  OCR a PDF or slide deck, or to get bounding boxes for words on screen. To locate a
  described object rather than read its text, use clip-box; to verify an OCR result
  against its source, use kem-ocr.

compatibility: "Requires Dual AMD Radeon RX 9060 XT GPUs with Vulkan, plus the OXR/CrispEmbed server on :8084 and LightOnOCR on :8085."
allowed-tools: "Bash(ocr:*) Bash(python3:*) Read Write"
---

> **Model layer:** the server behind this skill is registered in the `model-layer` skill (slot `:8084 + :8085`) — launcher, weights files, health and quirks. Read it before starting, swapping or debugging the model. If `:8085` is down, `ensure_lighton` starts it via `vram-rig-ctl up ocr`.

# `ocr` — Unified Premier OCR Hub

A unified, hardware-accelerated OCR toolchain on **Dual AMD Radeon RX 9060 XT** GPUs, combining:
1. **OXR-1.0 (Document Parser, `:8084`)**: 1.3B SoMark parser — D-FINE layout detection, per-region recognition with the right prompt (text/formula/table/code), reading order, and assembled Markdown or JSON. SOTA on olmOCR-Bench/OmniDocBench.
2. **LightOnOCR-3-0.8B (Speed Engine, `:8085`)**: fast slide, screenshot and short-page transcription into flat Markdown.
3. **CrispEmbed (Spatial Engine, `:8084`)**: PP-OCRv6 DB++ / DBNet for detecting 2D spatial coordinates `[x1, y1, x2, y2]`, text tokens, and UI button locations.

---

## 🛠️ Deterministic CLI Quickstart

The canonical executable is located at `~/.local/bin/ocr` (and `~/.local/bin/ocr-cli`, symlinked from `/run/media/rodri/AI/skills/ocr/ocr.py`).

### 1. Layout-Aware Document Parsing (OXR-1.0)
```bash
# Full page or PDF → Markdown with headings, tables (HTML) and formulas
ocr read page.png --engine oxr -o page.md
ocr read report.pdf --pages 1-5 --engine oxr -o report.md

# Textbook/lecture pages: extract figures as PNG crops and link them from the notes
ocr read page.png --engine oxr --assets notes/assets -o notes/page.md
# → notes/page.md  (# heading, paragraphs, inline math, *Figure captions*)
# → notes/assets/fig1.png, fig2.png …   (tight crop of each Picture region)

# Typed JSON: per-page blocks with type + bbox + content, plus timings and asset list
ocr read page.png --engine oxr --assets notes/assets --json

# The default `--engine auto` uses OXR when the parser is already loaded,
# otherwise it falls back to LightOnOCR without loading a 1.9 GB model.
```

The `--assets` pass also cleans two upstream layout artefacts: `Text` blocks that sit inside a detected `Table`/`Picture` (already captured there) are dropped, and a figure box that merely frames a tighter crop of the same drawing is collapsed to the tighter crop.

### 2. Document & Slide OCR (LightOnOCR-3-0.8B, grounding by default)
```bash
# Notes with figures: typed blocks, 0-1000 boxes, image descriptions, chart tables
ocr read page.png --engine lighton --assets notes/assets -o notes/page.md

# Same, without exporting crops
ocr read page.png --engine lighton --json

# Plain transcription only (no layout, flat Markdown)
ocr slide.png --transcribe > slide.md
```

LightOnOCR-3 has exactly two supported prompts and nothing else: an empty prompt
(transcription) and the literal string `grounding`. Grounding labels: `title`, `text`,
`list`, `header`, `footer`, `page_number`, `footnote`, `caption`, `formula`, `code`,
`table`, `image`, `chart`, `header_image`, `footer_image`, `aside_text`; `image`/`chart`
blocks also carry a description or an HTML data table.

**Runtime split (sh + py):** `sh/lighton-ocr.sh` starts `llama-server` with the GGUF and
mmproj (`--reasoning off`, so output lands in `content`). The prompt is *not* a server
option — llama-server applies the chat template, and the client sends the prompt text.
That client is this skill (`scripts/ocr_engine.py`), which is the llama.cpp equivalent of
the HF card's `if prompt:` branch: image + `grounding` when grounded, prompt + image
otherwise. The launcher exports `OCR_LIGHTON_PROMPT=grounding` as the machine default and
`--transcribe` overrides it per call.

### 3. Spatial Scene-Text & Bounding Boxes (CrispEmbed)
```bash
# Extract 2D bounding boxes and coordinates
ocr screenshot.png --boxes

# Output:
# 📍 [455.4, 340.7, 1123.3, 388.6] (94.5%) -> Confirm Order
# 📍 [120.0, 45.0, 210.0, 85.0] (98.2%) -> Cancel

# Output machine-readable spatial JSON (--json)
ocr spatial screenshot.png --json
# Output:
# {
#   "task": "spatial_ocr",
#   "engine": "crispembed",
#   "image": "/path/to/screenshot.png",
#   "n_regions": 2,
#   "results": [
#     {
#       "text": "Confirm Order",
#       "bbox": [455.4, 340.7, 1123.3, 388.6],
#       "confidence": 0.9449
#     }
#   ],
#   "latency_ms": 120.4
# }
```

### 4. Server Daemons & Doctor
```bash
# Check status of every engine
ocr doctor [--json]

# Manage background daemons
ocr server status
ocr server start --engine oxr        # OXR-1.0 document parser on :8084
ocr server start --engine lighton
ocr server stop --engine all
```

---

## 🏛️ Architecture & Endpoints

| Capability | Engine | Port | Format | Specialty |
|---|---|---|---|---|
| **Document / PDF / Scan** | **OXR-1.0** (`--engine oxr`) | `:8084` | Layout-aware Markdown + block JSON | tables, formulas, reading order; strongest on clean print/receipts |
| **Document + figures** | **LightOnOCR-3 grounding** (`--engine lighton --assets`) | `:8085` | Typed blocks + box crops + descriptions | 1.1 GB, ~2 s/page, best text on Fraktur/multilingual |
| **Slide / Screenshot** | **LightOnOCR-3-0.8B** | `:8085` | Flat Markdown | high-throughput transcription |
| **Spatial Scene Text / UI** | **CrispEmbed (PP-OCRv6)** | `:8084` | 2D Bounding Boxes `[x1, y1, x2, y2]` | sub-second spatial UI detection for `frontend-uat` |

### OXR runtime facts

- Launcher: `ENGINE=oxr sh/crispembed-ocr.sh`; `OXR_DEVICE=cpu` for the exact CPU arm.
- Vulkan must use the native flash-attention kernel (`CRISPEMBED_OXR_GPU_FLASH=1`, set by the launcher). RADV's dense F32 attention decodes garbage.
- Weights: default `models/cstr/OXR-1.0-GGUF/oxr-1.0-q4_k-head.gguf` (1.9 GB, ~35% faster and 2 GB less VRAM than F16 at the same measured CER; `OXR_MODEL=…/oxr-1.0-f16.gguf` for the token-exact arm) + `models/cstr/OXR-1.0-DFINE-layout-GGUF/oxr-1.0-dfine-layout-f32.gguf` (layout, always CPU by default).
- Measured on the repo's CC0 ground truth: OXR recognition is byte-exact on clean print/receipts (CER 0.000 on the receipt, 0.0007 on the 3k-char multi-column page) but loses to LightOnOCR on Fraktur (long-s transliteration) and Japanese. The native **document route** is upstream-experimental: on synthetic receipts it emits `Text` rows nested inside the `Table` region (duplicated content), and on small forms it can reduce the page to one image placeholder — verify structure before trusting it.
- License: OXR License (Apache-2.0 + terms) — commercial use above USD 2M needs a SoMark license; online services must credit SoMark OXR; no competing hosted OCR API.
- Route: `POST /oxr/document {"images": [paths], "format": "upstream"}` → `outputs.markdown` / `outputs.json`.
