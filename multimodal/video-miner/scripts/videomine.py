#!/usr/bin/env python3
"""
videomine - ICM Pipeline Orchestrator for Video Mining (Audio ASR + Visual OCR).

Interpretable Context Methodology (ICM) compliant:
- Every stage folder has a CONTEXT.md contract.
- Every stage output folder is an edit surface and human checkpoint.
- State is derived directly from the filesystem (PENDING, COMPLETE, STALE).

Stages:
  01_acquire       - Ingests video (URL or local), extracts audio & metadata
  02_audio_asr     - Speech-to-text with timestamps via audiocpp (CrisperWhisper 2.0 by default)
  03_visual_sample - Keyframe / scene-cut / fps sampling with PTS-exact timestamps
  04_visual_gate   - Deterministic gate: perceptual dedup + blank rejection, or h2o vision gate
  05_visual_ocr    - Visual OCR via LightOnOCR-3-0.8B or MiniCPM-OCR-1.0 (+ structural gate)
  06_synthesize    - Merges transcript & OCR into chronological mined_video.md
"""

from __future__ import annotations

import argparse
import base64
import datetime
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

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_DIR / "_templates" / "workspace"


def _drive_root() -> Path:
    """The AI volume root: $AI_ROOT, else the nearest ancestor holding models/.

    Weights, the llama.cpp binaries and sibling skills all live under it, so
    resolving from here keeps the skill working wherever the volume is mounted.
    """
    env = os.environ.get("AI_ROOT")
    if env:
        return Path(env).expanduser()
    for parent in Path(__file__).resolve().parents:
        if (parent / "models").is_dir():
            return parent
    return Path("/run/media/rodri/AI")


DRIVE = _drive_root()

STAGES = [
    "01_acquire",
    "02_audio_asr",
    "03_visual_sample",
    "04_visual_gate",
    "05_visual_ocr",
    "06_synthesize",
]

# The stream that carries machine-readable output. main() rebinds this to the
# real stdout before redirecting sys.stdout to stderr for --json runs, so a
# log line can never corrupt the JSON document.
_STDOUT = sys.stdout


def emit_json(payload: object) -> None:
    """Print JSON to the real stdout, bypassing any log redirection."""
    print(json.dumps(payload, indent=2, ensure_ascii=False), file=_STDOUT or sys.stdout)


# Service Endpoints
DECISION_URL = os.environ.get("JEV_URL", "http://127.0.0.1:8083/v1/systemone")


def _decision_model_is_h2o() -> bool:
    models_url = DECISION_URL.rsplit("/v1/systemone", 1)[0] + "/v1/models"
    try:
        req = urllib.request.Request(models_url)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("data") or []
        return bool(models and "h2o-lightning-4b" in str(models[0].get("id", "")).lower())
    except Exception:
        return False

LIGHTON_MODEL = Path(os.environ.get("LIGHTON_MODEL", DRIVE / "models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.Q4_K_M.gguf"))
LIGHTON_MMPROJ = Path(os.environ.get("LIGHTON_MMPROJ", DRIVE / "models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.mmproj-q8_0.gguf"))
LLAMA_SERVER_BIN = Path(os.environ.get("LLAMA_SERVER_BIN", DRIVE / "llama.cpp/build/bin/llama-server"))
LLAMA_MTMD_CLI = Path(os.environ.get("LLAMA_MTMD_CLI", DRIVE / "llama.cpp/build/bin/llama-mtmd-cli"))
LIGHTON_PORT = int(os.environ.get("LIGHTON_PORT", "8085"))
LIGHTON_URL = os.environ.get("LIGHTON_URL", f"http://127.0.0.1:{LIGHTON_PORT}/v1/chat/completions")

MINICPM_MODEL = Path(os.environ.get("MINICPM_OCR_MODEL", DRIVE / "models/openbmb/MiniCPM-OCR-1.0-gguf/MiniCPM-OCR-1_0-Q8_0.gguf"))
MINICPM_MMPROJ = Path(os.environ.get("MINICPM_OCR_MMPROJ", DRIVE / "models/openbmb/MiniCPM-OCR-1.0-gguf/mmproj-model-f16-4x.gguf"))
MINICPM_SERVER_BIN = Path(os.environ.get("MINICPM_SERVER_BIN", DRIVE / "llama.cpp/build-vulkan/bin/llama-server"))
MINICPM_PORT = int(os.environ.get("MINICPM_PORT", "18499"))
MINICPM_URL = os.environ.get("MINICPM_URL", f"http://127.0.0.1:{MINICPM_PORT}/v1/chat/completions")
KEM_SCRIPTS = Path(os.environ.get("KEM_OCR_SCRIPTS", Path(__file__).resolve().parents[2] / "kem-ocr" / "scripts"))

GATE_MODE = os.environ.get("VIDEOMINE_GATE", "hash")
OCR_BACKEND = os.environ.get("VIDEOMINE_OCR", "lighton")
HASH_DISTANCE = int(os.environ.get("VIDEOMINE_HASH_DISTANCE", "20"))
TEXT_SIMILARITY = float(os.environ.get("VIDEOMINE_TEXT_SIMILARITY", "0.9"))
ASR_MODEL = os.environ.get("VIDEOMINE_ASR_MODEL", "")
SAMPLE_MODE = os.environ.get("VIDEOMINE_SAMPLE", "auto")
SAMPLE_FPS = float(os.environ.get("VIDEOMINE_SAMPLE_FPS", "1.0"))
KEYFRAME_THRESHOLD_S = float(os.environ.get("VIDEOMINE_KEYFRAME_AFTER", "600"))
GRID = 4
BLOCK_W = 17
BLOCK_H = 16



