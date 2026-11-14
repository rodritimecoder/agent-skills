---
name: audiocpp

description: >
  Local audio intelligence: speech-to-text, text-to-speech, forced alignment and voice
  cloning, powered by audio.cpp v0.9.4 on dual AMD Radeon RX 9060 XT GPUs. Every model runs
  faster than real time. Use to transcribe a recording, turn speech into text, narrate or
  speak text out loud to a wav file, clone a voice, align a transcript to its audio, or work
  out who said what. For a spoken chat page with an avatar, use companion.

compatibility: "Requires Dual AMD Radeon RX 9060 XT GPUs with Vulkan and the audio.cpp v0.9.4 binary."
allowed-tools: "Bash(audiocpp:*) Bash(python3:*) Read Write"
---

> **Model layer:** the server behind this skill is registered in the `model-layer` skill (slot `:8081`) — launcher, weights files, health and quirks. Read it before starting, swapping or debugging the model. If it is down, the client starts it via `llama-rig up audio` (`--no-autostart` skips).
>
> **Orientation:** `README.md` routes tasks; `CONTEXT.md` holds the live state, the invariants and the failure modes; `scripts/check-docs.py` fails when the two disagree with the install.

# Local Audio Intelligence (`audiocpp`)

Hardware-accelerated speech-to-text, text-to-speech, forced alignment and voice
cloning, powered by `audio.cpp v0.9.4` on **dual AMD Radeon RX 9060 XT** GPUs
over Vulkan. Every model runs faster than real time, so a minute of audio
transcribes in under a second and a sentence narrates in under fifty
milliseconds.

---

## 🏛️ The Models

| Model | Task | Reach for it when |
| :--- | :--- | :--- |
| `nemotron` | `asr` | Fast streaming transcription — the default |
| `crisperwhisper` | `asr` | Verbatim accuracy, keeping disfluencies |
| `supertonic` | `tts` | Instant conversational speech — the default |
| `kokoro` | `tts` | Expressive narration, or a named voice ID |
| `fish_audio` | `tts` | Zero-shot voice cloning from a reference clip |
| `qwen3_forced_aligner` | `align` | Millisecond word boundaries for subtitles |
| `nemotron_3_diar` | `diar` | Who spoke when — up to 8 speakers, no word output |

---

## 🎙️ Speaker Diarization

`run-diarization.sh` is the one-shot tool: it extracts a 16 kHz mono track,
runs Nemotron 3 Diarization, and stamps an existing WebVTT/SRT with names.

```bash
DIAR="/run/media/rodri/AI/audio.cpp/run-diarization.sh"

# 1. Who spoke when — turns.json + a talk-time summary
"$DIAR" talk.mp4

# 2. Label an existing transcript with real speaker turns
"$DIAR" talk.mp4 --vtt talk.vtt --names Kem,Chase,Vince

# 3. Swap ids if arrival order guessed wrong (or add the 4th name)
"$DIAR" talk.mp4 --vtt talk.vtt --map 0=Chase,1=Kem,2=Vince

# 4. A directory of recordings, one output folder each
"$DIAR" recordings/ --out /tmp/diar
```

Output lands in `<input>.diar/`: `turns.json` (raw, samples at 16 kHz),
`transcript.vtt` (`<v Name>` voice spans), `transcript.srt`, `transcript.txt`,
`summary.json` (talk time, share, turn count, mean confidence per speaker).

- **BF16 is the default and is parity-safe.** `--precision q8_0` is 102 MB
  instead of 189 MB but can move speaker boundaries and change turn counts.
- **Ids are arrival order, not identity.** `speaker_0` is whoever spoke first,
  so always check the first line before trusting `--names`.
- **Overlap is not separated.** Crosstalk lands in one turn; the model does not
  split simultaneous speech. `summary.json` flags cues where a second speaker
  held >30% of the cue.
- **Diarization needs audio.** A transcript alone cannot be diarized; the
  recording is the input and `--vtt` only supplies the words.
- **One process, no server.** It runs `audiocpp_cli` directly, so the :8081
  server keeps its own model loaded. `--latency-profile` and
  `--threshold/--min-frames/--pad-frames` are passed straight through.

---

## 🛠️ CLI Quickstart

```bash
AC="/run/media/rodri/AI/skills/audiocpp/scripts/audiocpp_cli.py"

# 1. Transcribe — clean stdout, pipes straight into a file
python3 $AC asr recording.wav > transcript.txt

# 2. Transcribe with a specific model
python3 $AC asr recording.wav --model nemotron
python3 $AC asr speech.wav --model crisperwhisper

# 3. Transcribe to typed JSON
python3 $AC asr speech.wav --json
# {
#   "task": "asr",
#   "model": "crisperwhisper",
#   "text": "System diagnostic complete.",
#   "duration_s": 2.45,
#   "wall_ms": 78.4,
#   "rtf": 0.032,
#   "words": [...]
# }

# 4. Narrate to a wav file
python3 $AC tts "System diagnostic complete. All parameters nominal." --out notice.wav

# 5. Narrate with a named voice
python3 $AC tts "Welcome back, Rodrigo." --model kokoro --voice af_bella --out welcome.wav

# 6. Clone a voice from a reference clip
python3 $AC tts "Cloned voice sample." --model fish --voice-ref /run/media/rodri/AI/voice/maomao.wav --out clone.wav

# 7. Synthesize to typed JSON
python3 $AC tts "Processing completed." --json

# 8. Extract word-level timestamps
python3 $AC align audio.wav "Exact transcript of the speech." --json

# 9. Inspect the binary, the Vulkan device, and the installed models
python3 $AC doctor [--json]

# 10. List all 12 installed models
python3 $AC models [--json]

# 11. Run the live RTF benchmark across every model
python3 $AC benchmark [--json]

# 12. Talk to a remote node over Tailscale
export AUDIOCPP_HOST="rodri-x870-taichi-creator.tail2975a8.ts.net"
python3 $AC doctor --host "$AUDIOCPP_HOST"
python3 $AC asr speech.wav --model crisperwhisper
python3 $AC tts "Synthesizing from laptop over Tailscale" --model kokoro -o speech.wav
```

---

## 🔀 Switching builds

The install is reached through one symlink, so a version change is a link flip:

```
/run/media/rodri/AI/audio.cpp -> /run/media/rodri/AI/audio-v0.9.4-bin-ubuntu-x64-vulkan
```

Flip it with the gate, never by hand:

```bash
S=hardware/audiocpp/scripts/switch-version.sh
$S --status                                  # what is live, and what answers :8081
$S /home/rodri/audio-v0.9.5-bin-ubuntu-x64-vulkan
$S --rollback
```

The script validates the candidate by running its own `audiocpp_cli --version`
before touching anything — that single call is what rejects a HIP/ROCm build with
no runtime (`libhipblas.so.3`), instead of finding out on the port — seeds a
missing `server.json` from `references/server.json`, restarts :8081, and restores
the previous install if the new one fails its health check.

## Reference

- `README.md` — what this folder is, and where to go for each task
- `CONTEXT.md` — the contract and the **live state**: version, symlink, invariants, failure modes
- `references/benchmarks.md` — measured RTF, wall time and speed for all 12 models
- `references/server-json.md` — the install config, recoverable, with the model and voice-preset inventory
- `references/server.json` — the same config as a seed the switch script installs
- `scripts/check-docs.py` — fails when this folder's claims disagree with the install
