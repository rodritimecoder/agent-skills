---
name: companion

description: >
  Character chat page: hold to talk, and a pixel-art avatar answers out loud.
  Mic audio is resampled to 16 kHz mono, transcribed by Nemotron ASR on :8081,
  answered by the 35B on :8080, and spoken back through Kokoro one sentence at a
  time so audio starts ~1.2 s after you release the button. The avatar reuses
  pi-emote's Orchid Girl asset set; its mouth follows the real audio envelope.
  Use when asked to talk to the local model, add a voice interface to the
  homelab page, or drive an animated avatar from speech.

compatibility: "Python 3.10+ stdlib and ffmpeg. Needs audio.cpp on :8081 and llama-server on :8080."
allowed-tools: "Bash(companion:*) Bash(systemctl:*) Bash(tailscale:*) Read Write"
---

# companion

One page, one conversation, spoken out loud.

```bash
companion doctor                       # ffmpeg, both upstreams, models, avatar frames
companion serve                        # http://127.0.0.1:7778
companion serve --port 7788 --verbose
```

`doctor` exits non-zero when something is missing, so it works as a gate before
`serve`.

## Why it is not part of `deck`

`deck` is read-only by design: "a page that can evict a loaded model is one
stray click away from killing live inference." A chat page is the opposite —
it holds a conversation, POSTs to two model servers and starts playback. So it
runs as its own process on `:7778` and `deck` links to it. Restarting the chat
page never touches the status page, and a dead chat process never blanks the
dashboard.

## Pipeline

```
mic ──AudioWorklet(128 ms, 16 kHz s16le)──▶ POST /api/asr/live/{id}/pcm
                                             └─ one chunked POST ─▶ :8081
                                                /v1/audio/transcriptions/live
                                                (SSE deltas; `done` = final)
                             (rescue) ──MediaRecorder──▶ POST /api/asr
                                             └─ ffmpeg → 16 kHz WAV → multipart → :8081
                                POST /api/chat  (SSE) (when send is pressed)
                                 └─ llama-server :8080 /v1/chat/completions, streamed
                                POST /api/tts   (one call per sentence)
                                 └─ audio.cpp :8081 (kokoro, af_bella)
                                WebAudio ─▶ AnalyserNode ─▶ speakers
                                              └─ 4 mouth weights
```

Measured on this box (warm models):

| Stage | Cost |
|---|---|
| ASR, first partial | 0.99–1.25 s into speech |
| ASR, 3.2 s clip | 0.67 s |
| ASR, live pass | 0.19 s per second of audio |
| 35B first token | 0.24 s |
| Kokoro, 3.4 s of speech | 0.3–0.6 s |

Sentences are synthesised while the previous one plays, so time to first sound
is roughly `ASR + TTFT + one sentence`, not the sum of the whole reply.

## Talking to it

Hold the button and speak. The transcript types itself into the line above the
input as you go; release and the authoritative pass replaces the preview, drops
it into the input, and you press ↵ (or click ↑) to send. Nothing is sent until
you do, so a misheard word is editable first. Space does the same hold when the
page has focus and you are not typing.

The preview is not a re-transcription. The worklet slices the mic into 128 ms of
16 kHz mono PCM; each chunk is POSTed while the next one is being captured, and
the reply carries the text decoded so far. Cost is constant per second of audio,
where the old growing-buffer preview was linear (a 4 s hold re-decoded 0.9 s of
audio per pass, several passes a second).

Measured through the local proxy, 4.03 s of speech:

| Event | When |
|---|---|
| first partial | 0.99–1.25 s into speech |
| partial cadence | every 250–400 ms |
| `transcript.text.done` | 0.14–0.20 s after release |
| cost | 0.19 s per second of audio, independent of length |