def get_asr_cmd(audio_wav: Path, details: bool = True, offline: bool = False, words_out: Path | None = None,
                model: str = "") -> list[str]:
    audiocpp_cli = shutil.which("audiocpp") or str(DRIVE / "skills/audiocpp/scripts/audiocpp_cli.py")
    if shutil.which("audiocpp") or Path(audiocpp_cli).is_file():
        cmd = ["audiocpp" if shutil.which("audiocpp") else sys.executable]
        if not shutil.which("audiocpp"):
            cmd.append(audiocpp_cli)
        cmd.extend(["transcribe", str(audio_wav), "--metrics"])
        if model:
            cmd.extend(["--model", model])
        if words_out:
            cmd.extend(["--words-out", str(words_out)])
        return cmd

    candidates = [
        DRIVE / "skills/audiocpp/scripts/audiocpp_cli.py",
        DRIVE / "skills/hardware/audiocpp/scripts/audiocpp_cli.py",
        Path.home() / ".gemini" / "config" / "skills" / "audiocpp" / "scripts" / "audiocpp_cli.py",
        Path.home() / ".config" / "opencode" / "skills" / "audiocpp" / "scripts" / "audiocpp_cli.py",
        Path.home() / ".pi" / "agent" / "skills" / "audiocpp" / "scripts" / "audiocpp_cli.py",
    ]
    for c in candidates:
        if c.is_file():
            cmd = [sys.executable, str(c), "asr", "transcribe", str(audio_wav)]
            if words_out:
                cmd.extend(["--words-out", str(words_out)])
            return cmd
    raise FileNotFoundError("Could not locate the audiocpp skill (audiocpp_cli.py) on the system.")



def format_timestamp(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def get_latest_mtime(folder: Path) -> float:
    """Get the latest modification time of files in a directory."""
    if not folder.exists():
        return 0.0
    latest = 0.0
    for p in folder.rglob("*"):
        if p.is_file() and p.name != ".gitkeep":
            mtime = p.stat().st_mtime
            if mtime > latest:
                latest = mtime
    return latest


def stage_status(workspace: Path, stage_idx: int) -> str:
    """Compute ICM status: PENDING, COMPLETE, or STALE."""
    stage_name = STAGES[stage_idx]
    out_dir = workspace / "stages" / stage_name / "output"
    files = [f for f in out_dir.glob("*") if f.is_file() and f.name != ".gitkeep"]
    dirs = [d for d in out_dir.glob("*") if d.is_dir()]
    
    if not files and not dirs:
        return "PENDING"
    
    current_mtime = get_latest_mtime(out_dir)
    if current_mtime == 0.0:
        return "PENDING"
        
    if stage_idx > 0:
        prev_stage = STAGES[stage_idx - 1]
        prev_out = workspace / "stages" / prev_stage / "output"
        prev_mtime = get_latest_mtime(prev_out)
        if prev_mtime > current_mtime:
            return "STALE"
            
    return "COMPLETE"


def render_table(rows: list[dict], columns: list[str] | None = None, headers: list[str] | None = None) -> str:
    if not rows:
        return "*(no records)*\n"
    if columns is None:
        columns = list(rows[0].keys())
    if headers is None:
        headers = [col.replace("_", " ").title() for col in columns]

    col_widths = [len(h) for h in headers]
    for r in rows:
        for idx, col in enumerate(columns):
            val_str = str(r.get(col, "")).replace("\n", " ").strip()
            if len(val_str) > col_widths[idx]:
                col_widths[idx] = len(val_str)

    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * col_widths[i] for i in range(len(headers))) + " |"
    row_lines = []
    for r in rows:
        row_str = "| " + " | ".join(str(r.get(col, "")).replace("\n", " ").strip().ljust(col_widths[i]) for i, col in enumerate(columns)) + " |"
        row_lines.append(row_str)
    return "\n".join([header_line, sep_line] + row_lines) + "\n"


def stage_artifacts(workspace: Path, stage_name: str) -> str:
    out_dir = workspace / "stages" / stage_name / "output"
    if not out_dir.exists():
        return "none"
    files = [f.name for f in out_dir.glob("*") if f.is_file() and f.name != ".gitkeep"]
    dirs = [d.name for d in out_dir.glob("*") if d.is_dir()]
    parts = []
    if files:
        parts.append(", ".join(files[:3]) + (f" (+{len(files)-3})" if len(files) > 3 else ""))
    if dirs:
        parts.append(f"{len(dirs)} dir(s)")
    return "; ".join(parts) or "none"


def get_pipeline_status(workspace: Path) -> list[dict]:
    res = []
    for i, s in enumerate(STAGES):
        st = stage_status(workspace, i)
        arts = stage_artifacts(workspace, s)
        res.append({
            "stage": s,
            "status": st,
            "artifacts": arts
        })
    return res


def print_status(workspace: Path, as_table: bool = False, as_json: bool = False, project_keys: list[str] | None = None) -> None:
    """Print the ICM pipeline status diagram or table."""
    statuses = get_pipeline_status(workspace)
    if project_keys:
        statuses = [{k: v for k, v in row.items() if k.lower() in project_keys} for row in statuses]

    if as_json:
        emit_json({"workspace": workspace.name, "stages": statuses})
        return

    if as_table:
        cols = list(statuses[0].keys()) if statuses else ["stage", "status", "artifacts"]
        print(f"### Pipeline Status: {workspace.name}\n")
        print(render_table(statuses, cols))
        return

    # Default ASCII status
    print(f"\nPipeline Status: {workspace.name}")
    print("=" * 60)
    raw_statuses = [stage_status(workspace, i) for i in range(len(STAGES))]
    header = "  " + " -> ".join(f"[{s}]" for s in STAGES)
    cols = []
    for s, st in zip(STAGES, raw_statuses):
        bracket_len = len(s) + 2
        cols.append(st.center(bracket_len))
    status_line = "  " + "    ".join(cols)

    print(header)
    print(status_line)
    print("-" * 60)
    for s, st in zip(STAGES, raw_statuses):
        print(f"  {s:18} : {st}")
    print()


# ── Stage Implementations ───────────────────────────────────────────────────

