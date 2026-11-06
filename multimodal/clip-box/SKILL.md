---
name: clip-box
description: >
  Locate a thing in an image. Ask h2oai/h2o-lightning-4b for a bounding box around a
  referring phrase ("the total amount", "the red square", "the coffee mug") and get
  fractions of the image, pixel coordinates, a calibrated confidence (P(IoU >= 0.5))
  and a `present` probability that gates the answer. Use it for "where is X in this
  screenshot/receipt/photo", to crop a region before OCR, or to check that something
  is actually in the frame. Delegates to `decision-model box`; no cloud, no OCR.
compatibility: "Requires the decision-model skill (which owns the client and the h2o-serve launcher) and its h2o-lightning shim with the pinned llama.cpp backend, plus ~6 GB of weights in the cache. CPU always works; --backend vulkan needs a free GPU."
allowed-tools: "Bash(python3:*) Bash(h2o-serve:*) Bash(clip-box:*) Bash(decision-model:*) Read Write"
---

# `clip-box` — where is it in this image?

This is the **"where is X"** front door. The implementation lives in
`decision-model`: the same client answers `bool`, `choice`, `score` and `box`,
and `clip-box` is a thin entry point that keeps this vocabulary routable and
can point at a standalone shim when another model occupies the decision slot.

```bash
clip-box --image scene.png --target "the red square"          # slot shim on :8083
clip-box --image scene.png --target "the red square" --port 8761   # standalone shim
decision-model box --image scene.png --target "the red square"     # same thing
```

h2o-lightning is a 4B **decision** model: it answers typed questions with
probabilities and never generates prose. Its `box` question returns a rectangle
instead of a label, and three numbers that matter more than the rectangle:

| field | meaning |
|---|---|
| `box` | `left`, `top`, `right`, `bottom` as fractions of the image, from the top-left |
| `confidence` | P(IoU ≥ 0.5) — a decision readout on the image **with the box drawn on it**, not a number the model narrates |
| `present` | P(the target is visible at all) — a separate readout on the untouched image |
| `found` | whether any box was produced; a miss returns the whole image with confidence 0 |

**Gate on `present`, not on `found`.** Asked for a blue bicycle in a scene that
has none, the model returns a confident-looking box around something else with
`found: true` and `present: 0.111`. `present` is what says no.

## Usage

```bash
# start the API (box questions are on; the slot front port is :8083)
h2o-serve --port 8083          # CPU, Q8_0
h2o-serve --backend vulkan     # AMD GPUs: builds the pinned Vulkan backend once
h2o-serve --status
h2o-serve --stop

# ask
clip-box --image scene.png --target "the red square"
# ACCEPT  box=(0.247, 0.247) -> (0.753, 0.753)  confidence=0.651  present=0.885

clip-box --image scene.png --target "the blue bicycle"   # absent -> exits 2
clip-box --image receipt.png --target "the total amount" # confidence 0.163 < 0.30 -> rejected
clip-box --image scene.png --target "the red square" --json --crop /tmp/square.png
```

`--json` returns `accepted`, `reason`, `box`, `pixels` (computed from the real
image size), `confidence`, `present`, `found` and the `model` that answered.
Exit code 0 accepts, 2 rejects, 1 is a request error.

`--min-present` (default 0.5) and `--min-confidence` (default 0.30) set the
gates; both are also environment variables (`BOX_MIN_PRESENT`,
`BOX_MIN_CONFIDENCE`). `--crop` writes the accepted box; it needs Pillow.

## Capability, not assumption

`box` is a **shim** feature, not a protocol feature: llama.cpp's own
`/v1/systemone` accepts `choice`, `score` and `noul` only. The decision slot
rotates between five candidates, so:

```bash
decision-model caps
# model       /models/h2o-lightning-4b-Q4_K_M.gguf
# slot        :8083  (box on :8083)
# primitives  bool, choice, score, box
```

If the occupant is not h2o, `caps` lists no `box` and `box` refuses with the
served model named — instead of posting a question that endpoint cannot answer.

## What it is actually good at

Measured on this workstation (Q8_0, CPU backend), synthetic scenes with known truth:

| target | IoU | confidence | present |
|---|---:|---:|---:|
| red square, 512×512 centred | 0.976 | 0.651 | 0.885 |
| red rectangle, 512×1024 tall | 0.877 | 0.669 | 0.897 |
| red rectangle, 1024×512 wide | 0.848 | 0.722 | 0.895 |
| small red square in a cluttered scene | 0.603 | 0.359 | 0.896 |
| "the blue bicycle" (absent) | — | 0.188 | **0.111** |
| "the total amount" on a receipt | miss (box below the total) | 0.144 | 0.899 |

Salient objects, icons, shapes, single images: good, aspect ratio handled
correctly. Dense small text on a receipt: it misses, and its low confidence says
so. For a value on a receipt, crop with the total's neighbourhood or use the
decision API's `choice` question ("what is the TOTAL? subtotal/total/tax"), which
scored correctly on the same image.

## The trap this skill exists to absorb

**Pillow.** The shim draws the box before the tightness readout and returns
`None` on `ImportError`, so a Python without Pillow answers every box with
`confidence: 0.0`. `h2o-serve` builds its own venv and checks the import.

## Files

| path | role |
|---|---|
| `scripts/clip_box.py` | entry point — lifts `--port`/`--host`, delegates to `decision-model box` |
| `../hardware/decision-model/scripts/decision_model.py` | the client: one box question, two gates, crop, exit codes |
| `../hardware/decision-model/scripts/h2o_serve.py` | the launcher: pinned bootstrap by hash, Pillow-safe venv, CPU/CUDA/Vulkan backend, `--status`, `--stop` |

State lives in `~/.cache/h2o_lightning_gguf` (weights + pinned backend) and
`~/.local/share/h2o-lightning/venv`. Nothing outside those two paths is touched.

## Protocol notes

- The shim's `box.mode` is `generate` here: one constrained generation in Qwen's
  `bbox_2d` convention (0–1000, x first), parsed and clamped. `edges`/`hybrid`
  need a model trained on edge readouts; keep `generate` with this release.
- `confidence` is a probability with its own temperature, `1.0` until fitted, so
  it is conservative: a near-perfect box on a big square reads 0.65, not 0.95.
- One image per request by default; the shim accepts up to 8 with `images:` and
  the backend is started with `--image-max-tokens 1024`.
- The decision side of the same server answers `choice` / `noul` / `score` on
  text and images at `/v1/systemone`; for calibrated decisions on text, prefer
  `pplx-decider` (Decision Index 60.06 vs 51.38 here). Use this model for
  geometry, not for routing.
