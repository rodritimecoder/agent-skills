# Video Miner Workspace Contract

Orchestrates automated extraction, gating, OCR, and synthesis of spoken and visual content from a video into markdown documentation.

## Stages Overview

1. **`01_acquire`**: Downloads video (or links local file), extracts 16 kHz WAV audio for ASR, checks for embedded subtitles, and dumps stream metadata.
2. **`02_audio_asr`**: Transcribes speech using the local `audiocpp-asr` server (Nemotron 3.5 ASR on `:8081`), emitting timestamped intervals in `transcript.json` and human-readable `transcript.md`.
3. **`03_visual_sample`**: Extracts candidate visual frames with ffmpeg using scene change detection and adaptive interval sampling, deduplicating nearly identical visual states.
4. **`04_visual_gate`**: Evaluates sampled frames to filter out frames without meaningful text/code/diagrams (using the local h2o-lightning-4b vision decision model on `:8083` or fast edge/contrast filtering), emitting `gated_frames.json`.
5. **`05_visual_ocr`**: Runs `ocr-cli` (LightOnOCR-3-0.8B on `:8085`) across gated text frames to extract screen text, slides, and code into `ocr_timeline.json` and `ocr_timeline.md`.
6. **`06_synthesize`**: Merges the timestamped audio transcript and visual OCR timeline into an integrated, chronological `mined_video.md` document.

## Running the Pipeline

Use the orchestrator CLI:
```bash
# Check status of stages
python3 ~/.gemini/config/skills/video-miner/scripts/videomine.py status

# Run next stage or specific stage
python3 ~/.gemini/config/skills/video-miner/scripts/videomine.py step

# Run up to a specific checkpoint
python3 ~/.gemini/config/skills/video-miner/scripts/videomine.py run --until 02_audio_asr
```
