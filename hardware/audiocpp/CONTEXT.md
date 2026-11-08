# CONTEXT — audiocpp

The contract for this folder and the state behind its claims. `README.md` routes;
this file says what is true right now and how to prove it. Facts here are checked
by `scripts/check-docs.py`; if this file and the install disagree, the script fails.

## Inputs

Working, this run:

- an audio file: `.wav` 16 kHz mono is canonical, anything ffmpeg reads works
- a text string, for TTS

Reference, every run:

- `/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/` — the GGUF weights
- `/run/media/rodri/AI/voice/` — clone references (`maomao.wav`, `egirl.wav`)
- `references/server.json` — the install config, seed for a fresh extraction

## Process

Two paths, and they do not share a transport:

- **ASR** — `scripts/audiocpp_cli.py asr` resolves the slug to a `family` + path and
  runs the `audiocpp_cli` **binary** (`--task asr --family … --model <gguf>`). Word
  timestamps (`--words-out`) exist only on this path, which is why the miner uses it.
- **TTS / align** — the same wrapper, but requests reach the **server** on `:8081`
  (`/v1/audio/speech`, `/v1/audio/transcriptions`), which lazy-loads up to 3 models.

Both hang off one symlink, so a version change is one link flip.

## Outputs

- transcript: text to stdout, or `--out <file>`, or `--words-out <json>` for words + samples
- speech: a `.wav` at the requested path
- alignment: word-level timings for a given transcript

## Check

```bash
python3 scripts/check-docs.py          # this file + README vs the live install
python3 -m unittest tests/test_audiocpp.py
scripts/switch-version.sh --status     # link, version, config, :8081
python3 scripts/audiocpp_cli.py doctor # binary, config, GPU, model files
```

`check-docs.py` is the gate that was missing. It fails when a claim in this folder
disagrees with what is installed, which is exactly how every fault below survived.

## Live state — 2026-11-08

- **Version:** `0.9.4`  <!-- check-docs.py: binary, this line and ports.json must agree -->
- **Install:** `/run/media/rodri/AI/audio-v0.9.4-bin-ubuntu-x64-vulkan` (git `f7ac446f`, built 2026-11-04)
- **Symlink:** `/run/media/rodri/AI/audio.cpp` -> the install above
- **Backends:** `cpu,vulkan` — Vulkan only in practice, `RADV GFX1200`
- **Skill path:** `/run/media/rodri/AI/skills/audiocpp` -> `~/src/my-agent-skills/hardware/audiocpp`
- **Model specs:** 140 families; **configured:** 15 in `server.json`
- **Server:** `127.0.0.1:8081`, `lazy_load`, `max_loaded_models 3`
- **Port slot:** `ports.json` id `audio`, service `audio.cpp 0.9.4 (Vulkan)`, owning skill `audiocpp`
- **Defaults:** tts `kokoro` · asr `nemotron` — both served `mode: streaming`
- **Word timings:** only `crisperwhisper` emits them; `--words-out` with any other model warns and writes nothing
- **Launcher:** `/run/media/rodri/AI/sh/run-audiocpp.sh` (falls through to the symlink)
- **Previous install:** `/home/rodri/audio-v0.9.3-bin-ubuntu-x64-vulkan`, kept as fallback
- **Unusable:** `/home/rodri/Downloads/audio-v0.9.4-bin-ubuntu-x64-rocm10.0.0-test` — needs the ROCm 10.0.0 runtime, dies on `libhipblas.so.3`
- **Stale config entries:** `omnivoice`, `audio8-tts-bf16`, `index-tts2-f16` — declared, tolerated, each costs one failed request

Model inventory and voice presets live in `references/server-json.md`; measured
speed lives in `references/benchmarks.md`. Neither is repeated here.

## Invariants

1. **One switch point.** `/run/media/rodri/AI/audio.cpp` is the only path that names a
   version; the install itself is a versioned sibling directory on the same volume.
   Nothing outside this folder hardcodes `audio-v0.9.x-…`.
2. **Vulkan only.** The ROCm prebuilt needs its own runtime and measures slower here;
   it is upstream parity testing, never the serving path.
3. **The config is source, the index is not.** `server.json` is versioned in
   `references/`; `rag.db`-style artifacts are disposable. An install that ships no
   config gets seeded, never assumed.
4. **`crisperwhisper` stays the mining model.** `video-miner` passes `--model`
   explicitly, so changing the CLI default cannot move it.
5. **Default TTS is `kokoro`, default ASR is `nemotron`, both `streaming`.** The CLI
   constants, `server.json`'s modes and the `Defaults:` line in this file are checked
   against each other. `crisperwhisper` stays the mining model — requested explicitly,
   and the only family that returns word timings.

## Failure modes, as they actually happened

| Symptom | Cause | Fix that now exists |
|---|---|---|
| `not executable: …/sh/audiocpp_server` | the launcher assumed its binary and config sat beside it in `sh/`; they never did | launcher falls through to the symlink; `check-docs.py` asserts it |
| A rebuild found no `server.json` | the config was never versioned (0 commits anywhere referenced it) | `references/server.json` + `server.json.md` |
| `ports.json` said `0.9.0`, binary said `0.9.3` | the fact lived in two places, neither checked | one `Version:` line, cross-checked |
| `architecture.md` said `0.9.3`, symlink pointed at `0.9.4` | a duplicate of a fact that has one home | folded into this file |
| `maomao` read as a model, then as a kokoro voice | it is an `audio8_tts` **voice preset** in `server.json` | inventory in `references/server-json.md` |
| ROCm build promoted and then refused to run | nothing validated a candidate before the flip | `switch-version.sh` runs `--version` first, rolls back on failure |
| Transcript header said `Duration: N/A` | Instagram metadata carries no duration | `video-miner` writes ffprobe duration (pending) |

## Changing the version

```bash
S=scripts/switch-version.sh
$S --status                                   # what is live now
$S /home/rodri/audio-vX.Y.Z-bin-ubuntu-x64-vulkan
$S --rollback
```

The script validates the candidate, seeds a missing `server.json`, restarts `:8081`,
health-checks it and restores the previous install on failure. After any switch, run
`scripts/check-docs.py` and update the `Version:` line and the state block above —
the script exists to catch you when you forget.
