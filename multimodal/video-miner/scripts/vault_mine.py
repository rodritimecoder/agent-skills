#!/usr/bin/env python3
"""
vault_mine.py — High-Speed Creator Video Vault Miner & Indexer
Integrates yt-dlp single-pass ingestion, audiocpp GPU transcription,
fast keyframe extraction, and optional LightOnOCR diagram synthesis.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from PIL import Image
except ImportError:
    Image = None

def _drive_root() -> Path:
    """The AI volume root: $AI_ROOT, else the nearest ancestor holding models/.

    Vault, weights and the mtmd binary all live under it, so resolving from here
    keeps the skill working wherever the volume is mounted.
    """
    env = os.environ.get("AI_ROOT")
    if env:
        return Path(env).expanduser()
    for parent in Path(__file__).resolve().parents:
        if (parent / "models").is_dir():
            return parent
    return Path("/run/media/rodri/AI")


DRIVE = _drive_root()
DEFAULT_VAULT_DIR = Path(os.environ.get("CREATOR_VAULT_DIR", DRIVE / "creator-vault"))


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "_", text)[:60]


def is_ocr_server_online(port: int = 8085, timeout: float = 0.3) -> bool:
    """Fast non-blocking probe to check if LightOnOCR HTTP server is live."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def ocr_frame_http(image_path: Path, port: int = 8085) -> str:
    """Fast OCR via local LightOnOCR server (<500ms per frame)."""
    try:
        import base64
        img_bytes = image_path.read_bytes()
        b64 = base64.b64encode(img_bytes).decode("ascii")
        payload = json.dumps({
            "model": "LightOnOCR-3-0.8B",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe all visible text in Markdown. Output only the verbatim text."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                    ]
                }
            ],
            "max_tokens": 300,
            "temperature": 0.1
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            msg = data["choices"][0]["message"]
            return (msg.get("content") or msg.get("reasoning_content") or "").strip()
    except Exception:
        return ""


