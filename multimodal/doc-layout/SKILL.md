---
name: doc-layout

description: >
  Layout-aware document parsing: PP-DocLayoutV3 detects all 25 region types
  (text, titles, formulas, tables, images) with boxes, polygon outlines and
  reading order; each region is cropped and OCR'd by a VLM; output is
  normalized Markdown. Uses a torch-free ONNX layout model plus any
  llama.cpp / OpenAI-compatible vision endpoint. Use when a page, PDF or
  screenshot must become structured Markdown, when figures must be extracted
  as separate assets, when tables/formulas need type-aware handling, or when
  multi-column layout breaks whole-page OCR.

compatibility: "Requires the PP-DocLayoutV3 ONNX model (Bei0001 export) and an OpenAI-compatible vision endpoint passed with --vlm (e.g. LightOnOCR on :8085, or an ad-hoc MiniCPM-OCR llama-server). No torch, no PaddlePaddle."
allowed-tools: "Bash(doc-layout:*) Bash(python3:*) Read Write"
---

> **Model layer:** the server behind this skill is registered in the `model-layer` skill (slot `:8085`) — launcher, weights files, health and quirks. Read it before starting, swapping or debugging the model. Down? `vram-rig-ctl up ocr`.

# `doc-layout` — PP-DocLayoutV3 → crops → VLM → Markdown

A layout-first document parser. The layout model segments the page; the VLM
reads each crop with a type-appropriate prompt; the assembler renders the
official Markdown conventions.

```
layout (PP-DocLayoutV3) -> crop -> prompt-by-class -> VLM -> assemble -> .md
      [D]                   [D]         [D]           [P]       [D]
```

The VLM never controls the layout model. Control flows `CLI -> {layout, VLM}`;
both are stateless services. This mirrors OpenBMB's `minicpmvocr` SDK, which
runs PP-DocLayoutV3 first and then posts crops to a separate inference service.

## Why layout-first

Whole-page OCR fails when columns, figures and formulas interleave. Layout
detection gives each region an identity and an order, so:

- text is read as text, formulas as LaTeX, tables as HTML;
- figures are kept as image references instead of being OCR'd into noise;
- reading order survives two-column and side-figure pages.

## Quickstart

```bash
# Health: model present, VLM reachable
doc-layout doctor --vlm http://127.0.0.1:8085

# Detect regions only (JSON: boxes, quads, order, labels)  [no VLM needed]
doc-layout layout page.png --json regions.json

# Crop every region                                        [no VLM needed]
doc-layout crops page.png -o crops/

# Full parse to Markdown
doc-layout parse page.png -o page.md --vlm http://127.0.0.1:8085

# Multi-page PDF (pages rendered at --dpi, default 200)
doc-layout parse paper.pdf -o paper.md --vlm http://127.0.0.1:8085 --pages 1-5

# Multi-page PDF with layout/OCR overlap (layout page N+1 while OCRing page N)
doc-layout parse paper.pdf -o paper.md --vlm http://127.0.0.1:8085 --overlap

# One-model engine: whole page in a single call (LightOnOCR-3-0.8B)
doc-layout parse page.png --engine lighton -o page.md --vlm http://127.0.0.1:8085
doc-layout parse page.png --engine lighton --grounding --embed-images \
    -o page.md --vlm http://127.0.0.1:8085

# See it rendered: images in place, LaTeX typeset, no CDN needed
doc-layout render paper.md -o paper.html

# Figures only (extract the diagrams, skip OCR)
doc-layout layout page.png --images-only --json figures.json
```

## Commands

| command | purpose |
|---|---|
| `doctor` | check model + VLM endpoint, print JSON status |
| `layout IMAGE` | detect regions; `--json PATH` writes boxes/quads/order/labels, bare `--json` (or `--json -`) prints pure JSON to stdout |
| `crops IMAGE` | detect and crop each region to `-o DIR` |
| `parse IMAGE/PDF` | layout → crop → VLM → Markdown (`-o OUT.md`) |
| `render MD` | Markdown → standalone HTML with typeset math (KaTeX) |

## Options

