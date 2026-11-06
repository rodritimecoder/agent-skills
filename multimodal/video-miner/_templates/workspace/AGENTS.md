# Video Miner Pipeline Workspace

Processes a video file or URL into a structured, chronological text artifact combining spoken audio (ASR) and on-screen visuals (OCR).

Built on ICM: folders carry sequencing, hierarchy carries context, files carry state. Every stage output is an edit surface and a human checkpoint.

## Not this workspace

Say so and stop rather than running the wrong pipeline. This workspace is not for:
- Video/audio editing or transcoding as a final deliverable (use ffmpeg / video editor).
- Pure text document parsing without video (use `markitdown-cli`).
- Pure audio transcription with no video involved (use `audiocpp-asr`).

## Where things live

| Folder | What it holds |
|---|---|
| `stages/` | The 6 pipeline stages in execution order |
| `_shared/` | Shared configuration, prompts, and pipeline rules |
| `_templates/` | Clean stage templates |

## Route by what just happened

| If | Go to | Then stop at |
|---|---|---|
| Starting a new video | `stages/01_acquire/CONTEXT.md` | `stages/01_acquire/output/video_meta.json` |
| Video & audio acquired | `stages/02_audio_asr/CONTEXT.md` | `stages/02_audio_asr/output/transcript.md` |
| Audio transcribed | `stages/03_visual_sample/CONTEXT.md` | `stages/03_visual_sample/output/manifest.json` |
| Frames sampled | `stages/04_visual_gate/CONTEXT.md` | `stages/04_visual_gate/output/gated_frames.json` |
| Text frames gated | `stages/05_visual_ocr/CONTEXT.md` | `stages/05_visual_ocr/output/ocr_timeline.md` |
| OCR timeline ready | `stages/06_synthesize/CONTEXT.md` | `stages/06_synthesize/output/mined_video.md` |
| Asked for status | Run `videomine.py status` or inspect `stages/*/output/` | Report stage statuses |
| Upstream file edited | Rerun affected stage and downstream stages | — |

## The one rule

Every stage output is an edit surface: a plain file you can inspect, edit, and save. The next stage reads whatever is there. A human may review a stage's output before the next one starts — that is a choice at the handoff, not a lock on the pipeline.

## Status

Scan `stages/*/output/`. A stage is:

| State | When |
|---|---|
| `PENDING` | No files in `output/` (ignoring `.gitkeep`) |
| `COMPLETE` | Has files, and every file is newer than the previous stage's newest file |
| `STALE` | Has files, but at least one is **older** than the previous stage's newest file |

```
Pipeline Status:
  [01_acquire] -> [02_audio_asr] -> [03_visual_sample] -> [04_visual_gate] -> [05_visual_ocr] -> [06_synthesize]
```