def ocr_frame_cli(image_path: Path) -> str:
    """Fallback offline OCR via llama-mtmd-cli."""
    cli = Path(os.environ.get("LLAMA_MTMD_CLI", DRIVE / "llama.cpp/build/bin/llama-mtmd-cli"))
    model = Path(os.environ.get(
        "LIGHTON_MODEL",
        DRIVE / "models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.Q4_K_M.gguf",
    ))
    mmproj = Path(os.environ.get(
        "LIGHTON_MMPROJ",
        DRIVE / "models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.mmproj-q8_0.gguf",
    ))
    if not (cli.is_file() and model.is_file() and mmproj.is_file()):
        return ""
    cmd = [
        str(cli),
        "-m", str(model),
        "--mmproj", str(mmproj),
        "--image", str(image_path),
        "-p", "Extract all diagram labels, text, and architecture flow in markdown.",
        "-n", "300", "-ngl", "99", "--temp", "0.1"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        lines = res.stdout.splitlines()
        content: List[str] = []
        started = False
        for line in lines:
            if started:
                content.append(line)
            elif line.startswith("system_info:") or line.startswith("llama_perf_"):
                continue
            elif not line.startswith("llama_") and not line.startswith("load_"):
                started = True
                content.append(line)
        return "\n".join(content).strip()
    return ""


def ocr_frame(image_path: Path, allow_cli_fallback: bool = False) -> str:
    """Smart OCR: Uses fast HTTP API if live; only uses slow CLI if explicitly enabled."""
    if is_ocr_server_online():
        text = ocr_frame_http(image_path)
        if text:
            return text
    if allow_cli_fallback:
        return ocr_frame_cli(image_path)
    return ""


def format_words_to_transcript(words_json_path: Path) -> str:
    """Format audiocpp word-level timestamps into readable, timestamped markdown paragraphs."""
    try:
        words = json.loads(words_json_path.read_text(encoding="utf-8"))
        if not words:
            return ""
        blocks = []
        cur_words = []
        cur_start = None

        for w in words:
            start_sec = w.get("start_sample", 0) / 16000.0
            if cur_start is None:
                cur_start = start_sec
            cur_words.append(w.get("word", ""))
            if (start_sec - cur_start >= 15.0 and w.get("word", "").endswith((".", "!", "?"))) or (start_sec - cur_start >= 25.0):
                m = int(cur_start // 60)
                s = int(cur_start % 60)
                blocks.append(f"**[{m:02d}:{s:02d}]** " + " ".join(cur_words))
                cur_words = []
                cur_start = None

        if cur_words:
            m = int(cur_start // 60)
            s = int(cur_start % 60)
            blocks.append(f"**[{m:02d}:{s:02d}]** " + " ".join(cur_words))

        return "\n\n".join(blocks) + "\n"
    except Exception:
        return ""


def parse_vtt_to_transcript(vtt_file: Path) -> str:
    """Parse VTT/SRT subtitle file into timestamped markdown blocks grouped by ~15-25s."""
    try:
        if not vtt_file.is_file():
            return ""
        lines = vtt_file.read_text(encoding="utf-8", errors="replace").splitlines()
        cues: List[tuple[int, str]] = []
        ts_pattern = re.compile(r'(?:(\d{1,2}):)?(\d{2}):(\d{2})\.\d{3}\s+-->')

        cur_start_sec: Optional[int] = None
        cur_text_lines: List[str] = []

        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")) or line_str.isdigit():
                continue
            m = ts_pattern.search(line_str)
            if m:
                if cur_start_sec is not None and cur_text_lines:
                    text_block = " ".join(cur_text_lines).strip()
                    if text_block:
                        cues.append((cur_start_sec, text_block))
                    cur_text_lines = []
                hours = int(m.group(1)) if m.group(1) else 0
                mins = int(m.group(2))
                secs = int(m.group(3))
                cur_start_sec = hours * 3600 + mins * 60 + secs
            else:
                cleaned = re.sub(r'<[^>]+>', '', line_str).strip()
                if cleaned and (not cur_text_lines or cur_text_lines[-1] != cleaned):
                    cur_text_lines.append(cleaned)

        if cur_start_sec is not None and cur_text_lines:
            text_block = " ".join(cur_text_lines).strip()
            if text_block:
                cues.append((cur_start_sec, text_block))

        if not cues:
            return ""

        blocks: List[str] = []
        cur_chunk_start: Optional[int] = None
        cur_chunk_text: List[str] = []

        for start_sec, text in cues:
            if cur_chunk_start is None:
                cur_chunk_start = start_sec
            cur_chunk_text.append(text)

            elapsed = start_sec - cur_chunk_start
            if (elapsed >= 15.0 and text.endswith((".", "!", "?"))) or elapsed >= 30.0:
                m = int(cur_chunk_start // 60)
                s = int(cur_chunk_start % 60)
                blocks.append(f"**[{m:02d}:{s:02d}]** " + " ".join(cur_chunk_text))
                cur_chunk_start = None
                cur_chunk_text = []

        if cur_chunk_text and cur_chunk_start is not None:
            m = int(cur_chunk_start // 60)
            s = int(cur_chunk_start % 60)
            blocks.append(f"**[{m:02d}:{s:02d}]** " + " ".join(cur_chunk_text))

        return "\n\n".join(blocks) + "\n"
    except Exception:
        return ""


def update_vault_index(vault_dir: Path) -> None:
    index_file = vault_dir / "INDEX.md"
    rows: List[str] = []
    if not vault_dir.is_dir():
        return
    for creator_dir in sorted(vault_dir.iterdir()):
        if not creator_dir.is_dir() or creator_dir.name.startswith("."):
            continue
        for entry_dir in sorted(creator_dir.iterdir(), reverse=True):
            if not entry_dir.is_dir():
                continue
            notes_file = entry_dir / "notes.md"
            transcript_file = entry_dir / "transcript.md"
            visuals_dir = entry_dir / "visuals"
            num_visuals = len(list(visuals_dir.glob("*.jpg"))) if visuals_dir.is_dir() else 0
            has_notes = "✅" if notes_file.is_file() else "❌"
            has_transcript = "✅" if transcript_file.is_file() else "❌"
            rel_path = f"{creator_dir.name}/{entry_dir.name}/notes.md"
            rows.append(f"| {entry_dir.name[:10]} | `{creator_dir.name}` | [{entry_dir.name[11:]}]({rel_path}) | {has_transcript} | {num_visuals} frames | {has_notes} |")

    header = "# Creator Video Vault Index\n\nCurated archive of mined engineering videos, architectural diagrams, and full transcripts.\n\n"
    table_header = "| Date | Creator | Title | Transcript | Visuals | Notes |\n| :--- | :--- | :--- | :---: | :---: | :---: |\n"
    index_file.write_text(header + table_header + "\n".join(rows) + "\n", encoding="utf-8")



def dhash(img: Any, hash_size: int = 8) -> List[bool]:
    img = img.convert("L").resize((hash_size + 1, hash_size), getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1))
    diff = []
    for row in range(hash_size):
        for col in range(hash_size):
            diff.append(img.getpixel((col, row)) > img.getpixel((col + 1, row)))
    return diff


def hamming_distance(h1: List[bool], h2: List[bool]) -> int:
    return sum(b1 != b2 for b1, b2 in zip(h1, h2))


def update_reels_ledger(vault_dir: Path, reel_id: str, upload_date: str, topic: str, folder_name: str) -> bool:
    ledger_path = vault_dir / "kem_glitch" / "REELS_LEDGER.md"
    if not ledger_path.is_file() or not reel_id:
        return False
    try:
        content = ledger_path.read_text(encoding="utf-8")
        if f"`{reel_id}`" in content:
            return False

        m = re.search(r"\*\*(\d+)\s+verified in the vault\*\*", content)
        if m:
            old_count = int(m.group(1))
            content = content.replace(f"**{old_count} verified in the vault**", f"**{old_count + 1} verified in the vault**")

        today_str = datetime.date.today().strftime("%Y-%m-%d")
        content = re.sub(r"-\s+\*\*Last crawled:\*\*.*", f"- **Last crawled:** {today_str}", content)

        new_entry_header = f"## ✅ Newly mined (1) — {today_str}\n\n| Reel ID | Date | Topic | Vault entry |\n| :--- | :--- | :--- | :--- |\n"
        new_entry_row = f"| `{reel_id}` | {upload_date} | {topic} | ✅ {folder_name} |\n"

        missing_idx = content.find("## ❌ Missing")
        if missing_idx != -1:
            content = content[:missing_idx] + new_entry_header + new_entry_row + "\n" + content[missing_idx:]
        else:
            content += "\n" + new_entry_header + new_entry_row

        ledger_path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        print(f"⚠️ Could not update REELS_LEDGER.md: {e}")
        return False


def update_notes_index(vault_dir: Path) -> None:
    notes_index_bin = shutil.which("notes-index")
    if notes_index_bin:
        try:
            print("🔍 Updating notes-index FTS5 database (fast --no-summaries)...")
            res = subprocess.run([notes_index_bin, "--folder", str(vault_dir), "update", "--no-summaries"],
                                 capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                print("✅ Notes index updated.")
        except Exception:
            pass


def fast_mine_video(
    url_or_path: str,
    creator: Optional[str] = None,
    title: Optional[str] = None,
    vault_dir: Path = DEFAULT_VAULT_DIR,
    run_ocr: str = "auto",  # auto, never, always
    asr_model: str = "crisperwhisper",
    prefer_asr: bool = False,
) -> Path:
    """High-speed single-pass video mining pipeline."""
    t_start = time.perf_counter()
    tmp_scratch = Path(f"/tmp/vault_mine_{int(time.time())}")
    tmp_scratch.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image
    except ImportError:
        Image = None

    try:
        source_mp4 = tmp_scratch / "source.mp4"
        info_json = tmp_scratch / "source.info.json"
        creator_name = creator
        title_name = title
        meta: Dict[str, Any] = {}

        # 1. Acquire video (Single-pass download with info json)
        print(f"📥 [1/4] Acquiring video: {url_or_path}...")
        if Path(url_or_path).is_file():
            shutil.copy2(url_or_path, source_mp4)
            if not title_name:
                title_name = Path(url_or_path).stem
            if not creator_name:
                creator_name = "local"
        else:
            dl_cmd = [
                "yt-dlp",
                "--no-playlist",
                "--write-info-json",
                "--write-subs",
                "--write-auto-subs",
                "--sub-lang", "en.*,en",
                "--sub-format", "vtt/srt",
                "--merge-output-format", "mp4",
                "-o", str(tmp_scratch / "source.%(ext)s"),
                url_or_path
            ]
            res = subprocess.run(dl_cmd, capture_output=True, text=True)
            if res.returncode != 0:
                sys.exit(f"❌ Failed to download video: {res.stderr.strip()[:300]}")

            potential_videos = list(tmp_scratch.glob("source.*"))
            source_candidates = [p for p in potential_videos if p.suffix.lower() in [".mp4", ".mkv", ".webm", ".mov"]]
            if source_candidates:
                source_mp4 = source_candidates[0]
            else:
                sys.exit(f"❌ Could not find downloaded video in {tmp_scratch}")

            for p in tmp_scratch.glob("*.info.json"):
                try:
                    meta = json.loads(p.read_text(encoding="utf-8"))
                    if not creator_name:
                        creator_name = meta.get("uploader") or meta.get("channel") or meta.get("uploader_id") or "creator"
                    raw_title = meta.get("fulltitle") or meta.get("title") or ""
                    desc = meta.get("description") or ""
                    desc_lines = [l.strip() for l in desc.splitlines() if l.strip() and not l.strip().startswith(("#", "@"))]
                    if desc_lines and (not raw_title or raw_title.lower().startswith(("video by", "reel by", "post by")) or raw_title.lower() == "video"):
                        title_name = desc_lines[0]
                    else:
                        title_name = raw_title or (desc_lines[0] if desc_lines else "video")
                    break
                except Exception:
                    pass

        creator_name = creator_name or "creator"
        if "glitch" in creator_name.lower() or "kem" in creator_name.lower() or "kem_glitch" in url_or_path:
            creator_name = "kem_glitch"
        title_name = title_name or "video"

        raw_upload_date = meta.get("upload_date")
        if raw_upload_date and len(str(raw_upload_date)) == 8:
            date_str = f"{raw_upload_date[:4]}-{raw_upload_date[4:6]}-{raw_upload_date[6:]}"
        else:
            date_str = datetime.date.today().strftime("%Y-%m-%d")

        creator_slug = slugify(creator_name)
        title_slug = slugify(title_name)
        target_dir = vault_dir / creator_slug / f"{date_str}_{title_slug}"
        visuals_dir = target_dir / "visuals"
        target_dir.mkdir(parents=True, exist_ok=True)
        visuals_dir.mkdir(parents=True, exist_ok=True)

        dest_video = target_dir / "source.mp4"
        shutil.copy2(str(source_mp4), str(dest_video))
        source_mp4.unlink(missing_ok=True)

        # 2. Extract Transcript (Subtitles first, fallback to audiocpp ASR)
        vtt_candidates = list(tmp_scratch.glob("*.vtt")) + list(tmp_scratch.glob("*.srt"))
        transcript_body = ""
        if vtt_candidates and not prefer_asr:
            print(f"📄 Found downloaded subtitles ({vtt_candidates[0].name}), parsing directly...")
            vtt_parsed = parse_vtt_to_transcript(vtt_candidates[0])
            if vtt_parsed:
                transcript_body = vtt_parsed
        elif vtt_candidates:
            print(f"📄 Ignoring downloaded subtitles ({vtt_candidates[0].name}) - prefer_asr is set")

        if not transcript_body:
            print(f"🎙️ [2/4] Extracting audio and transcribing with {asr_model} via audiocpp...")
            audio_wav = tmp_scratch / "audio.wav"
            ffmpeg_audio = [
                "ffmpeg", "-y", "-i", str(dest_video),
                "-vn", "-ar", "16000", "-ac", "1",
                "-c:a", "pcm_s16le", str(audio_wav)
            ]
            subprocess.run(ffmpeg_audio, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

            words_json = tmp_scratch / "words.json"
            transcript_raw = tmp_scratch / "transcript.txt"

            audiocpp_cli = shutil.which("audiocpp") or next(
                (str(p) for p in (
                    DRIVE / "skills/audiocpp/scripts/audiocpp_cli.py",
                    DRIVE / "skills/hardware/audiocpp/scripts/audiocpp_cli.py",
                ) if p.is_file()),
                str(DRIVE / "skills/audiocpp/scripts/audiocpp_cli.py"),
            )
            cmd_asr = [
                "audiocpp" if shutil.which("audiocpp") else sys.executable,
            ]
            if not shutil.which("audiocpp"):
                cmd_asr.append(audiocpp_cli)
            cmd_asr.extend([
                "transcribe", str(audio_wav),
                "--model", asr_model,
                "--words-out", str(words_json),
                "--out", str(transcript_raw),
                "--metrics"
            ])

            subprocess.run(cmd_asr, capture_output=True, text=True)
            if words_json.is_file():
                formatted = format_words_to_transcript(words_json)
                if formatted:
                    transcript_body = formatted
            if not transcript_body and transcript_raw.is_file():
                transcript_body = transcript_raw.read_text(encoding="utf-8")

        duration_sec = meta.get("duration") or 0
        dur_m, dur_s = divmod(int(duration_sec), 60)
        dur_str = f"{dur_m:02d}:{dur_s:02d}" if duration_sec else "N/A"
        web_url = meta.get("webpage_url") or url_or_path

        full_transcript = (
            f"# Transcript — {title_name}\n\n"
            f"- **Reel:** `{web_url}`\n"
            f"- **Creator:** `{creator_name}`\n"
            f"- **Duration:** {dur_str}\n"
            f"- **Upload Date:** {date_str}\n"
            f"- **Method:** audio extracted with `yt-dlp`, transcribed by `{asr_model}` through `audiocpp`.\n\n"
            f"---\n\n"
            + (transcript_body if transcript_body else "_No audio transcript captured._")
            + "\n"
        )
        (target_dir / "transcript.md").write_text(full_transcript, encoding="utf-8")

        # 3. Fast Keyframe Sampling (0.5 fps + In-Memory dHash Hamming Dedup)
        print("🖼️ [3/4] Extracting and deduplicating visual frames (dHash)...")
        sample_tmp = tmp_scratch / "raw_frames"
        sample_tmp.mkdir(parents=True, exist_ok=True)
        ffmpeg_frames = [
            "ffmpeg", "-y", "-i", str(dest_video),
            "-vf", "fps=1/2",
            "-fps_mode", "vfr",
            "-pix_fmt", "yuvj420p",
            "-q:v", "2",
            str(sample_tmp / "frame_%04d.jpg")
        ]
        subprocess.run(ffmpeg_frames, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        raw_frames = sorted(list(sample_tmp.glob("frame_*.jpg")))
        captured_frames: List[Path] = []

        if raw_frames and Image is not None:
            try:
                last_h = dhash(Image.open(raw_frames[0]))
                dst_first = visuals_dir / "t000.jpg"
                shutil.copy2(str(raw_frames[0]), str(dst_first))
                captured_frames.append(dst_first)

                for rf in raw_frames[1:]:
                    num = int(rf.stem.replace("frame_", ""))
                    sec = (num - 1) * 2
                    cur_img = Image.open(rf)
                    cur_h = dhash(cur_img)
                    if hamming_distance(last_h, cur_h) >= 10:
                        dst = visuals_dir / f"t{sec:03d}.jpg"
                        shutil.copy2(str(rf), str(dst))
                        captured_frames.append(dst)
                        last_h = cur_h
            except Exception as e:
                print(f"⚠️ dHash filtering encountered: {e}, falling back to direct copy")
                captured_frames = []

        if not captured_frames and raw_frames:
            for idx, rf in enumerate(raw_frames):
                dst = visuals_dir / f"frame_{idx:06d}.jpg"
                shutil.copy2(str(rf), str(dst))
                captured_frames.append(dst)

        # 4. Smart Notes Generation
        print("📝 [4/4] Generating structured vault notes...")
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        should_ocr = False
        allow_cli = False
        if run_ocr == "always":
            should_ocr = True
            allow_cli = True
        elif run_ocr == "auto":
            should_ocr = is_ocr_server_online()

        caption = (meta.get("description") or "").replace("\n", " ").strip()
        likes = meta.get("like_count") or 0
        comments = meta.get("comment_count") or 0
        reel_id = meta.get("id") or ""

        if creator_slug == "kem_glitch":
            notes_lines = [
                f"# {title_name}",
                "",
                f"- **Creator:** `kem_glitch` (Glitch Cat Club)",
                f"- **Upload Date:** {date_str}",
                f"- **Mined Date:** {today_str}",
                f"- **Source:** [source.mp4](source.mp4)",
                f"- **Transcript:** [transcript.md](transcript.md)",
                f"- **Captured Visuals:** {len(captured_frames)} frames in [visuals/](visuals/)",
                f"- **Instagram Reel:** `{web_url}`",
                f"- **Duration:** {dur_str}",
                f"- **Caption:** *\"{caption}\"*",
                f"- **Engagement at capture:** {likes} likes · {comments} comments",
                f"- **Feeds:** `kem-thought`",
                "",
                "---",
                "",
                "## Provenance",
                "",
                "**Shown in the reel** — verbatim from [transcript.md](transcript.md); ellipses mark omitted words.",
                "",
                "| Claim | Quote | Time |",
                "| :--- | :--- | :---: |",
                "| Core Thesis | \"...\" | 00:00 |",
                "",
                "**Modeled in this note** — our synthesis, not his literal words.",
                "",
                "| Choice | Why it is not in the reel |",
                "| :--- | :--- |",
                "| Architectural Framing | Structured for cognitive retrieval and agent skill synthesis |",
                "",
                "---",
                "",
                "## 🎯 Executive Architectural Synthesis",
                "",
                "*(Synthesize key architectural patterns, principles, and trade-offs from the transcript here)*",
                "",
            ]
        else:
            notes_lines = [
                f"# {title_name}",
                "",
                f"- **Creator:** `{creator_name}`",
                f"- **Mined Date:** {today_str}",
                f"- **Source:** [source.mp4](source.mp4)",
                f"- **Transcript:** [transcript.md](transcript.md)",
                f"- **Captured Visuals:** {len(captured_frames)} frames in [visuals/](visuals/)",
                "",
                "## Key Visuals & Diagrams",
                "",
            ]

        if captured_frames and creator_slug != "kem_glitch":
            step = max(1, len(captured_frames) // 4)
            sample_frames = captured_frames[::step][:4]
            for cf in sample_frames:
                notes_lines.append(f"### Visual: `{cf.name}`\n")
                notes_lines.append(f"![{cf.name}](visuals/{cf.name})\n")
                if should_ocr:
                    ocr_res = ocr_frame(cf, allow_cli_fallback=allow_cli)
                    if ocr_res:
                        notes_lines.append("```markdown")
                        notes_lines.append(ocr_res)
                        notes_lines.append("```\n")

            notes_lines.extend([
                "## Full Audio Transcript",
                "",
                transcript_body if transcript_body else "_No audio transcript captured._",
                "",
            ])

        (target_dir / "notes.md").write_text("\n".join(notes_lines), encoding="utf-8")

        # 5. Ledger & Index Updates
        if creator_slug == "kem_glitch":
            ledger_updated = update_reels_ledger(vault_dir, reel_id, date_str, title_name, target_dir.name)
            if ledger_updated:
                print(f"📖 Appended `{reel_id}` to REELS_LEDGER.md")

        update_vault_index(vault_dir)
        update_notes_index(vault_dir)

        elapsed = time.perf_counter() - t_start
        print(f"\n⚡ Done in {elapsed:.1f}s! Vaulted to: {target_dir}")
        print(f"   📁 Target: {target_dir}")
        print(f"   🎙️ Transcript: {target_dir / "transcript.md"}")
        print(f"   🖼️ Visuals: {len(captured_frames)} frames in {visuals_dir}")
        return target_dir

    finally:
        shutil.rmtree(tmp_scratch, ignore_errors=True)


def import_workspace(workspace_dir: Path, creator: str, title: str, vault_dir: Path = DEFAULT_VAULT_DIR, run_ocr: bool = True) -> Path:
    ws = Path(workspace_dir).resolve()
    creator_slug = slugify(creator)
    title_slug = slugify(title)
    date_str = datetime.date.today().strftime("%Y-%m-%d")

    target_dir = vault_dir / creator_slug / f"{date_str}_{title_slug}"
    visuals_dir = target_dir / "visuals"
    target_dir.mkdir(parents=True, exist_ok=True)
    visuals_dir.mkdir(parents=True, exist_ok=True)

    src_video = ws / "stages/01_acquire/output/source_video.mp4"
    if src_video.is_file():
        shutil.copy2(src_video, target_dir / "source.mp4")

    src_transcript = ws / "stages/02_audio_asr/output/transcript.md"
    if src_transcript.is_file():
        shutil.copy2(src_transcript, target_dir / "transcript.md")

    frames_dir = ws / "stages/03_visual_sample/output/frames"
    copied_frames: List[Path] = []
    if frames_dir.is_dir():
        for f in sorted(frames_dir.glob("*.jpg")):
            dst = visuals_dir / f.name
            shutil.copy2(f, dst)
            copied_frames.append(dst)

    transcript_content = (target_dir / "transcript.md").read_text(encoding="utf-8") if (target_dir / "transcript.md").is_file() else ""

    notes_lines = [
        f"# {title}",
        "",
        f"- **Creator:** `{creator}`",
        f"- **Mined Date:** {date_str}",
        f"- **Source:** [source.mp4](source.mp4)",
        f"- **Transcript:** [transcript.md](transcript.md)",
        f"- **Captured Visuals:** {len(copied_frames)} frames",
        "",
        "## Key Visuals & Diagrams",
        "",
    ]

    for cf in copied_frames[:4]:
        notes_lines.append(f"### Visual: `{cf.name}`\n")
        notes_lines.append(f"![{cf.name}](visuals/{cf.name})\n")
        if run_ocr and is_ocr_server_online():
            ocr_text = ocr_frame_http(cf)
            if ocr_text:
                notes_lines.append("```markdown")
                notes_lines.append(ocr_text)
                notes_lines.append("```\n")

    notes_lines.extend([
        "## Full Audio Transcript",
        "",
        transcript_content if transcript_content else "_No transcript extracted._",
        "",
    ])

    (target_dir / "notes.md").write_text("\n".join(notes_lines), encoding="utf-8")
    update_vault_index(vault_dir)
    return target_dir


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


def list_vault_videos(vault_dir: Path, creator_filter: str | None = None, limit: int = 0) -> list[dict]:
    items = []
    if not vault_dir.is_dir():
        return items
    for creator_dir in sorted(vault_dir.iterdir()):
        if not creator_dir.is_dir() or creator_dir.name.startswith("."):
            continue
        if creator_filter and creator_dir.name.lower() != creator_filter.lower():
            continue
        for entry_dir in sorted(creator_dir.iterdir(), reverse=True):
            if not entry_dir.is_dir():
                continue
            date_str = entry_dir.name[:10]
            title_slug = entry_dir.name[11:]
            notes_file = entry_dir / "notes.md"
            transcript_file = entry_dir / "transcript.md"
            visuals_dir = entry_dir / "visuals"
            num_visuals = len(list(visuals_dir.glob("*.jpg"))) if visuals_dir.is_dir() else 0
            items.append({
                "date": date_str,
                "creator": creator_dir.name,
                "title": title_slug,
                "has_notes": "yes" if notes_file.is_file() else "no",
                "has_transcript": "yes" if transcript_file.is_file() else "no",
                "visuals": num_visuals,
                "path": str(notes_file if notes_file.is_file() else entry_dir)
            })
    if limit and limit > 0:
        items = items[:limit]
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="High-speed video mining and archiving into Creator Video Vault.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # 1. add
    p_add = sub.add_parser("add", help="Mine a video URL or local file directly into the vault (fast single pass)")
    p_add.add_argument("url", help="URL or path to video")
    p_add.add_argument("--creator", help="Creator name / handle")
    p_add.add_argument("--title", help="Video title or slug")
    p_add.add_argument("--vault-dir", default=str(DEFAULT_VAULT_DIR), help="Path to vault root")
    p_add.add_argument("--ocr", choices=["auto", "never", "always"], default="auto", help="OCR mode: auto (if :8085 live), never, or always")
    p_add.add_argument("--model", "-m", default="crisperwhisper", help="ASR model slug (crisperwhisper [default], nemotron)")
    p_add.add_argument("--prefer-asr", action="store_true",
                       help="transcribe locally even when a subtitle track exists "
                            "(YouTube auto-captions repeat each line three times)")

    # 2. import
    p_import = sub.add_parser("import", help="Import an existing videomine ICM workspace into the vault")
    p_import.add_argument("workspace", help="Path to videomine workspace")
    p_import.add_argument("--creator", required=True, help="Creator name")
    p_import.add_argument("--title", required=True, help="Video title")
    p_import.add_argument("--vault-dir", default=str(DEFAULT_VAULT_DIR), help="Path to vault root")

    # 3. list
    p_list = sub.add_parser("list", help="List vaulted videos in a high-density table")
    p_list.add_argument("--creator", help="Filter by creator name")
    p_list.add_argument("--table", "-t", action="store_true", default=True, help="Render as Markdown table")
    p_list.add_argument("--limit", "-n", type=int, default=0, help="Cap number of rows")
    p_list.add_argument("--json", action="store_true", help="Render as JSON")
    p_list.add_argument("--vault-dir", default=str(DEFAULT_VAULT_DIR), help="Path to vault root")

    # 4. reindex
    p_reindex = sub.add_parser("reindex", help="Rebuild vault INDEX.md")
    p_reindex.add_argument("--vault-dir", default=str(DEFAULT_VAULT_DIR), help="Path to vault root")

    # 5. kem
    p_kem = sub.add_parser("kem", help="Mine a Kem Glitch reel directly into the vault (automatic metadata, dHash dedup, ledger, FTS)")
    p_kem.add_argument("url", help="Instagram or YouTube URL of the reel")
    p_kem.add_argument("--vault-dir", default=str(DEFAULT_VAULT_DIR), help="Path to vault root")
    p_kem.add_argument("--ocr", choices=["auto", "never", "always"], default="auto", help="OCR mode: auto (if :8085 live), never, or always")
    p_kem.add_argument("--model", "-m", default="crisperwhisper", help="ASR model slug (crisperwhisper [default], nemotron)")
    p_kem.add_argument("--prefer-asr", action="store_true",
                       help="transcribe locally even when a subtitle track exists")

    args = parser.parse_args()
    v_dir = Path(args.vault_dir)
    v_dir.mkdir(parents=True, exist_ok=True)

    if args.cmd == "add":
        dest = fast_mine_video(
            args.url,
            creator=args.creator,
            title=args.title,
            vault_dir=v_dir,
            run_ocr=args.ocr,
            asr_model=args.model,
            prefer_asr=args.prefer_asr,
        )
        return 0
    elif args.cmd == "kem":
        dest = fast_mine_video(
            args.url,
            creator="kem_glitch",
            vault_dir=v_dir,
            run_ocr=args.ocr,
            asr_model=args.model,
            prefer_asr=args.prefer_asr,
        )
        return 0
    elif args.cmd == "import":
        dest = import_workspace(Path(args.workspace), creator=args.creator, title=args.title, vault_dir=v_dir)
        print(f"✅ Successfully imported workspace to: {dest}")
        return 0
    elif args.cmd == "list":
        rows = list_vault_videos(v_dir, creator_filter=args.creator, limit=args.limit)
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            cols = ["date", "creator", "title", "has_notes", "visuals"]
            print(f"### Creator Vault: {v_dir}\n")
            print(render_table(rows, cols))
        return 0
    elif args.cmd == "reindex":
        update_vault_index(v_dir)
        print(f"✅ Updated vault index: {v_dir / 'INDEX.md'}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
