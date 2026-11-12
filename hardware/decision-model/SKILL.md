---
name: decision-model
description: >
  Calibrated decision and visual grounding engine. Slot :8083 rotates between
  h2o-lightning-4b (4B + mmproj-lightning-f16), Valen-Decision-1.5-0.8B
  (Q5_K_M + vision Q8_0, native bbox head), and Fastino GLiDE-0.4B (ModernBERT
  encoder + separate 255-way readout). Answers typed bool, choice, score, and
  bounding-box queries (normalized 4-corner coordinates with calibrated
  confidence; presence gating where the backend has a presence head) without
  generating open-ended prose. The client names the served model in every result.
compatibility: "Requires a decision server on :8083 answering /v1/systemone (noul | choice | score). h2o-lightning-4b runs behind the h2o-serve shim with its pinned llama.cpp on :8621; Valen-Decision-1.5 runs on its own `valen` runtime (gguf-runtime 0.2.0, CPU) with bbox served natively; GLiDE-0.4B runs behind glide-serve with a private llama.cpp encoder. Set DECISION_REQUIRE_H2O=1 to reject any other slot occupant."
allowed-tools: "Bash(python3:*) Bash(decision-model:*) Bash(h2o-serve:*) Bash(glide-serve:*) Read Write"
---

# Decision Model (`decision-model`)

The workstation's decision and visual perception engine. The slot normally holds **h2o-lightning-4b** (4B) with **`mmproj-lightning-f16`**; **Valen-Decision-1.5-0.8B** is the small CPU alternative with a native bbox head.

A calibrated decision model never generates open-ended prose. It evaluates a context and typed questions, returning probabilities over a closed answer set in sub-second latency. h2o and Valen both understand structured text and visual assets (screenshots, documents, UI elements).

Backend bring-up, acceptance and stop rules: [CONTEXT.md](CONTEXT.md).

---

## ⚡ Primitives & Capabilities

| Primitive | Output | Best Used For |
| :--- | :--- | :--- |
| **`bool`** | `{decision, probability, confidence}` | Gating, branch guards, rule verification, invariant checks |
| **`choice`** | `{selection, probabilities{...}}` | Classification, intent routing, workflow dispatch |
| **`score`** | `{score, probabilities{...}}` | Quality thresholds, urgency, risk on `[0.0, 1.0]` |
| **`box`** | `{box[4], confidence, present?, found}` | **Visual grounding:** 4-corner coordinates (`left`, `top`, `right`, `bottom`) for a target phrase |

### The Visual Box Gates
When requesting bounding boxes via `box`:
- **`present` (P(target is in the frame)):** h2o's primary gate. If `present < 0.5`, reject even if a candidate box is generated. Valen's bbox head has no separate presence output, so the client reports `present: null` and only the confidence gate applies.
- **`confidence` (P(IoU ≥ 0.5)):** Measures box tightness. Reject if `confidence < 0.30`.

---

## 🛠️ Usage

```bash
DM="python3 hardware/decision-model/scripts/decision_model.py"

# 1. Health check
$DM doctor

# 2. Binary decision (Text or with --image)
$DM bool \
  --context "User requested refund after 45 days. Return policy limit is 30 days." \
  --question "Is this refund within policy?"
# Decision: NO | P(true) = 0.0042

# 3. Categorical choice
$DM choice \
  --context "Parallel unit tests must run isolated across 16 CPU cores." \
  --question "Which execution lane?" \
  --options sequential_lane parallel_lane skip_tests

# 4. Scalar score
$DM score \
  --context "All 48 skill tests passing with 0 warnings." \
  --criteria "test suite quality"

# 5. Visual bounding box (4 corners + optional crop)
$DM box \
  --image receipt.png \
  --target "the total amount" \
  --crop /tmp/total_crop.png

# 6. What can this slot actually answer?
$DM caps
# model       /models/h2o-lightning-4b-Q4_K_M.gguf
# slot        :8083  (box on :8083)
# primitives  bool, choice, score, box
```

`box` accepts `--min-present` (default 0.5) and `--min-confidence`
(default 0.30), and refuses when the served model has no box primitive — the
error names the occupant and points at `h2o.sh` / `valen.sh`. `clip-box` is the
same primitive under the "where is X" vocabulary.

