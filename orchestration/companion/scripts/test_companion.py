#!/usr/bin/env python3
"""Companion server tests. No GPU, no real models: a stub stands in for
audio.cpp and llama-server so the transport and format handling are exercised
on their own."""
from __future__ import annotations

import io
import json
import struct
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import companion  # noqa: E402


def tone_wav(seconds: float = 0.4, rate: int = 24000) -> bytes:
    frames = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(struct.pack("<h", (i * 97) % 2000 - 1000) for i in range(frames)))
    return buf.getvalue()


class StubUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen_asr_model = None
    fail_chat = False
    live_paths = []
    live_bytes = b""
    live_words = ["Hello", " from", " the", " live", " stub"]

    def log_message(self, *args):
        pass

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _chunk(self, payload):
        try:
            self.wfile.write(b"%x\r\n" % len(payload) + payload + b"\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise SystemExit

    def _live(self):
        StubUpstream.live_paths.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        heard = bytearray()
        spoken = 0
        try:
            while True:
                line = self.rfile.readline().strip()
                if not line:
                    break
                size = int(line.split(b";")[0], 16)
                if size == 0:
                    self.rfile.read(2)
                    break
                heard += self.rfile.read(size)
                self.rfile.read(2)
                if spoken < len(self.live_words):
                    event = {"type": "transcript.text.delta", "delta": self.live_words[spoken]}
                    self._chunk(f"data: {json.dumps(event)}\n\n".encode())
                    spoken += 1

            StubUpstream.live_bytes = bytes(heard)
            final = "".join(self.live_words) + "!"
            event = {"type": "transcript.text.done", "text": final, "timing": {"ms": 12}}
            self._chunk(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, SystemExit):
            return

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        elif self.path == "/v1/models":
            self._json(200, {"data": [{"id": "nemotron-asr"}, {"id": "kokoro"}]})
        else:
            self._json(404, {"error": "nope"})

    def do_POST(self):
        if self.path.startswith("/v1/audio/transcriptions/live"):
            self._live()
            return

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)

        if self.path == "/v1/audio/transcriptions":
            for chunk in body.split(b"name=\"model\"\r\n\r\n")[1:]:
                StubUpstream.seen_asr_model = chunk.split(b"\r\n")[0].decode()
            self._json(200, {"text": "  hello orchid  "})
            return

        if self.path == "/v1/audio/speech":
            payload = json.loads(body)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            audio = tone_wav(0.1, 24000) if payload.get("input") else b""
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
            return

        if self.path == "/v1/chat/completions":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            if StubUpstream.fail_chat:
                self.wfile.write(b'data: {"error": "boom"}\n\n')
            else:
                for piece in ["Hi", " there", "."]:
                    event = {"choices": [{"delta": {"content": piece}}]}
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
            return

        self._json(404, {"error": "nope"})


def start(server) -> int:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server.server_address[1]


class CompanionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), StubUpstream)
        cls.upstream.daemon_threads = True
        up_port = start(cls.upstream)
        cls.base = f"http://127.0.0.1:{up_port}"

        companion.AUDIO = cls.base
        companion.LLM = cls.base
        companion.PREFIX = "/chat"

        cls.app = ThreadingHTTPServer(("127.0.0.1", 0), companion.Handler)
        cls.app.daemon_threads = True
        port = start(cls.app)
        cls.root = f"http://127.0.0.1:{port}"

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.upstream.shutdown()

    # -- conversion ------------------------------------------------------- #

    def test_resamples_to_16k_mono(self):
        out = companion.to_wav16(tone_wav(0.3, 24000))
        with wave.open(io.BytesIO(out)) as wav:
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)

    def test_rejects_garbage_audio(self):
        with self.assertRaises(companion.UpstreamError):
            companion.to_wav16(b"not audio at all")

    # -- asr -------------------------------------------------------------- #

    def test_asr_returns_stripped_text(self):
        req = urllib.request.Request(
            self.root + "/chat/api/asr",
            data=tone_wav(),
            headers={"Content-Type": "audio/webm"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        self.assertEqual(data["text"], "hello orchid")
        self.assertEqual(StubUpstream.seen_asr_model, companion.ASR_MODEL)
        self.assertIn("total_ms", data)

    def test_asr_rejects_empty_body(self):
        req = urllib.request.Request(self.root + "/chat/api/asr", data=b"")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    # -- live asr --------------------------------------------------------- #

    def _live(self, path, body=b""):
        req = urllib.request.Request(self.root + path, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")

    def test_live_streams_partials_then_final(self):
        StubUpstream.live_bytes = b""
        start = self._live("/chat/api/asr/live")
        self.assertIn("id", start)
        self.assertEqual(start["rate"], 16000)

        sent = b""
        texts = []
        for marker in (b"\x01\x00", b"\x02\x00", b"\x03\x00"):
            pcm = marker * 2048
            sent += pcm
            snap = self._live(f"/chat/api/asr/live/{start['id']}/pcm", pcm)
            texts.append(snap["text"])

        end = self._live(f"/chat/api/asr/live/{start['id']}/end")
        self.assertEqual(StubUpstream.live_bytes, sent)
        seen = [text for text in texts if text]
        self.assertGreaterEqual(len(seen), 2, f"no progressive partials: {texts}")
        self.assertEqual(seen, sorted(seen, key=len), f"partials went backwards: {texts}")
        self.assertTrue(end["text"].startswith(seen[-1]), f"{seen[-1]!r} not a prefix of {end['text']!r}")
        self.assertEqual(end["text"], "Hello from the live stub!")
        self.assertEqual(end["partial"], "Hello from the")
        self.assertTrue(end["final"])
        self.assertAlmostEqual(end["seconds"], len(sent) / 32000, places=2)
        self.assertIsNone(end["error"])

        path = StubUpstream.live_paths[-1]
        self.assertIn("model=" + companion.ASR_MODEL, path)
        self.assertIn("sample_rate=16000", path)
        self.assertIn("language=" + companion.ASR_LANG, path)

    def test_live_unknown_session_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._live("/chat/api/asr/live/deadbeef/pcm", b"\x00\x00" * 8)
        self.assertEqual(ctx.exception.code, 404)

    def test_live_abort_drops_the_session(self):
        start = self._live("/chat/api/asr/live")
        self.assertTrue(self._live(f"/chat/api/asr/live/{start['id']}/abort")["ok"])
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._live(f"/chat/api/asr/live/{start['id']}/pcm", b"\x00\x00" * 8)
        self.assertEqual(ctx.exception.code, 404)

    def test_live_sweeper_aborts_idle_sessions(self):
        session = companion.live_start(companion.ASR_LANG)
        session.touched = time.time() - companion.LIVE_IDLE_S - 1
        companion.live_sweep()
        self.assertNotIn(session.id, companion.LIVE_SESSIONS)
        self.assertTrue(session._closed)

    # -- tts -------------------------------------------------------------- #

    def test_tts_returns_wav(self):
        req = urllib.request.Request(
            self.root + "/chat/api/tts",
            data=json.dumps({"text": "Hello."}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            audio = resp.read()
            self.assertEqual(resp.headers["Content-Type"], "audio/wav")
        self.assertTrue(audio.startswith(b"RIFF"))

    def test_tts_rejects_empty_text(self):
        req = urllib.request.Request(
            self.root + "/chat/api/tts",
            data=json.dumps({"text": "   "}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    # -- chat ------------------------------------------------------------- #

    def test_chat_streams_deltas(self):
        req = urllib.request.Request(
            self.root + "/chat/api/chat",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            self.assertEqual(resp.headers["Content-Type"], "text/event-stream")
            raw = resp.read().decode()

        events = [json.loads(line[6:]) for line in raw.split("\n\n") if line.startswith("data: ")]
        text = "".join(e["text"] for e in events if e["type"] == "delta")
        self.assertEqual(text, "Hi there.")
        self.assertEqual(events[-1]["type"], "done")

    def test_chat_requires_messages(self):
        req = urllib.request.Request(
            self.root + "/chat/api/chat",
            data=json.dumps({"messages": []}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    # -- static ----------------------------------------------------------- #

    def test_serves_page_under_prefix(self):
        with urllib.request.urlopen(self.root + "/chat/", timeout=10) as resp:
            self.assertIn(b"orchid", resp.read().lower())

    def test_serves_page_at_root(self):
        with urllib.request.urlopen(self.root + "/", timeout=10) as resp:
            self.assertIn(b"orchid", resp.read().lower())

    def test_serves_avatar(self):
        with urllib.request.urlopen(
            self.root + "/chat/avatar/orchid_girl/talk/talk_wide.png", timeout=10
        ) as resp:
            self.assertEqual(resp.headers["Content-Type"], "image/png")
            self.assertTrue(resp.read().startswith(b"\x89PNG"))

    def test_blocks_traversal(self):
        for path in ("/chat/../SKILL.md", "/chat/%2e%2e/%2e%2e/etc/passwd"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(self.root + path, timeout=10)
            self.assertEqual(ctx.exception.code, 404)

    def test_health_shape(self):
        with urllib.request.urlopen(self.root + "/chat/api/health", timeout=10) as resp:
            data = json.loads(resp.read())
        for key in ("asr", "tts", "llm", "voice", "asr_model"):
            self.assertIn(key, data)
        self.assertTrue(data["llm"])

    def test_healthz(self):
        with urllib.request.urlopen(self.root + "/chat/healthz", timeout=10) as resp:
            self.assertEqual(resp.read().strip(), b"ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
