# 04_visual_gate — Filter Frames for Readable Text

One job: filter candidate frames from `03_visual_sample` down to only those containing readable text, slides, diagrams, or code.

## Inputs
- Working (this run): `../03_visual_sample/output/manifest.json` and `../03_visual_sample/output/frames/`
- Reference (every run): `../../_shared/pipeline_rules.md`

Do NOT load: Audio data, transcripts, full OCR models.

## Process
1. For each candidate frame in `manifest.json`:
   - Run the fast text presence evaluator (h2o-lightning-4b vision decision query or local edge/contrast density heuristic).
   - Classify: `has_text` (P >= 0.5) vs `no_text`.
2. Record the score and classification decision in `output/gated_frames.json`.
3. Symlink or copy the accepted frames into `output/text_frames/`.

## Outputs
- `output/gated_frames.json` (decision log with frame, timestamp, confidence, and keep/drop flag)
- `output/text_frames/` (directory of frames selected for OCR)

## Human check
Review `output/gated_frames.json`. If an important slide or UI element was dropped, change `"keep": false` to `"keep": true` in the JSON, or manually add frames to `output/text_frames/`.
