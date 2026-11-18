#!/usr/bin/env python3
"""videomine stages 01-06 and the runner that walks the human checkpoints.

Each stage reads the previous stage's output folder and writes its own, so the
workspace tree is the state. `main` rebinds the options here (gate, OCR
backend, ASR model, sampling, diarization) before the runner starts.
"""
from __future__ import annotations

import base64
import datetime
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import procure
from videomine_core import (
    ASR_MODEL,
    DIARIZE,
    GATE_MODE,
    HASH_DISTANCE,
    KEYFRAME_THRESHOLD_S,
    LIGHTON_MMPROJ,
    LIGHTON_MODEL,
    LIGHTON_PORT,
    LIGHTON_URL,
    LLAMA_MTMD_CLI,
    LLAMA_SERVER_BIN,
    MINICPM_MMPROJ,
    MINICPM_MODEL,
    MINICPM_PORT,
    MINICPM_SERVER_BIN,
    MINICPM_URL,
    OCR_BACKEND,
    OCR_SLOT,
    OCR_WAIT_S,
    SAMPLE_FPS,
    SAMPLE_MODE,
    SPEAKER_NAMES,
    STAGES,
    TEXT_SIMILARITY,
    _decision_model_is_h2o,
    format_timestamp,
    get_asr_cmd,
    print_status,
    stage_status,
)
from videomine_visual import (
    frame_signature,
    frame_signatures,
    h2o_has_text,
    kem_gate,
    signature_distance,
    text_similarity,
)


def run_stage_01_acquire(workspace: Path, video_source: str) -> None:
    stage_dir = workspace / "stages" / "01_acquire"
    out_dir = stage_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"[01_acquire] Ingesting video source: {video_source}")
    target_mp4 = out_dir / "source_video.mp4"
    audio_wav = out_dir / "audio.wav"
    meta_json = out_dir / "video_meta.json"
    
    if video_source.startswith("http://") or video_source.startswith("https://"):
        kind = "short-form" if procure.is_short_form(video_source) else "video"
        print(f"[01_acquire] Downloading {kind} with yt-dlp "
              f"(res<={procure.max_res()}p, {procure.DEFAULT_FRAGMENTS} fragments)...")
        started = time.perf_counter()
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--no-progress",
            *procure.download_args(video_source),
            "-o", str(out_dir / "source_video.%(ext)s"),
            video_source,
        ]
        subprocess.run(cmd, check=True)
        media = [p for p in out_dir.glob("source_video.*")
                 if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".m4v")]
        if not media:
            raise FileNotFoundError(f"yt-dlp reported success but wrote no media file in {out_dir}")
        target_mp4 = sorted(media, key=lambda p: p.stat().st_size)[-1]
        if target_mp4.suffix.lower() != ".mp4":
            remuxed = out_dir / "source_video.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(target_mp4),
                 "-c", "copy", str(remuxed)],
                check=True,
            )
            target_mp4.unlink(missing_ok=True)
            target_mp4 = remuxed
        print(f"[01_acquire] Downloaded {target_mp4.stat().st_size / 1e6:.1f} MB "
              f"in {time.perf_counter() - started:.1f}s")
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


def _segment_words(word_list: list[dict], time_of, joiner: str,
                   turns: list[dict] | None = None) -> list[dict]:
    """Split a word stream into segments on pauses, sentence ends and speaker turns.

    `time_of(word)` returns `(start, end)` in seconds. A speaker change closes
    the segment so a `speaker` field stays true for the whole line.
    """
    segments = []
    cur_words: list[str] = []
    seg_start = None
    last_end = 0.0
    cur_speaker = None
    for w in word_list:
        w_text = w.get("word", "")
        w_start, w_end = time_of(w)
        speaker = procure.speaker_at(turns, w_start, w_end) if turns else None
        if seg_start is None:
            seg_start = w_start
        broke = bool(cur_words) and (
            (w_start - last_end > 1.2)
            or joiner.join(cur_words).strip().endswith((".", "!", "?"))
            or (turns and speaker != cur_speaker)
        )
        if broke:
            segments.append({"start": seg_start, "end": last_end,
                             "text": joiner.join(cur_words).strip()})
            cur_words = []
            seg_start = w_start
        cur_speaker = speaker
        cur_words.append(w_text)
        last_end = w_end
    if cur_words and seg_start is not None:
        segments.append({"start": seg_start, "end": last_end,
                         "text": joiner.join(cur_words).strip()})
    return segments


def parse_asr_segments(raw: Any, turns: list[dict] | None = None) -> list[dict]:
    if isinstance(raw, dict):
        if "words" in raw and raw["words"]:
            return _segment_words(
                raw["words"],
                lambda w: (w.get("start_sec", 0.0), w.get("end_sec", w.get("start_sec", 0.0))),
                "",
                turns,
            )
        elif "segments" in raw:
            return raw["segments"]
        elif "text" in raw:
            return [{"start": 0.0, "end": 0.0, "text": raw["text"]}]
    elif isinstance(raw, list):
        if raw and isinstance(raw[0], dict) and "start_sample" in raw[0]:
            return _segment_words(
                raw,
                lambda w: (w.get("start_sample", 0) / 16000.0, w.get("end_sample", 0) / 16000.0),
                " ",
                turns,
            )
        return raw
    return []


