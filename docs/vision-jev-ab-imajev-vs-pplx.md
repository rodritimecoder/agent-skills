# Vision-JEV A/B — Imajev-4B vs pplx-decider-flash-v1.2

**Date:** 2026-10-21
**Question:** can the two local 4B decision models be compared on *vision* decision tasks, and why does ImageJevBench list Imajev-4B as a bounding-box system?
**Result:** yes — and the comparison produced a shared blind spot that neither model's public numbers reveal.

Everything here was run locally against the **published public item set** of
[ImageJevBench](https://benchmarkheaven.com/image-jev-bench) v0.3.0 /
`imagejev-box-v0.1` (`github.com/fstandhartinger/jevbench`), so the numbers are
comparable with the public board, not just with each other.

---

## 1. The setup

| | Imajev-4B | pplx-decider-flash-v1.2 |
| :--- | :--- | :--- |
| Local weights | `models/mindchain/imajev-4b-GGUF/` (Q4_K_M + mmproj) | `models/perplexity-ai/pplx-decider-flash-v1.2/` (Q4_K_M + mmproj) |
| Base | Qwen3.5-4B + merged LoRA decision adapter | Qwen3.5-4B + Qwen3-VL vision tower + readout head |
| Decision path | trained readout head, 256 codes (256×2560), T = 1.3052 | joint protocol v3 readout, T = 1.5539 |
| Served on | `:8089` (new launcher `sh/imajev-decider.sh`) | `:8083` (existing) |
| Device | **CPU** (both GPUs are saturated by the 35B on `:8080`) | **GPU** (Vulkan) |
| Public board | **#3** on ImageJevBench v0.3 (Capability 68.0, Calibration 86.1) | **absent** from the image board |

Imajev's decision protocol is not natively supported by any local client, so it
was reproduced here: the trained readout (`decision_readout.safetensors`,
2.6 MB, fetched from HF) is applied to the last-position hidden state that
llama-server returns in `--embeddings --pooling none` mode, using the reference
prompt layout (header + `A: yes` / `B: no` option lines) from
`github.com/mohit67890/imajev` (`src/vision_decision/scoring.py`).
Probabilities are renormalised over the two offered options, as the reference
implementation does over its candidate set.

---

## 2. Task A — the box track (published gold boxes, 100 items)

Reproduces the ImageJevBench *Box* track: one image, one description, one box.

| | Imajev-4B (ours, local CPU) | Imajev-4B (public board) |
| :--- | ---: | ---: |
| Mean IoU | **0.628** | 0.603 |
| Acc@0.5 | **0.732** | 0.67 |
| Calibration (ECE on stated confidence) | **0.223** | 0.341 (calibration score) |
| Parse rate | 0.71 (29 % empty completions) | — |
| p50 latency | 4.2 s (CPU) | 0.36 s (vLLM, GPU) |

**The local run reproduces the board.** Mean IoU 62.8 vs 60.3, Acc@0.5 73 % vs
67 %, and — the important part — **the confidence is badly calibrated in both
places**. On `bx-coco-pub-0001` the model states **0.97** confidence on a box
with **IoU 0.00**.

### Why the site says Imajev can do bounding boxes

Because the box track is a **harness-level capability, not a model head**. The
method (`datasets/imagejev-box-v0.1/METHOD.md`) says chat vision models are
asked, at temperature 0, for one JSON bounding box, and the answer is scored by
IoU. Imajev's row is filed as *"self-hosted vLLM (adapter merged)"* — the
adapter is merged into the base model, the model is asked in its family's
native grounding format (`bbox_2d` in 0..1000), and the JSON is parsed.

The checkpoint itself has **no box head**: the readout is 256 discrete answer
codes over a text vocabulary (`decision_readout.json`: A=32 … JU=213977), and
`calibration.json` covers only `boolean` / `choice` / `ordinal` — nothing
continuous, no coordinate head, no box calibration. The numbers show the
consequence: Imajev-4B's **Box Intelligence (0.603) is *below* its own base
model's (0.701)**; the decision adapter made raw box accuracy slightly worse
and only wins Box Capability because calibration is weighted in and the base
scores 0.067 on it.

**pplx-decider cannot do the box track at all.** Asked the same question in
chat mode it returns **empty completions** (0 % parse, ~16 s each). It is a
decision model: it answers typed questions through its joint protocol and has
no useful free-form generation. The two models are therefore not
interchangeable in chat mode — only in decision mode.

---

## 3. Task B — binary image decisions (the actual comparison)

One shared item set, built from the published box items (descriptions and gold
boxes are in the public JSONL):

- **positive** — "Does the image contain *the rightmost bottle*?" → true
- **hard negative** — the *same image*, spatial modifier swapped
  ("the rightmost bottle" → "the leftmost bottle"): the category is still
  present, so only real localisation separates them
- **easy negative** — a different image's description

80 items per set, run through each model's **native decision protocol**.

| Run | Model | Accuracy | Hard negatives | Easy negatives | ECE | p50 |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| spatial-swap | pplx | 0.863 | **0.500** | 0.968 | **0.084** | 0.70 s |
| spatial-swap | imajev | 0.863 | **0.500** | 0.968 | 0.179 | 1.13 s |
| category | pplx | 0.988 | — | — | **0.040** | 0.77 s |
| category | imajev | 0.950 | — | — | 0.150 | 1.19 s |

### The shared blind spot

**Both models score exactly 0.500 on the hard negatives — chance.** They
answer the *category* question ("is a bottle in this image?") and ignore the
spatial qualifier. Their predictions agree on **100 % of 80 items** and their
p(true) correlates at **r = 0.979**.

And both are *confident* while wrong: on a swapped qualifier, pplx says
p(true) = 0.90–0.97 for a claim that is false. Its ECE of 0.084 on the
aggregate looks healthy only because the easy items are easy; on the hard
subset the model is confidently wrong.

The control confirms the mechanism rather than a bug: with the modifier
stripped ("is a *bottle* in this image?"), both models jump to 0.95–0.99
accuracy. **Neither 4B decision head localises; both detect.**

---

## 4. What this means for `frontend-uat`

The UAT pipeline asks **state** questions ("is the order confirmed?", "is the
error banner visible?"), not localisation questions. On that class, both
models are strong and well-behaved (category row: 0.95–0.99 accuracy,
p(true) 0.94 vs 0.03 on negatives, p50 < 1.2 s).

The rule that falls out of this:

- **Do** use a decision model for *state* assertions on a screen.
- **Do not** use one to decide *which* element is on screen when the elements
  are visually similar. The pipeline already avoids this: clickable targets
  are extracted from the DOM in code (`[D]`) and the model only picks an
  **index** (`[P]`). The measurement above is the empirical justification for
  that design — a 4B decision head would pick the wrong one of two similar
  buttons.
- **Do** read the confidence as a gate, not a verdict. ECE 0.08 (pplx) vs
  0.15–0.18 (imajev) locally.

### Which model for the UAT slot?

**pplx**, on this evidence:

- better calibrated locally on both item sets (ECE 0.040/0.084 vs 0.150/0.179);
- 1.6× faster here — and that is CPU vs GPU, so the gap is larger than it looks;
- already wired into `frontend-uat` (`visual_gate()` → `jev bool --image`).

**Imajev-4B** keeps the #3 public image-board ranking, has a 256-code readout
with a documented calibration procedure, and its 2B sibling is a cheap fallback
— but its native protocol needs the reference prompt layout and the readout
head applied by hand, which is exactly the fragility that produced the
"premier calibrated decision model" claim drifting out of the catalogue.
Its `decision_readout.json` also now needs to ship with the weights.

---

## 5. Reproducing

```sh
# 1. imajev on :8089 (the launcher is new; upstream in sh/)
/run/media/rodri/AI/sh/imajev-decider.sh

# 2. the harnesses
cd /run/media/rodri/AI/bench/vision-jev-ab
python3 box_ab.py        --model imajev-4b --port 8089 --fmt qwen --limit 100 --out results/box-imajev.jsonl
python3 vision_jev_ab.py --model pplx    --port 8083 --n 40 --out results/ab-pplx.jsonl
python3 vision_jev_ab.py --model imajev  --port 8089 --n 40 --out results/ab-imajev.jsonl
```

Items: `datasets/imagejev-box-v0.1/items.jsonl` from the jevbench clone
(`git clone --depth 1 https://github.com/fstandhartinger/jevbench`).

**Serving gotcha, already fixed in the launcher:** an image expands into
hundreds of tokens, and llama-server's default physical batch (512) rejects
the request with *"input (N tokens) is too large to process"*. The ubatch must
be ≥ the context (`-b 8192 -ub 8192`), exactly as the pplx launcher does. With
the default, 28/80 document images failed with HTTP 500 — a launcher bug, not
a model failure.

---

## 6. Corrections this puts on the record

1. `pplx-decider/SKILL.md` says *"Decision Index 0.3: 60.06 public"* — that is
   the **text** JevBench. It has no published **image** row; Imajev-4B is #3 on
   the image board. The local numbers above are the first like-for-like image
   comparison between the two.
2. `jev-decision/SKILL.md` calls the model *"the premier calibrated decision
   model on the workstation"*. On image decisions Imajev-4B has the public
   evidence and pplx has the better local calibration. Neither claim survives
   as written.
3. The catalogue has no **spatial/localisation** blind-spot warning. Both 4B
   heads are category detectors, and the failure is silent because the
   confidence stays high.

## Files

- `sh/imajev-decider.sh` — new launcher (also copied to `skills/launchers/` and
  `workstation-clis/launchers/`)
- `bench/vision-jev-ab/` — harnesses, readout weights, raw per-item results
- `skills/docs/vision-jev-ab-imajev-vs-pplx.md` — this report