def run_stage_01_acquire(workspace: Path, video_source: str) -> None:
    stage_dir = workspace / "stages" / "01_acquire"
    out_dir = stage_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"[01_acquire] Ingesting video source: {video_source}")
    target_mp4 = out_dir / "source_video.mp4"
    audio_wav = out_dir / "audio.wav"
    meta_json = out_dir / "video_meta.json"
    
    if video_source.startswith("http://") or video_source.startswith("https://"):
        print("[01_acquire] Downloading with yt-dlp...")
        # Download video stream
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "-o", str(target_mp4),
            video_source
        ]
        subprocess.run(cmd, check=True)

        # Attempt to grab subtitles if available, but don't fail if rate-limited
        try:
            cmd_sub = [
                "yt-dlp", "--no-playlist", "--skip-download",
                "--write-auto-sub", "--write-sub", "--sub-lang", "en", "--sub-format", "vtt",
                "-o", str(out_dir / "source_video.%(ext)s"),
                video_source
            ]
            subprocess.run(cmd_sub, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    else:
        src_path = Path(video_source).expanduser().resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"Source video not found: {src_path}")
        if target_mp4.exists() or target_mp4.is_symlink():
            target_mp4.unlink()
        target_mp4.symlink_to(src_path)
        print(f"[01_acquire] Linked local video: {src_path} -> {target_mp4}")

    # Extract 16 kHz mono WAV audio for ASR
    print("[01_acquire] Extracting 16 kHz mono audio WAV...")
    cmd_audio = [
        "ffmpeg", "-y", "-i", str(target_mp4),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(audio_wav)
    ]
    subprocess.run(cmd_audio, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # Probe duration and format
    probe_cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size,bit_rate:stream=width,height,r_frame_rate,codec_name",
        "-of", "json", str(target_mp4)
    ]
    res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
    meta = json.loads(res.stdout)
    meta["source"] = video_source
    meta["ingest_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    meta_json.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[01_acquire] Done. Outputs in {out_dir}")


def parse_asr_segments(raw: Any) -> list[dict]:
    segments = []
    if isinstance(raw, dict):
        if "words" in raw and raw["words"]:
            word_list = raw["words"]
            cur_words = []
            seg_start = word_list[0].get("start_sec", 0.0)
            last_end = seg_start
            for w in word_list:
                w_text = w.get("word", "")
                w_start = w.get("start_sec", last_end)
                w_end = w.get("end_sec", w_start)
                if cur_words and ((w_start - last_end > 1.2) or ("".join(cur_words).strip().endswith((".", "!", "?")))):
                    segments.append({
                        "start": seg_start,
                        "end": last_end,
                        "text": "".join(cur_words).strip()
                    })
                    cur_words = []
                    seg_start = w_start
                cur_words.append(w_text)
                last_end = w_end
            if cur_words:
                segments.append({
                    "start": seg_start,
                    "end": last_end,
                    "text": "".join(cur_words).strip()
                })
            return segments
        elif "segments" in raw:
            return raw["segments"]
        elif "text" in raw:
            return [{"start": 0.0, "end": 0.0, "text": raw["text"]}]
    elif isinstance(raw, list):
        if raw and isinstance(raw[0], dict) and "start_sample" in raw[0]:
            cur_words = []
            seg_start = raw[0].get("start_sample", 0) / 16000.0
            last_end = seg_start
            for w in raw:
                w_text = w.get("word", "")
                w_start = w.get("start_sample", 0) / 16000.0
                w_end = w.get("end_sample", 0) / 16000.0
                if cur_words and ((w_start - last_end > 1.2) or (" ".join(cur_words).strip().endswith((".", "!", "?")))):
                    segments.append({
                        "start": seg_start,
                        "end": last_end,
                        "text": " ".join(cur_words).strip()
                    })
                    cur_words = []
                    seg_start = w_start
                cur_words.append(w_text)
                last_end = w_end
            if cur_words:
                segments.append({
                    "start": seg_start,
                    "end": last_end,
                    "text": " ".join(cur_words).strip()
                })
            return segments
        return raw
    return []


def run_stage_02_audio_asr(workspace: Path) -> None:
    stage_dir = workspace / "stages" / "02_audio_asr"
    out_dir = stage_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    audio_wav = workspace / "stages" / "01_acquire" / "output" / "audio.wav"
    if not audio_wav.exists():
        raise FileNotFoundError(f"Missing upstream audio: {audio_wav}")

    print(f"[02_audio_asr] Transcribing speech (audiocpp, model={ASR_MODEL or 'crisperwhisper (audiocpp default)'})...")
    
    words_json = out_dir / "words.json"
    cmd = get_asr_cmd(audio_wav, details=True, offline=True, words_out=words_json, model=ASR_MODEL)
    res = subprocess.run(cmd, capture_output=True, text=True)

    segments = []
    if words_json.is_file():
        try:
            raw_words = json.loads(words_json.read_text(encoding="utf-8"))
            segments = parse_asr_segments(raw_words)
        except Exception:
            pass

    if not segments:
        try:
            raw = json.loads(res.stdout)
            segments = parse_asr_segments(raw)
        except Exception:
            segments = [{"start": 0.0, "end": 0.0, "text": res.stdout.strip()}]

    transcript_json = out_dir / "transcript.json"
    transcript_md = out_dir / "transcript.md"
    
    transcript_json.write_text(json.dumps(segments, indent=2), encoding="utf-8")
    
    # Render readable transcript.md (edit surface!)
    md_lines = ["# Audio Transcript\n\n"]
    for seg in segments:
        ts = format_timestamp(seg.get("start", 0.0))
        text = seg.get("text", "").strip()
        if text:
            md_lines.append(f"**[{ts}]** {text}\n\n")
            
    transcript_md.write_text("".join(md_lines), encoding="utf-8")
    print(f"[02_audio_asr] Done. Generated {len(segments)} timestamped segments in {transcript_md}")


def probe_duration(video: Path) -> float:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True,
    )
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


def resolve_sample_mode(requested: str, duration_s: float) -> str:
    if requested in ("keyframe", "fps"):
        return requested
    return "keyframe" if duration_s > KEYFRAME_THRESHOLD_S else "select"