`:8081` cannot be driven by the page directly: a live decoding connection needs
an incrementally delivered request body, and `ReadableStream` bodies in `fetch`
are Chrome-only (Firefox refuses). So the server proxies — the page posts PCM to
`/api/asr/live/{id}/pcm`, and one chunked connection to
`/v1/audio/transcriptions/live` is held server-side. Returning the partial in each
chunk's reply means no SSE or WebSocket is needed between page and server, and
every hop is an ordinary `Content-Length` request that `tailscale serve` proxies
untouched.

Deltas only append; the endpoint never rewrites a hypothesis mid-utterance. So
`done` is where the text is normalised — and on this model, where trailing
punctuation often goes missing. The final is what reaches the input; the partial
line only ever grows.

Release ends the utterance. The page does no silence endpointing, unlike the
terminal dictation (`mic-asr.sh`), because the button already says when you
stopped.

If the live session cannot start, or returns nothing, the clip that `MediaRecorder`
has been recording alongside it is sent to `/api/asr`, which is the old
peak-normalising path. `COMPANION_ASR_LIVE=0` forces that path outright; the
partials disappear, the transcript still arrives.

## Which microphone, and is it hearing anything

The page does not silently inherit whatever the desktop considers default. The
`mic` picker lists every `audioinput` and persists the choice in
`localStorage["companion.mic"]`; "system default" stays an option. The choice
is requested as `deviceId: {exact}`, and an unplugged device falls back to the
default instead of failing.

Next to it the diag line names the device the track actually came from and its
rate (`https ✓ · E2x2 OTG Multichannel · no signal`). That is the difference
between "the app is broken" and "the interface is at zero gain": without it,
both look like a dead button.

While the button is held a meter tracks the input RMS on a -60…-6 dBFS scale.
If it stays under -45 dBFS for a second the diag appends `no signal`, and an
empty transcription then says so explicitly instead of "didn't catch that":

```
nothing audible — the mic peaked at -72 dBFS.
Check that the mic is plugged into the selected input and its gain is up.
```

`autoGainControl` is off. The level is lifted on the server instead, where it is
predictable and measurable.

### A 10-channel interface is not a microphone

The E2x2 OTG publishes one capture PCM with ten channels: input 1 on `AUX0`,
input 2 on `AUX1`, and the DAW/loopback channels on `AUX2`–`AUX9`. A browser asks
for mono, so the mixer folds all ten into one stream and everything on them lands
in the transcript. Worse, a source that carries playback looks exactly like a
microphone that hears the room — the page cannot tell, and neither can you.

`systemd/e2x2-mic.service` publishes `AUX0` alone as a mono `Audio/Source`
called `E2x2 Mic (input 1)`. Measured on the hardware:

| Signal | Level |
|---|---|
| speaking into input 1 | −2.9 dBFS peak |
| room floor, input 1 open | −62 dBFS |
| input 2 (`AUX1`) | −81 dBFS flat, nothing connected |
| `AUX2`–`AUX9` while a tone plays | digital zero |
| the same −24 dBFS tone, recorded from `E2x2 Mic` | −63 dBFS |

The last row is the point: playback cannot reach this source digitally. A video
that still lands in a transcript came through the air, so the fix is the room
(headphones), not the routing. Input 1 also needs its gain knob to be up — at
zero gain the interface is a very good room microphone and a very poor one for
the person in front of it.

## Input level

Pro interfaces arrive quiet, and the ASR degrades sharply below -30 dBFS:

| Input peak | raw | after the +46 dB lift |
|---|---|---|
| -6 dBFS | full sentence | unchanged |
| -30 dBFS | only the first half | full sentence |
| -45 dBFS | nothing | full sentence |

`to_wav16_detailed` peak-normalises to -1 dBFS, caps the lift at 200x, and
leaves digital zero alone. White noise at -50 and -70 dBFS still decodes to
`""` after the same lift, so the boost does not manufacture words. `/api/asr`
returns `peak_db` and `gain_db` so the page can report what it heard.

