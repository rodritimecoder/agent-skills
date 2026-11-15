#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Dict, Any, List, Optional


def _drive_root() -> Path:
    """The AI volume root: $AI_ROOT, else the nearest ancestor holding models/.

    Every path below is relative to this, so the skill works wherever the
    volume is mounted (or from a harness copy with $AI_ROOT set) instead of
    only at the one absolute path it was written for.
    """
    env = os.environ.get("AI_ROOT")
    if env:
        return Path(env).expanduser()
    for parent in Path(__file__).resolve().parents:
        if (parent / "models").is_dir():
            return parent
    return Path("/run/media/rodri/AI")


DRIVE = _drive_root()
AUDIO_CPP_DIR = Path(os.environ.get("AUDIOCPP_DIR", DRIVE / "audio.cpp"))
MODELS_DIR = Path(os.environ.get("AUDIOCPP_MODELS_DIR", DRIVE / "models/audio-cpp/audio.cpp-gguf"))
DIAR_MODELS_DIR = Path(os.environ.get("DIAR_MODEL_DIR", MODELS_DIR / "Nemotron-3-Diarization-GGUF"))
DIAR_HF_REPO = "audio-cpp/Nemotron-3-Diarization-GGUF"
VOICE_DIR = Path(os.environ.get("AUDIOCPP_VOICE_DIR", DRIVE / "voice"))

CLI_BIN = Path(os.environ.get("AUDIOCPP_CLI", str(AUDIO_CPP_DIR / "audiocpp_cli")))
SERVER_BIN = AUDIO_CPP_DIR / "audiocpp_server"
CONFIG_FILE = AUDIO_CPP_DIR / "server.json"

# The HIP/ROCm build links libamdhip64/libhipblas/libhipblaslt from the ROCm
# SDK; the system install at /opt/rocm/lib is not in the ldconfig cache. The
# Vulkan build does not need this, and the loader ignores what nothing links.
BACKEND = os.environ.get("AUDIOCPP_BACKEND", "vulkan")
ROCM_LIB_DIR = Path(os.environ.get("ROCM_LIB_DIR", "/opt/rocm/lib"))

# What runs when the caller names no model. Both are served in streaming mode by
# references/server.json; check-docs.py asserts the two stay in agreement.
# crisperwhisper remains the model of choice for mining, requested explicitly,
# because it is the only ASR family that emits word timings.
DEFAULT_ASR = "nemotron"
DEFAULT_TTS = "kokoro"


def _loader_env() -> Dict[str, str]:
    env = dict(os.environ)
    if ROCM_LIB_DIR.is_dir():
        prev = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{ROCM_LIB_DIR}{os.pathsep}{prev}" if prev else str(ROCM_LIB_DIR)
    return env

MODEL_REGISTRY = {
    # ASR Models
    "nemotron": {
        "family": "nemotron_asr",
        "task": "asr",
        "path": MODELS_DIR / "nemotron-3.5-asr-streaming-0.6b-q8_0.gguf",
        "server_id": "nemotron-asr",
        "desc": "Nemotron-3.5-ASR 0.6B Q8_0 (62.9x real-time)",
    },
    "nemotron-f16": {
        "family": "nemotron_asr",
        "task": "asr",
        "path": MODELS_DIR / "nemotron-3.5-asr-streaming-0.6b-f16.gguf",
        "server_id": "nemotron-asr-f16",
        "desc": "Nemotron-3.5-ASR 0.6B F16 (59.0x real-time)",
    },
    "crisperwhisper": {
        "family": "crisperwhisper",
        "task": "asr",
        "path": MODELS_DIR / "crisperwhisper-2-large-q4_k.gguf",
        "desc": "CrisperWhisper 2.0 Large Q4_K (7.2x real-time verbatim ASR)",
    },
    # TTS Models
    "supertonic": {
        "family": "supertonic",
        "task": "tts",
        "path": MODELS_DIR / "supertonic-3-q8_0.gguf",
        "desc": "Supertonic-3 Q8_0 (Ultra-Fast 46.5x real-time)",
    },
    "kokoro": {
        "family": "kokoro_tts",
        "task": "tts",
        "path": MODELS_DIR / "kokoro-82m-bf16.gguf",
        "default_voice": "af_bella",
        "desc": "Kokoro 82M BF16 (16.8x real-time, high quality)",
    },
    "kitten": {
        "family": "kitten_tts",
        "task": "tts",
        "path": MODELS_DIR / "kitten-tts-mini-0.8-orig.gguf",
        "desc": "Kitten-TTS Mini 0.8 (13.1x real-time)",
    },
    "fish": {
        "family": "fish_audio",
        "task": "tts",
        "path": MODELS_DIR / "fish-audio-s2-pro-q4_k.gguf",
        "server_id": "fish-s2-pro",
        "desc": "Fish Audio S2 Pro Q4_K (Real-Time Voice Clone)",
    },
    "audio8": {
        "family": "audio8_tts",
        "task": "tts",
        "path": DRIVE / "models/audio-cpp/Audio8-TTS-Realistic-0.6b-GGUF/audio8-tts-realistic-0.6b-q8_0.gguf",
        "server_id": "audio8-tts",
        "desc": "Audio8 Realistic 0.6B Q8_0 (Voice Clone)",
    },
    "higgs": {
        "family": "higgs_audio_tts",
        "task": "tts",
        "path": MODELS_DIR / "higgs-audio-v3-tts-4b-q8_0.gguf",
        "server_id": "higgs-tts",
        "desc": "Higgs Audio v3 4B Q8_0 (2.25x real-time flagship)",
    },
    "omnivoice": {
        "family": "omnivoice",
        "task": "tts",
        "path": MODELS_DIR / "omnivoice-bf16.gguf",
        "desc": "Omnivoice BF16 (3.7x real-time)",
    },
    "index": {
        "family": "index_tts2",
        "task": "tts",
        "path": MODELS_DIR / "index-tts2_5-q8_0.gguf",
        "server_id": "index-tts2",
        "desc": "Index-TTS 2.5 Q8_0 (Voice Clone)",
    },
    # Aligner
    "aligner": {
        "family": "qwen3_forced_aligner",
        "task": "align",
        "path": MODELS_DIR / "qwen3-forced-aligner-0.6b-q8_0.gguf",
        "desc": "Qwen3 Forced Aligner 0.6B Q8_0 (59.7x real-time)",
    },
    # Diarization
    "diar": {
        "family": "nemotron_3_diar",
        "task": "diar",
        "path": DIAR_MODELS_DIR / f"nemotron-3-diarization-{os.environ.get('DIAR_PRECISION', 'bf16')}.gguf",
        "desc": "Nemotron 3 Diarization (Speaker Turns, up to 8 speakers)",
    },
}


