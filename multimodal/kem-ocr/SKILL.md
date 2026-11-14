---
name: kem-ocr

description: >
  Kem-pipeline OCR with Jev verification: parse a document image with MiniCPM-OCR-1.0,
  render the transcription back into an image, and score it with MiniCPM-OCR-Jev
  (P(faithful) in one forward pass). Every run carries a corrupted-candidate
  holdout that the gate must reject, plus a per-stage JSON ledger. Use for
  verified transcription of pages, crops, formulas, and tables where a wrong read
  must not ship silently.

compatibility: "Requires MiniCPM-OCR-1.0 (llama-mtmd-cli) and sh/minicpm-ocr-jev.sh on :8090. Node + Chromium for rendering (offline, KaTeX bundled)."
allowed-tools: "Bash(kem-ocr:*) Bash(python3:*) Read Write"
---

> **Model layer:** the server behind this skill is registered in the `model-layer` skill (slot `:8090`) — launcher, weights files, health and quirks. Read it before starting, swapping or debugging the model. Down? `llama-rig up ocr-jev`.

# `kem-ocr` — Kem-pipeline OCR with Jev verification

A lego-block OCR pipeline. Each stage is a small, composable, auditable block
with a typed input/output and a `step_NN.json` receipt. Code decides wherever it
can (thresholds, retries, holdouts); the models are the only `[P]` blocks.

```
01_acquire -> 02_parse -> 03_render -> 04_verify -> 05_holdout -> 06_decide -> 07_emit
   [D]          [P][D]        [D]           [P]          [P]           [D]          [D]
```

`02_parse` carries a deterministic structural assertion after the model call, so
malformed output never reaches Jev.

## Quickstart

```bash
# Single page, text mode
kem-ocr page.png

# Cropped formula
kem-ocr formula_crop.png --type formula

# Cropped table (OTSL or HTML output from 1.0 both render)
kem-ocr table_crop.png --type table

# Verify a transcription you already have
kem-ocr page.png --candidate "48520 Electronics & Circuits"

# Full output lands in ./kem-ocr-out/<timestamp>/ (final.md + verification.json)
```

## The gate (Kem invariants)

- **Cheap checks first**: empty, degenerate, and structure-mismatched output is
  rejected in code before Jev is called. No model time is spent on a candidate
  that cannot be right.
- **Code decides**: accept >= 0.5, reject < 0.3, escalate 0.3-0.7 to a human.
- **A gate that cannot fail is not a gate**: every run includes a corrupted
  holdout candidate. If Jev accepts it, the run exits `INVALID` (code 3).
- **A judge that shares the author's context is not a judge**: Jev is a separate
  model (2B value head, no LM head) on its own process (`:8090`).
- **The poison sits upstream**: on reject, retry at `02_parse`, never patch markdown.
- **Always run the control**: `--no-holdout` exists but is not recommended.
- **Human on uncertainty**: middling scores escalate instead of auto-deciding.

## Structural gate (`02_parse`)

Runs on the raw candidate, before render or verify:

| Check | Fails when |
| :--- | :--- |
| `non_empty` | candidate is whitespace only |
| `alnum_floor` | fewer than 4 alphanumerics (`text`), 1 otherwise |
| `no_line_loop` | 4+ lines and one line is >= 75% of them |
| `no_char_flood` | one repeated character is > 50% of the output |
| `table_structure` | no `<table>`, no `<otsl>`, and fewer than 2 pipe rows (`table`) |
| `latex_marker` | no TeX command, sub/superscript or relation (`formula`) |

All candidates failing means `decision: REJECT` with `gate: structural` in
`step_06_decide.json`, exit code 1, and no Jev call. Some candidates failing in
best-of-N mode means they are dropped and the rest continue.

These checks catch **malformed** output, not **wrong** output — a chart read as
LaTeX is well-formed and will pass. Jev owns correctness. Note that Jev is
trained on text/formula/table regions: a correct chart transcription scores low
(measured 0.011), so chart runs escalate by design rather than auto-accepting.

## Verification sidecar

`verification.json` records: candidate, render path + renderer, Jev prob +
verdict + confidence + input tokens, holdout prob + gate_ok, decision + reason,
the accept/reject thresholds, and the `structural` checks for the chosen
candidate. Renderer provenance is included because the
render environment moves small scores by multiples (lightweight Chromium render
by default; full SDK renderer optional).

## Requires

- `/run/media/rodri/AI/sh/minicpm-ocr-jev.sh` running on `:8090`
- `llama-mtmd-cli` + MiniCPM-OCR-1.0 Q8_0 (paths overridable via env)
- Node + Chromium (offline KaTeX bundled in ROCmFPX build tree)

## Tests

```bash
python3 multimodal/kem-ocr/tests/test_kem_ocr.py
```