| flag | meaning |
|---|---|
| `--vlm URL` | **required** for `doctor`/`parse`; OpenAI-compatible vision endpoint |
| `--engine MODE` | `auto` (default, detects from the served model), `layout`, or `lighton` |
| `--grounding` | lighton engine: emit labels + bboxes + figure crops + descriptions |
| `--max-edge N` | PDF: downscale longest edge to N px (default 2048; 0 = off) |
| `--model NAME` | served model id (default `minicpm-ocr`) |
| `--layout-model PATH` | PP-DocLayoutV3 `.onnx` (default: the Bei0001 export) |
| `--thr F` | detection score threshold (default 0.4) |
| `--iou F` | NMS IoU (default 0.45) |
| `--order MODE` | `xcut` (column-aware, default) or `y` (row-major) |
| `--images-only` | keep only `image`-class regions |
| `--keep-ignored` | keep footer/header/number regions in Markdown (default dropped) |
| `--pages RANGE` | PDF only: `1-5`, `3`, `1,3,5` (default all) |
| `--overlap` | PDF only: overlap layout (CPU) with OCR (GPU) across pages |
| `--buffers N` | pages buffered ahead under `--overlap` (default 2) |
| `--dpi N` | PDF render DPI (default 400, per LightOnOCR's spec) |
| `--max-tokens N` | per-region output cap override |

## Output conventions (ported from OpenBMB `prompts.py` / `markdown.py`)

Prompt by class:

| class | prompt | format |
|---|---|---|
| text, titles, header/footer/footnote, number, reference, algorithm | `Text Recognition:` | text |
| `display_formula` | `Formula Recognition:` | LaTeX |
| `table` | `Table Recognition:` | HTML |
| `chart` | `Chart to Table:` | HTML |
| `seal` | `Seal Recognition:` | text |
| `image`, `header_image`, `footer_image` | — (no VLM call) | `![image]()` |

Markdown assembly:

- dropped by default: `number`, `footnote`, `header`, `header_image`, `footer`, `footer_image`, `aside_text`
- `doc_title` → `# …`, `paragraph_title` → `## …`, `figure_title` → `*…*`
- `display_formula` → `$$ … $$`, `inline_formula` → `$ … $`
- `table` / `chart` → HTML as-is
- `image` → `![image]()` (reference, never OCR'd)

## Engines

**`layout`** (default): PP-DocLayoutV3 segments, each crop is OCR'd with a
per-class prompt. Gives quads, 25 classes, and per-region control; costs one
vision encoding per region.

**`auto`** (default) asks the endpoint what it serves (`/v1/models`, then
`/props`) and picks the engine from the model id: anything matching
`lighton` uses the one-call path, everything else uses `layout`. So
`doc-layout parse page.png --vlm URL` just works with either server.

**`lighton`**: one call for the whole page to LightOnOCR-3. Faster on normal
pages (0.8 s vs 2.9 s on an exercise sheet; 11 s vs 16 s on a 2-column paper)
and it decides reading order itself. Grounding mode adds labels + bboxes +
figure descriptions, and `--embed-images` crops the figures from those bboxes.

- Needs **LightOnOCR-3-0.8B / 4B** (Qwen3.5 arch). The **1B** is the older
  LightOnOCR-2 architecture: its `grounding` prompt is a no-op.
- **`enable_thinking` must be false** or llama.cpp returns empty `content` and
  puts everything in `reasoning_content`. The engine sets this automatically.
- **Transcription mode sends the image with no text part** (the card's
  `if prompt: content.append(...)`). An empty string behaves the same; only
  `grounding` is a recognised instruction, other prompts are out of
  distribution.
- PDFs are rendered at **400 DPI** then downscaled to a **2048** longest edge:
  sharper than rendering at a lower DPI, and fewer vision tokens than leaving
  it at full resolution (measured 5.89 s vs 6.76 s, identical text).

## Ports (do not default onto :8080)

`:8080` is the **primary LLM** (Qwen3.6-35B), not a vision model. `--vlm` is
therefore required rather than defaulted:

| port | service | works here? |
|---|---|---|
| `:8085` | LightOnOCR-3-0.8B (`llama-server`) | yes — OpenAI-compatible |
| ad-hoc | MiniCPM-OCR + DSpark (`llama-server`) | yes — pass its port |
| `:8084` | CrispEmbed (PP-OCRv6) | no — not OpenAI-compatible; use the `ocr` skill |
| `:8080` | primary LLM | no — text-only |

## Notes

- **Reading order is recursive XY-cut.** Vertical whitespace cuts split columns
  (left first), horizontal cuts split bands (top first); full-width headers and
  figures block a vertical cut and force a band split, so 2-column pages come
  out column-by-column. A split is only taken when both sides are similarly
  wide, which keeps a single column with side figures on the row-major path.
  On a real PRL paper this cut right-column interleaving from 17 to 3
  transitions. `--order y` restores plain top-to-bottom.
- **Contained inline formulas are dropped.** A text/figure-caption crop already
  carries its inline math, so an `inline_formula` region sitting ≥80% inside one
  is suppressed (on a real paper: 32 → 6, and parse time 24 s → 8 s).
- **PDFs are rendered page-by-page** (pymupdf) and concatenated with
  `<!-- page N -->` markers and `---` breaks. Cross-page paragraphs are *not*
  merged yet: a sentence split by a page break stays split. Each page's crops
  go to its own `pNNN/` directory so a producer cannot overwrite crops the
  consumer is still reading.
- **`--overlap` runs a layout producer thread (CPU/ONNX) feeding an OCR
  consumer (GPU/VLM).** They use different hardware, so this avoids the GPU
  contention that OCR-vs-OCR concurrency causes on llama.cpp (measured 2.3x
  slower there). The gain is bounded by the layout fraction of a page — ~9%
  on a figure-heavy paper, more on text-heavy pages. This mirrors OpenBMB's
  `pipeline.overlap_layout`, which is also opt-in and defaults to off.
- **OTSL tables are converted to HTML** (`<fcel>`/`<nl>` markup from
  `Chart to Table:` / `Table Recognition:`).
- Layout runs on the ONNX export `Bei0001/PP-DocLayoutV3-ONNX` (4 heads:
  logits / pred_boxes / out_masks / order_logits), so no PaddlePaddle and no
  torch are needed.
- Region crops are padded by 4 px; masks yield polygon outlines when present.
- For quality gating of the VLM reads, pair with `kem-ocr` (Jev verification).
