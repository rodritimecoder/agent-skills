# Choosing an ASR model in audio.cpp

Researched 2026-10-02 against `0xShug0/audio.cpp` **v0.9.0** (git `795c45fb`, 2026-09-30;
100+ models, 170+ variants). `docs/models/qwen3.md` is the authority for Qwen3 details.

## The short answer

**Whisper is not in audio.cpp, and you should not chase a replacement.** The problem you
actually hit was not "no Whisper" — it was that the RNNT model's **word tokens are fragments**
(`who`+`le`, `c`+`or`+`n`+`er`), which makes caption search return zero hits and makes word-level
anchoring unusable. That is a *timestamp* problem wearing a transcription costume.

Add **`qwen3_forced_aligner`** (Qwen3-ForcedAligner-0.6B). Verified working on this box — see
"Measured results" below. Keep Nemotron for free-running ASR and live dictation.

## The long-audio catch, and the workaround that works

From `docs/models/qwen3.md`:

> Standalone forced alignment **does not chunk audio** because exact transcript/audio chunk pairing
> cannot be inferred safely from a raw transcript. For long-audio timestamping, use Qwen3 ASR with
> `--words-out` and `qwen3_asr.forced_aligner_model_path`; ASR chunks the audio first, then aligns
> each recognized transcript to its matching audio chunk.

So `--task align` on a 6:54 file dies immediately:

```
audiocpp_cli failed: Qwen3 ASR audio encoder token count exceeds max_source_positions
```

**The workaround is that the warning is about a raw transcript — and captioned video does not have
one.** When the transcript already carries timings, the pairing is known, so slice the audio to the
caption cues and align each slice, then shift the results back onto the global clock. This is
`reference-video-mining/scripts/align.py`. It needs no ASR model at all, so it works with only the
aligner GGUF installed.

## Measured results — 6:54 reference clip, 0.9.0 + Vulkan (RX 9060 XT)

| | |
|---|---|
| Chunks | 25 × ~18 s |
| Words out | **1287** vs **1287** caption words — exact 1:1 |
| Wall time | **22 s** total, incl. 25 model loads |
| RTF | 0.015 (66× realtime), 3.9 GB peak footprint |
| Output | `--words-out` JSON: `word`, `start_sample`, `end_sample` at 16 kHz, **chunk-relative** |

The decisive result is the first aligned line versus the Nemotron output for the same audio:

```
aligner:    So this whole video came out of one folder on my computer
Nemotron:   So this who le video ca me out of one f ol der on my comp u ter
```

The aligner cannot mishear, because it is not listening for words — it is placing words you already
have. That makes it strictly more reliable than any recogniser for anchoring, including a 1.7B one.

Caveat: it still inherits the caption track's errors as *positions*. `context.md` came back as one
token `contextmd` (0.80 s), and `handdrawn` for "hand-drawn" — text you did not supply is never
corrected, only placed.

## Why the aligner beats "find a better transcriber"

Your two-transcript setup is the right shape, and it can be improved without a new ASR at all:

```
YouTube captions (clean text, sentence-level)  ← authoritative words
Qwen3-ForcedAligner (known text + audio)        ← authoritative timings
        = frame-accurate word timings, no fragmentation, no ASR error compounding
```

The forcing means a mis-heard word in the audio cannot corrupt the alignment the way it does with
free-running ASR. For anchoring cues to verbatim phrases — which is exactly what a storyboard needs
— that is strictly better than a bigger recogniser.

Nemotron's real strength is speed (0.108 RTF on your box: 6:54 in 46 s). Keep it as the fast path
and the fallback when the aligner has no match.

## The Whisper-analogue shortlist, if you want a second transcriber anyway

