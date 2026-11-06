/* Orchid — mic -> ASR -> 35B -> TTS -> pixel avatar.
 *
 * The avatar logic is pi-emote's state machine (idle+blink, think while
 * waiting, talk cycling four mouth weights, success/failure holds) rebuilt for
 * the browser. pi-emote only ships terminal renderers, so nothing could be
 * imported; the mouth is driven by the real audio envelope instead of token
 * counts, which is the one upgrade over the original.
 */

// The page may be mounted at "/" or under a path prefix ("/chat", "/chat/").
// index.html installs a <base> when the slash is missing, so the document's
// own baseURI is the single source of truth for every URL below.
const BASE = new URL(".", document.baseURI).href;
const AVATAR = BASE + "avatar/orchid_girl/";

const FRAMES = {
  idle: "idle/idle.png",
  blink: "idle/idle_blink.png",
  think: "think/think.png",
  thinkHard: "think/think_hard.png",
  mouths: ["talk/talk_close.png", "talk/talk_small.png", "talk/talk_mid.png", "talk/talk_wide.png"],
  success: "success/success.png",
  failure: "failure/failure.png",
};

const el = {
  avatar: document.getElementById("avatar"),
  stage: document.querySelector(".stage"),
  state: document.getElementById("state"),
  log: document.getElementById("log"),
  talk: document.getElementById("talk"),
  form: document.getElementById("text-form"),
  input: document.getElementById("text-input"),
  stats: document.getElementById("stats"),
  diag: document.getElementById("diag"),
  health: document.getElementById("health"),
  live: document.getElementById("live"),
  send: document.getElementById("send"),
  mic: document.getElementById("mic"),
  meter: document.getElementById("meter"),
};

const LABELS = {
  idle: "idle",
  listening: "listening",
  think: "thinking",
  talk: "speaking",
};

/* ---------- audio graph ---------- */

const ctx = new (window.AudioContext || window.webkitAudioContext)();
const analyser = ctx.createAnalyser();
analyser.fftSize = 1024;
analyser.smoothingTimeConstant = 0;
analyser.connect(ctx.destination);

const wave = new Uint8Array(analyser.fftSize);

let queue = [];
let playing = false;
let current = null;
let seq = 0; // incremented on every barge-in; stale work is dropped
let ttsInFlight = 0;
let turnActive = false;
let recording = false;
let mouth = -1;
let raf = null;

function unlock() {
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
}
document.addEventListener("pointerdown", unlock, { passive: true });
document.addEventListener("keydown", unlock);

/* ---------- avatar state machine ---------- */

let state = "";
let blinkTimer = null;
let thinkTimer = null;

function show(path) {
  const next = AVATAR + path;
  if (el.avatar.getAttribute("src") !== next) el.avatar.src = next;
}

function setState(next) {
  if (next === state) return;
  state = next;
  clearTimeout(blinkTimer);
  clearInterval(thinkTimer);
  blinkTimer = thinkTimer = null;

  el.stage.classList.toggle("listening", next === "listening");
  el.state.textContent = LABELS[next] || next;
  el.state.className = "state " + (next === "talk" ? "talking" : next === "think" ? "thinking" : "");

  if (next === "listening") {
    show(FRAMES.idle);
  } else if (next === "idle") {
    show(FRAMES.idle);
    scheduleBlink();
  } else if (next === "think") {
    let hard = false;
    show(FRAMES.think);
    thinkTimer = setInterval(() => {
      hard = !hard;
      show(hard ? FRAMES.thinkHard : FRAMES.think);
    }, 650);
  } else if (next === "talk") {
    mouth = -1;
    startMouth();
  } else if (next === "success") {
    show(FRAMES.success);
    blinkTimer = setTimeout(() => setState("idle"), 700);
  } else if (next === "failure") {
    show(FRAMES.failure);
    blinkTimer = setTimeout(() => setState("idle"), 1600);
  }
}

function scheduleBlink() {
  clearTimeout(blinkTimer);
  blinkTimer = setTimeout(() => {
    if (state !== "idle") return;
    show(FRAMES.blink);
    setTimeout(() => {
      if (state === "idle") show(FRAMES.idle);
    }, 140);
    scheduleBlink();
  }, 3000 + Math.random() * 3000);
}