---

## 🚀 Server Launchers

### h2o-lightning-4b on the decision slot
```bash
/run/media/rodri/AI/sh/h2o.sh              # :8083, shim + pinned llama.cpp on :8621
/run/media/rodri/AI/sh/decide.sh startlux  # rotate the slot to another candidate
```
`llama.cpp` has no backend for `qwen35.decision.type=h2o-lightning` — a stock `llama-server` rejects this GGUF at load. The decision head and the box readout live in h2oai's shim, so `h2o.sh` drives `h2o-serve` (Python front on `:8083`, pinned Vulkan backend on `:8621`). The shim serves decisions and boxes on the same port, so `BOX_PORT` follows `DECISION_PORT` unless overridden. `h2o-serve` ships in this skill (`scripts/h2o_serve.py`); a standalone front on `:8761` is the fallback when another candidate occupies the slot.

### Valen-Decision-1.5-0.8B on the decision slot
```bash
/run/media/rodri/AI/sh/valen.sh             # :8083, own CPU runtime, native bbox
DECISION_RESTART=1 /run/media/rodri/AI/sh/valen.sh   # take the port from h2o
```
Valen is a custom `valen` architecture (block bidirectional attention, decision mixer, grounding head), so only the runtime that ships with the weights (`gguf-runtime-v0.2.0`, Linux x86-64 CPU) can load it — not the system llama.cpp. One forward pass answers `noul`, `choice`, `score` and `bbox`; output tokens are always 0, so the whole request must fit `-c/-b/-ub` (4096 by default).

- **Weight files:** `/run/media/rodri/AI/models/Valen-Team/` — `Valen-Decision-1.5-0.8B-Q5_K_M.gguf` (569 MB) and `vision-native-limits-Q8_0.gguf` (111 MB), both quantized with the runtime's patched `llama-quantize` from the published F32 files. `src/` keeps the SHA-verified F32 originals for reference.
- **Pairing caveat:** with the default image token budget, small images can shift the box (the grounding head sees a few hundred tokens). `valen.sh` pins `--image-min-tokens 1024`, after which Q5_K_M + Q8 vision tracked F32 within 0.016 on the reviewed shapes, UI links and photos.
- **Bbox answers** are `bbox: [x1,y1,x2,y2]`, `point: [x,y]`, `confidence`, both normalized to image width/height. The client flattens this to the same four corners as h2o so `--crop`, `pixels` and the gates behave identically.
- **Request shape:** images go inline in `state.messages` as `data:image/...;base64,...`; a `bbox` question names its image by zero-based index. The client picks this shape from the served model id (`is_valen`), so `h2o.sh` and `valen.sh` share one CLI.
- **Cost:** ~570 MB text + 111 MB vision on CPU, about 1 s per image request, 0 VRAM.

### GLiDE-0.4B (Fastino) on the decision slot
```bash
/run/media/rodri/AI/sh/glide-decider.sh      # :8083 front, encoder on a private llama.cpp port
/run/media/rodri/AI/sh/decide.sh glide       # rotate the shared slot to it
```
GLiDE is a 0.4B ModernBERT **encoder** plus a separate 255x1024 bf16 decision readout. The GGUF carries the encoder only — no `modern-bert.decision.type`, no head tensors — so a stock `llama-server` answers `501 This model is not a decision model` on `/v1/systemone`. `scripts/glide_serve.py` closes the gap the same way `pplx_decider.py` does: it runs llama-server with `--embeddings --pooling none`, reads the hidden state of the last real token before `[SEP]`, applies the readout, softmaxes the first N option slots and serves Fastino's own `/v1/systemone` contract (`choice`, `noul`, `score`, `probabilities`, `confidence`). Prompts, option codes and truncation follow `glide/prompt.py`: 7999 tokens max, first 1024 + tail.