| Family | Langs | Size | Why / why not |
|---|---|---|---|
| **`qwen3_asr`** 0.6B / 1.7B | 26 incl. zh/en/ja/ko/ar/es/fr/de | Q8 | Best default. Whisper's slot. |
| **`voxtral_realtime`** Voxtral-Mini-4B | ~30 | Q4_K, streaming | Mistral, very strong 2026 model; heavier. |
| **`cohere_asr`** Transcribe 03-2026 | 13 | Q8/Q4_0 | High quality, less language coverage than Qwen3. |
| **`granite5asr`** (community) 470M TurboCTC | en | Q8 | **The actual Whisper lineage** — IBM distilled `whisper-large-v3-turbo` *from* Granite Speech CTC. Ultra-fast. But it is CTC, so expect the same class of fragmentary tokens as Nemotron. |
| **`moonshine_asr`** tiny/small/medium | en | Q8, streaming | Very fast, lower accuracy. Live-caption tier. |
| **`canary_asr`** 180M Flash | en/de/es/fr | Q8 | NVIDIA, small, 4 languages only. |
| **`moss_transcribe_diarize`** | 50+ | Q8/Q4_K, streaming | Only if you need **speaker labels** — e.g. multi-speaker panels and interviews. |
| **`vibevoice_asr_streaming`** 1.5B / 7B | 10 | Q4, streaming | Speaker turns; 7B is heavy for a 0.6B-class box. |

Avoid for this use case: `gigaam_asr` (ru/kk/ky/uz + en), `hviske_asr` (da), `fun_asr_nano`
(zh/en/ja), `citrinet_asr` (en, but CTC), `niagara_asr` (en, tiny CTC), `higgs_audio_stt` (en only).
All CTC/RNNT-first, all English-or-narrow, none of them solve timestamps better than what you have.

## Adding a model on this box

No skill changes needed — `asr.py` is already model-agnostic and auto-detects the newest install
(`/run/media/rodri/AI/audio.cpp`, then the versioned installs, then any `AUDIOCPP_APP_DIR` override):

```bash
# 1. weights: GGUF from https://huggingface.co/audio-cpp/audio.cpp-gguf
cp qwen3-asr-*.gguf /run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/

# 2. select at call time
export AUDIOCPP_ASR_MODEL=qwen3-asr          # or --model / --model-path / --family
export AUDIOCPP_GGUF_DIR=/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf
export AUDIOCPP_ASR_FAMILY=qwen3_asr

# 3. confirm the server actually loaded it
python3 ~/.gemini/config/skills/audiocpp-asr/scripts/asr.py doctor
```

### The aligner, offline, no server

`--task align` needs no server at all:

```bash
/run/media/rodri/AI/audio.cpp/audiocpp_cli \
  --task align --family qwen3_forced_aligner \
  --model /run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf/qwen3-forced-aligner-0.6b-q8_0.gguf \
  --backend vulkan --audio clip.wav --language en --text "exact transcript" --words-out words.json
```

Required: `--text` **and** `--language` (it fails with "requires transcript text and language"
otherwise). Optional `--request-option clamp_timestamps_to_audio=true` keeps repaired spans inside
the chunk. For audio over ~30 s, chunk it — see the workaround above.

The server can also run ASR with built-in alignment via
`--session-option qwen3_asr.forced_aligner_model_path=<gguf>`; that is the documented long-audio
route, but it requires the Qwen3-ASR weights and re-hears the audio, so for captioned video the
caption-driven chunker is both cheaper and more accurate.

The server holds 21 GB of weights on the external volume; check headroom before pulling a second
1–2 GB model.

## Verification plan before trusting any of it

1. Same 6:54 clip, all three: captions-only, Nemotron, Qwen3-ASR. Diff the word sequences.
2. Score word-level timestamps by how well they place Jake's named artefacts
   (`anim.py`, `stills`, `Exposure sheet`) — proper nouns are where a 0.6B model shows its age.
3. **Already done for the aligner** (see "Measured results"): 1287/1287 words, 22 s. Still open is
   whether free-running Qwen3-ASR beats Nemotron on proper nouns — that needs the ASR GGUF, which is
   not installed. If the aligner wins, make captions+aligner the default path and keep Nemotron
   only for live dictation and fast first passes.
