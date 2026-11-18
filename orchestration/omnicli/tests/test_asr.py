#!/usr/bin/env python3
"""Offline tests for audiocpp-asr. Stubs the audio.cpp server; no real model."""
import http.server
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest import mock

SKILL_DIR = Path(__file__).resolve().parent.parent

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    if os.environ.get("_AUDIOCPP_TEST_REEXEC") != "1":
        os.environ["_AUDIOCPP_TEST_REEXEC"] = "1"
        py = str(SKILL_DIR / ".venv" / "bin" / "python")
        os.execv(py, [py, str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.exit("requests missing from the skill venv")

sys.path.insert(0, str(SKILL_DIR / "scripts"))
import asr  # noqa: E402

CLI = [sys.executable, str(SKILL_DIR / "scripts" / "asr.py")]
TEXT = "hello from the stub server"


DEAD = "http://127.0.0.1:1"          # nothing listens here


def run(*args, base: str | None = DEAD):
    """Invoke the CLI in a subprocess with AUDIOCPP_BASE pointed at a stub.

    The endpoint is passed by environment variable: the CLI is a separate
    process, so patching this module's globals would not reach it.
    """
    env = {**os.environ, "AUDIOCPP_BASE": base or DEAD}
    return subprocess.run(CLI + list(args), capture_output=True, text=True, env=env)


def tone_wav(path: Path, seconds: float = 0.5, rate: int = 16000, channels: int = 1) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<h", (i * 37) % 20000 - 10000) for i in range(int(rate * seconds)))
        w.writeframes(frames)
    return path


class StubServer:
    """Stand-in audio.cpp: /health, /v1/models, and the transcription routes."""

    def __init__(self, text=TEXT, details=True):
        self.received = []
        self.text = text
        self.details = details
        received, text, details = self.received, self.text, self.details

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _json(self, obj, code=200):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                if self.path.startswith("/health"):
                    self._json({"status": "ok", "models": 2})
                elif self.path.startswith("/v1/models"):
                    self._json({"data": [{"id": "nemotron-asr", "task": "asr"},
                                         {"id": "audio8-tts", "task": "tts"}]})
                else:
                    self._json({"error": "nf"}, 404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n)
                ctype = self.headers.get("Content-Type", "")
                body = raw.decode("latin-1")
                received.append({"raw_len": len(raw), "ctype": ctype, "body": body})
                # multipart encodes a field as name="stream"\r\n\r\ntrue, so the
                # literal text "stream=true" never appears in the body.
                if 'name="stream"' in body and "true" in body:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for payload in ('{"type":"transcript.text.delta","delta":"hello "}',
                                    '{"type":"transcript.text.delta","delta":"world"}',
                                    "[DONE]"):
                        data = f"data: {payload}\n\n".encode()
                        self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                    return
                if self.path.endswith("/details") and details:
                    self._json({"text": text, "language": "en-US",
                                "words": [{"word": "hello", "start_sample": 0,
                                           "end_sample": 160, "confidence": 0.99}]})
                else:
                    self._json({"text": text, "timing": {"total_ms": 12}})

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()


class TestLanguages(unittest.TestCase):
    def test_reads_real_model_spec(self):
        r = run("languages")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("40 locales", r.stdout)
        self.assertIn("en-US", r.stdout)
        self.assertIn("zh-CN", r.stdout)

    def test_locale_count_matches_spec_json(self):
        spec = json.loads((asr.MODEL_SPECS / "nemotron_asr.json").read_text())
        self.assertEqual(len(spec["languages"]), 40)


class TestDoctor(unittest.TestCase):
    def test_unreachable_exits_nonzero_and_shows_launcher(self):
        r = run("doctor", base=DEAD)
        self.assertEqual(r.returncode, 1)
        self.assertIn("reachable   NO", r.stdout)
        self.assertIn("run-audiocpp.sh", r.stdout)

    def test_reports_server_and_models_when_up(self):
        srv = StubServer()
        self.addCleanup(srv.stop)
        r = run("doctor", base=f"http://127.0.0.1:{srv.port}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("reachable   yes", r.stdout)
        self.assertIn("nemotron-asr", r.stdout)
        self.assertIn("<- default", r.stdout)


def requests_stub(srv):
    """A requests-shaped object whose URLs are rewritten to the stub port."""
    class R:
        def __init__(self, real):
            self._r = real

        def get(self, url, **kw):
            return self._r.get(rewrite(url, srv), **kw)

        def post(self, url, **kw):
            return self._r.post(rewrite(url, srv), **kw)

    import requests
    return R(requests)


def rewrite(url, srv):
    if url.startswith("http://127.0.0.1:1") or "AUDIOCPP" in url:
        return url
    parts = url.split("/", 3)
    return f"http://127.0.0.1:{srv.port}/" + parts[3] if len(parts) > 3 else url


class TestTranscribe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        self.srv = StubServer()
        self.addCleanup(self.srv.stop)
        self.base = f"http://127.0.0.1:{self.srv.port}"

    def _transcribe(self, *extra):
        return run("transcribe", *extra, base=self.base)

    def test_already_normalised_wav_is_not_reconverted(self):
        src = tone_wav(self.p / "a.wav")
        r = self._transcribe(str(src))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(TEXT, r.stdout)
        self.assertNotIn("normalising", r.stderr)

    def test_multipart_request_shape(self):
        src = tone_wav(self.p / "a.wav")
        self._transcribe(str(src))
        req = self.srv.received[0]
        self.assertIn("multipart/form-data", req["ctype"])
        body = req["body"]
        self.assertIn('name="model"', body)
        self.assertIn("nemotron-asr", body)
        self.assertIn('name="language"', body)
        self.assertIn("en-US", body)
        self.assertIn("RIFF", body, "wav payload should be in the multipart body")

    def test_language_and_prompt_are_sent(self):
        src = tone_wav(self.p / "a.wav")
        self._transcribe(str(src), "--language", "es-ES", "--prompt", "Kanban Kubernetes")
        body = self.srv.received[0]["body"]
        self.assertIn("es-ES", body)
        self.assertIn("Kanban Kubernetes", body)

    def test_auto_language(self):
        src = tone_wav(self.p / "a.wav")
        self._transcribe(str(src), "--language", "auto")
        self.assertIn("auto", self.srv.received[0]["body"])

    def test_details_returns_json(self):
        src = tone_wav(self.p / "a.wav")
        r = self._transcribe(str(src), "--details")
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["text"], TEXT)
        self.assertIn("words", payload)

    def test_stream_emits_deltas_and_final(self):
        src = tone_wav(self.p / "a.wav")
        r = self._transcribe(str(src), "--stream")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hello world", r.stdout)

    def test_output_file(self):
        src = tone_wav(self.p / "a.wav")
        out = self.p / "t.txt"
        r = self._transcribe(str(src), "-o", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(TEXT, out.read_text())

    def test_multiple_files(self):
        a = tone_wav(self.p / "a.wav")
        b = tone_wav(self.p / "b.wav")
        r = self._transcribe(str(a), str(b))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count(TEXT), 2)
        self.assertEqual(len(self.srv.received), 2)

    def test_unsupported_extension_rejected(self):
        bad = self.p / "notes.pdf"
        bad.write_text("x")
        r = self._transcribe(str(bad))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unsupported audio type", r.stderr)

    def test_missing_file(self):
        r = self._transcribe(str(self.p / "ghost.wav"))
        self.assertNotEqual(r.returncode, 0)

    def test_no_files(self):
        self.assertNotEqual(run("transcribe").returncode, 0)

    def test_non_wav_is_normalised_via_gstreamer(self):
        """A stereo 44.1 kHz wav must be resampled to 16 kHz mono."""
        src = tone_wav(self.p / "stereo.wav", seconds=0.4, rate=44100, channels=2)
        dest = self.p / "norm.wav"
        out = asr.to_wav(src, dest)
        with wave.open(str(out)) as w:
            self.assertEqual(w.getframerate(), 16000)
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)

    def test_garbage_audio_fails_clearly(self):
        """A non-audio file must error, not silently produce an empty transcript."""
        junk = self.p / "fake.mp3"
        junk.write_text('{"ModTime": "2026-09-28"}')
        with self.assertRaises(SystemExit) as cm:
            asr.to_wav(junk, self.p / "junk.wav")
        self.assertIn("could not decode", str(cm.exception))

    def test_is_normalised_wav_detection(self):
        self.assertTrue(asr.is_normalised_wav(tone_wav(self.p / "ok.wav")))
        self.assertFalse(asr.is_normalised_wav(tone_wav(self.p / "st.wav", rate=44100)))
        self.assertFalse(asr.is_normalised_wav(tone_wav(self.p / "du.wav", channels=2)))
        self.assertFalse(asr.is_normalised_wav(self.p / "junk.mp3"))


class ChunkedSseServer:
    """Raw socket server that speaks the chunked request/response protocol
    used by /v1/audio/transcriptions/live."""

    def __init__(self, events):
        self.events = events
        self.got_request = b""
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        conn, _ = self.sock.accept()
        conn.settimeout(5)
        data = b""
        try:
            while b"\r\n\r\n" not in data:
                data += conn.recv(4096)
            head, rest = data.split(b"\r\n\r\n", 1)
            self.got_request = head
            # Respond immediately, as a real server does: the client is still
            # uploading and must be able to read the response concurrently.
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                         b"Transfer-Encoding: chunked\r\n\r\n")
            for payload in self.events:
                chunk = f"data: {payload}\n\n".encode()
                conn.sendall(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                time.sleep(0.01)
            conn.sendall(b"0\r\n\r\n")
            # drain the rest of the upload so the client's sends don't block
            while b"0\r\n\r\n" not in rest:
                more = conn.recv(4096)
                if not more:
                    break
                rest += more
            self.got_body_len = len(rest)
        except OSError:
            pass
        conn.close()

    def stop(self):
        self.sock.close()


import time  # noqa: E402


class TestLiveProtocol(unittest.TestCase):
    def test_chunked_upload_and_sse_deltas(self):
        srv = ChunkedSseServer([
            '{"type":"transcript.text.delta","delta":"hello "}',
            '{"type":"transcript.text.delta","delta":"there"}',
            '{"type":"transcript.text.done","text":"hello there"}',
            "[DONE]",
        ])
        self.addCleanup(srv.stop)
        stream = asr.LiveStream("127.0.0.1", srv.port, "/v1/audio/transcriptions/live?model=nemotron-asr")
        self.addCleanup(stream.close)
        self.assertEqual(stream.status, 200)
        self.assertTrue(stream.chunked)

        pcm = b"\x00\x01" * 16000                       # 1 s of s16 at 16 kHz
        stream.send(pcm)
        stream.send(pcm)
        stream.end()

        deltas, final = [], ""
        for evt in stream.events(idle_timeout=10):
            if evt.get("type") == "transcript.text.delta":
                deltas.append(evt["delta"])
            elif evt.get("type") == "transcript.text.done":
                final = evt["text"]
        self.assertEqual("".join(deltas), "hello there")
        self.assertEqual(final, "hello there")

        # the request must be a chunked upload with the right query string
        self.assertIn(b"Transfer-Encoding: chunked", srv.got_request)
        self.assertIn(b"Accept: text/event-stream", srv.got_request)
        self.assertIn(b"/v1/audio/transcriptions/live?model=nemotron-asr", srv.got_request)

    def test_live_url_includes_language_and_prompt(self):
        ns = mock.Mock(model="nemotron-asr", language="es-ES",
                       prompt="Kanban Kubernetes", output=None, options=None)
        captured = {}

        def fake_stream(host, port, path, timeout=300.0):
            captured["path"] = path
            raise OSError("stop here")

        with mock.patch.object(asr, "LiveStream", fake_stream):
            with self.assertRaises(SystemExit):
                asr.live(ns)
        self.assertIn("sample_rate=16000", captured["path"])
        self.assertIn("channels=1", captured["path"])
        self.assertIn("sample_format=s16le", captured["path"])
        self.assertIn("language=es-ES", captured["path"])
        self.assertIn("Kanban", captured["path"])


class TestNoServerControl(unittest.TestCase):
    def test_skill_never_launches_the_server(self):
        """The skill must not start or kill audiocpp_server behind the user."""
        src = (SKILL_DIR / "scripts" / "asr.py").read_text()
        for banned in ("pkill", "subprocess.run([\"audiocpp", "nohup", "run-audiocpp.sh\")"):
            self.assertNotIn(banned, src, f"{banned!r} would mean the skill manages the server")

    def test_launcher_reference_present(self):
        self.assertTrue(asr.LAUNCHER.exists(), "expected the audio.cpp desktop launcher")
        self.assertIn("run-audiocpp.sh", asr.server_command())


if __name__ == "__main__":
    unittest.main(verbosity=2)