function startMouth() {
  if (raf) return;
  let peak = 0.02;
  let env = 0;

  const tick = () => {
    if (state !== "talk") {
      raf = null;
      return;
    }
    analyser.getByteTimeDomainData(wave);
    let sum = 0;
    for (let i = 0; i < wave.length; i++) {
      const x = (wave[i] - 128) / 128;
      sum += x * x;
    }
    const rms = Math.sqrt(sum / wave.length);
    peak = Math.max(rms, peak * 0.995);
    env = Math.max(rms, env * 0.8);
    const ratio = peak > 0.001 ? env / peak : 0;
    const level = ratio < 0.1 ? 0 : ratio < 0.34 ? 1 : ratio < 0.66 ? 2 : 3;
    if (level !== mouth) {
      mouth = level;
      show(FRAMES.mouths[level]);
    }
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
}

/* ---------- playback ---------- */

function pump() {
  if (playing || !queue.length) {
    if (!playing && !queue.length) maybeIdle();
    return;
  }
  playing = true;
  unlock();
  setState("talk");
  const src = ctx.createBufferSource();
  src.buffer = queue.shift();
  src.connect(analyser);
  current = src;
  src.onended = () => {
    if (current === src) current = null;
    playing = false;
    pump();
  };
  src.start();
}

function maybeIdle() {
  if (playing || queue.length || ttsInFlight || turnActive || recording) return;
  if (state === "talk" || state === "think") setState("success");
}

function stopAudio() {
  seq++;
  queue = [];
  if (current) {
    try {
      current.onended = null;
      current.stop();
    } catch (e) {
      /* already stopped */
    }
    current = null;
  }
  playing = false;
  ttsInFlight = 0;
  turnActive = false;
  if (state === "talk" || state === "success") setState("idle");
}

function speak(text) {
  const mine = seq;
  ttsInFlight++;
  return fetch(BASE + "api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: clean(text) }),
  })
    .then((res) => {
      if (!res.ok) throw new Error("tts " + res.status);
      return res.arrayBuffer();
    })
    .then((buf) => ctx.decodeAudioData(buf))
    .then((audio) => {
      if (mine !== seq) return;
      queue.push(audio);
      pump();
    })
    .finally(() => {
      ttsInFlight--;
      if (mine === seq) maybeIdle();
    });
}