def run_stage_02_audio_asr(workspace: Path) -> None:
    stage_dir = workspace / "stages" / "02_audio_asr"
    out_dir = stage_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    audio_wav = workspace / "stages" / "01_acquire" / "output" / "audio.wav"
    if not audio_wav.exists():
        raise FileNotFoundError(f"Missing upstream audio: {audio_wav}")

    print(f"[02_audio_asr] Transcribing speech (audiocpp, model={ASR_MODEL})...")
    if DIARIZE and ASR_MODEL.startswith("nemotron"):
        print("[02_audio_asr] Note: nemotron emits no word timings, so speaker "
              "labels land on whole segments (use crisperwhisper for per-turn splits).")
    
    words_json = out_dir / "words.json"
    cmd = get_asr_cmd(audio_wav, details=True, offline=True, words_out=words_json, model=ASR_MODEL)
    res = subprocess.run(cmd, capture_output=True, text=True)

    # Optional: who spoke when, one extra pass over the same recording. It runs
    # before segmentation so the segments can break on a speaker change too.
    turns = None
    labels = {}
    speaker_summary = []
    if DIARIZE:
        print("[02_audio_asr] Diarizing speakers (Nemotron 3)...")
        turns = procure.run_diarization(audio_wav, stage_dir / "diar", names=SPEAKER_NAMES)
        if turns:
            labels = procure.speaker_labels(turns, SPEAKER_NAMES)
            speaker_summary = procure.talk_time(turns, labels)
            print("[02_audio_asr] " + " · ".join(f"{n} {s:.0f}s" for n, s in speaker_summary))

    segments = []
    if words_json.is_file():
        try:
            raw_words = json.loads(words_json.read_text(encoding="utf-8"))
            segments = parse_asr_segments(raw_words, turns=turns)
        except Exception:
            pass

    if not segments:
        try:
            raw = json.loads(res.stdout)
            segments = parse_asr_segments(raw, turns=turns)
        except Exception:
            segments = [{"start": 0.0, "end": 0.0, "text": res.stdout.strip()}]

    if turns:
        for seg in segments:
            speaker = procure.speaker_at(turns, seg.get("start", 0.0), seg.get("end", 0.0))
            if speaker:
                seg["speaker"] = labels.get(speaker, speaker)

    transcript_json = out_dir / "transcript.json"
    transcript_md = out_dir / "transcript.md"
    
    transcript_json.write_text(json.dumps(segments, indent=2), encoding="utf-8")
    
    # Render readable transcript.md (edit surface!)
    md_lines = ["# Audio Transcript\n\n"]
    if speaker_summary:
        md_lines.append("**Speakers:** " + " · ".join(f"{n} {s:.0f}s" for n, s in speaker_summary) + "\n\n")
    for seg in segments:
        ts = format_timestamp(seg.get("start", 0.0))
        text = seg.get("text", "").strip()
        speaker = seg.get("speaker")
        if text:
            md_lines.append(f"**[{ts}] {speaker}:** {text}\n\n" if speaker
                            else f"**[{ts}]** {text}\n\n")
            
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

    frame_paths = [workspace / item["path"] for item in manifest]
    signatures = frame_signatures(frame_paths)
    signature_index = 0
    for item in manifest:
        frame_path = workspace / item["path"]
        if not frame_path.exists():
            continue

        if signature_index < len(signatures):
            sig = signatures[signature_index]
            signature_index += 1
        else:
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


    spawn_cmd = None
    slot = OCR_SLOT
    if OCR_BACKEND == "minicpm":
        spawn_cmd = [
            str(ocr_bin),
            "-m", str(ocr_model),
            "--mmproj", str(ocr_mmproj),
            "--port", str(ocr_port),
            "-ngl", "99",
            "-c", "8192",
            "--reasoning", "off",
        ]
        slot = None

    ocr_ok, ocr_how, server_proc = procure.ensure_service(
        ocr_url, slot=slot, spawn_cmd=spawn_cmd, wait_s=OCR_WAIT_S
    )
    started_server = ocr_how == "spawned"
    if ocr_ok and ocr_how == "llama-rig":
        print(f"[05_visual_ocr] The slot was down; started it. It stays up for the next run "
              f"(`llama-rig down {slot}` frees the VRAM).")
    if not ocr_ok:
        # Leave the stage PENDING instead of writing an empty timeline: an
        # empty `[]` would mark 05_visual_ocr COMPLETE and let 06_synthesize
        # emit notes with no visual text while looking successful.
        raise RuntimeError(
            f"{OCR_BACKEND} is not answering on {ocr_url}. Start it with "
            f"`llama-rig up {slot or 'ocr'}` and re-run `step`."
        )

    def is_server_listening(url: str, timeout: float = 1.0) -> bool:
        return procure.http_up(url.replace("/v1/chat/completions", "/health"), timeout=timeout)

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
        if started_server:
            print(f"[05_visual_ocr] Stopping the throwaway {OCR_BACKEND} server...")
            procure.stop_child(server_proc)

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
            "speaker": t.get("speaker"),
            "text": t.get("text", ""),
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
                speaker = ev.get("speaker")
                who = f"] {speaker}:**" if speaker else "]**"
                doc.append(f"> **[{ts_str}{who} {text}\n\n")

    final_md = out_dir / "mined_video.md"
    final_json = out_dir / "mined_video.json"
    
    final_md.write_text("".join(doc), encoding="utf-8")
    final_json.write_text(json.dumps(events, indent=2), encoding="utf-8")
    print(f"\n[06_synthesize] Successfully synthesized deliverable: {final_md}")


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
