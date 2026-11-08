#!/usr/bin/env python3
"""Character chat over the local stack: mic -> ASR -> 35B -> TTS -> avatar.

Serves a single page plus seven endpoints. The page is the only client; the
server owns nothing but the translation between browser speech formats and
audio.cpp's OpenAI-ish API, because the browser cannot send WebM to a server
that only parses WAV, nor drive a chunked request body from Firefox.

Dictation takes the live path: the page posts 16 kHz PCM chunks, the server
holds one chunked connection to `/v1/audio/transcriptions/live` and relays the
SSE deltas back in each chunk's reply. `/api/asr` stays as the rescue pass for
a clip the live path could not decode.

    companion serve [--host 127.0.0.1] [--port 7778]
    companion doctor
"""
from __future__ import annotations

import argparse
import array
import json
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

AUDIO = os.environ.get("COMPANION_AUDIO", "http://127.0.0.1:8081")
LLM = os.environ.get("COMPANION_LLM", "http://127.0.0.1:8080")
ASR_MODEL = os.environ.get("COMPANION_ASR_MODEL", "nemotron-asr")
TTS_MODEL = os.environ.get("COMPANION_TTS_MODEL", "kokoro")
TTS_VOICE = os.environ.get("COMPANION_TTS_VOICE", "af_bella")
LLM_MODEL = os.environ.get("COMPANION_LLM_MODEL", "local")
MAX_BODY = int(os.environ.get("COMPANION_MAX_BODY", str(32 * 1024 * 1024)))
MAX_TURNS = int(os.environ.get("COMPANION_MAX_TURNS", "20"))
PREFIX = os.environ.get("COMPANION_PREFIX", "/chat")
ASR_LANG = os.environ.get("COMPANION_ASR_LANG", "en-US")
ASR_LIVE = os.environ.get("COMPANION_ASR_LIVE", "1").lower() not in ("0", "false", "no", "off")
LIVE_IDLE_S = float(os.environ.get("COMPANION_ASR_IDLE", "30"))
LIVE_FINAL_S = float(os.environ.get("COMPANION_ASR_FINAL_TIMEOUT", "6"))

SYSTEM_PROMPT = (
    "You are Orchid, the voice assistant living on Rodrigo's workstation. "
    "You speak out loud through a speech synthesiser, so reply with plain prose: "
    "no markdown, no lists, no code blocks, no emoji. "
    "Keep it to one to three short sentences unless asked to go deeper. "
    "Be warm and direct. You have local tools (a 35B model, speech recognition, "
    "speech synthesis, OCR, a homelab dashboard) but you answer conversationally."
)

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".wav": "audio/wav",
}


class UpstreamError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(f"[companion] {msg}", flush=True)


# -- upstream calls --------------------------------------------------------- #

def _read_json(resp: Any, what: str) -> Dict[str, Any]:
    raw = resp.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise UpstreamError(f"{what}: non-JSON reply ({raw[:160]!r})")


SAMPLE_RATE = 16000


def _wav_header(data_bytes: int, rate: int = SAMPLE_RATE) -> bytes:
    block_align = 2  # mono, 16-bit
    return b"".join(
        [
            b"RIFF",
            struct.pack("<I", 36 + data_bytes),
            b"WAVEfmt ",
            struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * block_align, block_align, 16),
            b"data",
            struct.pack("<I", data_bytes),
        ]
    )


def to_wav16(raw: bytes) -> bytes:
    """Anything the browser records -> 16 kHz mono WAV."""
    return to_wav16_detailed(raw)[0]


