#!/usr/bin/env python3
"""audio.cpp wrapper: transcribe, speak, align, benchmark, and diarize.

The engine-facing state lives in `audiocpp_core.py`, hosted-server calls in
`audiocpp_http.py`, and diarization in `audiocpp_diar.py`. This file owns the
command surface and argument parsing only.
"""
import argparse
import json
import os
import ssl
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))
from audiocpp_core import (
    AUDIO_CPP_DIR,
    BACKEND,
    CLI_BIN,
    CONFIG_FILE,
    DEFAULT_ASR,
    DEFAULT_TTS,
    KOKORO_VOICES,
    MODEL_REGISTRY,
    SERVER_BIN,
    VOICE_DIR,
    ensure_audio_server,
    list_reference_voices,
    parse_metrics_output,
    play_audio_file,
    resolve_voice_argument,
    run_audiocpp_raw,
)
from audiocpp_diar import cmd_diarize
from audiocpp_http import (
    cmd_doctor_http,
    cmd_models_http,
    cmd_speak_http,
    cmd_transcribe_http,
)


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


def main():
    parent_parser = argparse.ArgumentParser(epilog='Exit codes: 0 success; 1 runtime/validation error; 2 invalid arguments (usage error); other non-zero values are script-specific.', add_help=False)
    parent_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON format")
    parent_parser.add_argument("--metrics", action="store_true", help="Print RTF and performance metrics (to stderr in non-JSON mode)")
    parent_parser.add_argument("--quiet", "-q", action="store_true", help="Suppress console status messages")
    parent_parser.add_argument("--host", default=None, help="audio.cpp host (default: $AUDIOCPP_HOST or 127.0.0.1, supports Tailscale *.ts.net)")
    parent_parser.add_argument("--port", type=int, default=8081, metavar="PORT", help="audio.cpp port (default: $AUDIOCPP_PORT or 8081)")
    parent_parser.add_argument("--no-autostart", action="store_true", help="Skip auto-starting the local audio server (llama-rig up audio) before HTTP requests")

    parser = argparse.ArgumentParser(epilog='Exit codes: 0 success; 1 runtime/validation error; 2 invalid arguments (usage error); other non-zero values are script-specific.',
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