The live path does not lift the level — a stream cannot be re-levelled
retroactively — and does not need to. Measured through
`/v1/audio/transcriptions/live`: a −46 dBFS clip transcribes in full, and at
−61 dBFS the words still arrive with one of them wrong. The clip the page keeps
recording alongside the stream is the rescue for a genuinely quiet hold, which
is why the two paths coexist.

## What actually streams

The ASR and the LLM both stream; TTS is one-shot per sentence, and the
pipelining above is what hides it.

| Stage | Streams? | Evidence |
|---|---|---|
| LLM | yes | SSE `delta` frames from `/v1/chat/completions` |
| ASR | yes, both directions | the page posts 128 ms PCM chunks and the server holds one chunked `POST /v1/audio/transcriptions/live`; `transcript.text.delta` frames append to the hypothesis, `transcript.text.done` carries the final. Measured: deltas concatenate exactly to the final text, first delta ~1 s in, then every 250–400 ms |
| TTS | no | `kokoro` is `mode: offline` and returns a whole wav; even `supertonic` (`mode: streaming`) returns one `named_audio_outputs` chunk per request, measured at 4.98 s of audio in a single `chunk_0` |

`POST /api/tts` therefore synthesises one sentence at a time rather than
streaming bytes.

## Two constraints worth knowing

**`nemotron-asr` only accepts 16 kHz mono audio.** Anything else returns
`Nemotron ASR streaming requires mono audio at the model sample rate`. The live
path satisfies that in the browser: the worklet resamples to 16 kHz and sends
s16le. The rescue clip is still WebM (Chrome) or MP4 (Safari), so ffmpeg runs
there. That resample also fixes accuracy: the same clip transcribes "Hey" at
16 kHz and "Hei" at 24 kHz.

**There are no visemes.** Kokoro returns audio, not phonemes, so the mouth is
driven by the RMS envelope of what is actually playing, mapped to the four
mouth weights with a decaying peak normaliser. It looks synced because it *is*
synced to the waveform — but it cannot show a specific vowel.

## Avatar

The asset set is a copy of pi-emote's `orchid_girl`: 10 states, 15 frames at
128×128, four mouth weights, blink frame. It is copied rather than referenced
because `~/.pi/agent/extensions/` is pi's to overwrite.

pi-emote's *renderers* are terminal-only (kitty, iTerm, ASCII, tmux), so no code
was imported. What was rebuilt is its state machine:

| State | Trigger | Behaviour |
|---|---|---|
| `idle` | nothing happening | blink every 3–6 s |
| `listening` | button held | frame pulses, mic hot |
| `think` | waiting for the first token | alternates `think` / `think_hard` at 650 ms |
| `talk` | audio playing | mouth weight from RMS |
| `success` | turn finished | 700 ms hold |
| `failure` | any error | 1.6 s hold |

Barge-in is real: pressing the button stops playback, drops queued audio, aborts
the in-flight chat stream and invalidates pending TTS with a sequence counter,
so a late response cannot speak over you.

## Endpoints

| Path | Purpose |
|---|---|
| `GET /` | the page |
| `GET /api/health` | `{asr, tts, llm, asr_model, asr_live, asr_lang, tts_model, voice}` |
| `POST /api/asr/live` | opens a live session → `{id, language, model, rate}` |
| `POST /api/asr/live/{id}/pcm` | raw 16 kHz mono s16le → `{text, rev, bytes, ms}` |
| `POST /api/asr/live/{id}/end` | closes the stream → `{text, partial, final, seconds, first_delta_ms, total_ms, peak_db}` |
| `POST /api/asr/live/{id}/abort` | drops the session, closes the upstream socket |
| `POST /api/asr` | raw recorded audio (rescue pass) → `{text, asr_ms, total_ms, seconds}` |
| `POST /api/chat` | `{messages:[…]}` → SSE `delta` / `done` / `error` |
| `POST /api/tts` | `{text, voice}` → `audio/wav` |
| `GET /healthz` | `ok` |