def to_wav16_detailed(raw: bytes) -> Tuple[bytes, float, float]:
    """Same, plus the input's peak level and the gain that was applied.

    `nemotron-asr` rejects anything else outright ("requires mono audio at the
    model sample rate"), and resampling also removes the accuracy loss the same
    clip shows at 24 kHz.

    ffmpeg is asked for raw PCM and the header is written here: a pipe is not
    seekable, so ffmpeg's own WAV muxer cannot backfill the chunk sizes and
    audio.cpp answers "failed to read WAV data chunk".
    """
    if not raw:
        raise UpstreamError("empty recording")
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0", "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
        ],
        input=raw,
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0 or not proc.stdout:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise UpstreamError(f"ffmpeg: {detail[-1] if detail else 'no output'}")
    pcm, peak_db, gain_db = _peak_normalise(proc.stdout[: len(proc.stdout) // 2 * 2])
    return _wav_header(len(pcm)) + pcm, peak_db, gain_db


def _peak_normalise(pcm: bytes, target: int = 32000, max_gain: float = 200.0):
    """Lift a quiet interface input into the range the ASR was trained on.

    A pro interface at low gain reads as noise. Measured on the same clip:
    at -40 dBFS it returns only the first sentence, at -55 dBFS nothing; after
    a peak lift both come back complete. Silence and white noise still decode
    to "" at +46 dB, so this boosts without inventing words.
    """
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if not samples:
        return pcm, -120.0, 0.0
    peak = max(abs(min(samples)), abs(max(samples)))
    peak_db = 20.0 * math.log10(peak / 32768) if peak else -120.0
    if peak < 4:  # digital zero: nothing to lift
        return pcm, peak_db, 0.0
    gain = min(target / peak, max_gain)
    if gain <= 1.0:
        return pcm, peak_db, 0.0
    lifted = array.array("h", (max(-32768, min(32767, int(x * gain))) for x in samples))
    return lifted.tobytes(), peak_db, 20.0 * math.log10(gain)


def transcribe(wav: bytes, language: str = "en") -> Tuple[str, float]:
    boundary = "----companion" + uuid.uuid4().hex
    parts: List[bytes] = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{ASR_MODEL}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n{language}\r\n'.encode(),
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n'
        ).encode(),
        wav,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    req = urllib.request.Request(
        f"{AUDIO}/v1/audio/transcriptions",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = _read_json(resp, "asr")
    except urllib.error.HTTPError as exc:
        raise UpstreamError(f"asr: {exc.read().decode('utf-8', 'replace')[:200]}")
    except urllib.error.URLError as exc:
        raise UpstreamError(f"asr: audio.cpp unreachable ({exc.reason})")
    return str(data.get("text") or "").strip(), (time.perf_counter() - start) * 1000


# -- live asr --------------------------------------------------------------- #

def _audio_addr() -> Tuple[str, int]:
    parts = urllib.parse.urlsplit(AUDIO)
    return parts.hostname or "127.0.0.1", parts.port or (443 if parts.scheme == "https" else 80)


def peak_of(pcm: bytes) -> int:
    if len(pcm) < 2:
        return 0
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if not samples:
        return 0
    return max(abs(min(samples)), abs(max(samples)))


class LiveStream:
    """Chunked request body and concurrent SSE reads on one socket.

    http.client buffers a request body and does not hand over the response
    until it is finished, so the only way to hold a live decoding connection
    is a raw socket. Fifteenth time this pattern has been needed; it is copied
    from `launchers/audiocpp_live.py` rather than imported so the skill stands
    on its own.
    """

    def __init__(self, path: str, host: str, port: int, timeout: float = 300.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(0.25)
        self.buf = b""
        head = (
            f"POST {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Content-Type: application/octet-stream\r\n"
            "Accept: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n"
        )
        self.sock.sendall(head.encode())
        self.status, self.chunked = self._headers()

    def _headers(self) -> Tuple[int, bool]:
        while b"\r\n\r\n" not in self.buf:
            data = self.sock.recv(65536)
            if not data:
                raise ConnectionError("audio.cpp closed during headers")
            self.buf += data
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        status = int(lines[0].split()[1])
        headers: Dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        return status, headers.get("transfer-encoding", "").lower() == "chunked"

    def send(self, data: bytes) -> None:
        if data:
            self.sock.sendall(b"%x\r\n" % len(data) + data + b"\r\n")

    def end(self) -> None:
        self.sock.sendall(b"0\r\n\r\n")

    def _fill(self, deadline: float) -> bool:
        while time.time() < deadline:
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not data:
                return False
            self.buf += data
            return True
        return False

    def _line(self, deadline: float) -> Optional[bytes]:
        while b"\r\n" not in self.buf:
            if not self._fill(deadline):
                return None
        line, self.buf = self.buf.split(b"\r\n", 1)
        return line

    def _exact(self, size: int, deadline: float) -> Optional[bytes]:
        while len(self.buf) < size:
            if not self._fill(deadline):
                return None
        out, self.buf = self.buf[:size], self.buf[size:]
        return out

    def events(self, idle_timeout: float = 600.0) -> Iterable[Dict[str, Any]]:
        deadline = time.time() + idle_timeout
        pending = b""
        while True:
            if self.chunked:
                size_line = self._line(deadline)
                if size_line is None:
                    return
                if not size_line:
                    continue
                try:
                    size = int(size_line.split(b";")[0], 16)
                except ValueError:
                    continue
                if size == 0:
                    return
                payload = self._exact(size, deadline)
                if payload is None or self._exact(2, deadline) is None:
                    return
                pending += payload
            else:
                line = self._line(deadline)
                if line is None:
                    return
                pending += line + b"\n"

            while b"\n" in pending:
                raw, pending = pending.split(b"\n", 1)
                raw = raw.strip()
                if not raw.startswith(b"data:"):
                    continue
                body = raw[5:].strip()
                if body == b"[DONE]":
                    return
                try:
                    yield json.loads(body)
                except json.JSONDecodeError:
                    continue

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class LiveSession:
    """One live decoding connection, fed by PCM chunks from the page.

    The reader thread owns the SSE side and appends deltas; each chunk reply
    carries the accumulated text, so the browser needs no event stream of its
    own. `transcript.text.done` is the authoritative transcript.
    """

    def __init__(self, language: str = ASR_LANG):
        host, port = _audio_addr()
        query = urllib.parse.urlencode(
            {
                "model": ASR_MODEL,
                "sample_rate": str(SAMPLE_RATE),
                "channels": "1",
                "sample_format": "s16le",
                "language": language,
            }
        )
        self.id = uuid.uuid4().hex
        self.language = language
        self.touched = time.time()
        self.t0 = time.perf_counter()
        self.lock = threading.Lock()
        self._closed = False
        self._done = threading.Event()
        self.stream = LiveStream(f"/v1/audio/transcriptions/live?{query}", host, port)
        if self.stream.status != 200:
            self.stream.close()
            raise UpstreamError(f"live asr: HTTP {self.stream.status}")
        self.partial = ""
        self.rev = 0
        self.final: Optional[str] = None
        self.bytes = 0
        self.peak = 0
        self.error: Optional[str] = None
        self.first_delta_ms: Optional[float] = None
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        try:
            for event in self.stream.events():
                kind = str(event.get("type") or "")
                if kind == "transcript.text.delta":
                    delta = str(event.get("delta") or "")
                    with self.lock:
                        if self.first_delta_ms is None:
                            self.first_delta_ms = round((time.perf_counter() - self.t0) * 1000, 1)
                        self.partial += delta
                        self.rev += 1
                elif kind == "transcript.text.done":
                    with self.lock:
                        self.final = str(event.get("text") or "")
        except OSError as exc:
            if not self._closed:
                self.error = f"live asr stream: {exc}"
        finally:
            self._done.set()

    def feed(self, pcm: bytes) -> Dict[str, Any]:
        if len(pcm) < 2:
            raise ValueError("empty pcm chunk")
        peak = peak_of(pcm)
        with self.lock:
            if self._closed:
                raise ValueError("session is closed")
            self.stream.send(pcm)
            self.bytes += len(pcm)
            self.touched = time.time()
            if peak > self.peak:
                self.peak = peak
        return self.snapshot()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "text": self.partial,
                "rev": self.rev,
                "bytes": self.bytes,
                "ms": round((time.perf_counter() - self.t0) * 1000, 1),
            }

    def finish(self) -> Dict[str, Any]:
        with self.lock:
            if not self._closed:
                try:
                    self.stream.end()
                except OSError:
                    pass
        self._done.wait(LIVE_FINAL_S)
        with self.lock:
            text = self.final if self.final is not None else self.partial
            out = {
                "text": (text or "").strip(),
                "partial": self.partial.strip(),
                "final": self.final is not None,
                "seconds": round(self.bytes / (SAMPLE_RATE * 2), 2),
                "first_delta_ms": self.first_delta_ms,
                "total_ms": round((time.perf_counter() - self.t0) * 1000, 1),
                "peak_db": round(20 * math.log10(self.peak / 32768), 1) if self.peak else -120.0,
                "bytes": self.bytes,
                "error": self.error,
            }
        self.close()
        return out

    def close(self) -> None:
        with self.lock:
            self._closed = True
        self.stream.close()
        self._done.set()

    def idle_for(self) -> float:
        return time.time() - self.touched


LIVE_SESSIONS: Dict[str, LiveSession] = {}
LIVE_LOCK = threading.Lock()


def live_start(language: str) -> LiveSession:
    session = LiveSession(language)
    with LIVE_LOCK:
        LIVE_SESSIONS[session.id] = session
    log(f"live {session.id[:8]} open ({language})")
    return session


def live_get(session_id: str) -> LiveSession:
    with LIVE_LOCK:
        session = LIVE_SESSIONS.get(session_id)
    if session is None:
        raise KeyError(session_id)
    return session


def live_drop(session_id: str) -> None:
    with LIVE_LOCK:
        LIVE_SESSIONS.pop(session_id, None)


def live_sweep() -> None:
    """Abort dictations a vanished tab never ended."""
    with LIVE_LOCK:
        stale = [s for s in LIVE_SESSIONS.values() if s.idle_for() > LIVE_IDLE_S]
        for session in stale:
            LIVE_SESSIONS.pop(session.id, None)
    for session in stale:
        log(f"live {session.id[:8]} idle {LIVE_IDLE_S:.0f}s — aborted")
        session.close()


def synthesize(text: str, voice: str) -> bytes:
    payload = {"model": TTS_MODEL, "input": text, "voice": voice or TTS_VOICE}
    req = urllib.request.Request(
        f"{AUDIO}/v1/audio/speech",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as exc:
        raise UpstreamError(f"tts: {exc.read().decode('utf-8', 'replace')[:200]}")
    except urllib.error.URLError as exc:
        raise UpstreamError(f"tts: audio.cpp unreachable ({exc.reason})")
    if not audio:
        raise UpstreamError("tts: empty audio")
    return audio


def chat_stream(messages: List[Dict[str, str]]) -> Iterable[str]:
    """Yield text deltas from llm-server's SSE stream."""
    trimmed = messages[-MAX_TURNS:]
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *trimmed],
        "stream": True,
        "temperature": 0.7,
        "max_tokens": 400,
    }
    req = urllib.request.Request(
        f"{LLM}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=600)
    except urllib.error.HTTPError as exc:
        raise UpstreamError(f"llm: {exc.read().decode('utf-8', 'replace')[:200]}")
    except urllib.error.URLError as exc:
        raise UpstreamError(f"llm: llama-server unreachable ({exc.reason})")

    with resp:
        for line in resp:
            if not line.startswith(b"data: "):
                continue
            chunk = line[6:].strip()
            if chunk == b"[DONE]":
                break
            try:
                event = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            delta = (event.get("choices") or [{}])[0].get("delta") or {}
            text = delta.get("content")
            if text:
                yield text


def health() -> Dict[str, Any]:
    def probe(url: str) -> bool:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    return {
        "asr": probe(AUDIO),
        "tts": probe(AUDIO),
        "llm": probe(LLM),
        "asr_model": ASR_MODEL,
        "asr_live": ASR_LIVE,
        "asr_lang": ASR_LANG,
        "tts_model": TTS_MODEL,
        "voice": TTS_VOICE,
    }


# -- http ------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "companion/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    # -- helpers --

    def _path(self) -> str:
        path = urllib.parse.urlsplit(self.path).path
        if PREFIX and path.startswith(PREFIX):
            path = path[len(PREFIX):] or "/"
        return path

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self._status = status
        self._bytes = len(body)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        self._send(status, json.dumps(payload).encode(), MIME[".json"])

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("empty body")
        if length > MAX_BODY:
            raise ValueError(f"body too large ({length} bytes)")
        return self.rfile.read(length)

    def _body_or_empty(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > MAX_BODY:
            raise ValueError(f"body too large ({length} bytes)")
        return self.rfile.read(length)

    # -- routes --

    def do_GET(self) -> None:
        path = self._path()

        if path == "/healthz":
            self._send(200, b"ok\n", "text/plain; charset=utf-8")
            return

        if path == "/api/health":
            self._json(200, health())
            return

        if path in ("", "/"):
            path = "/index.html"

        target = (ASSETS / path.lstrip("/")).resolve()
        if not str(target).startswith(str(ASSETS.resolve())) or not target.is_file():
            self._send(404, b"not found\n", "text/plain; charset=utf-8")
            return

        ctype = MIME.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    def do_POST(self) -> None:
        path = self._path()
        if not path.startswith("/api/"):
            self._json(404, {"error": "unknown endpoint"})
            return

        started = time.perf_counter()
        self._status = None
        self._bytes = 0
        declared = self.headers.get("Content-Length") or "?"
        try:
            if path == "/api/asr":
                self._asr()
            elif path == "/api/asr/live":
                self._live_start()
            elif path.startswith("/api/asr/live/"):
                self._live_step(path)
            elif path == "/api/chat":
                self._chat()
            elif path == "/api/tts":
                self._tts()
            else:
                self._json(404, {"error": "unknown endpoint"})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except UpstreamError as exc:
            self._json(502, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - surfaced to the page, not swallowed
            log(f"unhandled: {type(exc).__name__}: {exc}")
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
        finally:
            if not path.endswith("/pcm") or getattr(self.server, "verbose", False):
                ms = (time.perf_counter() - started) * 1000
                log(f"{path} {self._status} {declared}B {self._bytes}B out {ms:.0f}ms")

    def _asr(self) -> None:
        raw = self._body()
        start = time.perf_counter()
        wav, peak_db, gain_db = to_wav16_detailed(raw)
        text, asr_ms = transcribe(wav)
        self._json(
            200,
            {
                "text": text,
                "asr_ms": round(asr_ms, 1),
                "total_ms": round((time.perf_counter() - start) * 1000, 1),
                "seconds": round((len(wav) - 44) / 32000, 2),
                "peak_db": round(peak_db, 1),
                "gain_db": round(gain_db, 1),
            },
        )

    def _live_start(self) -> None:
        self._body_or_empty()
        if not ASR_LIVE:
            raise UpstreamError("live asr disabled (COMPANION_ASR_LIVE=0)")
        session = live_start(ASR_LANG)
        self._json(
            200,
            {"id": session.id, "language": session.language, "model": ASR_MODEL, "rate": SAMPLE_RATE},
        )

    def _live_step(self, path: str) -> None:
        parts = path.strip("/").split("/")
        if len(parts) != 5:
            self._json(404, {"error": "unknown endpoint"})
            return
        session_id, action = parts[3], parts[4]
        try:
            session = live_get(session_id)
        except KeyError:
            self._json(404, {"error": "unknown live session"})
            return

        if action == "pcm":
            pcm = self._body()
            if len(pcm) % 2:
                pcm = pcm[:-1]
            self._json(200, session.feed(pcm))
        elif action == "end":
            self._body_or_empty()
            result = session.finish()
            log(
                f"live {session_id[:8]} done {result['seconds']:.1f}s audio "
                f"-> {len(result['text'])} chars in {result['total_ms']:.0f}ms"
            )
            self._json(200, result)
            live_drop(session_id)
        elif action == "abort":
            self._body_or_empty()
            session.close()
            live_drop(session_id)
            log(f"live {session_id[:8]} aborted")
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "unknown endpoint"})

    def _tts(self) -> None:
        payload = json.loads(self._body().decode("utf-8"))
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("no text")
        voice = str(payload.get("voice") or TTS_VOICE)
        self._send(200, synthesize(text, voice), MIME[".wav"])

    def _chat(self) -> None:
        payload = json.loads(self._body().decode("utf-8"))
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("no messages")

        self._status = 200
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(event: Dict[str, Any]) -> None:
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()

        try:
            for delta in chat_stream(messages):
                emit({"type": "delta", "text": delta})
            emit({"type": "done"})
        except UpstreamError as exc:
            emit({"type": "error", "message": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass


def _sweep_loop() -> None:
    while True:
        time.sleep(5)
        try:
            live_sweep()
        except Exception as exc:  # noqa: BLE001 - a sweeper must never die
            log(f"sweep: {type(exc).__name__}: {exc}")


def serve(host: str, port: int, verbose: bool) -> int:
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.verbose = verbose  # type: ignore[attr-defined]
    threading.Thread(target=_sweep_loop, daemon=True).start()
    log(f"serving http://{host}:{port}{PREFIX if PREFIX != '/' else '/'}")
    mode = f"live/{ASR_LANG}" if ASR_LIVE else "clip-only"
    log(f"asr={ASR_MODEL}@{AUDIO} ({mode})  llm={LLM}  tts={TTS_MODEL}/{TTS_VOICE}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("stopped")
    finally:
        httpd.server_close()
    return 0


def doctor() -> int:
    ok = True
    print("companion doctor")

    ffmpeg = shutil.which("ffmpeg")
    print(f"  {'ok  ' if ffmpeg else 'FAIL'} ffmpeg           {ffmpeg or 'not on PATH'}")
    ok &= bool(ffmpeg)

    probe = health()
    for key, label in (("asr", "audio.cpp :8081"), ("llm", "llama-server :8080")):
        state = "ok  " if probe[key] else "FAIL"
        print(f"  {state} {label:<16} {'up' if probe[key] else 'unreachable'}")
        ok &= bool(probe[key])

    try:
        with urllib.request.urlopen(f"{AUDIO}/v1/models", timeout=5) as resp:
            data = _read_json(resp, "models")
        ids = {m.get("id") for m in data.get("data") or []}
        for model in (ASR_MODEL, TTS_MODEL):
            present = model in ids
            print(f"  {'ok  ' if present else 'FAIL'} model {model:<12} {'installed' if present else 'missing'}")
            ok &= present
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL models           {exc}")
        ok = False

    if ASR_LIVE:
        try:
            session = live_start(ASR_LANG)
            result = session.finish()
            live_drop(session.id)
            state = "ok  " if result["final"] or not result["error"] else "warn"
            print(f"  {state} live asr         {ASR_MODEL} · {ASR_LANG} · empty pass {result['total_ms']:.0f} ms")
            ok &= not result["error"]
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL live asr          {exc}")
            ok = False
    else:
        print("  idle live asr          disabled (COMPANION_ASR_LIVE=0)")

    avatar = ASSETS / "avatar" / "orchid_girl"
    frames = list(avatar.glob("*/*.png")) if avatar.is_dir() else []
    print(f"  {'ok  ' if len(frames) >= 10 else 'FAIL'} avatar           {len(frames)} frames in {avatar.name}")
    ok &= len(frames) >= 10

    print("  ready" if ok else "  not ready")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="companion", description=__doc__)
    sub = parser.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve", help="run the chat page")
    p_serve.add_argument("--host", default=os.environ.get("COMPANION_HOST", "127.0.0.1"))
    p_serve.add_argument("--port", type=int, metavar="PORT", default=int(os.environ.get("COMPANION_PORT", "7778")))
    p_serve.add_argument("--verbose", action="store_true")

    sub.add_parser("doctor", help="check ffmpeg, upstreams, models and avatar assets")

    args = parser.parse_args()
    if args.cmd == "doctor":
        return doctor()
    if args.cmd == "serve":
        return serve(args.host, args.port, args.verbose)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
