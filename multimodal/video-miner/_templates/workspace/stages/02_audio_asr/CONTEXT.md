# 02_audio_asr — Transcribe Speech to Timestamps

One job: transcribe speech from `01_acquire` into timestamped segments using `audiocpp-asr`.

## Inputs
- Working (this run): `../01_acquire/output/audio.wav` (and optional `../01_acquire/output/subtitles.vtt`)
- Reference (every run): `../../_shared/pipeline_rules.md`

Do NOT load: Visual frames, OCR outputs, model weights.

## Process
1. If high quality native subtitles exist in `../01_acquire/output/subtitles.vtt`, parse and convert them to the canonical transcript schema.
2. Otherwise, invoke the local ASR engine (`~/.gemini/config/skills/audiocpp-asr/scripts/asr.py` against `http://127.0.0.1:8081`):
   ```bash
   python3 ~/.gemini/config/skills/audiocpp-asr/scripts/asr.py transcribe ../01_acquire/output/audio.wav --details > output/raw_asr.json
   ```
3. Format output segments into clean JSON with `start`, `end`, and `text` fields.
4. Render a readable markdown version `output/transcript.md`.

## Outputs
- `output/transcript.json` (canonical timestamped segments)
- `output/transcript.md` (human-readable transcript with [MM:SS] timestamps)

## Human check
Open and read `output/transcript.md`. Correct any domain jargon, misspelled technical names, or incorrect speaker tags. Any changes made to `transcript.md` will directly flow into downstream stages.
