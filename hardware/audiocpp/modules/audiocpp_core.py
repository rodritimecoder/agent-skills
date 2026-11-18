#!/usr/bin/env python3
"""Shared state for the audio.cpp wrapper: volume paths, model table, engine calls.

`audiocpp_cli.py` (commands), `audiocpp_http.py` (hosted engines) and
`audiocpp_diar.py` (diarization) all read this module, so a path, a model slug
or a default changes in exactly one place.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