def run_stage_03_visual_sample(workspace: Path) -> None:
    stage_dir = workspace / "stages" / "03_visual_sample"
    out_dir = stage_dir / "output"
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    video_mp4 = workspace / "stages" / "01_acquire" / "output" / "source_video.mp4"
    if not video_mp4.exists():
        raise FileNotFoundError(f"Missing upstream video: {video_mp4}")

    duration = probe_duration(video_mp4)
    mode = resolve_sample_mode(SAMPLE_MODE, duration)

    # VLM tile boundary snapping: clamp max dimension to 1568 and snap W & H to multiples of 28px patch grid
    scale_expr = "scale=w='trunc(min(1568,iw)/28)*28':h='trunc((min(1568,iw)*ih/iw)/28)*28':flags=bicubic"

    if mode == "keyframe":
        print(f"[03_visual_sample] Extracting codec keyframes (-skip_frame nokey) from {duration:.0f}s source...")
        cmd = [
            "ffmpeg", "-y", "-skip_frame", "nokey", "-i", str(video_mp4),
            "-an",
            "-vf", f"{scale_expr},showinfo",
            "-vsync", "0",
            "-q:v", "2",
            str(frames_dir / "frame_%06d.jpg"),
        ]
    elif mode == "fps":
        print(f"[03_visual_sample] Sampling at {SAMPLE_FPS} fps from {duration:.0f}s source...")
        cmd = [
            "ffmpeg", "-y", "-i", str(video_mp4),
            "-an",
            "-vf", f"fps={SAMPLE_FPS},{scale_expr},showinfo",
            "-vsync", "vfr",
            "-q:v", "2",
            str(frames_dir / "frame_%06d.jpg"),
        ]
    else:
        print("[03_visual_sample] Extracting content frames (motion accumulator + scene cuts + mpdecimate)...")
        # Native FFmpeg filter:
        # 1. First frame always captured: eq(n,0)
        # 2. Cumulative motion accumulator st(0,...): sums inter-frame motion (scene delta). When >= 0.5 (~50% viewport shift), triggers a capture and resets.
        # 3. Sudden slide/scene jump: gt(scene, 0.22) triggers immediately and resets.
        # 4. Periodic safety fallback: not(mod(n, 120)) captures every ~4-5s even during perfectly still pauses.
        # 5. Debounce: max 1 capture per 0.5s during hyper-fast scrolls (prevents blurred duplicate bursts).
        # 6. mpdecimate: drops identical frames if the video was completely still.
        # 7. showinfo: emits exact pts_time to eliminate PTS clock drift.
        select_expr = (
            "st(0, if(eq(n,0), 0, ld(0)) + scene);"
            "if(gte(ld(0), 0.5) + gt(scene, 0.22) + eq(n,0) + not(mod(n, 120)),"
            "  st(0, 0) + (isnan(prev_selected_t) + gte(t - prev_selected_t, 0.5)),"
            "  0)"
        )
        cmd = [
            "ffmpeg", "-y", "-i", str(video_mp4),
            "-an",
            "-vf", f"select='{select_expr}',mpdecimate=hi=768:lo=320:frac=0.33,{scale_expr},showinfo",
            "-vsync", "vfr",
            "-q:v", "2",
            str(frames_dir / "frame_%06d.jpg"),
        ]

    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=True)

    # Parse exact presentation timestamps (pts_time) directly from ffmpeg showinfo log
    pts_times = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", res.stderr or "")]
    
    frame_files = sorted(list(frames_dir.glob("frame_*.jpg")) + list(frames_dir.glob("frame_*.png")))
    manifest = []
    
    for i, f in enumerate(frame_files):
        pts_sec = pts_times[i] if i < len(pts_times) else float(i * 3.0)
        manifest.append({
            "index": i,
            "filename": f.name,
            "path": str(f.relative_to(workspace)),
            "timestamp": pts_sec,
            "timestamp_str": format_timestamp(pts_sec)
        })
        
    manifest_file = out_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[03_visual_sample] Sampled {len(manifest)} frames ({mode}) into {frames_dir}")


def frame_signature(path: Path) -> dict:
    w, h = GRID * BLOCK_W, GRID * BLOCK_H
    res = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h},format=gray",
         "-frames:v", "1", "-f", "rawvideo", "-"],
        capture_output=True,
    )
    px = res.stdout
    if len(px) < w * h:
        return {"hashes": [], "luma": 0.0, "spread": 0.0}
    hashes = []
    for gy in range(GRID):
        for gx in range(GRID):
            bits = 0
            for r in range(BLOCK_H):
                for c in range(BLOCK_W - 1):
                    i = (gy * BLOCK_H + r) * w + gx * BLOCK_W + c
                    bits = (bits << 1) | (px[i] < px[i + 1])
            hashes.append(bits)
    return {"hashes": hashes, "luma": round(sum(px) / len(px), 1),
            "spread": float(max(px) - min(px))}


def hash_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def signature_distance(a: dict, b: dict) -> int:
    if not a["hashes"] or len(a["hashes"]) != len(b["hashes"]):
        return 999
    return max(hash_distance(x, y) for x, y in zip(a["hashes"], b["hashes"]))


def text_similarity(a: str, b: str) -> float:
    la = {ln.strip() for ln in a.splitlines() if ln.strip()}
    lb = {ln.strip() for ln in b.splitlines() if ln.strip()}
    if not la or not lb:
        return 0.0
    return len(la & lb) / len(la | lb)


