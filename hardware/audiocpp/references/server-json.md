# `server.json` — audio.cpp install config (recoverable copy)

The config an audio.cpp install runs on: which models exist, which GGUF backs each
one, and which voice presets are wired. The install lives on ext4; this copy lives
in git so it survives a re-extraction, a wiped install, or a machine rebuild.

**Snapshot:** audio.cpp 0.9.4 · 2026-11-08 · 15 models, 3 of them pointing at absent files (below)
**Machine copy:** `references/server.json` — the seed the switch script installs
**Why this file exists:** the config was never versioned. On 2026-11-08 a rebuild
revealed that `/run/media/rodri/AI/sh/run-audiocpp.sh` had always pointed at
`sh/audiocpp_server` and `sh/server.json`, neither of which ever existed there —
0 commits anywhere referenced either path. Prose survives in a repo; a 5 KB JSON
on an NTFS volume does not.

## Restore

```bash
# the switch script seeds a fresh install that ships no config (v0.9.4 does not)
hardware/audiocpp/scripts/switch-version.sh /path/to/audio-vX.Y.Z-bin-ubuntu-x64-vulkan

# or by hand
cp references/server.json /run/media/rodri/AI/audio.cpp/server.json
```

## What is in it

| id | family | task | mode | GGUF | on disk |
|---|---|---|---|---|---|
| `kokoro` | kokoro_tts | tts | streaming | `kokoro-82m-bf16.gguf` | ✅ |
| `kitten` | kitten_tts | tts | offline | `kitten-tts-mini-0.8-orig.gguf` | ✅ |
| `nemotron-asr` | nemotron_asr | asr | streaming | `nemotron-3.5-asr-streaming-0.6b-q8_0.gguf` | ✅ |
| `nemotron-asr-f16` | nemotron_asr | asr | streaming | `nemotron-3.5-asr-streaming-0.6b-f16.gguf` | ✅ |
| `crisperwhisper` | crisperwhisper | asr | offline | `crisperwhisper-2-large-q4_k.gguf` | ✅ |
| `supertonic` | supertonic | tts | streaming | `supertonic-3-q8_0.gguf` | ✅ |
| `omnivoice` | omnivoice | tts | streaming | `omnivoice-q8_0.gguf` | ❌ absent |
| `omnivoice-bf16` | omnivoice | tts | streaming | `omnivoice-bf16.gguf` | ✅ |
| `audio8-tts` | audio8_tts | tts | streaming | `audio8-tts-preview-0.6b-q8_0.gguf` | ✅ |
| `audio8-tts-bf16` | audio8_tts | tts | streaming | `audio8-tts-preview-0.6b-bf16.gguf` | ❌ absent |
| `index-tts2` | index_tts2 | tts | offline | `index-tts2_5-q8_0.gguf` | ✅ |
| `index-tts2-f16` | index_tts2 | tts | offline | `index-tts2_5-f16.gguf` | ❌ absent |
| `higgs-tts` | higgs_audio_tts | tts | offline | `higgs-audio-v3-tts-4b-q8_0.gguf` | ✅ |
| `fish-s2-pro` | fish_audio | tts | offline | `fish-audio-s2-pro-q4_k.gguf` | ✅ |
| `aligner` | qwen3_forced_aligner | align | offline | `qwen3-forced-aligner-0.6b-q8_0.gguf` | ✅ |

The three ✗ entries are stale: they cost one failed request each and nothing else.
Delete them rather than leave a config describing files that do not exist.

### Voice presets

- **kokoro** — 15 `voice_id` presets, default `af_heart` (US female). UK/JP/ZH sets present.
- **audio8-tts** — two clone presets, each a `voice_ref` wav plus the `reference_text`
  that wav actually says:
  - **`maomao`** (default) — `/run/media/rodri/AI/voice/maomao.wav`, 503 KB
  - `egirl` — `/run/media/rodri/AI/voice/egirl.wav`, 895 KB

A clone preset is only as good as its reference text matching the audio word for word.
`audiocpp_cli.py:612` falls back to `maomao.wav` for any `audio8_tts`, `index_tts2` or
`fish_audio` request that names no reference.

## The file