function clean(text) {  return text
    .replace(/\*\*?([^*]+)\*\*?/g, "$1")
    .replace(/[`#]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/* ---------- transcript ---------- */

function bubble(kind, text) {
  const node = document.createElement("div");
  node.className = "msg " + kind;
  node.textContent = text;
  el.log.appendChild(node);
  el.log.scrollTop = el.log.scrollHeight;
  return node;
}

function note(text) {
  bubble("err", text);
}

/* ---------- chat ---------- */

let history = [];
let chatAbort = null;
let ttsChain = Promise.resolve();

function enqueueSpeech(text) {
  const body = clean(text);
  if (!body) return;
  ttsChain = ttsChain.then(() => speak(body)).catch((err) => console.warn("tts", err));
}

function takeSentences(buf) {
  const out = [];
  let rest = buf;
  for (;;) {
    const m = rest.match(/[.!?…]["')\]]?\s/);
    if (!m) break;
    const end = m.index + m[0].length;
    const sentence = rest.slice(0, end).trim();
    if (sentence.replace(/[^\p{L}\p{N}]/gu, "").length < 2) {
      rest = rest.slice(end);
      continue;
    }
    out.push(sentence);
    rest = rest.slice(end);
  }
  return { out, rest };
}

async function turn(text) {
  const message = text.trim();
  if (!message) return;

  stopAudio();
  chatAbort?.abort();
  const control = new AbortController();
  chatAbort = control;
  const mine = seq;

  bubble("you", message);
  history.push({ role: "user", content: message });

  const node = bubble("orchid", "");
  setState("think");
  turnActive = true;

  const started = performance.now();
  let ttft = null;
  let full = "";
  let pending = "";

  try {
    const res = await fetch(BASE + "api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
      signal: control.signal,
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail.slice(0, 200) || "chat " + res.status);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let raw = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      raw += decoder.decode(value, { stream: true });

      let split;
      while ((split = raw.indexOf("\n\n")) >= 0) {
        const block = raw.slice(0, split);
        raw = raw.slice(split + 2);
        for (const line of block.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          let event;
          try {
            event = JSON.parse(line.slice(6));
          } catch (e) {
            continue;
          }
          if (event.type === "error") throw new Error(event.message || "upstream error");
          if (event.type !== "delta") continue;

          if (ttft === null) ttft = performance.now() - started;
          full += event.text;
          node.textContent = full;
          el.log.scrollTop = el.log.scrollHeight;

          pending += event.text;
          const { out, rest } = takeSentences(pending);
          if (out.length) {
            out.forEach(enqueueSpeech);
            pending = rest;
          } else if (pending.length > 180) {
            const cut = pending.lastIndexOf(" ", 180);
            const at = cut > 80 ? cut : pending.length;
            enqueueSpeech(pending.slice(0, at));
            pending = pending.slice(at);
          }
        }
      }
    }

    if (pending.trim()) enqueueSpeech(pending);
    if (full.trim()) history.push({ role: "assistant", content: full });
    else node.textContent = "…";

    await ttsChain;
    if (mine === seq) {
      const stats = [`llm ${((performance.now() - started) / 1000).toFixed(2)}s`];
      if (ttft !== null) stats.unshift(`first token ${(ttft / 1000).toFixed(2)}s`);
      el.stats.textContent = stats.join(" · ");
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    console.error(err);
    node.remove();
    note(String(err.message || err));
    setState("failure");
  } finally {
    if (chatAbort === control) chatAbort = null;
    turnActive = false;
    maybeIdle();
  }
}

/* ---------- recording ---------- */

let recorder = null;
let mic = null;
let chunks = [];
let pressHeld = false;
let dictation = null; // the live session, when one is running

function setLive(text, state) {
  el.live.textContent = text;
  if (state) el.live.dataset.state = state;
  else delete el.live.dataset.state;
}

/* Dictation streams: the worklet slices the mic into 128 ms PCM chunks, each
 * chunk goes up, and the reply carries the text decoded so far. The server
 * holds the single chunked connection to audio.cpp, so no event stream and no
 * Chrome-only request body is needed here. */
function captureContext() {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  try {
    return new Ctx({ sampleRate: 16000 });
  } catch (err) {
    return new Ctx();
  }
}

async function startLive(stream) {
  const res = await fetch(BASE + "api/asr/live", { method: "POST" });
  if (!res.ok) throw new Error((await res.text()).slice(0, 160) || "live asr " + res.status);
  const { id } = await res.json();

  const capture = captureContext();
  const source = capture.createMediaStreamSource(stream);
  let node;
  try {
    if (capture.state === "suspended") await capture.resume().catch(() => {});
    await capture.audioWorklet.addModule(BASE + "asr-worklet.js");
    node = new AudioWorkletNode(capture, "pcm16", {
      processorOptions: { rate: capture.sampleRate },
    });
  } catch (err) {
    fetch(`${BASE}api/asr/live/${id}/abort`, { method: "POST" }).catch(() => {});
    capture.close().catch(() => {});
    throw err;
  }
  const sink = capture.createGain();
  sink.gain.value = 0; // a worklet with no output is not pulled on every browser
  source.connect(node);
  node.connect(sink);
  sink.connect(capture.destination);

  const session = {
    id,
    capture,
    source,
    node,
    sink,
    queue: [],
    busy: false,
    failed: false,
    ending: false,
    rev: -1,
    drained: null,
  };
  node.port.onmessage = (ev) => {
    session.queue.push(ev.data.pcm);
    pumpLive(session);
  };
  return session;
}

async function pumpLive(session) {
  if (session.busy) return;
  session.busy = true;
  try {
    while (session.queue.length && !session.failed) {
      const pcm = session.queue.shift();
      const res = await fetch(`${BASE}api/asr/live/${session.id}/pcm`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: pcm,
      });
      if (!res.ok) {
        session.failed = true;
        break;
      }
      const data = await res.json();
      if (data.rev !== session.rev && !session.ending) {
        session.rev = data.rev;
        const text = (data.text || "").trim();
        if (text) setLive(text, "partial");
      }
    }
  } catch (err) {
    session.failed = true;
  } finally {
    session.busy = false;
    if (!session.queue.length && session.drained) {
      const resume = session.drained;
      session.drained = null;
      resume();
    }
  }
}

function drainLive(session) {
  return new Promise((resolve) => {
    const check = () => {
      if (!session.queue.length && !session.busy) resolve();
      else session.drained = check;
    };
    check();
  });
}

function teardownLive(session) {
  try {
    session.node.port.onmessage = null;
  } catch (err) {
    /* already detached */
  }
  for (const part of [session.source, session.node, session.sink]) {
    try {
      part.disconnect();
    } catch (err) {
      /* already gone */
    }
  }
  session.capture.close().catch(() => {});
}

async function stopLive(session) {
  session.ending = true;
  try {
    session.node.port.postMessage("flush");
  } catch (err) {
    /* worklet already gone */
  }
  await new Promise((resolve) => setTimeout(resolve, 90)); // let the flush land
  await drainLive(session);
  try {
    const res = await fetch(`${BASE}api/asr/live/${session.id}/end`, { method: "POST" });
    if (!res.ok) throw new Error((await res.text()).slice(0, 160) || "asr end " + res.status);
    return await res.json();
  } finally {
    teardownLive(session);
  }
}

function abortLive(session) {
  session.ending = true;
  fetch(`${BASE}api/asr/live/${session.id}/abort`, { method: "POST" }).catch(() => {});
  teardownLive(session);
}

const MIC_KEY = "companion.mic";

function savedMic() {
  try {
    return localStorage.getItem(MIC_KEY) || "";
  } catch (err) {
    return "";
  }
}

function rememberMic(id) {
  try {
    if (id) localStorage.setItem(MIC_KEY, id);
    else localStorage.removeItem(MIC_KEY);
  } catch (err) {
    /* private mode: the picker just won't persist */
  }
}

/* Labels are only populated after a successful capture, so this runs again
 * after every recording. Until then the list shows device indices. */
async function refreshDevices() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  let inputs = [];
  try {
    const all = await navigator.mediaDevices.enumerateDevices();
    inputs = all.filter((d) => d.kind === "audioinput");
  } catch (err) {
    return;
  }
  const chosen = savedMic();
  const frag = document.createDocumentFragment();
  const auto = document.createElement("option");
  auto.value = "";
  auto.textContent = "system default";
  frag.appendChild(auto);
  inputs.forEach((d, i) => {
    const o = document.createElement("option");
    o.value = d.deviceId;
    o.textContent = d.label || `microphone ${i + 1}`;
    frag.appendChild(o);
  });
  el.mic.replaceChildren(frag);
  el.mic.value = inputs.some((d) => d.deviceId === chosen) ? chosen : "";
  renderDiag();
}

el.mic.addEventListener("change", () => {
  rememberMic(el.mic.value);
  micLabel = "";
  renderDiag();
});

let micLabel = "";
let micRate = 0;
let micQuiet = false;
let micSource = null;
let micAnalyser = null;
let meterRaf = null;

/* The only honest answer to "is my microphone actually being used": show the
 * device the track came from and move a bar with its level while you speak. An
 * interface at zero gain looks identical to a wrong device otherwise. */
function startMeter(stream) {
  stopMeter();
  try {
    micSource = ctx.createMediaStreamSource(stream);
  } catch (err) {
    return;
  }
  micAnalyser = ctx.createAnalyser();
  micAnalyser.fftSize = 1024;
  micAnalyser.smoothingTimeConstant = 0.2;
  micSource.connect(micAnalyser);

  const buf = new Float32Array(micAnalyser.fftSize);
  el.meter.hidden = false;
  let quiet = 0;

  const tick = () => {
    micAnalyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const db = 20 * Math.log10(Math.sqrt(sum / buf.length) + 1e-7);
    el.meter.firstElementChild.style.width = Math.max(0, Math.min(100, ((db + 60) / 54) * 100)) + "%";
    if (db < -45) {
      quiet++;
      if (quiet >= 60 && !micQuiet) {
        micQuiet = true;
        renderDiag();
      }
    } else {
      quiet = 0;
      if (micQuiet) {
        micQuiet = false;
        renderDiag();
      }
    }
    meterRaf = requestAnimationFrame(tick);
  };
  meterRaf = requestAnimationFrame(tick);
}

function stopMeter() {
  if (meterRaf) cancelAnimationFrame(meterRaf);
  meterRaf = null;
  try {
    micSource?.disconnect();
  } catch (err) {
    /* already gone */
  }
  micSource = null;
  micAnalyser = null;
  micQuiet = false;
  el.meter.hidden = true;
  el.meter.firstElementChild.style.width = "0%";
  renderDiag();
}

async function startRecording() {
  if (recording) return;
  stopAudio();
  unlock();
  pressHeld = true;

  const base = {
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: false, // the server lifts the level, and does it predictably
  };
  const ask = (pinned) =>
    navigator.mediaDevices.getUserMedia({
      audio: pinned ? { ...base, deviceId: { exact: pinned } } : { ...base },
    });

  try {
    const pinned = savedMic();
    mic = pinned
      ? await ask(pinned).catch((err) => {
          if (err.name !== "OverconstrainedError" && err.name !== "NotFoundError") throw err;
          rememberMic("");
          refreshDevices();
          return ask("");
        })
      : await ask("");
  } catch (err) {
    pressHeld = false;
    note("microphone: " + (err.message || err.name || err));
    setState("idle");
    return;
  }

  const track = mic.getAudioTracks()[0];
  micLabel = track?.label || "microphone";
  micRate = track?.getSettings?.().sampleRate || 0;
  startMeter(mic);
  renderDiag();
  refreshDevices();

  // The first press on a phone raises a permission prompt, and the natural
  // reaction is to let go of the button while it is up. Without this check the
  // release is swallowed (recording was never true) and the recorder starts
  // afterwards with nothing left to stop it.
  if (!pressHeld) {
    mic.getTracks().forEach((t) => t.stop());
    mic = null;
    setState("idle");
    el.stats.textContent = "microphone ready — hold the button again";
    return;
  }

  try {
    const types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
    const mime = types.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
    recorder = new MediaRecorder(mic, mime ? { mimeType: mime } : undefined);
  } catch (err) {
    pressHeld = false;
    mic?.getTracks().forEach((t) => t.stop());
    mic = null;
    note("this browser cannot record audio: " + (err.name || err.message || err));
    setState("failure");
    return;
  }

  chunks = [];
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size) chunks.push(e.data);
  };
  recorder.start(250); // rescue clip: if the live pass fails, this still decodes

  recording = true;
  setLive("…", "partial");
  el.talk.classList.add("recording");
  el.talk.querySelector(".talk-label").textContent = "release to stop";
  setState("listening");

  try {
    dictation = await startLive(mic);
  } catch (err) {
    dictation = null;
    note("streaming asr unavailable — using the clip pass: " + (err.message || err));
  }
  if (!recording && dictation) {
    abortLive(dictation);
    dictation = null;
  }
}

function stopRecording() {
  pressHeld = false;
  if (!recording) return;
  recording = false;
  stopMeter();
  el.talk.classList.remove("recording");
  el.talk.querySelector(".talk-label").textContent = "hold to talk";

  const preview = el.live.textContent;
  const session = dictation;
  dictation = null;
  const clip = stopRecorder();
  mic?.getTracks().forEach((t) => t.stop());
  mic = null;
  finishDictation(session, clip, preview);
}

function stopRecorder() {
  return new Promise((resolve) => {
    const active = recorder;
    recorder = null;
    const done = () => resolve(new Blob(chunks, { type: chunks[0]?.type || "audio/webm" }));
    if (!active) {
      done();
      return;
    }
    active.onstop = done;
    try {
      active.stop();
    } catch (err) {
      done();
    }
  });
}

function appendToInput(text) {
  const body = text.trim();
  if (!body) return;
  const current = el.input.value.trim();
  el.input.value = current ? current + " " + body : body;
  el.send.disabled = false;
}

async function finishDictation(session, clipPromise, preview) {
  const clip = await clipPromise;
  chunks = [];
  let text = "";
  let stats = "";
  let peak = NaN;

  if (session) {
    setState("think");
    try {
      const out = await stopLive(session);
      text = (out.text || "").trim();
      peak = Number(out.peak_db);
      const first = out.first_delta_ms
        ? `${(out.first_delta_ms / 1000).toFixed(2)}s to first word · `
        : "";
      stats = `asr live · ${first}${Number(out.seconds).toFixed(1)}s audio · ${(Number(out.total_ms) / 1000).toFixed(2)}s`;
      if (!text) preview = out.partial || preview;
    } catch (err) {
      note("live asr failed — falling back to the clip pass: " + (err.message || err));
    }
  }

  if (!text && clip.size) {
    setState("think");
    try {
      const res = await fetch(BASE + "api/asr", { method: "POST", body: clip });
      if (!res.ok) throw new Error((await res.text()).slice(0, 200) || "asr " + res.status);
      const data = await res.json();
      text = (data.text || "").trim();
      peak = Number(data.peak_db);
      const level = Number.isFinite(data.peak_db) ? ` · in ${Math.round(data.peak_db)} dB` : "";
      stats = `asr clip ${(data.total_ms / 1000).toFixed(2)}s · ${data.seconds}s audio${level}`;
    } catch (err) {
      console.error(err);
      setLive("");
      note("transcription failed: " + (err.message || err));
      setState("failure");
      return;
    }
  }

  if (stats) el.stats.textContent = stats;

  if (!text && !clip.size && !session) {
    setLive("");
    setState("idle");
    return;
  }

  if (!text) {
    setLive("");
    if (Number.isFinite(peak) && peak < -50) {
      note(
        `nothing audible — the mic peaked at ${Math.round(peak)} dBFS. ` +
          "Check that the mic is plugged into the selected input and its gain is up."
      );
    } else if (preview && preview !== "…") {
      appendToInput(preview);
      el.input.focus();
    } else {
      note("didn't catch that");
    }
    setState("idle");
    return;
  }

  setLive(text, "final");
  appendToInput(text);
  el.input.focus();
  el.stats.textContent += " · review, then ↵";
  setState("idle");
  setTimeout(() => {
    if (el.live.dataset.state === "final") setLive("");
  }, 1500);
}

/* ---------- wiring ---------- */

el.talk.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  try {
    el.talk.setPointerCapture?.(e.pointerId);
  } catch (err) {
    /* synthetic pointer ids have no capture target */
  }
  startRecording();
});
el.talk.addEventListener("pointerup", (e) => {
  e.preventDefault();
  stopRecording();
});
el.talk.addEventListener("pointercancel", () => stopRecording());
el.talk.addEventListener("contextmenu", (e) => e.preventDefault());

window.addEventListener("pagehide", () => {
  if (dictation) abortLive(dictation);
  dictation = null;
});

const TYPING = new Set(["INPUT", "TEXTAREA", "BUTTON"]);

document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !e.repeat && !TYPING.has(document.activeElement?.tagName)) {
    e.preventDefault();
    startRecording();
  }
});
document.addEventListener("keyup", (e) => {
  if (e.code === "Space" && !TYPING.has(document.activeElement?.tagName)) {
    e.preventDefault();
    stopRecording();
  }
});

el.form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = el.input.value.trim();
  if (!text) return;
  el.input.value = "";
  el.send.disabled = true;
  el.input.blur();
  turn(text);
});

el.input.addEventListener("input", () => {
  el.send.disabled = !el.input.value.trim();
});

function checkHealth() {
  fetch(BASE + "api/health")
    .then((r) => r.json())
    .then((h) => {
      const ok = h.asr && h.llm;
      el.health.className = "dot " + (ok ? "ok" : "bad");
      el.health.title = ok
        ? `asr ${h.asr_model} · llm up · tts ${h.tts_model}/${h.voice}`
        : `asr ${h.asr ? "up" : "down"} · llm ${h.llm ? "up" : "down"}`;
      if (!ok) el.stats.textContent = "a backend is down — run: companion doctor";
    })
    .catch(() => {
      el.health.className = "dot bad";
      el.health.title = "companion unreachable";
    });
}

let micPermission = "unknown";

function renderDiag() {
  const secure = window.isSecureContext;
  const missing = typeof MediaRecorder === "undefined";
  const parts = [secure ? "https ✓" : "not secure ✗"];
  if (missing) parts.push("no recorder ✗");
  if (micLabel) {
    parts.push(micRate ? `${micLabel} · ${(micRate / 1000).toFixed(1)} kHz` : micLabel);
  } else {
    parts.push(micPermission === "granted" ? "mic ready" : `mic ${micPermission}`);
  }
  if (micQuiet) parts.push("no signal");
  el.diag.textContent = parts.join(" · ");
  el.diag.classList.toggle("warn", !secure || missing);
}

if (navigator.permissions?.query) {
  navigator.permissions
    .query({ name: "microphone" })
    .then((status) => {
      micPermission = status.state;
      renderDiag();
      status.onchange = () => {
        micPermission = status.state;
        renderDiag();
      };
    })
    .catch(() => renderDiag());
} else {
  renderDiag();
}

refreshDevices();
setState("idle");
Object.values(FRAMES)
  .flat()
  .forEach((p) => {
    const img = new Image();
    img.src = AVATAR + p;
  });
checkHealth();
setInterval(checkHealth, 15000);