- **Weights:** `models/irdor/GLiDE-0.4B-Q8_0-GGUF/` — `glide-0.4b-q8_0.gguf` (421 MB on disk, 400 MiB, 8.5 BPW) + `readout.safetensors` (522 KB) + `decision_config.json` (255 single-token option codes). The readout is not in the GGUF; keep it next to it.
- **Verified against the model card** on Q8_0: refund `0.789` vs `0.784`, cancel `0.086` vs `0.089`, urgent `0.593` vs `0.595`, priority `[0.031, 0.306, 0.663]` vs `[0.032, 0.311, 0.656]`, and the card's exact `usage.input_tokens = 395` — prompt layout and tokenization match the official server.
- **Text only:** `images`/`files` answer `422`, and `box` is unsupported (`422`). A doctor line claiming the box shim is online is the shared-port assumption of `decision_model.py`, not a capability of this model.
- **No KV cache.** It is a non-causal encoder, so llama.cpp builds a no-cache graph: the memory breakdown's `context` column is `0 MiB`, and `-ctk q8_0 -ctv q8_0` are accepted but allocate nothing. (A causal model of this shape would need 112 KiB/token — 0.9 GiB at 7999 in f16, 0.45 GiB in q8_0; here the question does not arise.)
- **Memory is the ubatch, not the model.** Weights are 347 MiB per GPU; `-c/-b/-ub` reserve a full-batch attention graph on top. Measured on one RX 9060 XT (`--device Vulkan0`, which `glide-serve` pins by default): ub 512 → 372 MB VRAM + 61 MB host, 2048 → 457 + 72, 4096 → 598 + 180, 7999 → 963 + 427. On both GPUs the same 7999 shape costs 1.9 + 1.7 GB VRAM and 1.4 GB host (~5 GB): each split reserves its own copy of the graph, so always pin `GLIDE_DEVICE`. If states stay under 2k tokens, `GLIDE_CTX=2048 glide-decider.sh` runs in ~0.5 GB.
- **Why VRAM *and* RAM.** On Vulkan, VRAM holds the 347 MB of weights plus the graph; RAM holds the mmap'd GGUF pages, a `Vulkan_Host` compute split (375 MB reserved) for the embedding/output ops and cross-device staging, and the 38 MB Python shim. Resident is much smaller than reserved: backend RSS 162 MB, shim 38 MB.
- **RAM only.** `GLIDE_NGL=0 glide-decider.sh` adds `--device none --no-op-offload` (plain `-ngl 0` still reserves 615 MB on the card): 0 MB VRAM, 1.05 GB reserved / ~0.55 GB resident. The cost is the O(n²) attention: a 150-token prompt takes ~150 ms instead of 40 ms, and a full 7999-token prompt 17.6 s instead of 2.3 s. Fine as a fallback when the cards are full and states are short.
- **Cost:** one forward pass per question, ~60 ms per question at the 8k-reserved graph, deterministic. `glide-decider.sh --status` / `--stop` manage both ports.

### The wire contract (shared with every slot candidate)
```json
{"state": {"context": "…"},
 "questions": {"q": {"type": "noul", "instructions": "Is this within policy?"}}}
```
| CLI primitive | wire type | question field | answer field |
| :--- | :--- | :--- | :--- |
| `bool` | `noul` | `instructions` | `noul` = P(true) |
| `choice` | `choice` | `instructions` + `criteria` map | `choice`, `probabilities` |
| `score` | `score` | `instructions` + ordered `criteria` levels | `score` = level index, `legend` |
| `box` | `box` \| `bbox` | `instructions` | h2o: `box`, `confidence`, `present`; Valen: `bbox`, `point`, `confidence` |

Valen swaps the envelope, not the primitives: `state.messages` with inline data URLs, `noul`/`choice`/`score` unchanged, and `box` sent as `bbox`. The client normalizes both answer shapes to four corners.

`bool` + `question` is the retired dialect: llama.cpp and the shim both answer `422` to it.

---

## 📜 Historical Reference: pplx-decider-flash v1.2

The previous decision model in this slot was Perplexity's `pplx-decider-flash-v1.2` (4.8B).

- **Architecture:** Qwen3.5-4B backbone with a `[255, 2560]` BF16 readout head distilled from 27B teachers.
- **Why It Was Retired:** It required non-causal attention (`qwen35.attention.causal=false`) and an 8192-token ubatch (`-ub 8192 -b 8192`) that consumed ~8.2 GB VRAM and spilled ~7.9 GB into GTT system RAM alongside Qwen 35B.
- **Legacy Client:** Preserved at [`scripts/pplx_decider.py`](scripts/pplx_decider.py) for testing joint protocol v3.
