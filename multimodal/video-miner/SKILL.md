---
name: video-miner

description: "Extract, transcribe, and synthesize knowledge from video files or URLs into structured markdown notes using local verbatim speech-to-text, deterministic frame gating (perceptual dedup + blank rejection), and OCR with the kem-ocr structural gate. Built on ICM with staged folders and human review checkpoints. Use to turn a lecture recording, talk, webinar or screen recording into study notes, to mine a pile of recordings for what they teach, or to get the transcript and the slides out of videos you already have on disk. For audio with no picture, use audiocpp; for a Zoom cloud link, use zoom-recorder."

compatibility: "Requires ffmpeg, `yt-dlp` and the `audiocpp` CLI (CrisperWhisper 2.0 Large Q4_K, verbatim with word timings; `--asr-model nemotron` for faster output without timings). No ASR server needed. OCR needs LightOnOCR (:8082) or MiniCPM-OCR-1.0 GGUF + the kem-ocr skill; the scripts run `llama-rig up ocr` themselves, so a stopped slot never blocks. Speaker labels come from `audiocpp diarize`. h2o-lightning-4b on :8083 is optional, only for --gate h2o."
allowed-tools: "Bash(video-miner:*) Bash(ffmpeg:*) Bash(python3:*) Bash(llama-rig:*) Read Write"
---

> **Model layer:** the server behind this skill is registered in the `model-layer` skill (slot `:8082`) — launcher, weights files, health and quirks. Read it before swapping or debugging the model. A stopped slot is not an error: the pipeline runs `llama-rig up ocr` itself, and the slot stays warm for the next run (`llama-rig down ocr` frees the VRAM).

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
| `02_audio_asr` | Transcribe speech via `audiocpp` (CrisperWhisper 2.0, verbatim + word timings); `--diarize` adds `Name:` per turn | `01_acquire/output/audio.wav` | `output/transcript.md` *(edit/correct terms)* |
| `03_visual_sample` | Keyframe (`-skip_frame nokey`), scene-cut, or fps sampling with PTS timing | `01_acquire/output/source_video.mp4` | `output/frames/`, `manifest.json` |
| `04_visual_gate` | Perceptual dedup (dHash) + blank rejection, or h2o vision gate | `03_visual_sample/output/manifest.json` | `output/gated_frames.json` *(check kept frames)* |
| `05_visual_ocr` | OCR via LightOnOCR-3-0.8B or MiniCPM-OCR-1.0 (+ structural gate) | `04_visual_gate/output/text_frames/` | `output/ocr_timeline.md` *(fix OCR typos)* |
| `06_synthesize` | Merge audio transcript & visual OCR into notes | `02_audio_asr` + `05_visual_ocr` | `output/mined_video.md` *(final deliverable)* |


## Quick Usage

### 1. Initialize a video mining workspace

```bash
CLI=scripts/videomine.py
python3 $CLI init ./my_video_run "https://www.youtube.com/watch?v=..."
# Or with a local video file:
python3 $CLI init ./lecture_run ~/Videos/lecture.mp4
```