def h2o_has_text(frame_path: Path) -> tuple[bool, float]:
    ext = frame_path.suffix.lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    with open(frame_path, "rb") as img_file:
        b64_data = base64.b64encode(img_file.read()).decode("utf-8")
    payload = {
        "state": {"context": "Frame sampled from a technical video or lecture recording."},
        "questions": {
            "answer": {
                "type": "bool",
                "question": "Does this image show slides, code, UI text, or diagrams with readable text?",
                "image": "frame",
            }
        },
        "assets": {
            "frame": {
                "type": "image",
                "format": "jpg" if mime == "image/jpeg" else "png",
                "data_base64": b64_data,
            }
        },
    }
    req = urllib.request.Request(
        DECISION_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    answer = (data.get("answers") or {}).get("answer", {})
    probabilities = answer.get("probabilities") or {}
    p_true = float(answer.get("probability", probabilities.get("true", 1.0 if answer.get("decision") else 0.0)))
    return p_true >= 0.5, round(abs(p_true - 0.5) * 2.0, 4)


def run_stage_04_visual_gate(workspace: Path) -> None:
    stage_dir = workspace / "stages" / "04_visual_gate"
    out_dir = stage_dir / "output"
    text_frames_dir = out_dir / "text_frames"
    text_frames_dir.mkdir(parents=True, exist_ok=True)

    manifest_file = workspace / "stages" / "03_visual_sample" / "output" / "manifest.json"
    if not manifest_file.exists():
        raise FileNotFoundError(f"Missing upstream manifest: {manifest_file}")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    print(f"[04_visual_gate] Evaluating {len(manifest)} frames (gate={GATE_MODE})...")

    if GATE_MODE == "h2o" and not _decision_model_is_h2o():
        raise RuntimeError("gate=h2o requires h2o-lightning-4b on the JEV endpoint")

    gated_results = []
    last_kept_sig = None
    last_kept_name = None
    counts = {"new": 0, "duplicate": 0, "blank": 0, "no-text": 0}

    for item in manifest:
        frame_path = workspace / item["path"]
        if not frame_path.exists():
            continue

        sig = frame_signature(frame_path)
        blank = sig["spread"] < 8.0
        duplicate_of = None
        if not blank and last_kept_sig is not None and signature_distance(sig, last_kept_sig) <= HASH_DISTANCE:
            duplicate_of = last_kept_name

        if blank:
            keep, reason = False, "blank"
        elif duplicate_of:
            keep, reason = False, "duplicate"
        elif GATE_MODE == "h2o":
            has_text, _ = h2o_has_text(frame_path)
            keep, reason = has_text, "new" if has_text else "no-text"
        else:
            keep, reason = True, "new"

        counts[reason] = counts.get(reason, 0) + 1
        record = dict(item)
        record.update({
            "hash": "".join(f"{h:016x}" for h in sig["hashes"])[:64],
            "luma": sig["luma"],
            "luma_spread": sig["spread"],
            "keep": keep,
            "reason": reason,
            "duplicate_of": duplicate_of,
        })
        gated_results.append(record)

        if keep:
            last_kept_sig = sig
            last_kept_name = item["filename"]
            dest = text_frames_dir / item["filename"]
            if not dest.exists():
                dest.symlink_to(frame_path)

    gated_json = out_dir / "gated_frames.json"
    gated_json.write_text(json.dumps(gated_results, indent=2), encoding="utf-8")
    kept_count = sum(1 for r in gated_results if r["keep"])
    print(f"[04_visual_gate] Retained {kept_count}/{len(gated_results)} frames "
          f"(new={counts['new']} duplicate={counts['duplicate']} blank={counts['blank']} "
          f"no-text={counts['no-text']}) in {text_frames_dir}")


def kem_gate(text: str, block_type: str = "text"):
    try:
        scripts = str(KEM_SCRIPTS)
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from kem_ocr import assert_structure
        return assert_structure(text, block_type)
    except Exception:
        return None


def run_stage_05_visual_ocr(workspace: Path) -> None:
    stage_dir = workspace / "stages" / "05_visual_ocr"
    out_dir = stage_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    gated_json = workspace / "stages" / "04_visual_gate" / "output" / "gated_frames.json"
    if not gated_json.exists():
        raise FileNotFoundError(f"Missing upstream gated frames: {gated_json}")

    records = json.loads(gated_json.read_text(encoding="utf-8"))
    kept = [r for r in records if r.get("keep", False)]
    label = "MiniCPM-OCR-1.0 + structural gate" if OCR_BACKEND == "minicpm" else "LightOnOCR-3-0.8B"
    print(f"[05_visual_ocr] Running OCR ({label}) on {len(kept)} frames...")


    ocr_json = out_dir / "ocr_timeline.json"
    ocr_md = out_dir / "ocr_timeline.md"
    preprocessed_dir = out_dir / "preprocessed_frames"
    preprocessed_dir.mkdir(parents=True, exist_ok=True)

    def preprocess_frame_for_ocr(frame_path: Path) -> Path:
        """Applies grayscale, contrast boost (1.3x), and unsharp mask to maximize OCR legibility."""
        ocr_target = preprocessed_dir / f"{frame_path.stem}_ocr.jpg"
        if not ocr_target.exists():
            cmd = [
                "ffmpeg", "-y", "-i", str(frame_path),
                "-vf", "format=gray,eq=contrast=1.3:brightness=0.02,unsharp=5:5:1.0:5:5:0.0",
                "-q:v", "2",
                str(ocr_target)
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return ocr_target if ocr_target.exists() else frame_path

    if not kept:
        ocr_json.write_text("[]", encoding="utf-8")
        ocr_md.write_text(f"# Visual OCR Timeline ({label})\n\nNo text frames detected.\n", encoding="utf-8")
        return

    if OCR_BACKEND == "minicpm":
        ocr_bin, ocr_model, ocr_mmproj = MINICPM_SERVER_BIN, MINICPM_MODEL, MINICPM_MMPROJ
        ocr_port, ocr_url = MINICPM_PORT, MINICPM_URL
    else:
        ocr_bin, ocr_model, ocr_mmproj = LLAMA_SERVER_BIN, LIGHTON_MODEL, LIGHTON_MMPROJ
        ocr_port, ocr_url = LIGHTON_PORT, LIGHTON_URL

    for kind, path in (("model", ocr_model), ("mmproj", ocr_mmproj)):
        if not path.exists():
            raise FileNotFoundError(f"Missing {OCR_BACKEND} {kind}: {path}")


    server_proc = None
    started_server = False

    def is_server_listening(url: str, timeout: float = 1.0) -> bool:
        try:
            health_url = url.replace("/v1/chat/completions", "/health")
            req = urllib.request.Request(health_url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status in (200, 404)
        except Exception:
            return False

    # Check if a server is already listening, or spawn an ephemeral one for speed
    if not is_server_listening(ocr_url):
        if ocr_bin.exists():
            print(f"[05_visual_ocr] Spawning ephemeral {OCR_BACKEND} server on port {ocr_port}...")
            cmd = [
                str(ocr_bin),
                "-m", str(ocr_model),
                "--mmproj", str(ocr_mmproj),
                "--port", str(ocr_port),
                "-ngl", "99",
                "-c", "8192" if OCR_BACKEND == "minicpm" else "4096",
            ]
            if OCR_BACKEND == "minicpm":
                cmd += ["--reasoning", "off"]
            server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            started_server = True
            for _ in range(30):
                time.sleep(0.5)
                if is_server_listening(ocr_url):
                    print(f"[05_visual_ocr] Server ready on http://127.0.0.1:{ocr_port}")
                    break
            else:
                print("[05_visual_ocr] Warning: Server start timed out, falling back to CLI if needed.")


    def minicpm_single_frame(frame_file: Path) -> str:
        if not is_server_listening(ocr_url):
            return ""
        try:
            with open(frame_file, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            mime = "png" if frame_file.suffix.lower() == ".png" else "jpeg"
            payload = {
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}},
                        {"type": "text", "text": "Text Recognition:"},
                    ],
                }],
                "max_tokens": 1536,
                "temperature": 0.0,
            }
            req = urllib.request.Request(
                ocr_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            msg = data["choices"][0]["message"]
            return (msg.get("content") or msg.get("reasoning_content") or "").strip()
        except Exception:
            return ""

    def ocr_single_frame(frame_file: Path) -> str:
        if OCR_BACKEND == "minicpm":
            return minicpm_single_frame(frame_file)
        return lighton_single_frame(frame_file)

    def lighton_single_frame(frame_file: Path) -> str:
        # 1. Try persistent / ephemeral HTTP server
        if is_server_listening(LIGHTON_URL):
            try:
                with open(frame_file, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                payload = {
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Transcribe all visible text in Markdown. Output only the verbatim text."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                        ]
                    }],
                    "max_tokens": 2048,
                    "temperature": 0.0,
                }
                req = urllib.request.Request(
                    LIGHTON_URL,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=45) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        msg = data["choices"][0]["message"]
                        text = (msg.get("content") or msg.get("reasoning_content") or "").strip()
                        if text:
                            return text
            except Exception:
                pass

        # 2. Direct llama-mtmd-cli fallback
        if LLAMA_MTMD_CLI.exists():
            try:
                cmd = [
                    str(LLAMA_MTMD_CLI),
                    "-m", str(LIGHTON_MODEL),
                    "--mmproj", str(LIGHTON_MMPROJ),
                    "--image", str(frame_file),
                    "-p", "Extract all text and code from this image in markdown.",
                    "-ngl", "99",
                    "--temp", "0",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                if res.returncode == 0:
                    lines = res.stdout.splitlines()
                    clean_lines = []
                    past_header = False
                    for line in lines:
                        if past_header:
                            clean_lines.append(line)
                        elif "mtmd batch encoding done" in line:
                            past_header = True
                    text = "\n".join(clean_lines).strip()
                    if text:
                        return text
                    return res.stdout.strip()
            except Exception:
                pass

        return ""

    ocr_entries = []
    last_text = ""
    try:
        for idx, r in enumerate(kept, 1):
            frame_file = workspace / "stages" / "04_visual_gate" / "output" / "text_frames" / r["filename"]
            if not frame_file.exists():
                continue
                
            print(f"[05_visual_ocr] Processing frame {idx}/{len(kept)}: {r['filename']} ({r['timestamp_str']})...")
            ocr_input_file = frame_file if OCR_BACKEND == "minicpm" else preprocess_frame_for_ocr(frame_file)
            text_out = ocr_single_frame(ocr_input_file)
            structure = kem_gate(text_out) if (OCR_BACKEND == "minicpm" and text_out) else None

            if structure is not None and not structure["ok"]:
                print(f"[05_visual_ocr]   drop {r['filename']}: structural {'+'.join(structure['failed'])}")
                continue

            if text_out and last_text and text_similarity(text_out, last_text) >= TEXT_SIMILARITY:
                print(f"[05_visual_ocr]   drop {r['filename']}: near-duplicate text "
                      f"({text_similarity(text_out, last_text):.2f})")
                continue

            # Deduplicate consecutive identical text
            if text_out and text_out != last_text:
                entry = {
                    "timestamp": r["timestamp"],
                    "timestamp_str": r["timestamp_str"],
                    "frame": r["filename"],
                    "text": text_out,
                }
                if structure is not None:
                    entry["structural"] = structure
                ocr_entries.append(entry)
                last_text = text_out

    finally:
        if started_server and server_proc is not None:
            print(f"[05_visual_ocr] Stopping ephemeral {OCR_BACKEND} server...")
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()

    ocr_json.write_text(json.dumps(ocr_entries, indent=2), encoding="utf-8")
    
    md_lines = [f"# Visual OCR Timeline ({label})\n\n"]
    for entry in ocr_entries:
        ts = entry["timestamp_str"]
        frame = entry["frame"]
        content = entry["text"]
        md_lines.append(f"### [{ts}] Frame `{frame}`\n\n{content}\n\n---\n\n")
        
    ocr_md.write_text("".join(md_lines), encoding="utf-8")
    print(f"[05_visual_ocr] Done. Extracted {len(ocr_entries)} visual segments in {ocr_md}")



def run_stage_06_synthesize(workspace: Path) -> None:
    stage_dir = workspace / "stages" / "06_synthesize"
    out_dir = stage_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    asr_json = workspace / "stages" / "02_audio_asr" / "output" / "transcript.json"
    ocr_json = workspace / "stages" / "05_visual_ocr" / "output" / "ocr_timeline.json"
    meta_json = workspace / "stages" / "01_acquire" / "output" / "video_meta.json"
    
    transcript = json.loads(asr_json.read_text(encoding="utf-8")) if asr_json.exists() else []
    ocr_timeline = json.loads(ocr_json.read_text(encoding="utf-8")) if ocr_json.exists() else []
    meta = json.loads(meta_json.read_text(encoding="utf-8")) if meta_json.exists() else {}
    
    print("[06_synthesize] Merging audio transcript and visual OCR into mined_video.md...")
    
    # Merge items chronologically
    events = []
    for t in transcript:
        events.append({
            "type": "spoken",
            "timestamp": t.get("start", 0.0),
            "end": t.get("end", 0.0),
            "text": t.get("text", "")
        })
    for o in ocr_timeline:
        events.append({
            "type": "visual",
            "timestamp": o.get("timestamp", 0.0),
            "frame": o.get("frame", ""),
            "text": o.get("text", "")
        })
        
    events.sort(key=lambda x: x["timestamp"])
    
    # Render final markdown artifact
    doc = [
        f"# Mined Video Notes: {workspace.name}\n\n",
        f"- **Source:** {meta.get('source', 'Unknown')}\n",
        f"- **Processed on:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n",
        "---\n\n",
        "## Chronological Content\n\n"
    ]
    
    current_time_str = ""
    for ev in events:
        ts_str = format_timestamp(ev["timestamp"])
        if ev["type"] == "visual":
            doc.append(f"\n#### 🖥️ Visual Slide / Code [{ts_str}]\n\n")
            doc.append(f"{ev['text']}\n\n")
        else:
            text = ev["text"].strip()
            if text:
                doc.append(f"> **[{ts_str}]** {text}\n\n")

    final_md = out_dir / "mined_video.md"
    final_json = out_dir / "mined_video.json"
    
    final_md.write_text("".join(doc), encoding="utf-8")
    final_json.write_text(json.dumps(events, indent=2), encoding="utf-8")
    print(f"\n[06_synthesize] Successfully synthesized deliverable: {final_md}")


# ── Pipeline Runner ──────────────────────────────────────────────────────────

def init_workspace(target_path: Path, video_source: str) -> Path:
    """Scaffold a fresh ICM workspace from template."""
    target_path = target_path.resolve()
    if target_path.exists() and any(target_path.iterdir()):
        print(f"Directory {target_path} already exists. Using existing workspace.")
        return target_path
        
    shutil.copytree(TEMPLATES_DIR, target_path, dirs_exist_ok=True)
    # Store source in _shared/source.json
    shared_dir = target_path / "_shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    (shared_dir / "source.json").write_text(
        json.dumps({"video_source": video_source, "created_at": datetime.datetime.now().isoformat()}, indent=2),
        encoding="utf-8"
    )
    print(f"Created ICM workspace at: {target_path}")
    return target_path