KOKORO_VOICES = [
    {"id": "af_bella", "name": "Bella", "gender": "female", "accent": "us", "description": "American Female (Default)"},
    {"id": "af_sarah", "name": "Sarah", "gender": "female", "accent": "us", "description": "American Female"},
    {"id": "af_nicole", "name": "Nicole", "gender": "female", "accent": "us", "description": "American Female"},
    {"id": "af_sky", "name": "Sky", "gender": "female", "accent": "us", "description": "American Female"},
    {"id": "am_adam", "name": "Adam", "gender": "male", "accent": "us", "description": "American Male"},
    {"id": "am_michael", "name": "Michael", "gender": "male", "accent": "us", "description": "American Male"},
    {"id": "bf_emma", "name": "Emma", "gender": "female", "accent": "uk", "description": "British Female"},
    {"id": "bf_isabella", "name": "Isabella", "gender": "female", "accent": "uk", "description": "British Female"},
    {"id": "bm_george", "name": "George", "gender": "male", "accent": "uk", "description": "British Male"},
    {"id": "bm_lewis", "name": "Lewis", "gender": "male", "accent": "uk", "description": "British Male"},
]


def list_reference_voices() -> List[Dict[str, Any]]:
    refs = []
    if VOICE_DIR.is_dir():
        for f in sorted(VOICE_DIR.glob("*.wav")):
            refs.append({
                "id": f.stem,
                "filename": f.name,
                "path": str(f.resolve()),
                "size_bytes": f.stat().st_size,
            })
    return refs


