---
name: video-miner

description: "Extract, transcribe, and synthesize knowledge from video files or URLs into structured markdown notes using local verbatim speech-to-text, deterministic frame gating (perceptual dedup + blank rejection), and OCR with the kem-ocr structural gate. Built on ICM with staged folders and human review checkpoints. Use to turn a recorded lecture, talk, webinar or screen recording into study notes, to mine a pile of video for what it teaches, or to get a transcript plus slides out of video you already have. For audio with no picture, use audiocpp; for a Zoom cloud recording link, use zoom-recorder."

compatibility: "Requires ffmpeg and the `audiocpp` CLI (CrisperWhisper 2.0 Large Q4_K by default — verbatim, 15x real-time; `--asr-model nemotron` to switch). No ASR server is needed. OCR needs either LightOnOCR (:8085) or MiniCPM-OCR-1.0 GGUF + the kem-ocr skill. h2o-lightning-4b on :8083 is optional, only for --gate h2o."
allowed-tools: "Bash(video-miner:*) Bash(ffmpeg:*) Bash(python3:*) Read Write"
---

> **Model layer:** the server behind this skill is registered in the `model-layer` skill (slot `:8085`) — launcher, weights files, health and quirks. Read it before starting, swapping or debugging the model.

# video-miner

Video mining pipeline combining local speech ASR and on-screen visual OCR into a unified, chronological markdown notes document.

Follows **Interpretable Context Methodology (ICM)**:
- Folders carry sequencing (`01_acquire` through `06_synthesize`).
- Files carry state: every stage has a `CONTEXT.md` contract and an `output/` edit surface.
- Human review checkpoints: inspect, edit, or adjust any stage before the next stage reads it.

## The 6 Stages

| Stage | Job | Input | Output & Human Checkpoint |
|---|---|---|---|
| `01_acquire` | Download/link video & extract 16 kHz audio | Video URL or path | `output/audio.wav`, `video_meta.json` |
| `02_audio_asr` | Transcribe speech via `audiocpp` (CrisperWhisper 2.0, verbatim + word timings) | `01_acquire/output/audio.wav` | `output/transcript.md` *(edit/correct terms)* |
| `03_visual_sample` | Keyframe (`-skip_frame nokey`), scene-cut, or fps sampling with PTS timing | `01_acquire/output/source_video.mp4` | `output/frames/`, `manifest.json` |
| `04_visual_gate` | Perceptual dedup (dHash) + blank rejection, or h2o vision gate | `03_visual_sample/output/manifest.json` | `output/gated_frames.json` *(check kept frames)* |
| `05_visual_ocr` | OCR via LightOnOCR-3-0.8B or MiniCPM-OCR-1.0 (+ structural gate) | `04_visual_gate/output/text_frames/` | `output/ocr_timeline.md` *(fix OCR typos)* |
| `06_synthesize` | Merge audio transcript & visual OCR into notes | `02_audio_asr` + `05_visual_ocr` | `output/mined_video.md` *(final deliverable)* |


## Quick Usage

### 1. Initialize a video mining workspace

```bash
CLI=~/.gemini/config/skills/video-miner/scripts/videomine.py
python3 $CLI init ./my_video_run "https://www.youtube.com/watch?v=..."
# Or with a local video file:
python3 $CLI init ./lecture_run ~/Videos/lecture.mp4
```

### 2. Check pipeline status (ASCII diagram or Token-Shielded table)

```bash
# Default ASCII flowchart:
python3 $CLI status ./my_video_run

# Token-shielded Markdown pipe table with artifacts:
python3 $CLI status ./my_video_run --table
```

### 3. Timeline Outline & Chapter Bookmarks (Glitch Cat / Kem Architecture)

Instead of reading 30k tokens of full synthesized video notes, extract a high-density chronological timeline table (~150 tokens):

```bash
# High-density timeline of visual slides and speech checkpoints:
python3 $CLI outline ./my_video_run --table

# Project specific columns and cap rows:
python3 $CLI outline ./my_video_run -p time,type,preview -n 15

# Buffer full timeline JSON to disk with receipt:
python3 $CLI outline ./my_video_run -o ./checkpoints.json
```

### 4. Step through one stage at a time (Human Checkpoint Mode)

Run the next stage and stop so you can review and edit intermediate files:
```bash
python3 $CLI step ./my_video_run
```

### 5. Run up to a specific checkpoint

```bash
# E.g. run acquisition and ASR first, then pause for transcript review:
python3 $CLI run ./my_video_run --until 02_audio_asr
```

### 6. Run the entire pipeline end-to-end

```bash
python3 $CLI run ./my_video_run
```

### 7. Choose the gate and the OCR backend