def run_pipeline(workspace: Path, video_source: str | None = None, until_stage: str | None = None, step_only: bool = False) -> None:
    source_file = workspace / "_shared" / "source.json"
    if source_file.exists():
        src_data = json.loads(source_file.read_text(encoding="utf-8"))
        video_source = video_source or src_data.get("video_source")
        
    if not video_source and stage_status(workspace, 0) == "PENDING":
        raise ValueError("Video source (URL or file) must be provided for initial stage.")

    for i, stage in enumerate(STAGES):
        st = stage_status(workspace, i)
        
        # If complete and not stale, skip
        if st == "COMPLETE":
            continue
            
        print(f"\n▶ Executing Stage: {stage} (Status: {st})")
        if stage == "01_acquire":
            run_stage_01_acquire(workspace, video_source)
        elif stage == "02_audio_asr":
            run_stage_02_audio_asr(workspace)
        elif stage == "03_visual_sample":
            run_stage_03_visual_sample(workspace)
        elif stage == "04_visual_gate":
            run_stage_04_visual_gate(workspace)
        elif stage == "05_visual_ocr":
            run_stage_05_visual_ocr(workspace)
        elif stage == "06_synthesize":
            run_stage_06_synthesize(workspace)
            
        if step_only:
            print(f"\n[Human Checkpoint] Pausing after stage {stage}.")
            print(f"Review and edit files in: stages/{stage}/output/")
            break
            
        if until_stage and stage == until_stage:
            print(f"\nReached requested stage: {until_stage}. Stopping.")
            break

    print_status(workspace)


