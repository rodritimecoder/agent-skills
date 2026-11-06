# Voice-Driven Animation

This workspace produces narrated explainer videos where the recorded voiceover is the source of truth. The script is a plan; the audio is the timeline; the transcript drives scene boundaries; Remotion is the assembler.

## When to Use This Workspace

Use this when the deliverable is a 1 to 6 minute animated video with full narration (no on-camera footage), and you want timing locked to the actual recorded VO. Good for explainers, case-study videos, product walkthroughs, advisory pitches. Not for short-form social where on-camera face is the asset, and not for live-action shoots.

If your video has no narration, use `script-to-animation` instead.

## Not this workspace

| If | Go to instead |
|---|---|
| no recorded narration — timing can follow the script | `script-to-animation` |
| on-camera footage or live action is the asset | neither — this pipeline produces animation only |
| you have narration but not the final script | enter at `stages/02-script/CONTEXT.md` |
| you need only the audio, no video | stop after `stages/03-voice/CONTEXT.md` |

## Folder Map

```
voice-driven-animation/
|-- AGENTS.md              (you are here)
|-- CONTEXT.md             (start here for task routing)
|-- setup/
|   `-- questionnaire.md   (run with "setup")
|-- brand-vault/
|   |-- CONTEXT.md
|   |-- identity.md        (brand, audience, positioning)
|   `-- voice-rules.md     (tone, hard constraints, examples)
|-- skills/
|   |-- elevenlabs-narration/   (generate VO from a PASTE-block script)
|   |-- whisper-beat-finder/    (CPU-safe transcription + beat extraction)
|   `-- remotion-scene-anatomy/ (gap-fill sequences, beat-local time, end card)
|-- shared/
|   |-- pipeline-overview.md   (five-stage diagram)
|   |-- env-template.md        (.env vars across stages)
|   `-- platform-specs.md      (resolution, fps, duration per platform)
`-- stages/
    |-- 01-research/   (topic -> verified brief with citations)
    |-- 02-script/     (brief -> script + PASTE block + beat markers)
    |-- 03-voice/      (script -> audio.mp3 + transcript + beat-timings)
    |-- 04-animate/    (beat-timings -> timing.ts + per-beat scenes)
    `-- 05-render/     (scenes -> rendered mp4)
```

Each stage has `CONTEXT.md`, `output/`, and `references/`. Outputs are the human edit surface between stages.

## Triggers

| Keyword | Action |
|---------|--------|
| `setup` | Run the onboarding questionnaire. Configures brand, voice, ElevenLabs voice id, Whisper preference, end-card assets. |
| `status` | Scan `stages/*/output/`. Show each stage as COMPLETE if its output folder has files other than `.gitkeep`, otherwise PENDING. |

## Routing

| Task | Go To |
|------|-------|
| Research a topic and produce a brief | `stages/01-research/CONTEXT.md` |
| Write the script with the PASTE block | `stages/02-script/CONTEXT.md` |
| Generate VO and find beat boundaries | `stages/03-voice/CONTEXT.md` |
| Build Remotion scenes | `stages/04-animate/CONTEXT.md` |
| Render the final mp4 | `stages/05-render/CONTEXT.md` |
| Configure this workspace | `setup/questionnaire.md` |

## What to Load

| Task | Load These | Do NOT Load |
|------|-----------|-------------|
| Research | `brand-vault/identity.md` (Audience), `stages/01-research/references/*` | voice-rules, skills, later stages |
| Script | `brand-vault/voice-rules.md` ("Hard Constraints" through "What the Voice Is NOT"), `brand-vault/identity.md` (One-Sentence + Audience), `stages/01-research/output/`, `stages/02-script/references/*` | skills, animate, render |
| Voice | `stages/02-script/output/`, `stages/03-voice/references/audio-pipeline.md`, `skills/elevenlabs-narration/SKILL.md`, `skills/whisper-beat-finder/SKILL.md` | brand-vault, animate references |
| Animate | `stages/03-voice/output/`, `stages/04-animate/references/*`, `skills/remotion-scene-anatomy/SKILL.md` | brand-vault, earlier stages |
| Render | `stages/04-animate/output/`, `stages/05-render/references/render-checklist.md` | everything else |

## Status

Scan `stages/*/output/` and compare modification times. `PENDING` with no files (ignoring `.gitkeep`); `COMPLETE` when the stage's newest file is newer than the previous stage's newest file; `STALE` when it is **older** — an upstream output was edited after this stage ran.

```
Pipeline Status: voice-driven-animation

  [01-research] --> [02-script] --> [03-voice] --> [04-animate] --> [05-render]
     COMPLETE        COMPLETE       STALE          PENDING          PENDING
```

`STALE` is the normal state of this pipeline after any retiming. `stages/03-voice/output/audio.mp3` is the timing truth, so re-record or edit the transcript and stages 04 and 05 are wrong until re-run. The transcript is the highest-leverage edit in the workspace: change it and re-run 04, then 05.

## Stage Handoffs

Each stage writes to its own `output/`. The next stage reads from there. If you edit an output file (rewrite a script line, retime a beat, adjust a scene's `T` constants), the next stage picks up the edit automatically. That is the primary control surface.

The audio file in `stages/03-voice/output/audio.mp3` is the timing truth. If the audio is regenerated, every downstream timing (timing.ts, scene-local T constants) needs to be re-derived from the new transcript. The phrase-match script in `skills/whisper-beat-finder/scripts/` does this.

## Re-running

Do not clear `output/` folders. Re-rolling a video is normal here and destroying the previous take loses the comparison that makes retiming decisions obvious.

- **Re-record the VO:** overwrite `stages/03-voice/output/`, then re-run 04 and 05. 01 and 02 stay valid if the script is unchanged.
- **Change a script line:** edit `stages/02-script/output/` and re-run 03, 04, 05 — the transcript must be regenerated or the audio will not match.
- **New video, same workspace:** write into a dated subfolder (`output/2026-03-30/`) and keep the previous take until the new one passes 05.