```bash
# MiniCPM-OCR-1.0 with the kem-ocr structural gate (tables, charts, dense screen text)
python3 $CLI run ./my_video_run --ocr minicpm

# h2o-lightning-4b vision gate instead of perceptual dedup
python3 $CLI run ./my_video_run --gate h2o

# Switch ASR: nemotron (fast, normalized) instead of the verbatim default
python3 $CLI run ./my_video_run --asr-model nemotron

# Frame sampling: codec keyframes, fixed fps, or the content selector
python3 $CLI run ./my_video_run --sample keyframe
python3 $CLI run ./my_video_run --sample fps --sample-fps 0.5
```

`--gate hash` (default) is deterministic and free: the frame is reduced to a
68×64 grey image and cut into a 4×4 grid of dHash regions (256 bits each).
Frames are duplicates only when *every* region stays within the Hamming budget
of the last kept frame, so a scrolling terminal counts as change and a static
slide does not. The budget is 20 bits (~8% of a region,
`VIDEOMINE_HASH_DISTANCE`): raise it to 28 to collapse more, lower it to 12 to
keep more. Frames with no luminance spread are dropped as blank.
`--gate h2o` spends a vision decision per frame and is the right choice for
talking-head footage where the screen is not the subject.

`--ocr lighton` (default) keeps LightOnOCR-3-0.8B. `--ocr minicpm` runs
MiniCPM-OCR-1.0 with `Text Recognition:` and then applies the `kem-ocr`
structural gate (`text` mode): frames whose OCR is empty, repetitive or
non-textual are dropped before they reach the timeline. Frames whose text is
≥90% the same as the previous kept frame are dropped too, so a slide that sits
on screen for a minute becomes one entry instead of ten. The gate is imported
from the sibling `kem-ocr` skill; if that skill is missing the OCR still runs
and the structural field is simply absent.

### Frame sampling modes (`03_visual_sample`)

| Mode | How | Frames / 5.5 min | Wall |
|---|---|---|---|
| `keyframe` | `-skip_frame nokey`, no non-key decode | 96 (encoder schedule) | **0.22 s** |
| `select` | scene cuts + motion accumulator + 4 s tick | 84 (metronome-dominated) | 3.5 s |
| `fps` | fixed cadence, `--sample-fps` | 335 at 1 fps | ~4 s |

`auto` (default) uses `keyframe` above 10 minutes (`VIDEOMINE_KEYFRAME_AFTER`) and
`select` below it. Keyframes are ~16× cheaper because the decoder never touches
a non-key frame; the trade is that positions are chosen by the encoder, not the
content. On a screen recording the `select` thresholds rarely fire — a terminal
scrolling a line moves `scene` far below 0.22 — so it degenerates to its 4 s
tick. The dHash gate in `04_visual_gate` then decides what is new: on the 5.5
minute lecture 96 keyframes collapsed to 79, because the terminal genuinely
changes every few seconds. A slide deck collapses much harder.


The final synthesized markdown document is emitted at:
`./my_video_run/stages/06_synthesize/output/mined_video.md`

## Human Checkpoints & Editing

Because every stage output is an edit surface:
- **Audio Transcript Checkpoint (`02_audio_asr`):** Open `stages/02_audio_asr/output/transcript.md` and correct any misrecognized technical jargon or names. Downstream synthesis will use your edits.
- **Visual Gating Checkpoint (`04_visual_gate`):** Inspect `stages/04_visual_gate/output/gated_frames.json`. Each record carries `keep`, `reason` (`new`, `duplicate`, `blank`, `no-text`) and `duplicate_of`; toggle `"keep": true` to force a frame back in.
- **OCR Checkpoint (`05_visual_ocr`):** Open `stages/05_visual_ocr/output/ocr_timeline.md` and polish any code blocks before final merge.

---

## 🏛️ Creator Video Vault (`vault-mine`)

High-speed single-pass video mining and cataloging into `/run/media/rodri/AI/creator-vault/`. Powered by `audiocpp` GPU speech-to-text (8.5x–67x real-time), single-pass download with info JSON, and smart OCR gating:

```bash
# List vaulted videos in a high-density Markdown table:
vault-mine list --table --limit 10

# Filter vault by creator:
vault-mine list --creator "kem_glitch" --table

# Fast single-pass video mining directly from URL into the vault (~12s end-to-end):
vault-mine add "https://www.instagram.com/reel/..." --creator "kem_glitch" --title "graph-memory-rant"

# Ultra-fast mining with Nemotron streaming STT:
vault-mine add "https://..." --model nemotron

# Import an existing mined ICM workspace into the vault:
vault-mine import ./my_video_run --creator "kem_glitch" --title "5-agents-worktree"

# Rebuild vault catalog index:
vault-mine reindex
```

## Tests

```bash
python3 ~/.gemini/config/skills/video-miner/scripts/test_videomine.py
```
