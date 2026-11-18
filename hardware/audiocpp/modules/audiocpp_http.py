#!/usr/bin/env python3
"""audio.cpp HTTP commands: talk to an already-running server over the network.

Split out of `audiocpp_cli.py`; the server is remote-tolerant (Tailscale
hosts), so these paths need sockets and auth but never touch the local engine.
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Any, Dict, Optional

from audiocpp_core import (
    BACKEND,
    DEFAULT_ASR,
    MODEL_REGISTRY,
    play_audio_file,
)


def cmd_transcribe_http(
    host: str,
    port: int,
    scheme: str,
    ssl_ctx: ssl.SSLContext,
    audio_path: str,
    model_key: str = DEFAULT_ASR,
    language: str = "en",
    mode: str = "verbatim",
    out_file: Optional[str] = None,
    words_out: Optional[str] = None,
    metrics: bool = False,
    json_mode: bool = False,
    quiet: bool = False,
) -> Dict[str, Any]:
    p = Path(audio_path).resolve()
    if not p.is_file():
        sys.exit(f"❌ Error: Audio file not found: {audio_path}")

    audio_bytes = p.read_bytes()
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
    server_id = MODEL_REGISTRY.get(model_key, {}).get("server_id", model_key)
    body_parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{server_id}\r\n".encode("utf-8"),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\n{language}\r\n".encode("utf-8"),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{p.name}\"\r\nContent-Type: audio/wav\r\n\r\n".encode("utf-8"),
        audio_bytes,
        f"\r\n--{boundary}--\r\n".encode("utf-8")
    ]
    full_body = b"".join(body_parts)

    endpoint = f"{scheme}://{host}:{port}/v1/audio/transcriptions"
    req = urllib.request.Request(
        endpoint,
        data=full_body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )

    t0 = time.time()
    ctx = ssl_ctx if scheme == "https" else None
    try:
        with urllib.request.urlopen(req, timeout=60.0, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        sys.exit(f"❌ Transcription over HTTP failed: {e}")

    wall_ms = round((time.time() - t0) * 1000.0, 1)
    text = data.get("text", "").strip()
    timing = data.get("timing", {})
    dur_s = round(timing.get("audio_duration_ms", 0) / 1000.0, 3)
    if dur_s == 0.0:
        try:
            with wave.open(str(p), "rb") as wf:
                dur_s = round(wf.getnframes() / float(wf.getframerate()), 3)
        except Exception:
            pass

    rtf = round(timing.get("rtf", (wall_ms / 1000.0) / dur_s if dur_s > 0 else 0.0), 4)

    if out_file:
        Path(out_file).resolve().write_text(text, encoding="utf-8")

    if json_mode:
        payload = {
            "task": "asr",
            "model": model_key,
            "text": text,
            "duration_s": dur_s,
            "wall_ms": wall_ms,
            "rtf": rtf,
            "words": [],
            "remote": True,
            "host": f"{scheme}://{host}:{port}"
        }
        print(json.dumps(payload, indent=2))
        return payload

    if metrics and not quiet:
        x_rt = round(dur_s / (wall_ms / 1000.0), 1) if wall_ms > 0 else 0.0
        sys.stderr.write(f"📊 [Metrics] Wall: {wall_ms:.1f}ms | RTF: {rtf:.4f} ({x_rt:.1f}x real-time)\n")

    if not out_file:
        print(text)

    return {
        "text": text,
        "audio_duration_ms": int(dur_s * 1000),
        "wall_ms": wall_ms,
        "rtf": rtf
    }


def cmd_speak_http(
    host: str,
    port: int,
    scheme: str,
    ssl_ctx: ssl.SSLContext,
    text: str,
    model_key: str = "supertonic",
    voice_id: Optional[str] = None,
    voice_ref: Optional[str] = None,
    out_file: str = "output.wav",
    metrics: bool = False,
    json_mode: bool = False,
    quiet: bool = False,
    play: bool = False,
) -> Dict[str, Any]:
    meta = MODEL_REGISTRY.get(model_key, {})
    v_id = voice_id or meta.get("default_voice")
    if not v_id and model_key == "kokoro":
        v_id = "af_bella"

    payload: Dict[str, Any] = {
        "model": MODEL_REGISTRY.get(model_key, {}).get("server_id", model_key),
        "input": text,
    }
    if v_id:
        payload["voice"] = v_id

    out_p = Path(out_file).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    endpoint = f"{scheme}://{host}:{port}/v1/audio/speech"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, headers={"Content-Type": "application/json"})

    t0 = time.time()
    ctx = ssl_ctx if scheme == "https" else None
    try:
        with urllib.request.urlopen(req, timeout=60.0, context=ctx) as resp:
            audio_bytes = resp.read()
    except Exception as e:
        sys.exit(f"❌ Speech synthesis over HTTP failed: {e}")

    wall_ms = round((time.time() - t0) * 1000.0, 1)
    out_p.write_bytes(audio_bytes)

    dur_s = 0.0
    try:
        with wave.open(str(out_p), "rb") as wf:
            dur_s = round(wf.getnframes() / float(wf.getframerate()), 3)
    except Exception:
        pass

    rtf = round((wall_ms / 1000.0) / dur_s, 4) if dur_s > 0 else 0.0
    played = play_audio_file(out_p, quiet=quiet) if play else False

    if json_mode:
        res = {
            "task": "tts",
            "status": "ok",
            "audio_file": str(out_p),
            "model": model_key,
            "voice": v_id or "default",
            "duration_s": dur_s,
            "wall_ms": wall_ms,
            "rtf": rtf,
            "played": played,
            "remote": True,
            "host": f"{scheme}://{host}:{port}"
        }
        print(json.dumps(res, indent=2))
        return res

    if metrics and not quiet:
        x_rt = round(dur_s / (wall_ms / 1000.0), 1) if wall_ms > 0 else 0.0
        sys.stderr.write(f"📊 [Metrics] Wall: {wall_ms:.1f}ms | RTF: {rtf:.4f} ({x_rt:.1f}x real-time)\n")

    if not quiet:
        sys.stderr.write(f"[audiocpp] Generated {dur_s}s audio -> {out_p}\n")

    return {
        "text": text,
        "audio_out": str(out_p),
        "wall_ms": wall_ms,
        "audio_duration_ms": int(dur_s * 1000),
        "rtf": rtf,
        "played": played,
    }


def cmd_models_http(host: str, port: int, scheme: str, ssl_ctx: ssl.SSLContext, json_mode: bool = False):
    endpoint = f"{scheme}://{host}:{port}/v1/models"
    ctx = ssl_ctx if scheme == "https" else None
    try:
        req = urllib.request.Request(endpoint)
        with urllib.request.urlopen(req, timeout=5.0, context=ctx) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        sys.exit(f"❌ Server at {scheme}://{host}:{port} unreachable: {e}")

    models_list = raw.get("data", [])
    if json_mode:
        print(json.dumps(models_list, indent=2))
        return

    print(f"{'MODEL ID':<18} {'FAMILY':<22} {'TASK':<8} {'LOADED':<10} {'MODE'}")
    print("-" * 75)
    for m in models_list:
        loaded_str = "Loaded" if m.get("loaded") else "Standby"
        print(f"{m.get('id', ''):<18} {m.get('family', ''):<22} {m.get('task', ''):<8} {loaded_str:<10} {m.get('mode', '')}")


def cmd_doctor_http(host: str, port: int, scheme: str, ssl_ctx: ssl.SSLContext, json_mode: bool = False):
    endpoint = f"{scheme}://{host}:{port}/health"
    ctx = ssl_ctx if scheme == "https" else None
    try:
        req = urllib.request.Request(endpoint)
        with urllib.request.urlopen(req, timeout=3.0, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        if json_mode:
            print(json.dumps({"status": "offline", "error": str(e), "host": f"{scheme}://{host}:{port}"}))
            return
        sys.exit(f"❌ Server at {scheme}://{host}:{port} unreachable: {e}")

    if json_mode:
        doc = {
            "status": "online",
            "remote": True,
            "host": f"{scheme}://{host}:{port}",
            "backend": data.get("backend", BACKEND),
            "models_total": data.get("models", 15),
            "gpu_ready": data.get("backend") in ("hip", "rocm", "vulkan", "cuda", "metal"),
        }
        print(json.dumps(doc, indent=2))
        return

    print(f"🔍 [audiocpp] Remote Diagnostic Health Check ({scheme}://{host}:{port})")
    print(f"  Status:       🟢 ONLINE")
    print(f"  Backend:      {data.get('backend', BACKEND)}")
    print(f"  Models Total: {data.get('models', 15)} registered models")