Live sessions idle out after `COMPANION_ASR_IDLE` seconds so a tab that
disappears cannot strand a decoder slot; the page also aborts on `pagehide`.

The page works whether it is mounted at `/` or under a path prefix, and the
server strips `/chat` itself, so it does not care which side removes it.

## Environment

| Variable | Default |
|---|---|
| `COMPANION_AUDIO` | `http://127.0.0.1:8081` |
| `COMPANION_LLM` | `http://127.0.0.1:8080` |
| `COMPANION_ASR_MODEL` | `nemotron-asr` |
| `COMPANION_ASR_LANG` | `en-US` (any of the 40 locales nemotron_asr supports) |
| `COMPANION_ASR_LIVE` | `1` — `0` forces the clip-only path |
| `COMPANION_ASR_IDLE` / `COMPANION_ASR_FINAL_TIMEOUT` | `30` / `6` seconds |
| `COMPANION_TTS_MODEL` / `COMPANION_TTS_VOICE` | `kokoro` / `af_bella` |
| `COMPANION_HOST` / `COMPANION_PORT` | `127.0.0.1` / `7778` |
| `COMPANION_PREFIX` | `/chat` |

## Install and expose

```bash
mkdir -p ~/.config/systemd/user
cp systemd/companion.service systemd/e2x2-mic.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now companion e2x2-mic
```

`e2x2-mic` is machine-specific: it hardcodes the ALSA node name of the Topping
interface. Skip it on a laptop, or repoint `-C` at that machine's capture node.
Make it the default source so "system default" in the page resolves to it:

```bash
wpctl set-default "$(pw-dump | python3 -c 'import json,sys; print(next(n["id"] for n in json.load(sys.stdin) if n.get("info",{}).get("props",{}).get("node.name") == "e2x2_mic"))')"
```

Then `tailscale serve --bg --set-path /chat http://127.0.0.1:7778`.

Then `https://<host>.<tailnet>.ts.net/chat`. The HTTPS origin matters: browsers
only expose the microphone in a secure context, so `http://<tailnet-ip>:7778`
works on the machine itself but not from a phone.

## Tests

```bash
python3 scripts/test_companion.py     # 18 checks, stubbed upstreams, no GPU
python3 scripts/test_browser.py       # mic path in a real browser, skips without geckodriver
```

`test_browser.py` drives a real browser through the four things a phone does:

1. **boot** — avatar frame and idle state render.
2. **the permission prompt** — the bug static review could not see. On a phone
   the first press raises a prompt, so `getUserMedia` resolves *after* the
   finger has already lifted. If that release is ignored because `recording`
   was never set, a recorder starts afterwards that nothing stops — no request,
   no error, a dead button. The test delays `getUserMedia` by 900 ms, releases
   after 100 ms, and asserts the page returns to idle with "microphone ready —
   hold the button again".
3. **the meter** — a real `getUserMedia` hold (Firefox's fake device is a tone)
   must show the meter and move it off zero, and the diag must name a device.
   This has to be a `getUserMedia` stream: Firefox will not hand a media-element
   `captureStream()` to the page's audio graph, so measuring the meter during
   step 4 reads 0 for reasons that have nothing to do with the meter.
4. **dictation** — real speech, not the fake tone: the test asks the companion
   for a wav, plays it into `audio.captureStream()` and hands that to the page.
   With live ASR on it asserts the live line grows across at least two distinct
   values while the button is held; with `COMPANION_ASR_LIVE=0` it only requires
   the clip pass, and the same script checks both. Either way, release must
   empty the live line and fill the input with send enabled, and tapping send
   is what creates the `.msg.you` bubble.

Both audio steps need a trusted gesture first (`click("header")`), otherwise the
page's `AudioContext` stays suspended and every analyser reads zero.

The page also renders a `#diag` strip (`https ✓ · recorder ✓ audio/webm … ·
mic prompt`) so a screenshot from a phone reports its own capability state.
