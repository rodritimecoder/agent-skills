# Pipeline Rules & Defaults

## Audio & ASR Defaults
- Sample rate: 16,000 Hz, mono, s16le PCM WAV.
- ASR Endpoint: `http://127.0.0.1:8081` (`audiocpp-asr`).
- Native captions: If available from source (e.g. YouTube `.vtt` or embedded `.srt`), save as baseline alongside generated ASR.

## Visual Sampling Defaults
- Strategy: Scene detection (`gt(scene,0.15)`) combined with maximum interval fallback (every 3 seconds).
- Deduplication: Perceptual hash difference threshold (> 8% difference required to accept a new keyframe).
- Format: PNG or high-quality JPEG stored in `stages/03_visual_sample/output/frames/`.

## Visual Gating Defaults
- Gating engine: `h2o-lightning-4b` on `:8083` (vision `/v1/systemone`) or local variance/edge density heuristic.
- Threshold: Drop candidate frames where probability of containing readable text/code is < 0.5.

## OCR Defaults
- OCR Endpoint: `http://127.0.0.1:8085` (`ocr-cli` / `LightOnOCR-3-0.8B`).
- Output format: Markdown formatted text/code blocks per frame timestamp.

## Synthesis Defaults
- Format: Chronological Markdown timeline with linked/embedded keyframe images.
- Structure: Headers for sections/intervals, blockquotes for spoken transcript, code/text blocks for visual OCR.