def extract_timeline(workspace: Path, limit: int = 0) -> list[dict]:
    """Extract chronological timeline checkpoints from mined video artifacts."""
    synth_json = workspace / "stages" / "06_synthesize" / "output" / "mined_video.json"
    events = []
    if synth_json.is_file():
        try:
            events = json.loads(synth_json.read_text(encoding="utf-8"))
        except Exception:
            events = []

    if not events:
        ocr_file = workspace / "stages" / "05_visual_ocr" / "output" / "ocr_timeline.json"
        if ocr_file.is_file():
            try:
                for o in json.loads(ocr_file.read_text(encoding="utf-8")):
                    events.append({
                        "type": "visual",
                        "timestamp": o.get("timestamp", 0.0),
                        "frame": o.get("frame", ""),
                        "text": o.get("text", "")
                    })
            except Exception:
                pass

        asr_file = workspace / "stages" / "02_audio_asr" / "output" / "transcript.json"
        if asr_file.is_file():
            try:
                for t in json.loads(asr_file.read_text(encoding="utf-8")):
                    events.append({
                        "type": "audio",
                        "timestamp": t.get("timestamp", 0.0),
                        "frame": "-",
                        "text": t.get("text", "")
                    })
            except Exception:
                pass

    events.sort(key=lambda x: x.get("timestamp", 0.0))
    rows = []
    for ev in events:
        ts = ev.get("timestamp", 0.0)
        ts_str = format_timestamp(ts)
        ev_type = "Visual" if ev.get("type") == "visual" else "Speech"
        raw_text = str(ev.get("text") or "").strip().replace("\n", " ")
        preview = raw_text[:75] + "..." if len(raw_text) > 75 else raw_text
        frame = ev.get("frame") or "-"
        rows.append({
            "time": ts_str,
            "type": ev_type,
            "preview": preview,
            "frame": frame
        })

    if limit and limit > 0:
        rows = rows[:limit]
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="videomine - ICM Video Mining Pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize a new ICM workspace")
    p_init.add_argument("workspace", type=Path, help="Workspace directory")
    p_init.add_argument("source", type=str, help="Video URL or local file path")

    # status
    p_status = subparsers.add_parser("status", help="Show ICM status")
    p_status.add_argument("workspace", type=Path, nargs="?", default=Path("."), help="Workspace directory")
    p_status.add_argument("--table", "-t", action="store_true", help="Render status as a Markdown table")
    p_status.add_argument("--json", action="store_true", help="Render status as JSON")
    p_status.add_argument("--project", "-p", help="Comma-separated fields to project")

    # outline / timeline
    p_outline = subparsers.add_parser("outline", aliases=["timeline"], help="Extract chronological timeline outline of video checkpoints")
    p_outline.add_argument("workspace", type=Path, nargs="?", default=Path("."), help="Workspace directory")
    p_outline.add_argument("--table", "-t", action="store_true", default=True, help="Render as Markdown table (default: True)")
    p_outline.add_argument("--json", action="store_true", help="Render as JSON")
    p_outline.add_argument("--project", "-p", help="Comma-separated fields to project")
    p_outline.add_argument("--limit", "-n", type=int, default=0, metavar="LIMIT", help="Cap number of rows")
    p_outline.add_argument("--out", "-o", help="Buffer full JSON to disk and output a 1-line receipt")

    # step
    p_step = subparsers.add_parser("step", help="Run the next single stage and stop at human checkpoint")
    p_step.add_argument("workspace", type=Path, nargs="?", default=Path("."), help="Workspace directory")
    p_step.add_argument("--source", type=str, help="Video source if running stage 01")
    p_step.add_argument("--ocr", choices=["lighton", "minicpm"], help="OCR backend (default: lighton)")
    p_step.add_argument("--gate", choices=["hash", "h2o"], help="frame gate (default: hash)")
    p_step.add_argument("--asr-model", help="audiocpp ASR slug (default: crisperwhisper); e.g. nemotron")
    p_step.add_argument("--sample", choices=["auto", "keyframe", "fps"], help="frame sampling (default: auto — keyframe over 10 min)")
    p_step.add_argument("--sample-fps", type=float, metavar="RATIO", help="fps for --sample fps (default: 1.0)")

    # run
    p_run = subparsers.add_parser("run", help="Run pipeline stages")
    p_run.add_argument("workspace", type=Path, nargs="?", default=Path("."), help="Workspace directory")
    p_run.add_argument("--source", type=str, help="Video source")
    p_run.add_argument("--until", type=str, help="Stop at this stage (e.g. 02_audio_asr)")
    p_run.add_argument("--ocr", choices=["lighton", "minicpm"], help="OCR backend (default: lighton)")
    p_run.add_argument("--gate", choices=["hash", "h2o"], help="frame gate (default: hash)")
    p_run.add_argument("--asr-model", help="audiocpp ASR slug (default: crisperwhisper); e.g. nemotron")
    p_run.add_argument("--sample", choices=["auto", "keyframe", "fps"], help="frame sampling (default: auto — keyframe over 10 min)")
    p_run.add_argument("--sample-fps", type=float, metavar="RATIO", help="fps for --sample fps (default: 1.0)")

    args = parser.parse_args()

    # In --json mode every log line belongs on stderr: capture the real stdout
    # for the JSON document, then point sys.stdout at stderr so all existing
    # print() progress/notification calls are rerouted without touching them.
    global _STDOUT
    if getattr(args, "json", False):
        _STDOUT = sys.stdout
        sys.stdout = sys.stderr

    global GATE_MODE, OCR_BACKEND, ASR_MODEL, SAMPLE_MODE, SAMPLE_FPS
    if getattr(args, "gate", None):
        GATE_MODE = args.gate
    if getattr(args, "ocr", None):
        OCR_BACKEND = args.ocr
    if getattr(args, "asr_model", None):
        ASR_MODEL = args.asr_model
    if getattr(args, "sample", None):
        SAMPLE_MODE = args.sample
    if getattr(args, "sample_fps", None):
        SAMPLE_FPS = args.sample_fps

    if args.command == "init":
        init_workspace(args.workspace, args.source)
        print_status(args.workspace)
    elif args.command == "status":
        project_keys = [k.strip().lower() for k in args.project.split(",") if k.strip()] if getattr(args, "project", None) else None
        print_status(args.workspace.resolve(), as_table=args.table, as_json=args.json, project_keys=project_keys)
    elif args.command in ["outline", "timeline"]:
        ws = args.workspace.resolve()
        rows = extract_timeline(ws, limit=args.limit)
        if args.out:
            out_p = Path(args.out).expanduser()
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"### Buffered {len(rows)} timeline checkpoints to `{args.out}`\n")
        if getattr(args, "project", None) and rows:
            proj = [k.strip().lower() for k in args.project.split(",") if k.strip()]
            cols = [c for c in list(rows[0].keys()) if c.lower() in proj] or list(rows[0].keys())
            rows = [{k: r[k] for k in cols if k in r} for r in rows]
        else:
            cols = list(rows[0].keys()) if rows else ["time", "type", "preview", "frame"]

        if args.json:
            emit_json(rows)
        else:
            print(f"### Timeline Outline: {ws.name}\n")
            print(render_table(rows, cols))
    elif args.command == "step":
        run_pipeline(args.workspace.resolve(), video_source=args.source, step_only=True)
    elif args.command == "run":
        run_pipeline(args.workspace.resolve(), video_source=args.source, until_stage=args.until, step_only=False)


if __name__ == "__main__":
    main()