> **Short-form (Shorts, Reels, TikTok) goes to `vault-mine`, not to the 6-stage
> workspace** — one download, one transcript, a notes file, no stage ceremony.
> See [Creator Video Vault](#-creator-video-vault-vault-mine).

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

`--ocr lighton` (default) keeps LightOnOCR-0.8B on `:8082`. `--ocr minicpm` runs
MiniCPM-OCR-1.0 on `:18499` (a throwaway child that is stopped when the stage
ends) with `Text Recognition:` and then applies the `kem-ocr` structural gate
(`text` mode): frames whose OCR is empty, repetitive or non-textual are dropped
before they reach the timeline. Frames whose text is ≥90% the same as the
previous kept frame are dropped too, so a slide that sits on screen for a minute
becomes one entry instead of ten. The gate is imported from the sibling
`kem-ocr` skill; if that skill is missing the OCR still runs and the structural
field is simply absent.

**The OCR slot starts itself.** Stage `05_visual_ocr` probes `:8082`; if nothing
answers it runs `llama-rig up ocr` (measured 1.1 s from cold to serving) and
says so in the log. The slot is then left running, because that warm server is
what makes a repeated run cheap. If the backend genuinely cannot start, the
stage fails with the one command that fixes it rather than writing an empty
timeline that would mark the stage COMPLETE and let `06_synthesize` emit
visual-less notes that look successful. Never report "the server is down" — run
`llama-rig up ocr` or let the stage do it.

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

## Speed

Acquisition is the stage that used to decide the wall clock, and it is tuned:

| | default yt-dlp | this skill |
|---|---|---|
| 117 s video | 33 MB (4K AV1) / 6.2 s | 7.4 MB (1080p) / 3.0 s |
| frame extraction after | 4.4 s | 0.9 s |
| 8 min video | 15.0 s | 9.6 s |

`-S res:1080` caps by the *smaller* dimension, so a 720x1280 reel is capped at
720 wide and a 2160p lecture at 1080 tall; `--concurrent-fragments 8` fetches
DASH segments in parallel and `--remux-video mp4` stream-copies instead of
re-encoding. Override the cap with `--max-res 720` (or `VIDEOMINE_MAX_RES`) when
the on-screen text is large; raise it to `1440` only for dense code screens.

Everything else that looked slow was overhead, not work: the signature gate now
decodes every frame in **one** ffmpeg pass instead of one process per frame, the
dHash gate reads JPEGs through `Image.draft()` at 1/8 scale (12x faster, same
hashes), and the acquisition step no longer runs yt-dlp twice.

Instagram and TikTok serve the media only to a logged-in session often enough
that an unauthenticated attempt looks like a hang. Put a jar at
`~/.config/yt-dlp/cookies.txt` (or set `YTDLP_COOKIES`) and it is passed through
automatically.

## Speech models and speakers

Two ASR models are installed, and they are not interchangeable. Measured on the
same 117 s technical video (454 words):

| `--asr-model` | wall | word timings | technical terms |
|---|---|---|---|
| `crisperwhisper` (default) | 5.7 s (20x) | **yes** | "git", "VS Code" — correct |
| `nemotron` | 1.5 s (78x) | no | "Get", "VSCOD", "RunGit Add" |

`crisperwhisper` is the default because this skill mines *technical* video and
because stage `02_audio_asr` needs word timings for its timestamps: audiocpp's
own default is `nemotron`, which returns text without them, so the stage would
collapse into one untimestamped blob. Reach for `nemotron` when the audio is
long and the words are ordinary.

### Speaker labels (`--diarize`)

Diarization is one extra pass over the same recording with Nemotron 3, and it
needs no server:

```bash
# ICM pipeline: labels land in 02_audio_asr/transcript.md and transcript.json
python3 $CLI run ./my_video_run --diarize
python3 $CLI run ./my_video_run --speaker-names Kem,Chase

# Vault: same flags on `add` / `kem`
vault-mine add "https://www.youtube.com/watch?v=..." --creator kem_glitch --diarize
vault-mine add ./panel.mp4 --creator kem_glitch --speaker-names Kem,Chase,Vince
```

Measured: 0.8 s for 2 minutes of audio, 0.8 s for a 16 s two-voice clip that it
split into 4/4 turns. A transcript paragraph breaks on a speaker change, so the
label is true for its whole line:

```markdown
**[00:00] Speaker 1:** The pipeline downloads the reel, then transcribes it locally.

**[00:04] Speaker 2:** Right, and the diarization pass should tell us who is speaking.
```

Ids are **arrival order**, not identity: `speaker_0` is whoever spoke first.
Read the first line before trusting `--speaker-names`. With `--asr-model
nemotron` there are no word timings, so labels land on whole segments instead of
per turn — the stage says so in its log. Overlapping speech is not separated
(crosstalk lands in one turn).

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

# Fast single-pass video mining directly from URL into the vault (~7-13s end-to-end):
vault-mine add "https://www.instagram.com/reel/..." --creator "kem_glitch" --title "graph-memory-rant"

# Ultra-fast mining with Nemotron streaming STT:
vault-mine add "https://..." --model nemotron

# Cap the download lower when the screen text is big:
vault-mine add "https://..." --max-res 720

# Label who said what (interviews, panels, two-person podcasts):
vault-mine add "https://..." --diarize
vault-mine add "https://..." --speaker-names Kem,Chase

# Import an existing mined ICM workspace into the vault:
vault-mine import ./my_video_run --creator "kem_glitch" --title "5-agents-worktree"

# Rebuild vault catalog index:
vault-mine reindex
```

A reel is mined in one pass: download (with its info JSON and any subtitle
track), transcript, dHash-deduped keyframes, notes. `--ocr auto` (default)
starts `:8082` through `llama-rig` when it is down, then OCRs the four sampled
frames; `--ocr never` skips it; `--ocr always` refuses to finish without it
instead of quietly writing notes with no diagram text. Progress streams line by
line — a run never goes silent for its whole duration.

YouTube rolling captions are parsed as *increments*: each cue in an auto-named
`.vtt` restates the previous line, so the parser keeps the tag-carrying line,
trims the overlap with what it already emitted, and starts a new timestamped
paragraph after a 5 s gap. The transcript in `transcript.md` is the spoken text
once, not three times. `--prefer-asr` still forces `audiocpp` when the caption
track mangles the technical terms.

### Vault publish done-check (mandatory)

`creator-vault` is **its own git repo** with a `creator-vault.git` origin.
`sync-skills publish` does not touch it. A reel is not vaulted until the entry is
committed and pushed:

```bash
V=/run/media/rodri/AI/creator-vault
vault-mine reindex                     # refresh INDEX.md
git -C "$V" status --short             # inspect; scope out unrelated untracked work
git-sync guarded-commit --repo "$V" \
  --include kem_glitch/<new-entry> \
  --include INDEX.md \
  --include kem_glitch/REELS_LEDGER.md \
  -m "docs(vault): mine <reel-id> — <topic>"
git -C "$V" show --stat HEAD | grep <new-entry>   # PROVE the entry is in the commit
git -C "$V" push origin main
git -C "$V" status -sb                 # clean, except unrelated untracked dirs
```

**Use the directory prefix without a trailing slash.** `--include <entry>/` can
silently stage only `INDEX.md`, publishing a pointer to content that is not in
the commit. The `git show --stat HEAD | grep <new-entry>` line is the gate: if it
prints nothing, re-commit with the bare prefix before pushing.

`source.mp4` is gitignored: the video stays local, notes/transcripts/frames
publish. The generated `notes.md` is a **template stub** (`"Core Thesis | '...'"`)
— write the synthesis before committing. If reindex picked up an unrelated
untracked reel in `INDEX.md`, remove that line before staging, or use `--include`
to stage only your own entry.

## Tests

```bash
python3 tests/test_videomine.py
```
