#!/usr/bin/env python3
"""
audiocpp-asr - speech-to-text against a local audio.cpp server.

Covers the ASR half of the audio.cpp server (Nemotron 3.5 ASR by default):
transcribing audio files, and live microphone dictation.

The server is never started or stopped by this script. `--doctor` reports its
state and `server-cmd` prints the launcher to run.

This machine has no ffmpeg or sox, so audio is normalised to 16 kHz mono s16
WAV with GStreamer, which auto-decodes mp3/m4a/aac/flac/opus/vorbis/wav.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent

# ── Config ────────────────────────────────────────────────────────────────────

HOST = os.environ.get("AUDIOCPP_HOST", "127.0.0.1")
PORT = int(os.environ.get("AUDIOCPP_PORT", "8081"))
BASE = os.environ.get("AUDIOCPP_BASE", f"http://{HOST}:{PORT}")
TRANSCRIBE_URL = f"{BASE}/v1/audio/transcriptions"
DETAILS_URL = f"{BASE}/v1/audio/transcriptions/details"
LIVE_URL = f"{BASE}/v1/audio/transcriptions/live"
HEALTH_URL = f"{BASE}/health"

MODEL = os.environ.get("AUDIOCPP_ASR_MODEL", "crisperwhisper")
FAMILY = os.environ.get("AUDIOCPP_ASR_FAMILY", "crisperwhisper")
LANGUAGE = os.environ.get("AUDIOCPP_ASR_LANGUAGE", "en")
# audiocpp_cli lives beside server.json; it needs no server and runs offline mode.
# audio.cpp v0.9.3 layout: audiocpp_cli / server.json / model_specs/ sit together
_APP_CANDIDATES = [
    os.environ.get("AUDIOCPP_APP_DIR"),
    "/run/media/rodri/AI/audio.cpp",
    "/home/rodri/audio-v0.9.3-bin-ubuntu-x64-vulkan",
    "~/audio-v0.9.0-cpu",
    "~/Desktop/audio-v0.8.2-audio8-perf-hotfix-bin-ubuntu-x64-vulkan",
]


def _pick_app_dir():
    for cand in _APP_CANDIDATES:
        if cand and (Path(cand).expanduser() / "audiocpp_cli").exists():
            return Path(cand).expanduser()
    return Path("/run/media/rodri/AI/audio.cpp").expanduser()


APP_DIR = _pick_app_dir()
CLI_BIN = os.environ.get("AUDIOCPP_CLI", str(APP_DIR / "audiocpp_cli"))
AUDIO_DIR = Path(os.environ.get(
    "AUDIOCPP_GGUF_DIR", "/run/media/rodri/AI/models/audio-cpp/audio.cpp-gguf"))
DEFAULT_MODEL_PATH = os.environ.get(
    "AUDIOCPP_ASR_MODEL_PATH",
    str(AUDIO_DIR / "crisperwhisper-2-large-q4_k.gguf"))
MODEL_SPECS = Path(os.environ.get("AUDIOCPP_MODEL_SPECS", str(APP_DIR / "model_specs")))
LAUNCHER = Path(os.environ.get(
    "AUDIOCPP_LAUNCHER", "/home/rodri/Desktop/audio.cpp-server.desktop"))

TARGET_RATE = 16000
# docs/asr.md: nemotron_asr is cache-aware streaming with a 320 ms preferred
# input cadence; larger chunks decode fine but are off the tuned path.
LIVE_CHUNK_SECONDS = 0.320
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".mp4", ".aiff", ".wma"}


def parse_options(pairs: list) -> dict:
    """Build the request `options` object from repeated --option key=value.

    Values are coerced so the model receives a number/bool rather than a
    string: lookahead_tokens=13 must not arrive as "13".
    """
    out: dict = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"--option expects key=value, got {pair!r}")
        k, v = pair.split("=", 1)
        k, v = k.strip(), v.strip()
        low = v.lower()
        if low in ("true", "false"):
            out[k] = low == "true"
        else:
            try:
                out[k] = int(v)
            except ValueError:
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    return out


def add_seconds(payload: dict) -> dict:
    """Attach seconds to the sample offsets the model reports.

    docs: words/segments/speaker_turns carry start_sample/end_sample, and
    sample_rate is what converts them. Callers otherwise misread them as
    seconds and are wrong by a factor of sample_rate.
    """
    rate = payload.get("sample_rate")
    if not rate:
        return payload
    for key in ("words", "segments", "speaker_turns"):
        for item in payload.get(key) or []:
            for src, dst in (("start_sample", "start_sec"), ("end_sample", "end_sec")):
                if isinstance(item.get(src), (int, float)):
                    item[dst] = round(item[src] / rate, 3)
    return payload


def _bootstrap() -> None:
    """Re-exec into the skill's .venv if requests isn't importable here."""
    try:
        import requests  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    if os.environ.get("_AUDIOCPP_REEXEC") == "1":
        return
    py = SKILL_DIR / ".venv" / "bin" / "python"
    if py.exists():
        os.environ["_AUDIOCPP_REEXEC"] = "1"
        os.execv(str(py), [str(py), str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.exit(f"ERROR: requests is not installed. Create the venv:\n"
             f"  python3 -m venv {SKILL_DIR / '.venv'} && "
             f"{SKILL_DIR / '.venv' / 'bin' / 'pip'} install requests")


if __name__ == "__main__":
    _bootstrap()

import argparse  # noqa: E402

import requests  # noqa: E402


# ── Audio normalisation (GStreamer; no ffmpeg/sox on this machine) ────────────

def is_normalised_wav(path: Path) -> bool:
    try:
        with wave.open(str(path)) as w:
            return (w.getnchannels() == 1 and w.getframerate() == TARGET_RATE
                    and w.getsampwidth() == 2)
    except (wave.Error, EOFError, OSError):
        return False


def to_wav(src: Path, dest: Path) -> Path:
    """Decode/resample any supported audio to 16 kHz mono s16 WAV."""
    if src.suffix.lower() == ".wav" and is_normalised_wav(src):
        return src
    if not shutil_which("gst-launch-1.0"):
        sys.exit("gst-launch-1.0 not found; it is required to normalise audio "
                 "(no ffmpeg/sox on this machine). Install gstreamer1.0-tools.")
    pipeline = (
        "gst-launch-1.0 -q "
        f"uridecodebin3 uri=file://{src.resolve()} "
        "! audioconvert ! audioresample "
        f"! audio/x-raw,rate={TARGET_RATE},channels=1,format=S16LE "
        f"! wavenc ! filesink location={dest}"
    )
    proc = subprocess.run(pipeline, shell=True, capture_output=True, text=True, timeout=600)
    # gst-launch still creates a stub file on failure, so verify the result.
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size <= 44:
        detail = next((l for l in (proc.stderr or "").splitlines() if "ERROR" in l), "")
        sys.exit(f"could not decode {src.name}: {detail or 'unknown audio format'}")
    return dest


def shutil_which(bin_: str) -> str | None:
    from shutil import which
    return which(bin_)


def wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


# ── Server ────────────────────────────────────────────────────────────────────

def health() -> tuple[bool, str]:
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        return r.ok, r.text[:200] if r.ok else f"HTTP {r.status_code}"
    except requests.RequestException as e:
        return False, str(e)


def transcribe_file(wav: Path, ns, details: bool = False) -> dict:
    url = DETAILS_URL if details else TRANSCRIBE_URL
    data = {"model": ns.model}
    if ns.language:
        data["language"] = ns.language
    if ns.prompt:
        data["prompt"] = ns.prompt
    if ns.options:
        data["options"] = json.dumps(ns.options)
    with open(wav, "rb") as fh:
        r = requests.post(url, data=data, files={"file": (wav.name, fh, "audio/wav")},
                          timeout=ns.timeout)
    r.raise_for_status()
    payload = r.json()
    return add_seconds(payload) if details else payload


def transcribe_cli(wav: Path, ns) -> dict:
    """Offline, full-context ASR via audiocpp_cli. No server required.

    The server's nemotron-asr is configured mode: "streaming" so that live
    dictation works; mode is config-only, so whole-file accuracy comes from
    the CLI, which defaults to --mode offline and uses the same GGUF.
    """
    cli = Path(ns.cli)
    if not cli.exists():
        sys.exit(f"audiocpp_cli not found at {cli}\nSet AUDIOCPP_CLI or pass --cli.")
    if not Path(ns.model_path).exists():
        sys.exit(f"ASR model not found: {ns.model_path}\nPass --model-path or set "
                 f"AUDIOCPP_ASR_MODEL_PATH.")

    with tempfile.TemporaryDirectory() as tmp:
        text_out = Path(tmp) / "transcript.txt"
        cli_mode = getattr(ns, "cli_mode", "streaming")
        if ns.family == "crisperwhisper":
            cli_mode = "offline"
        cmd = [str(cli), "--task", "asr", "--family", ns.family,
               "--model", ns.model_path, "--backend", ns.backend,
               "--mode", cli_mode, "--audio", str(wav), "--text-out", str(text_out)]
        if ns.family == "crisperwhisper":
            cmd += ["--request-option", f"language={ns.language or 'en'}"]
        elif ns.language:
            cmd += ["--language", ns.language]
        if ns.prompt:
            cmd += ["--request-option", f"prompt={ns.prompt}"]
        for k, v in (ns.options or {}).items():
            cmd += ["--request-option", f"{k}={str(v).lower() if isinstance(v, bool) else v}"]
        words_out = None
        if ns.details:
            words_out = Path(tmp) / "words.json"
            cmd += ["--words-out", str(words_out)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=ns.timeout)
        if proc.returncode != 0:
            tail = "\n".join((proc.stderr or proc.stdout or "").splitlines()[-5:])
            sys.exit(f"audiocpp_cli failed (exit {proc.returncode}):\n{tail}")
        text = text_out.read_text(encoding="utf-8").strip() if text_out.exists() else ""
        if not text and proc.stdout:
            text = next((l.split("=", 1)[1].strip() for l in proc.stdout.splitlines()
                         if l.startswith("text_output=")), "")
        payload = {"text": text, "engine": "audiocpp_cli", "mode": "offline"}
        if words_out and words_out.exists():
            try:
                words = json.loads(words_out.read_text())
            except json.JSONDecodeError:
                words = None
            # --words-out writes a bare list of word objects, not an object.
            if isinstance(words, list):
                payload["words"] = words
            elif isinstance(words, dict):
                payload.update(words)
            payload.setdefault("sample_rate", TARGET_RATE)
            payload = add_seconds(payload)
        return payload


def stream_file(wav: Path, ns) -> None:
    """SSE deltas while an already-uploaded file is decoded."""
    data = {"model": ns.model, "stream": "true"}
    if ns.language:
        data["language"] = ns.language
    if ns.prompt:
        data["prompt"] = ns.prompt
    if ns.options:
        data["options"] = json.dumps(ns.options)
    with open(wav, "rb") as fh:
        with requests.post(TRANSCRIBE_URL, data=data,
                           files={"file": (wav.name, fh, "audio/wav")},
                           stream=True, timeout=ns.timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    evt = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if evt.get("type") == "transcript.text.delta":
                    print(evt.get("delta", ""), end="", flush=True)
                elif evt.get("type") == "transcript.text.done":
                    print(file=sys.stderr)
                    print(evt.get("text", ""), file=sys.stderr)


# ── Live dictation ────────────────────────────────────────────────────────────

class LiveStream:
    """Chunked request body + concurrent SSE reads on one socket.

    http.client cannot do this: request() buffers the body and getresponse()
    may not be called until it is finished.
    """

    def __init__(self, host: str, port: int, path: str, timeout: float = 300.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(0.25)
        self.buf = b""
        self.sock.sendall(
            f"POST {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"Accept: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n".encode()
        )
        self.status, self.chunked = self._read_headers()

    def _read_headers(self) -> tuple[int, bool]:
        while b"\r\n\r\n" not in self.buf:
            d = self.sock.recv(65536)
            if not d:
                raise ConnectionError("server closed during headers")
            self.buf += d
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        status = int(lines[0].split()[1])
        hdrs = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                hdrs[k.strip().lower()] = v.strip()
        return status, hdrs.get("transfer-encoding", "").lower() == "chunked"

    def send(self, data: bytes) -> None:
        self.sock.sendall(b"%x\r\n" % len(data) + data + b"\r\n")

    def end(self) -> None:
        self.sock.sendall(b"0\r\n\r\n")

    def _fill(self, deadline: float) -> bool:
        while time.time() < deadline:
            try:
                d = self.sock.recv(65536)
                if not d:
                    return False
                self.buf += d
                return True
            except socket.timeout:
                continue
        return False

    def _line(self, deadline: float) -> bytes | None:
        while b"\r\n" not in self.buf:
            if not self._fill(deadline):
                return None
        line, self.buf = self.buf.split(b"\r\n", 1)
        return line

    def _exact(self, n: int, deadline: float) -> bytes | None:
        while len(self.buf) < n:
            if not self._fill(deadline):
                return None
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def events(self, idle_timeout: float = 900.0):
        """Yield parsed SSE payloads until [DONE] or the server closes."""
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
                    n = int(size_line.split(b";")[0], 16)
                except ValueError:
                    continue
                if n == 0:
                    return
                payload = self._exact(n, deadline)
                if payload is None or self._exact(2, deadline) is None:
                    return
                pending += payload
            else:
                payload = self._line(deadline)
                if payload is None:
                    return
                pending += payload + b"\n"

            while b"\n" in pending:
                raw, pending = pending.split(b"\n", 1)
                raw = raw.strip()
                if not raw.startswith(b"data:"):
                    continue
                p = raw[5:].strip()
                if p == b"[DONE]":
                    return
                try:
                    yield json.loads(p)
                except json.JSONDecodeError:
                    continue

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def live(ns) -> int:
    if not shutil_which("pw-cat"):
        sys.exit("pw-cat not found (pipewire-utils); it captures the microphone.")
    params = (f"model={ns.model}&sample_rate={TARGET_RATE}&channels=1"
              f"&sample_format=s16le")
    if ns.language:
        params += f"&language={ns.language}"
    if ns.prompt:
        params += f"&prompt={requests.utils.quote(ns.prompt)}"
    for k, v in (getattr(ns, "options", None) or {}).items():
        val = str(v).lower() if isinstance(v, bool) else v
        params += f"&{k}={requests.utils.quote(str(val))}"
    path = f"/v1/audio/transcriptions/live?{params}"

    try:
        stream = LiveStream(HOST, PORT, path)
    except OSError as e:
        sys.exit(f"cannot reach audio.cpp at {HOST}:{PORT} ({e})")
    if stream.status != 200:
        stream.close()
        sys.exit(f"live endpoint returned HTTP {stream.status}")

    proc = subprocess.Popen(
        ["pw-cat", "-r", "-", "--rate", str(TARGET_RATE), "--channels", "1", "--format", "s16"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

    stop = threading.Event()

    def pump() -> None:
        try:
            while not stop.is_set():
                chunk = proc.stdout.read(int(LIVE_CHUNK_SECONDS * TARGET_RATE) * 2)
                if not chunk:
                    break
                stream.send(chunk)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.end()
            except OSError:
                pass

    threading.Thread(target=pump, daemon=True).start()
    print("listening — press Ctrl-C to stop", file=sys.stderr)
    final = ""
    try:
        for evt in stream.events():
            kind = evt.get("type")
            if kind == "transcript.text.delta":
                sys.stdout.write(evt.get("delta", ""))
                sys.stdout.flush()
            elif kind == "transcript.text.done":
                final = evt.get("text", final)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        proc.terminate()
        stream.close()

    if ns.output and final:
        Path(ns.output).expanduser().write_text(final, encoding="utf-8")
        print(f"\nwrote {ns.output}", file=sys.stderr)
    else:
        print(file=sys.stderr)
    return 0


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_doctor(ns) -> int:
    ok, detail = health()
    print(f"server        {HEALTH_URL}")
    print(f"  reachable   {'yes' if ok else 'NO'}  {detail}")
    if ok:
        try:
            models = requests.get(f"{BASE}/v1/models", timeout=5).json().get("data", [])
            for m in models:
                mark = "<- default" if m.get("id") == ns.model else ""
                print(f"  model       {m.get('id')} ({m.get('task', '?')}){mark}")
            if not any(m.get("id") == ns.model for m in models):
                print(f"  WARNING     default model '{ns.model}' is not loaded; "
                      f"is it in server.json?")
        except Exception as e:                    # noqa: BLE001
            print(f"  models      could not list ({e})")

    spec = MODEL_SPECS / "nemotron_asr.json"
    print(f"model spec    {spec} ({'found' if spec.exists() else 'missing'})")
    weights = sorted(AUDIO_DIR.glob("*asr*.gguf"))
    print(f"asr weights   {AUDIO_DIR}")
    for w in weights:
        print(f"  {w.name}  ({w.stat().st_size / 1e9:.2f} GB)")
    if not weights:
        print("  none found")
    for tool in ("gst-launch-1.0", "pw-cat"):
        print(f"{tool:13} {shutil_which(tool) or 'NOT INSTALLED'}")
    print(f"launcher      {LAUNCHER} ({'present' if LAUNCHER.exists() else 'missing'})")
    if not ok:
        print("\nStart the server (double-click the desktop icon, or):")
        print(server_command())
    return 0 if ok else 1


def server_command() -> str:
    app = Path(os.environ.get(
        "AUDIOCPP_APP_DIR",
        str(APP_DIR)))
    script = app / "run-audiocpp.sh"
    if script.exists():
        return f"{script}          # foreground, streams logs; Ctrl-C to stop"
    return (f"# Expected launcher at {script}\n"
            f"{app / 'audiocpp_server'} --config {app / 'server.json'} "
            f"--host {HOST} --port {PORT} --backend vulkan --device 0")


def cmd_languages(ns) -> int:
    spec = MODEL_SPECS / "nemotron_asr.json"
    if not spec.exists():
        sys.exit(f"model spec not found: {spec}")
    langs = json.loads(spec.read_text()).get("languages", [])
    print(f"{len(langs)} locales supported by Nemotron 3.5 ASR:")
    for i in range(0, len(langs), 6):
        print("  " + "  ".join(langs[i:i + 6]))
    print("\nUse 'auto' (or omit) for automatic language detection.")
    return 0


def cmd_transcribe(ns) -> int:
    if ns.details and ns.stream:
        sys.exit("--details and --stream are mutually exclusive: the SSE response "
                 "carries transcript deltas only and has nowhere to put the "
                 "timestamp arrays (the server returns 400 for this).")
    if ns.engine == "cli" and ns.stream:
        sys.exit("--stream is server-only; the CLI has no SSE route.")

    ns.options = parse_options(ns.options)
    files = [Path(f).expanduser() for f in ns.files]
    for f in files:
        if not f.exists():
            sys.exit(f"no such file: {f}")
        if f.suffix.lower() not in AUDIO_EXTS:
            sys.exit(f"unsupported audio type '{f.suffix}' for {f.name}; expected one of "
                     + ", ".join(sorted(AUDIO_EXTS)))

    outputs = []
    for src in files:
        tmp = None
        try:
            if src.suffix.lower() == ".wav" and is_normalised_wav(src):
                wav = src
            else:
                tmp = Path(tempfile.mkstemp(suffix=".wav")[1])
                print(f"normalising {src.name} -> 16 kHz mono...", file=sys.stderr)
                wav = to_wav(src, tmp)
                print(f"  {wav_duration(wav):.1f}s of audio", file=sys.stderr)
            if ns.stream:
                stream_file(wav, ns)
                outputs.append("")
                continue
            if ns.engine == "cli":
                result = transcribe_cli(wav, ns)
            else:
                result = transcribe_file(wav, ns, details=ns.details)
            if ns.details:
                outputs.append(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                outputs.append(result.get("text", "").strip())
        except requests.HTTPError as e:
            body = e.response.text[:300] if e.response is not None else ""
            sys.exit(f"{src.name}: HTTP {e.code} from the server: {body}")
        finally:
            if tmp and not ns.keep_wav:
                tmp.unlink(missing_ok=True)
            elif tmp:
                print(f"kept {tmp}", file=sys.stderr)

    if ns.output:
        out = Path(ns.output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n\n".join(o for o in outputs if o) + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print("\n\n".join(o for o in outputs if o))
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(
        prog="asr.py",
        description="Local speech-to-text via the audio.cpp server (Nemotron ASR).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--model", default=MODEL, help=f"ASR model id (default: {MODEL})")
        sp.add_argument("--language", default=LANGUAGE,
                        help="BCP-47 locale, or 'auto' (default: %(default)s)")
        sp.add_argument("--prompt", help="hotwords / spellings to bias recognition")
        sp.add_argument("-o", "--output", help="write text here instead of stdout")
        sp.add_argument("--option", action="append", dest="options", metavar="KEY=VALUE",
                        help="model request option, repeatable; values are typed "
                             "(e.g. --option lookahead_tokens=13 --option keep_language_tags=true)")

    t = sub.add_parser("transcribe", help="transcribe audio file(s)")
    t.add_argument("files", nargs="+", help="audio file(s): wav, mp3, m4a, flac, ogg, opus…")
    t.add_argument("--details", action="store_true",
                   help="return token timestamps / speaker turns as JSON")
    t.add_argument("--stream", action="store_true", help="print SSE deltas while decoding")
    t.add_argument("--keep-wav", action="store_true", help="keep the normalised wav")
    t.add_argument("--timeout", type=int, default=900)
    t.add_argument("--engine", choices=["server", "cli"], default="server",
                   help="'server' (default) needs the audio.cpp server running; "
                        "'cli' shells out to audiocpp_cli in offline mode and "
                        "needs no server")
    t.add_argument("--cli", default=CLI_BIN, help="audiocpp_cli binary (--engine cli)")
    t.add_argument("--model-path", default=DEFAULT_MODEL_PATH,
                   help="GGUF weights for --engine cli")
    t.add_argument("--family", default=FAMILY, help="model family for --engine cli")
    t.add_argument("--backend", default="vulkan", help="compute backend for --engine cli")
    add_common(t)
    t.set_defaults(func=cmd_transcribe)

    lv = sub.add_parser("live", help="dictate from the microphone")
    lv.add_argument("--timeout", type=int, default=900)
    add_common(lv)
    lv.set_defaults(func=live)

    d = sub.add_parser("doctor", help="check server, models, and audio tooling")
    d.add_argument("--model", default=MODEL)
    d.set_defaults(func=lambda ns: cmd_doctor(ns))

    lang = sub.add_parser("languages", help="list supported locales")
    lang.set_defaults(func=cmd_languages)

    ns = p.parse_args()
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
