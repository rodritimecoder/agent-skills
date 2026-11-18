#!/usr/bin/env python3
"""audio.cpp diarization: Nemotron 3 speaker turns, labelled and stamped.

Split out of `audiocpp_cli.py`. Everything here is local: fetch the GGUF, turn
the media into 16 kHz mono PCM, run the engine, then re-label the transcript.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

from audiocpp_core import (
    BACKEND,
    DIAR_HF_REPO,
    DIAR_MODELS_DIR,
    parse_metrics_output,
    run_audiocpp_raw,
)


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