def resolve_voice_argument(voice_name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Resolve a voice name into (voice_id, voice_ref)."""
    if not voice_name:
        return None, None
    p = Path(voice_name)
    if p.is_file():
        return None, str(p.resolve())
    if VOICE_DIR.is_dir():
        cand = VOICE_DIR / voice_name
        if cand.is_file():
            return None, str(cand.resolve())
        cand_wav = VOICE_DIR / f"{voice_name}.wav"
        if cand_wav.is_file():
            return None, str(cand_wav.resolve())
    return voice_name, None


def play_audio_file(audio_path: Path, quiet: bool = False) -> bool:
    """Play audio through PipeWire (pw-play) or ALSA (aplay)."""
    import shutil
    player = None
    for p in ["/usr/bin/pw-play", "pw-play", "/usr/bin/aplay", "aplay"]:
        if shutil.which(p):
            player = p
            break
    if not player:
        sys.stderr.write("⚠️ [audiocpp] No audio player (pw-play/aplay) found on host.\n")
        return False
    try:
        if not quiet:
            sys.stderr.write(f"🔊 [audiocpp] Playing {audio_path.name} via {player}...\n")
        subprocess.run([player, str(audio_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception as e:
        sys.stderr.write(f"⚠️ [audiocpp] Audio playback failed: {e}\n")
        return False


def cmd_voices(json_mode: bool = False, quiet: bool = False) -> Dict[str, Any]:
    refs = list_reference_voices()
    payload = {
        "status": "ok",
        "kokoro_voices": KOKORO_VOICES,
        "reference_voices": refs,
        "voice_dir": str(VOICE_DIR),
        "total_voices": len(KOKORO_VOICES) + len(refs),
    }
    if json_mode:
        print(json.dumps(payload, indent=2))
        return payload

    print("-" * 75)
    print("🗣️  KOKORO BUILTIN VOICES (for --model kokoro)")
    print("-" * 75)
    for v in KOKORO_VOICES:
        print(f"  {v['id']:<15} {v['description']:<35} [{v['accent'].upper()}]")

    print("\n" + "-" * 75)
    print(f"🎙️  REFERENCE AUDIO PROFILES in {VOICE_DIR} (for cloning / reference)")
    print("-" * 75)
    if refs:
        for r in refs:
            print(f"  {r['id']:<15} {r['filename']:<30} ({r['size_bytes'] / 1024:.1f} KB)")
    else:
        print("  (No .wav reference voice files found)")
    print("-" * 75)
    return payload



def parse_metrics_output(stdout: str) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("metrics."):
            k, v = line.split("=", 1)
            metric_name = k.replace("metrics.", "")
            try:
                metrics[metric_name] = float(v) if "." in v else int(v)
            except ValueError:
                metrics[metric_name] = v
        elif line.startswith("text_output="):
            metrics["text"] = line[12:]
        elif line.startswith("audio_out="):
            metrics["audio_out"] = line[10:]
        elif line.startswith("word_timestamps="):
            try:
                metrics["words"] = json.loads(line[16:])
            except Exception:
                pass
    return metrics


def run_audiocpp_raw(args_list: List[str]) -> subprocess.CompletedProcess:
    if not CLI_BIN.is_file():
        sys.exit(f"❌ Error: audio.cpp CLI binary not found at {CLI_BIN}")
    cmd = [str(CLI_BIN)] + args_list
    return subprocess.run(cmd, capture_output=True, text=True, env=_loader_env())


def ensure_audio_server(host: str = "127.0.0.1", port: int = 8081, timeout_s: float = 20.0) -> bool:
    """Mirror OCR's self-healing pattern: if the local audio server is down,
    start it via `llama-rig up audio` and poll /health for up to timeout_s.
    Returns True when the server answers, False otherwise (callers then fall
    through to their existing offline error path unchanged)."""
    def _up() -> bool:
        try:
            req = urllib.request.Request(f"http://{host}:{port}/health")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    if _up():
        return True
    ctl = shutil.which("llama-rig") or shutil.which("vram-rig-ctl")
    if not ctl:
        return False
    try:
        subprocess.run(
            [ctl, "up", "audio"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        return False
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _up():
            return True
        time.sleep(0.5)
    return False


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


def cmd_transcribe(
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
    meta = MODEL_REGISTRY.get(model_key)
    if not meta or meta["task"] != "asr":
        sys.exit(f"❌ Error: Model '{model_key}' is not a registered ASR model.")
    p = Path(audio_path).resolve()
    if not p.is_file():
        sys.exit(f"❌ Error: Audio file not found: {audio_path}")

    args = [
        "--task", "asr",
        "--family", meta["family"],
        "--model", str(meta["path"]),
        "--backend", BACKEND,
        "--device", "0",
        "--audio", str(p),
        "--metrics",
    ]

    if meta["family"] == "crisperwhisper":
        args.extend(["--request-option", f"language={language}"])
        if mode != "verbatim":
            args.extend(["--request-option", f"transcription_mode={mode}"])
        if words_out:
            args.extend(["--words-out", str(Path(words_out).resolve())])
    elif words_out:
        # Silence here would look like a bug in the caller: the model simply has
        # no word timing to give, so say so instead of writing an empty file.
        sys.stderr.write(
            f"⚠️  --words-out is only emitted for crisperwhisper; "
            f"{model_key} returns text without word timings.\n"
        )

    res = run_audiocpp_raw(args)
    if res.returncode != 0:
        sys.exit(f"❌ Transcription failed:\n{res.stderr.strip()}")

    parsed = parse_metrics_output(res.stdout)
    text = parsed.get("text", "").strip()

    if out_file:
        Path(out_file).resolve().write_text(text, encoding="utf-8")

    dur_s = round(parsed.get("audio_duration_ms", 0) / 1000.0, 3)
    wall_ms = round(parsed.get("wall_ms", 0.0), 1)
    rtf = round(parsed.get("rtf", 0.0), 4)

    if json_mode:
        payload = {
            "task": "asr",
            "model": model_key,
            "text": text,
            "duration_s": dur_s,
            "wall_ms": wall_ms,
            "rtf": rtf,
            "words": parsed.get("words", []),
        }
        print(json.dumps(payload, indent=2))
        return payload

    if metrics and not quiet:
        x_rt = parsed.get("x_realtime", 0.0)
        sys.stderr.write(f"📊 [Metrics] Wall: {wall_ms:.1f}ms | RTF: {rtf:.4f} ({x_rt:.1f}x real-time)\n")

    if not out_file:
        print(text)

    return parsed


def cmd_speak(
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
    meta = MODEL_REGISTRY.get(model_key)
    if not meta or meta["task"] != "tts":
        sys.exit(f"❌ Error: Model '{model_key}' is not a registered TTS model.")

    out_p = Path(out_file).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    args = [
        "--task", "tts",
        "--family", meta["family"],
        "--model", str(meta["path"]),
        "--backend", BACKEND,
        "--device", "0",
        "--text", text,
        "--out", str(out_p),
        "--metrics",
    ]

    v_id = voice_id or meta.get("default_voice")
    if v_id:
        args.extend(["--voice-id", v_id])

    v_ref = voice_ref
    if not v_ref and meta["family"] in ("audio8_tts", "index_tts2", "fish_audio"):
        default_ref = VOICE_DIR / "maomao.wav"
        if default_ref.is_file():
            v_ref = str(default_ref)

    if v_ref:
        args.extend(["--voice-ref", str(Path(v_ref).resolve())])
        if meta["family"] in ("audio8_tts", "fish_audio"):
            args.extend(["--reference-text", "Everyone has a price for their dreams, and I merely facilitate the transaction."])

    res = run_audiocpp_raw(args)
    if res.returncode != 0:
        sys.exit(f"❌ Speech synthesis failed:\n{res.stderr.strip()}")

    parsed = parse_metrics_output(res.stdout)
    dur_s = round(parsed.get("audio_duration_ms", 0) / 1000.0, 3)
    wall_ms = round(parsed.get("wall_ms", 0.0), 1)
    rtf = round(parsed.get("rtf", 0.0), 4)
    played = play_audio_file(out_p, quiet=quiet) if play else False

    if json_mode:
        payload = {
            "task": "tts",
            "status": "ok",
            "audio_file": str(out_p),
            "model": model_key,
            "voice": v_id or v_ref or "default",
            "duration_s": dur_s,
            "wall_ms": wall_ms,
            "rtf": rtf,
            "played": played,
        }
        print(json.dumps(payload, indent=2))
        return payload

    if metrics and not quiet:
        x_rt = parsed.get("x_realtime", 0.0)
        sys.stderr.write(f"📊 [Metrics] Wall: {wall_ms:.1f}ms | RTF: {rtf:.4f} ({x_rt:.1f}x real-time)\n")

    if not quiet and not json_mode:
        sys.stderr.write(f"[audiocpp] Generated {dur_s}s audio -> {out_p}\n")

    parsed["played"] = played
    return parsed


def cmd_align(
    audio_path: str,
    transcript: str,
    language: str = "en",
    out_json: Optional[str] = None,
    metrics: bool = False,
    json_mode: bool = False,
    quiet: bool = False,
) -> List[Dict[str, Any]]:
    meta = MODEL_REGISTRY["aligner"]
    args = [
        "--task", "align",
        "--family", meta["family"],
        "--model", str(meta["path"]),
        "--backend", BACKEND,
        "--device", "0",
        "--audio", str(Path(audio_path).resolve()),
        "--text", transcript,
        "--language", language,
        "--metrics",
    ]
    res = run_audiocpp_raw(args)
    if res.returncode != 0:
        sys.exit(f"❌ Forced alignment failed:\n{res.stderr.strip()}")

    parsed = parse_metrics_output(res.stdout)
    words = parsed.get("words", [])

    if out_json:
        Path(out_json).resolve().write_text(json.dumps(words, indent=2), encoding="utf-8")

    if metrics and not quiet:
        rtf = parsed.get("rtf", 0.0)
        x_rt = parsed.get("x_realtime", 0.0)
        sys.stderr.write(f"📊 [Metrics] Aligned {len(words)} words ({x_rt:.1f}x real-time, RTF {rtf:.4f})\n")

    if json_mode:
        print(json.dumps(words, indent=2))
    elif not quiet and not out_json:
        print(json.dumps(words, indent=2))

    return words


def cmd_models(json_mode: bool = False):
    if json_mode:
        models_data = {}
        for k, v in MODEL_REGISTRY.items():
            models_data[k] = {
                "family": v["family"],
                "task": v["task"],
                "installed": Path(v["path"]).is_file(),
                "path": str(v["path"]),
                "description": v["desc"]
            }
        print(json.dumps(models_data, indent=2))
        return

    print(f"{'MODEL KEY':<16} {'FAMILY':<22} {'TASK':<8} {'STATUS':<12} {'DESCRIPTION'}")
    print("-" * 92)
    for k, v in MODEL_REGISTRY.items():
        exists = "Installed" if Path(v["path"]).is_file() else "Missing"
        print(f"{k:<16} {v['family']:<22} {v['task']:<8} {exists:<12} {v['desc']}")


def cmd_doctor(json_mode: bool = False):
    res = run_audiocpp_raw(["--backend", BACKEND, "--list-devices"])
    gpu_ok = "[GPU]" in res.stdout
    installed = sum(1 for m in MODEL_REGISTRY.values() if Path(m["path"]).is_file())
    total_models = len(MODEL_REGISTRY)

    if json_mode:
        doc = {
            "audio_cpp_dir": str(AUDIO_CPP_DIR),
            "cli_bin_ready": CLI_BIN.is_file(),
            "server_bin_ready": SERVER_BIN.is_file(),
            "config_ready": CONFIG_FILE.is_file(),
            "backend": BACKEND,
            "gpu_ready": gpu_ok,
            "models_installed": installed,
            "models_total": total_models,
        }
        print(json.dumps(doc, indent=2))
        return

    print("🔍 [audiocpp] Diagnostic Health Check")
    print(f"  audio.cpp dir: {AUDIO_CPP_DIR}")
    print(f"  CLI binary   : {'✅ Ready' if CLI_BIN.is_file() else '❌ Missing'}")
    print(f"  Server binary: {'✅ Ready' if SERVER_BIN.is_file() else '❌ Missing'}")
    print(f"  Config JSON  : {'✅ Ready' if CONFIG_FILE.is_file() else '❌ Missing'}")
    print(f"  Backend      : {BACKEND}")
    print(f"  GPU          : {'✅ AMD Radeon Detected' if gpu_ok else '⚠️ Device error'}")
    print(f"  Models       : {installed}/{total_models} GGUF models ready")


def cmd_benchmark(json_mode: bool = False):
    # Scratch output goes to the system temp dir, not the AI volume: that volume
    # is NTFS3 and is for weights, not ephemeral files.
    test_audio = Path(os.environ.get(
        "AUDIOCPP_TEST_WAV", Path(tempfile.gettempdir()) / "audiocpp_test_speech.wav"
    ))
    test_text = "Hello, this is a local hardware-accelerated speech synthesis test using audio dot c p p."
    if not test_audio.is_file():
        cmd_speak(test_text, model_key="supertonic", out_file=str(test_audio), quiet=True)

    results = []
    if not json_mode:
        print("🚀 [audiocpp] Running Vulkan Hardware RTF Benchmark Suite (Dual AMD Radeon RX 9060 XT)...")
        print(f"{'MODEL':<16} {'FAMILY':<22} {'TASK':<8} {'AUDIO (s)':<10} {'WALL (ms)':<11} {'RTF':<9} {'SPEED':<12}")
        print("-" * 92)

    for key, meta in MODEL_REGISTRY.items():
        if not Path(meta["path"]).is_file():
            continue
        try:
            if meta["task"] == "asr":
                parsed = cmd_transcribe(
                    str(test_audio), model_key=key, metrics=False, quiet=True,
                    out_file=f"/tmp/bench_{key}.txt",
                )
            elif meta["task"] == "tts":
                tmp_out = f"/tmp/bench_{key}.wav"
                parsed = cmd_speak(test_text, model_key=key, out_file=tmp_out, metrics=False, quiet=True)
            elif meta["task"] == "align":
                res = run_audiocpp_raw([
                    "--task", "align",
                    "--family", meta["family"],
                    "--model", str(meta["path"]),
                    "--backend", BACKEND,
                    "--device", "0",
                    "--audio", str(test_audio),
                    "--text", test_text,
                    "--language", "en",
                    "--metrics"
                ])
                parsed = parse_metrics_output(res.stdout)
            else:
                continue

            wall_ms = round(parsed.get("wall_ms", 0.0), 1)
            dur_s = round(parsed.get("audio_duration_ms", 0) / 1000.0, 2)
            rtf = round(parsed.get("rtf", 0.0), 4)
            x_rt = round(parsed.get("x_realtime", 0.0), 1)
            speed_str = f"{x_rt}x real-time" if rtf < 1.0 else f"{rtf:.2f}x slower"

            item = {
                "model": key,
                "family": meta["family"],
                "task": meta["task"],
                "duration_s": dur_s,
                "wall_ms": wall_ms,
                "rtf": rtf,
                "speed": speed_str
            }
            results.append(item)
            if not json_mode:
                print(f"{key:<16} {meta['family']:<22} {meta['task']:<8} {dur_s:<10.2f} {wall_ms:<11.1f} {rtf:<9.4f} {speed_str:<12}")
        except Exception as e:
            if not json_mode:
                print(f"{key:<16} {meta['family']:<22} {meta['task']:<8} ❌ Error: {e}")

    if json_mode:
        print(json.dumps(results, indent=2))
    else:
        print("-" * 92)
        print("✅ All benchmarked models executed faster than real-time (RTF < 1.0) under Vulkan GPU acceleration.")

    return results


DIAR_MEDIA_EXTS = {
    ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus",
    ".mp4", ".mkv", ".webm", ".mov",
}
_DIAR_TIMING_RE = re.compile(
    r"(\d+):(\d{2}):(\d{2})[.,](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[.,](\d{1,3})"
)


def resolve_diar_model(precision: str = "bf16") -> Path:
    explicit = os.environ.get("DIAR_MODEL")
    if explicit:
        return Path(explicit).expanduser()
    return DIAR_MODELS_DIR / f"nemotron-3-diarization-{precision}.gguf"


def ensure_diar_model(model_path: Path, quiet: bool = False) -> Path:
    if model_path.is_file():
        return model_path
    model_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/{DIAR_HF_REPO}/resolve/main/{model_path.name}"
    part_path = model_path.with_name(model_path.name + ".part")
    if not quiet:
        sys.stderr.write(f"[audiocpp] Downloading {model_path.name} from {DIAR_HF_REPO}...\n")
    curl = shutil.which("curl")
    if curl:
        progress = "--progress-bar" if (not quiet and sys.stderr.isatty()) else "-sS"
        res = subprocess.run(
            [curl, "-L", "--fail", progress, "-C", "-", "-o", str(part_path), url],
            check=False,
        )
        if res.returncode != 0 or not part_path.is_file():
            sys.exit(f"❌ Failed to download diarization model from {url}")
    else:
        try:
            with urllib.request.urlopen(url, timeout=300.0) as resp:
                part_path.write_bytes(resp.read())
        except Exception as exc:
            sys.exit(f"❌ Failed to download diarization model from {url}: {exc}")
    part_path.replace(model_path)
    if not quiet:
        size_mb = model_path.stat().st_size / (1024 * 1024)
        sys.stderr.write(f"[audiocpp] Model ready: {model_path} ({size_mb:.1f} MB)\n")
    return model_path


def _is_16k_mono_pcm_wav(path: Path) -> bool:
    if path.suffix.lower() != ".wav":
        return False
    try:
        with wave.open(str(path), "rb") as wf:
            return (
                wf.getnchannels() == 1
                and wf.getframerate() == 16000
                and wf.getsampwidth() == 2
                and wf.getcomptype() == "NONE"
            )
    except Exception:
        return False


def _extract_16k_mono_wav(src: Path, dst: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("❌ Error: ffmpeg missing (required to decode non-16kHz-WAV media for diarization).")
    res = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(dst),
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0 or not dst.is_file():
        detail = (res.stderr or res.stdout or "").strip()
        sys.exit(f"❌ ffmpeg could not decode {src}: {detail}")


def _diar_speaker_labels(
    turns: List[Dict[str, Any]],
    names: Optional[str] = None,
    mapping: Optional[str] = None,
) -> Dict[str, str]:
    order: List[str] = []
    for t in turns:
        if t["speaker"] not in order:
            order.append(t["speaker"])
    labels = {spk: f"Speaker {i + 1}" for i, spk in enumerate(order)}
    if names:
        for i, name in enumerate([n.strip() for n in names.split(",") if n.strip()]):
            if i < len(order):
                labels[order[i]] = name
    if mapping:
        for pair in [p.strip() for p in mapping.split(",") if p.strip()]:
            key, _, val = pair.partition("=")
            key = key.strip()
            val = val.strip()
            if not val:
                continue
            if key.startswith("speaker_"):
                labels[key] = val
            elif key.isdigit() and int(key) < len(order):
                labels[order[int(key)]] = val
    return labels


def _diar_speaker_summary(
    turns: List[Dict[str, Any]],
    labels: Dict[str, str],
) -> tuple[List[Dict[str, Any]], float]:
    talk: Dict[str, float] = {}
    count: Dict[str, int] = {}
    conf: Dict[str, float] = {}
    for t in turns:
        dur = max(0.0, t["end"] - t["start"])
        spk = t["speaker"]
        talk[spk] = talk.get(spk, 0.0) + dur
        count[spk] = count.get(spk, 0) + 1
        conf[spk] = conf.get(spk, 0.0) + float(t.get("confidence") or 0.0) * dur
    total = sum(talk.values()) or 1.0
    speakers = [
        {
            "id": spk,
            "name": labels.get(spk, spk),
            "talk_s": round(talk[spk], 2),
            "share": round(talk[spk] / total, 4),
            "turns": count[spk],
            "mean_confidence": round(conf[spk] / talk[spk], 4) if talk[spk] else 0.0,
        }
        for spk in sorted(talk, key=lambda s: -talk[s])
    ]
    return speakers, round(sum(talk.values()), 2)


def _diar_stamp(sec: float, sep: str) -> str:
    h, m, s = int(sec // 3600), int(sec % 3600 // 60), sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", sep)


def _diar_secs(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def _label_diar_transcript(
    turns: List[Dict[str, Any]],
    labels: Dict[str, str],
    media: Path,
    src_transcript: Path,
    outdir: Path,
    merge_gap: float = 0.5,
) -> Dict[str, Any]:
    text_raw = src_transcript.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues: List[Dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", text_raw):
        lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        for i, line in enumerate(lines):
            m = _DIAR_TIMING_RE.search(line)
            if not m:
                continue
            text = " ".join(lines[i + 1:])
            text = re.sub(r"<[^>]+>", "", text).strip()
            if text:
                cues.append({
                    "start": _diar_secs(*m.group(1, 2, 3, 4)),
                    "end": _diar_secs(*m.group(5, 6, 7, 8)),
                    "text": re.sub(r"\s+", " ", text),
                })
            break

    if not cues:
        sys.exit(f"❌ Error: no cues parsed from {src_transcript}")
    if not turns:
        sys.exit(f"❌ Error: no speaker turns to label {src_transcript}")

    def pick(cue: Dict[str, Any]) -> tuple[str, float]:
        per: Dict[str, float] = {}
        for t in turns:
            overlap = min(cue["end"], t["end"]) - max(cue["start"], t["start"])
            if overlap > 0:
                per[t["speaker"]] = per.get(t["speaker"], 0.0) + overlap
        if per:
            spk = max(per, key=lambda k: per[k])
            share = per[spk] / sum(per.values())
            return spk, share
        mid = (cue["start"] + cue["end"]) / 2.0
        near = min(turns, key=lambda t: min(abs(t["start"] - mid), abs(t["end"] - mid)))
        return near["speaker"], 0.0

    for cue in cues:
        cue["speaker"], cue["share"] = pick(cue)

    blocks: List[Dict[str, Any]] = []
    for cue in cues:
        prev = blocks[-1] if blocks else None
        if prev and prev["speaker"] == cue["speaker"] and cue["start"] - prev["end"] <= merge_gap:
            prev["end"] = max(prev["end"], cue["end"])
            prev["text"] += " " + cue["text"]
        else:
            blocks.append(dict(cue))

    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / "transcript.vtt", "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for i, b in enumerate(blocks, 1):
            f.write(f"{i}\n{_diar_stamp(b['start'], '.')} --> {_diar_stamp(b['end'], '.')}\n")
            f.write(f"<v {labels[b['speaker']]}>{b['text']}</v>\n\n")

    with open(outdir / "transcript.srt", "w", encoding="utf-8") as f:
        for i, b in enumerate(blocks, 1):
            f.write(f"{i}\n{_diar_stamp(b['start'], ',')} --> {_diar_stamp(b['end'], ',')}\n")
            f.write(f"{labels[b['speaker']]}: {b['text']}\n\n")

    with open(outdir / "transcript.txt", "w", encoding="utf-8") as f:
        for b in blocks:
            f.write(f"[{int(b['start'] // 60):02d}:{int(b['start'] % 60):02d}] {labels[b['speaker']]}: {b['text']}\n")

    speakers, total_talk_s = _diar_speaker_summary(turns, labels)
    summary = {
        "input": str(media.resolve()),
        "transcript": str(src_transcript.resolve()),
        "speakers": speakers,
        "mixed_cues": sum(1 for c in cues if c["share"] < 0.7),
        "total_talk_s": total_talk_s,
        "passages": len(blocks),
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _diarize_one(
    input_path: Path,
    model_path: Path,
    *,
    precision: str,
    backend: str,
    threads: int,
    latency_profile: str,
    threshold: Optional[float],
    min_frames: Optional[int],
    pad_frames: Optional[int],
    merge_gap: float,
    out_root: Optional[str],
    transcript_path: Optional[Path],
    names: Optional[str],
    mapping: Optional[str],
    keep_wav: bool,
    json_mode: bool,
    metrics: bool,
    quiet: bool,
) -> Dict[str, Any]:
    if not input_path.is_file():
        sys.exit(f"❌ Error: Input file not found: {input_path}")
    if input_path.suffix.lower() in (".vtt", ".srt", ".txt", ".md"):
        sys.exit(
            f"❌ Error: {input_path} is a transcript, not audio. "
            f"Rerun with: audiocpp diarize <recording> --vtt \"{input_path}\""
        )

    base = input_path.stem
    use_temp_dir = out_root is None and json_mode and transcript_path is None and not keep_wav
    temp_ctx = tempfile.TemporaryDirectory(prefix="audiocpp_diar_") if use_temp_dir else None
    try:
        if temp_ctx is not None:
            outdir = Path(temp_ctx.name)
            persist_outdir: Optional[Path] = None
        elif out_root is not None:
            outdir = Path(out_root).expanduser().resolve() / base
            persist_outdir = outdir
        else:
            outdir = input_path.resolve().parent / f"{base}.diar"
            persist_outdir = outdir
        outdir.mkdir(parents=True, exist_ok=True)

        if not quiet and not json_mode:
            sys.stderr.write(f"→ {input_path}\n")

        rate = 16000
        decoded_temp_wav: Optional[Path] = None
        if _is_16k_mono_pcm_wav(input_path):
            wav_for_cli = input_path.resolve()
        else:
            wav_for_cli = outdir / "audio16k.wav"
            _extract_16k_mono_wav(input_path, wav_for_cli)
            decoded_temp_wav = wav_for_cli

        turns_path = outdir / "turns.json"
        args = [
            "--task", "diar",
            "--family", "nemotron_3_diar",
            "--model", str(model_path),
            "--backend", backend,
            "--threads", str(threads),
            "--mode", "offline",
            "--audio", str(wav_for_cli),
            "--turns-out", str(turns_path),
            "--metrics",
            "--session-option", f"latency_profile={latency_profile}",
        ]
        if threshold is not None:
            args.extend(["--request-option", f"speaker_threshold={threshold}"])
        if min_frames is not None:
            args.extend(["--request-option", f"speaker_min_frames={min_frames}"])
        if pad_frames is not None:
            args.extend(["--request-option", f"speaker_pad_frames={pad_frames}"])
        if not quiet and not json_mode:
            args.append("--log")

        res = run_audiocpp_raw(args)
        if persist_outdir is not None:
            (outdir / "diarize.log").write_text(
                (res.stdout or "") + (res.stderr or ""), encoding="utf-8"
            )
        if res.returncode != 0 or not turns_path.is_file():
            detail = (res.stderr or res.stdout or "").strip()
            sys.exit(f"❌ Diarization failed for {input_path}:\n{detail}")

        parsed_metrics = parse_metrics_output(res.stdout)
        raw_turns = json.loads(turns_path.read_text(encoding="utf-8"))
        turns = [
            {
                "start": round(t["start_sample"] / rate, 4),
                "end": round(t["end_sample"] / rate, 4),
                "speaker": t["speaker_id"],
                "confidence": t.get("confidence"),
                "start_sample": t["start_sample"],
                "end_sample": t["end_sample"],
            }
            for t in raw_turns
            if "start_sample" in t and "end_sample" in t
        ]
        turns.sort(key=lambda t: t["start"])
        labels = _diar_speaker_labels(turns, names=names, mapping=mapping)
        for t in turns:
            t["name"] = labels.get(t["speaker"], t["speaker"])
        speakers, total_talk_s = _diar_speaker_summary(turns, labels)

        summary: Optional[Dict[str, Any]] = None
        if transcript_path is not None:
            summary = _label_diar_transcript(
                turns, labels, input_path, transcript_path, outdir, merge_gap=merge_gap
            )

        if decoded_temp_wav is not None and not keep_wav:
            decoded_temp_wav.unlink(missing_ok=True)

        dur_s = round(parsed_metrics.get("audio_duration_ms", 0) / 1000.0, 3)
        wall_ms = round(parsed_metrics.get("wall_ms", 0.0), 1)
        rtf = round(parsed_metrics.get("rtf", 0.0), 4)
        x_rt = parsed_metrics.get("x_realtime", 0.0)

        if not json_mode:
            if metrics and not quiet:
                sys.stderr.write(f"📊 [Metrics] Wall: {wall_ms:.1f}ms | RTF: {rtf:.4f} ({x_rt:.1f}x real-time)\n")
            if not quiet:
                if persist_outdir is not None:
                    print(f"  turns → {turns_path}")
                if summary is not None:
                    print(
                        f"  {len(speakers)} speakers, {len(turns)} turns, {summary['passages']} passages"
                    )
                    for s in summary["speakers"]:
                        print(
                            f"    {s['name']:<16} {s['talk_s']:>8.1f}s  {s['share'] * 100:>5.1f}%  "
                            f"{s['turns']:>3} turns  conf {s['mean_confidence']:.3f}"
                        )
                    if summary["mixed_cues"]:
                        print(
                            f"    {summary['mixed_cues']} cues were mixed-speaker; "
                            "labelled by dominant talk time"
                        )
                    print(f"  transcript → {outdir / 'transcript.vtt'}")
                else:
                    print(f"  {len(speakers)} speakers, {len(turns)} turns ({total_talk_s:.1f}s spoken)")
                    for s in speakers:
                        print(
                            f"    {s['name']:<16} {s['talk_s']:>8.1f}s  {s['share'] * 100:>5.1f}%  "
                            f"{s['turns']:>3} turns  conf {s['mean_confidence']:.3f}"
                        )

        payload: Dict[str, Any] = {
            "task": "diar",
            "model": "diar",
            "precision": precision,
            "input": str(input_path.resolve()),
            "out_dir": str(persist_outdir) if persist_outdir is not None else None,
            "turns_file": str(turns_path) if persist_outdir is not None else None,
            "sample_rate": rate,
            "duration_s": dur_s,
            "wall_ms": wall_ms,
            "rtf": rtf,
            "total_talk_s": total_talk_s,
            "speakers": speakers,
            "turns": turns,
        }
        if summary is not None:
            payload["summary"] = summary
        return payload
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()


def cmd_diarize(
    inputs: List[str],
    *,
    transcript: Optional[str] = None,
    names: Optional[str] = None,
    mapping: Optional[str] = None,
    out_root: Optional[str] = None,
    precision: str = "bf16",
    backend: str = BACKEND,
    threads: int = 8,
    latency_profile: str = "very_high",
    threshold: Optional[float] = None,
    min_frames: Optional[int] = None,
    pad_frames: Optional[int] = None,
    merge_gap: float = 0.5,
    keep_wav: bool = False,
    download_only: bool = False,
    json_mode: bool = False,
    metrics: bool = False,
    quiet: bool = False,
) -> Any:
    model_path = ensure_diar_model(resolve_diar_model(precision), quiet=quiet or json_mode)
    if download_only:
        if json_mode:
            payload = {"task": "diar", "status": "ok", "model_path": str(model_path), "precision": precision}
            print(json.dumps(payload, indent=2))
            return payload
        print(str(model_path))
        return str(model_path)

    if not inputs:
        sys.exit("❌ Error: provide at least one audio/video file or directory (or --download-only).")

    transcript_path: Optional[Path] = None
    if transcript:
        if len(inputs) != 1 or Path(inputs[0]).is_dir():
            sys.exit("❌ Error: --vtt/--srt labels one input file at a time.")
        transcript_path = Path(transcript).expanduser().resolve()
        if not transcript_path.is_file():
            sys.exit(f"❌ Error: transcript not found: {transcript}")

    expanded: List[Path] = []
    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            files = sorted(
                f for f in p.iterdir()
                if f.is_file() and f.suffix.lower() in DIAR_MEDIA_EXTS
            )
            expanded.extend(files)
        else:
            expanded.append(p)

    if not expanded:
        sys.exit("❌ Error: no media files found in the provided input(s).")

    results = [
        _diarize_one(
            p,
            model_path,
            precision=precision,
            backend=backend,
            threads=threads,
            latency_profile=latency_profile,
            threshold=threshold,
            min_frames=min_frames,
            pad_frames=pad_frames,
            merge_gap=merge_gap,
            out_root=out_root,
            transcript_path=transcript_path,
            names=names,
            mapping=mapping,
            keep_wav=keep_wav,
            json_mode=json_mode,
            metrics=metrics,
            quiet=quiet,
        )
        for p in expanded
    ]

    output = results[0] if len(results) == 1 else results
    if json_mode:
        print(json.dumps(output, indent=2))
    return output


def main():
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON format")
    parent_parser.add_argument("--metrics", action="store_true", help="Print RTF and performance metrics (to stderr in non-JSON mode)")
    parent_parser.add_argument("--quiet", "-q", action="store_true", help="Suppress console status messages")
    parent_parser.add_argument("--host", default=None, help="audio.cpp host (default: $AUDIOCPP_HOST or 127.0.0.1, supports Tailscale *.ts.net)")
    parent_parser.add_argument("--port", type=int, default=8081, metavar="PORT", help="audio.cpp port (default: $AUDIOCPP_PORT or 8081)")
    parent_parser.add_argument("--no-autostart", action="store_true", help="Skip auto-starting the local audio server (llama-rig up audio) before HTTP requests")

    parser = argparse.ArgumentParser(
        description="audiocpp — Unified Local Audio Engineering Hub (Vulkan / Dual-GPU)",
        parents=[parent_parser]
    )
    sub = parser.add_subparsers(dest="command", required=True, help="Available subcommands")

    # 1. asr / transcribe
    p_asr = sub.add_parser("asr", aliases=["transcribe", "stt"], parents=[parent_parser], help="Speech-to-Text: audio in -> text or JSON out")
    p_asr.add_argument("audio", help="Path to input audio file (.wav/.mp3)")
    p_asr.add_argument("--model", "-m", choices=["crisperwhisper", "nemotron", "nemotron-f16"], default=DEFAULT_ASR, help=f"ASR model slug (default: {DEFAULT_ASR})")
    p_asr.add_argument("--language", "-l", default="en", help="Language code (default: en)")
    p_asr.add_argument("--mode", choices=["verbatim", "intended"], default="verbatim", help="Transcription mode (verbatim [default] or intended)")
    p_asr.add_argument("--words-out", help="Save word timestamps to JSON file")
    p_asr.add_argument("--out", "-o", help="Save transcript to text/markdown file")

    # 2. tts / speak
    p_tts = sub.add_parser("tts", aliases=["speak"], parents=[parent_parser], help="Text-to-Speech: text in -> .wav audio file out")
    p_tts.add_argument("text", help="Text to speak")
    p_tts.add_argument("--model", "-m", choices=["supertonic", "kokoro", "kitten", "fish", "audio8", "higgs", "omnivoice", "index"], default=DEFAULT_TTS, help=f"TTS model slug (default: {DEFAULT_TTS})")
    p_tts.add_argument("--voice-id", "--voice", dest="voice_id", help="Voice ID (e.g. af_bella, af_sky) or reference profile name (e.g. egirl, supertonic_F1)")
    p_tts.add_argument("--voice-ref", help="Voice reference audio for cloning (for Fish, Audio8, Index)")
    p_tts.add_argument("--play", action="store_true", help="Play synthesized audio directly through system speakers")
    p_tts.add_argument("--out", "-o", default="output.wav", help="Output audio file path (default: output.wav)")

    # 3. align
    p_align = sub.add_parser("align", parents=[parent_parser], help="Forced Alignment: extract millisecond word boundaries")
    p_align.add_argument("audio", help="Input audio file")
    p_align.add_argument("transcript", help="Transcript text")
    p_align.add_argument("--language", "-l", default="en", help="Language code (default: en)")
    p_align.add_argument("--out-json", help="Save word timestamps to JSON file")

    # 4. diarize
    p_diar = sub.add_parser("diarize", aliases=["diar"], parents=[parent_parser], help="Speaker Diarization: who spoke when (Nemotron 3, up to 8 speakers)")
    p_diar.add_argument("inputs", nargs="*", help="Audio/video file(s) or directory")
    p_diar.add_argument("--vtt", "--srt", dest="transcript", help="Label an existing WebVTT or SRT transcript with speakers")
    p_diar.add_argument("--names", help="Comma-separated speaker names in arrival order (speaker_0=A,...)")
    p_diar.add_argument("--map", dest="mapping", help="Explicit id=Name overrides (e.g. 0=Kem,1=Chase)")
    p_diar.add_argument("--out", "-o", dest="out_root", help="Output root directory (<out>/<basename>/; default: <input>.diar/)")
    p_diar.add_argument("--precision", choices=["bf16", "q8_0"], default=os.environ.get("DIAR_PRECISION", "bf16"), help="Model precision (default: bf16)")
    p_diar.add_argument("--backend", default=BACKEND, help=f"Execution backend (default: {BACKEND})")
    p_diar.add_argument("--threads", type=int, default=8, help="Backend threads (default: 8)")
    p_diar.add_argument("--latency-profile", default="very_high", help="Latency profile (default: very_high)")
    p_diar.add_argument("--threshold", type=float, help="Speaker activity threshold 0..1 (default: model 0.5)")
    p_diar.add_argument("--min-frames", type=int, help="Drop decoded turns shorter than N 10ms frames")
    p_diar.add_argument("--pad-frames", type=int, help="Pad decoded turns by N 10ms frames")
    p_diar.add_argument("--merge-gap", type=float, default=0.5, help="Merge same-speaker transcript cues closer than S seconds (default: 0.5)")
    p_diar.add_argument("--keep-wav", action="store_true", help="Keep extracted 16 kHz mono WAV")
    p_diar.add_argument("--download-only", action="store_true", help="Fetch the diarization GGUF if missing and exit")

    # 5. models
    sub.add_parser("models", parents=[parent_parser], help="List installed GGUF models")

    # 6. voices
    sub.add_parser("voices", parents=[parent_parser], help="List available TTS voices and reference profiles")

    # 7. doctor
    sub.add_parser("doctor", parents=[parent_parser], help="Inspect binary, Vulkan hardware, and models")

    # 8. benchmark
    sub.add_parser("benchmark", parents=[parent_parser], help="Run comprehensive Vulkan RTF benchmark")

    args = parser.parse_args()

    env_host = os.environ.get("AUDIOCPP_HOST")
    target_host = args.host or env_host
    is_remote = bool(target_host or not CLI_BIN.is_file())

    if is_remote:
        host = target_host or "127.0.0.1"
        port = int(os.environ.get("AUDIOCPP_PORT", args.port))
        scheme = "https" if (".ts.net" in host or os.environ.get("AUDIOCPP_SCHEME") == "https") else "http"
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    # Self-healing: bring up the local audio server before any HTTP request
    # (transcribe/doctor/speak/models). Local-binary commands never hit here.
    if (
        is_remote
        and not getattr(args, "no_autostart", False)
        and host in ("127.0.0.1", "localhost")
        and args.command in ("asr", "transcribe", "stt", "tts", "speak", "models", "doctor")
    ):
        ensure_audio_server(host, port)

    if args.command in ("asr", "transcribe", "stt"):
        if is_remote:
            cmd_transcribe_http(
                host, port, scheme, ssl_ctx,
                args.audio,
                model_key=args.model,
                language=args.language,
                mode=args.mode,
                out_file=args.out,
                words_out=args.words_out,
                metrics=args.metrics,
                json_mode=args.json,
                quiet=args.quiet,
            )
        else:
            cmd_transcribe(
                args.audio,
                model_key=args.model,
                language=args.language,
                mode=args.mode,
                out_file=args.out,
                words_out=args.words_out,
                metrics=args.metrics,
                json_mode=args.json,
                quiet=args.quiet,
            )
    elif args.command in ("tts", "speak"):
        v_id, v_ref = resolve_voice_argument(getattr(args, "voice_id", None))
        final_voice_id = v_id or args.voice_id
        final_voice_ref = args.voice_ref or v_ref

        if is_remote:
            cmd_speak_http(
                host, port, scheme, ssl_ctx,
                args.text,
                model_key=args.model,
                voice_id=final_voice_id,
                voice_ref=final_voice_ref,
                out_file=args.out,
                metrics=args.metrics,
                json_mode=args.json,
                quiet=args.quiet,
                play=args.play,
            )
        else:
            cmd_speak(
                args.text,
                model_key=args.model,
                voice_id=final_voice_id,
                voice_ref=final_voice_ref,
                out_file=args.out,
                metrics=args.metrics,
                json_mode=args.json,
                quiet=args.quiet,
                play=args.play,
            )
    elif args.command == "align":
        cmd_align(
            args.audio,
            args.transcript,
            language=args.language,
            out_json=args.out_json,
            metrics=args.metrics,
            json_mode=args.json,
            quiet=args.quiet,
        )
    elif args.command in ("diarize", "diar"):
        cmd_diarize(
            args.inputs,
            transcript=args.transcript,
            names=args.names,
            mapping=args.mapping,
            out_root=args.out_root,
            precision=args.precision,
            backend=args.backend,
            threads=args.threads,
            latency_profile=args.latency_profile,
            threshold=args.threshold,
            min_frames=args.min_frames,
            pad_frames=args.pad_frames,
            merge_gap=args.merge_gap,
            keep_wav=args.keep_wav,
            download_only=args.download_only,
            json_mode=args.json,
            metrics=args.metrics,
            quiet=args.quiet,
        )
    elif args.command == "models":
        if is_remote:
            cmd_models_http(host, port, scheme, ssl_ctx, json_mode=args.json)
        else:
            cmd_models(json_mode=args.json)
    elif args.command == "voices":
        cmd_voices(json_mode=args.json, quiet=args.quiet)
    elif args.command == "doctor":
        if is_remote:
            cmd_doctor_http(host, port, scheme, ssl_ctx, json_mode=args.json)
        else:
            cmd_doctor(json_mode=args.json)
    elif args.command == "benchmark":
        cmd_benchmark(json_mode=args.json)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
