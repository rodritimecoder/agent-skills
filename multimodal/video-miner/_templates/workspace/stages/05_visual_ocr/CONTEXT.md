# 05_visual_ocr — Extract Screen Text & Code

One job: run fast local OCR on gated text frames using CrispEmbed `PP-OCRv6` (port 8084 or direct CLI) to extract slides, diagrams, and code snippets.

## Inputs
- Working (this run): `../04_visual_gate/output/gated_frames.json` and `../04_visual_gate/output/text_frames/`
- Reference (every run): `../../_shared/pipeline_rules.md`

Do NOT load: Audio waveforms, un-gated frames.

## Process
1. Read the list of accepted frames from `../04_visual_gate/output/gated_frames.json`.
2. For each frame, run local OCR via CrispEmbed PP-OCRv6 (`http://127.0.0.1:8084/ocr/pipeline` or CLI):
   ```bash
   curl -s -X POST http://127.0.0.1:8084/ocr/pipeline -d '{"image": "frame.jpg"}'
   ```
3. Extract and parse text, headers, and code blocks.
4. Deduplicate text across consecutive frames (if slide content remained constant).
5. Compile structured entries with timestamps into `output/ocr_timeline.json` and `output/ocr_timeline.md`.

## Outputs
- `output/ocr_timeline.json` (timestamped OCR entries)
- `output/ocr_timeline.md` (human-readable OCR timeline with images)

## Human check
Open `output/ocr_timeline.md`. Clean up any OCR typos or misread characters in key code blocks or slide headings.
