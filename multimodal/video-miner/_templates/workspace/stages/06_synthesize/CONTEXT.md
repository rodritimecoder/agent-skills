# 06_synthesize — Merge Audio & Visual Knowledge

One job: fuse the spoken audio transcript and on-screen visual OCR into a unified, chronological markdown notes document.

## Inputs
- Working (this run):
  - `../02_audio_asr/output/transcript.json` (and `transcript.md`)
  - `../05_visual_ocr/output/ocr_timeline.json` (and `ocr_timeline.md`)
  - `../01_acquire/output/video_meta.json`
- Reference (every run): `../../_shared/pipeline_rules.md`

Do NOT load: Raw frames, intermediate model logits.

## Process
1. Load both streams:
   - Spoken segments (with `start`, `end`, `text`).
   - Visual OCR slides/code blocks (with `timestamp`, `content`).
2. Interleave events chronologically into time intervals (e.g., sections or 30–60s blocks).
3. Associate on-screen code or slide points with the narration explaining them.
4. Render the final deliverable `output/mined_video.md`:
   - Title, video metadata, duration.
   - Table of contents / section index.
   - Chronological walkthrough with spoken explanation, on-screen text/code snippets, and keyframe image references.

## Outputs
- `output/mined_video.md` (the primary deliverable)
- `output/mined_video.json` (structured machine-readable representation)

## Human check
Read `output/mined_video.md`. Confirm that slide headings match the spoken flow and code blocks are properly fenced. This is the final artifact leaving the workspace.