```json
{
  "host": "127.0.0.1",
  "port": 8081,
  "backend": "vulkan",
  "device": 0,
  "threads": 4,
  "lazy_load": true,
  "max_loaded_models": 3,
  "busy_timeout_ms": 300000,
  "models": [
    {
      "id": "kokoro",
      "family": "kokoro_tts",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/kokoro-82m-bf16.gguf",
      "task": "tts",
      "mode": "streaming",
      "default_voice_preset": "af_heart",
      "voice_presets": {
        "af_heart": { "voice_id": "af_heart" },
        "af_bella": { "voice_id": "af_bella" },
        "af_nicole": { "voice_id": "af_nicole" },
        "af_sarah": { "voice_id": "af_sarah" },
        "am_adam": { "voice_id": "am_adam" },
        "am_michael": { "voice_id": "am_michael" },
        "bf_emma": { "voice_id": "bf_emma" },
        "bm_george": { "voice_id": "bm_george" },
        "ef_dora": { "voice_id": "ef_dora" },
        "ff_siwis": { "voice_id": "ff_siwis" },
        "hf_alpha": { "voice_id": "hf_alpha" },
        "im_nicola": { "voice_id": "im_nicola" },
        "jf_alpha": { "voice_id": "jf_alpha" },
        "zf_xiaobei": { "voice_id": "zf_xiaobei" },
        "zm_yunjian": { "voice_id": "zm_yunjian" }
      },
      "session_options": { "language": "en-us" }
    },
    {
      "id": "kitten",
      "family": "kitten_tts",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/kitten-tts-mini-0.8-orig.gguf",
      "task": "tts",
      "mode": "offline"
    },
    {
      "id": "nemotron-asr",
      "family": "nemotron_asr",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/nemotron-3.5-asr-streaming-0.6b-q8_0.gguf",
      "task": "asr",
      "mode": "streaming",
      "session_options": { "language": "en-US" }
    },
    {
      "id": "nemotron-asr-f16",
      "family": "nemotron_asr",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/nemotron-3.5-asr-streaming-0.6b-f16.gguf",
      "task": "asr",
      "mode": "streaming",
      "session_options": { "language": "en-US" }
    },
    {
      "id": "crisperwhisper",
      "family": "crisperwhisper",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/crisperwhisper-2-large-q4_k.gguf",
      "task": "asr",
      "mode": "offline"
    },
    {
      "id": "supertonic",
      "family": "supertonic",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/supertonic-3-q8_0.gguf",
      "task": "tts",
      "mode": "streaming"
    },
    {
      "id": "omnivoice",
      "family": "omnivoice",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/omnivoice-q8_0.gguf",
      "task": "tts",
      "mode": "streaming"
    },
    {
      "id": "omnivoice-bf16",
      "family": "omnivoice",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/omnivoice-bf16.gguf",
      "task": "tts",
      "mode": "streaming"
    },
    {
      "id": "audio8-tts",
      "family": "audio8_tts",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/audio8-tts-preview-0.6b-q8_0.gguf",
      "task": "tts",
      "mode": "streaming",
      "default_voice_preset": "maomao",
      "voice_presets": {
        "maomao": {
          "voice_ref": "/run/media/rodri/AI/voice/maomao.wav",
          "reference_text": "Everyone has a price for their dreams, and I merely facilitate the transaction. If you seek to ascend, you must be prepared to offer something truly precious. Is it your memories or perhaps your future? Whatever you choose, the results will be quite exquisite. Shall we begin?"
        },
        "egirl": {
          "voice_ref": "/run/media/rodri/AI/voice/egirl.wav",
          "reference_text": "Hey why are you sitting here all alone in the corner come on let me sit next to you what's wrong you're being way too quiet tonight I know you're not usually like this is it because of what happened earlier don't worry about that just relax with me"
        }
      }
    },
    {
      "id": "audio8-tts-bf16",
      "family": "audio8_tts",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/audio8-tts-preview-0.6b-bf16.gguf",
      "task": "tts",
      "mode": "streaming"
    },
    {
      "id": "index-tts2",
      "family": "index_tts2",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/index-tts2_5-q8_0.gguf",
      "task": "tts",
      "mode": "offline"
    },
    {
      "id": "index-tts2-f16",
      "family": "index_tts2",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/index-tts2_5-f16.gguf",
      "task": "tts",
      "mode": "offline"
    },
    {
      "id": "higgs-tts",
      "family": "higgs_audio_tts",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/higgs-audio-v3-tts-4b-q8_0.gguf",
      "task": "tts",
      "mode": "offline"
    },
    {
      "id": "fish-s2-pro",
      "family": "fish_audio",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/fish-audio-s2-pro-q4_k.gguf",
      "task": "tts",
      "mode": "offline"
    },
    {
      "id": "aligner",
      "family": "qwen3_forced_aligner",
      "path": "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/qwen3-forced-aligner-0.6b-q8_0.gguf",
      "task": "align",
      "mode": "offline"
    }
  ]
}
```
