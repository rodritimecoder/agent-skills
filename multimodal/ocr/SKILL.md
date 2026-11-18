---
name: ocr

description: >
  LightOnOCR-3-0.8B OCR hub on :8082: transcribe documents, PDFs, slides,
  screenshots and scans into Markdown, with optional grounding that returns typed
  blocks, 0-1000 boxes, figure crops and chart tables. Use to read text out of an
  image, screenshot or scanned page, to OCR a PDF or slide deck, or to pull
  figures out of a page. This is the only OCR engine on the machine. To locate a
  described object rather than read its text, use `jev box`; to coordinate a PDF
  conversion pipeline, use doc-layout.

compatibility: "Requires an AMD Radeon RX 9060 XT GPU with Vulkan and the LightOnOCR-3-0.8B server on :8082."
allowed-tools: "Bash(ocr:*) Bash(python3:*) Read Write"
---

> **Model layer:** the server behind this skill is registered in the `model-layer` skill (slot `:8082`) — launcher, weights files, health and quirks. Read it before starting or debugging the model. If `:8082` is down, `ensure_lighton` starts it via `llama-rig up ocr`.

# `ocr` — LightOnOCR Document Hub

Everything goes through one engine: **LightOnOCR-3-0.8B** on **`:8082`**. It is a
0.8B vision-language model that transcribes a page in about two seconds, and in
grounding mode also reports where each block sits and what it is.

---

## 🛠️ Deterministic CLI Quickstart

The canonical executable is located at `~/.local/bin/ocr` (and `~/.local/bin/ocr-cli`, symlinked from `multimodal/ocr/ocr.py`).

### 1. Document & Slide OCR (grounding by default)

```bash
# Notes with figures: typed blocks, 0-1000 boxes, image descriptions, chart tables
ocr read page.png --assets notes/assets -o notes/page.md
# → notes/page.md  (# heading, paragraphs, inline math, *Figure captions*)
# → notes/assets/fig1.png, fig2.png …   (tight crop of each image region)

# Same, without exporting crops
ocr read page.png --json

# A PDF: one request per page, pages merged with HTML comments
ocr read report.pdf --pages 1-5 -o report.md

# Plain transcription only (no layout, flat Markdown)
ocr slide.png --transcribe > slide.md
```

### 2. Server Daemon & Doctor

```bash
# Check the engine, weights and port
ocr doctor [--json]

# Manage the background daemon
ocr server status
ocr server start --engine lighton
ocr server restart
ocr server stop
```

---

## 🏛️ Architecture & Endpoints

| Capability | Engine | Port | Format | Specialty |
|---|---|---|---|---|
| **Document / PDF / Scan** | **LightOnOCR-3-0.8B** | `:8082` | Flat Markdown | high-throughput transcription |
| **Document + figures** | **LightOnOCR-3 grounding** | `:8082` | Typed blocks + box crops + descriptions | best text on Fraktur/multilingual |

### LightOn runtime facts

- Launcher: `sh/lighton-ocr.sh` starts `llama-server` with the GGUF and mmproj
  (`--reasoning off`, so output lands in `content`); `llama-rig up ocr` is the
  managed path and the one `ocr server start` uses when the rig is installed.
- Weights: `models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/`
  (`LightOnOCR-3-0.8B.Q4_K_M.gguf` + `LightOnOCR-3-0.8B.mmproj-q8_0.gguf`).
- Endpoint: OpenAI-compatible `POST /v1/chat/completions` with base64 image parts;
  health is `GET /health`.
- The prompt is *not* a server option — llama-server applies the chat template,
  and the client sends the prompt text. That client is this skill
  (`modules/ocr_engine.py`), which is the llama.cpp equivalent of the HF card's
  `if prompt:` branch: image + `grounding` when grounded, prompt + image
  otherwise. The launcher exports `OCR_LIGHTON_PROMPT=grounding` as the machine
  default and `--transcribe` overrides it per call.

LightOnOCR-3 has exactly two supported prompts and nothing else: an empty prompt
(transcription) and the literal string `grounding`. Grounding labels: `title`, `text`,
`list`, `header`, `footer`, `page_number`, `footnote`, `caption`, `formula`, `code`,
`table`, `image`, `chart`, `header_image`, `footer_image`, `aside_text`; `image`/`chart`
blocks also carry a description or an HTML data table.

### Removed engines

OXR-1.0 and CrispEmbed were removed on 2026-11-08. The OXR weights are deleted and
`ENGINE=oxr sh/crispembed-ocr.sh` now exits 1; the `/oxr/document` route and the
`spatial`/`--boxes` scene-text mode are gone with them. There is no fallback
engine: if `:8082` is down, start it.
