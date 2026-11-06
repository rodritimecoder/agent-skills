## ⚡ Verified Vulkan RTF Performance (100% Real-Time or Faster)

Measured on `audio.cpp v0.9.3` (Vulkan, dual AMD Radeon RX 9060 XT) with
`scripts/audiocpp_cli.py benchmark`. All 12 local GGUF models run faster than
real-time (`RTF < 1.0`):

| Model | Family | Task | Audio (s) | Wall Time | RTF | Speed Multiplier | Key Specialty |
|---|---|---|---|---|---|---|---|
| **Aligner** | `qwen3_forced_aligner` | `align` | 6.10s | 53.3ms | **0.0087** | **114.4x** | Millisecond-accurate word boundaries |
| **Nemotron F16** | `nemotron_asr` | `asr` | 6.10s | 85.7ms | **0.0141** | **71.1x** | Ultra-fast streaming speech-to-text |
| **Nemotron Q8** | `nemotron_asr` | `asr` | 6.10s | 88.8ms | **0.0146** | **68.7x** | High-efficiency speech-to-text |
| **Supertonic-3** | `supertonic` | `tts` | 6.09s | 166.3ms | **0.0273** | **36.6x** | Instant conversational voice synthesis |
| **Kokoro 82M** | `kokoro_tts` | `tts` | 7.30s | 398.7ms | **0.0546** | **18.3x** | Expressive studio narration & voice IDs |
| **Kitten-TTS** | `kitten_tts` | `tts` | 9.94s | 852.9ms | **0.0858** | **11.7x** | Lightweight edge TTS |
| **CrisperWhisper 2.0** | `crisperwhisper` | `asr` | 6.10s | 609.1ms | **0.0999** | **10.0x** | Verbatim acoustic transcription & disfluencies |
| **Omnivoice** | `omnivoice` | `tts` | 5.07s | 1108.5ms | **0.2186** | **4.6x** | High-fidelity multi-speaker synthesis |
| **Audio8** | `audio8_tts` | `tts` | 5.48s | 2033.0ms | **0.3710** | **2.7x** | Zero-shot reference voice cloning |
| **Higgs Audio v3** | `higgs_audio_tts` | `tts` | 6.24s | 2492.7ms | **0.3995** | **2.5x** | 4B Flagship emotive voice generation |
| **Index-TTS 2.5** | `index_tts2` | `tts` | 6.66s | 4801.9ms | **0.7206** | **1.4x** | High-precision reference cloning |
| **Fish Audio S2 Pro** | `fish_audio` | `tts` | 5.99s | 4985.2ms | **0.8322** | **1.2x** | Production-grade zero-shot voice clone |

---
