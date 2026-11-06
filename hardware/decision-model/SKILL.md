---
name: decision-model
description: >
  Calibrated decision and visual grounding engine (h2o-lightning-4b, 4B) with vision projector
  (mmproj-lightning-f16). Answers typed bool, choice, score, and bounding-box queries
  (normalized 4-corner coordinates with calibrated confidence and presence gating) on port :8083
  without generating open-ended prose. The :8083 slot rotates between decision models; this client
  names the served model in every result.
compatibility: "Requires a decision server on :8083 answering /v1/systemone (noul | choice | score). h2o-lightning-4b runs behind the h2o-serve shim with its pinned llama.cpp on :8621; set DECISION_REQUIRE_H2O=1 to reject any other slot occupant."
allowed-tools: "Bash(python3:*) Bash(decision-model:*) Bash(h2o-serve:*) Read Write"
---

# Decision Model (`decision-model`)

The workstation's premier decision and visual perception engine: **h2o-lightning-4b** (4B) with **`mmproj-lightning-f16`**.

A calibrated decision model never generates open-ended prose. It evaluates a context and typed questions, returning probabilities over a closed answer set in sub-50ms latency. Because it is built on Qwen2.5-VL, it natively understands both structured text and visual assets (screenshots, documents, UI elements).

---

## ⚡ Primitives & Capabilities

| Primitive | Output | Best Used For |
| :--- | :--- | :--- |
| **`bool`** | `{decision, probability, confidence}` | Gating, branch guards, rule verification, invariant checks |
| **`choice`** | `{selection, probabilities{...}}` | Classification, intent routing, workflow dispatch |
| **`score`** | `{score, probabilities{...}}` | Quality thresholds, urgency, risk on `[0.0, 1.0]` |
| **`box`** | `{box[4], confidence, present, found}` | **Visual grounding:** 4-corner coordinates (`left`, `top`, `right`, `bottom`) for a target phrase |

### The Two Visual Box Gates
When requesting bounding boxes via `box`:
- **`present` (P(target is in the frame)):** The primary gate. If `present < 0.5`, reject even if a candidate box is generated.
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
error names the occupant and points at `h2o.sh`. `clip-box` is the same
primitive under the "where is X" vocabulary.

---

## 🚀 Server Launchers

### h2o-lightning-4b on the decision slot
```bash
/run/media/rodri/AI/sh/h2o.sh              # :8083, shim + pinned llama.cpp on :8621
/run/media/rodri/AI/sh/decide.sh startlux  # rotate the slot to another candidate
```
`llama.cpp` has no backend for `qwen35.decision.type=h2o-lightning` — a stock `llama-server` rejects this GGUF at load. The decision head and the box readout live in h2oai's shim, so `h2o.sh` drives `h2o-serve` (Python front on `:8083`, pinned Vulkan backend on `:8621`). The shim serves decisions and boxes on the same port, so `BOX_PORT` follows `DECISION_PORT` unless overridden. `h2o-serve` ships in this skill (`scripts/h2o_serve.py`); a standalone front on `:8761` is the fallback when another candidate occupies the slot.

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
| `box` | `box` | `instructions` | `box`, `confidence`, `present` |

`bool` + `question` is the retired dialect: llama.cpp and the shim both answer `422` to it.

---

## 📜 Historical Reference: pplx-decider-flash v1.2

The previous decision model in this slot was Perplexity's `pplx-decider-flash-v1.2` (4.8B).

- **Architecture:** Qwen3.5-4B backbone with a `[255, 2560]` BF16 readout head distilled from 27B teachers.
- **Why It Was Retired:** It required non-causal attention (`qwen35.attention.causal=false`) and an 8192-token ubatch (`-ub 8192 -b 8192`) that consumed ~8.2 GB VRAM and spilled ~7.9 GB into GTT system RAM alongside Qwen 35B.
- **Legacy Client:** Preserved at [`scripts/pplx_decider.py`](scripts/pplx_decider.py) for testing joint protocol v3.
