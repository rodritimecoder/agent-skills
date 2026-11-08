#!/usr/bin/env python3
"""
zoom_download.py - Download transcripts, audio, and keyframes from Zoom cloud recordings.

Features:
- Public and password-protected Zoom cloud recordings (utsmeet.zoom.us, *.zoom.us).
- Unwraps Mimecast and Microsoft SafeLinks protection URLs.
- Password validation without requiring Zoom OAuth / Developer Admin credentials.
- Automatic extraction and formatting of transcripts (VTT, TXT, Markdown).
- High-density transcript outline/agenda extraction (--outline / --agenda).
- Selective keyframe extraction using ffmpeg without downloading the entire video.
- Token shielding: --table (-t), --project, --limit (-n), --info-only, and structured receipts.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
try:
    import requests
except ImportError:
    requests = None


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X-11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def unwrap_protected_url(raw_url: str) -> str:
    """Unwrap Mimecast, Outlook Safelinks, or direct URL."""
    url = raw_url.strip()

    # Outlook Safelinks
    if "protection.outlook.com" in url and "url=" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "url" in qs:
            return unwrap_protected_url(qs["url"][0])

    # Mimecast protection URL
    if "mimecastprotect.com" in url and "domain=" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "domain" in qs:
            return unwrap_protected_url(qs["domain"][0])

    return url


def parse_time_str(ts: str) -> float:
    """Convert timestamp 'HH:MM:SS.mmm' or 'MM:SS.mmm' to seconds."""
    parts = ts.strip().split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def format_seconds(secs: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    secs = int(round(secs))
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_duration(secs: float) -> str:
    """Format seconds into human duration (e.g., '1h 14m 20s' or '45s')."""
    secs = int(round(secs))
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    parts = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0:
        parts.append(f"{m}m")
    if s > 0 or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


def parse_vtt_cues(vtt_text: str) -> List[Dict[str, Any]]:
    """Parse WebVTT into structured cues: start_sec, end_sec, speaker, text."""
    lines = vtt_text.strip().splitlines()
    timestamp_re = re.compile(
        r"(\d{2}:\d{2}:\d{2}(?:\.\d{3})?|\d{2}:\d{2}(?:\.\d{3})?)\s*-->\s*(\d{2}:\d{2}:\d{2}(?:\.\d{3})?|\d{2}:\d{2}(?:\.\d{3})?)"
    )
    voice_tag_re = re.compile(r"^<v\s+([^>]+)>(.*?)(?:</v>)?$", re.DOTALL)
    tag_strip_re = re.compile(r"<[^>]+>")

    cues = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("WEBVTT") or line.isdigit():
            continue

        m_time = timestamp_re.search(line)
        if m_time:
            start_sec = parse_time_str(m_time.group(1))
            end_sec = parse_time_str(m_time.group(2))

            text_lines = []
            while i < len(lines) and lines[i].strip() and not timestamp_re.search(lines[i]):
                text_lines.append(lines[i].strip())
                i += 1

            raw_text = " ".join(text_lines).strip()
            speaker = ""
            vm = voice_tag_re.match(raw_text)
            if vm:
                speaker = vm.group(1).strip()
                raw_text = vm.group(2).strip()
            elif ":" in raw_text:
                parts = raw_text.split(":", 1)
                if len(parts[0]) < 40 and not any(p in parts[0] for p in ["http", "www", "/"]):
                    speaker = parts[0].strip()
                    raw_text = parts[1].strip()

            clean_text = tag_strip_re.sub("", raw_text).strip()
            if clean_text:
                cues.append({
                    "start": start_sec,
                    "end": end_sec,
                    "speaker": speaker,
                    "text": clean_text
                })
    return cues


def build_vtt_outline(cues: List[Dict[str, Any]], pause_threshold: float = 20.0, monologue_threshold: float = 300.0) -> Dict[str, Any]:
    """Group cues into structured outline blocks with speaker stats and topic snippets."""
    if not cues:
        return {
            "total_duration": "0s",
            "total_duration_seconds": 0,
            "total_words": 0,
            "speakers": {},
            "entries": []
        }

    total_start = cues[0]["start"]
    total_end = cues[-1]["end"]
    total_duration_sec = max(0.0, total_end - total_start)
    speaker_counts: Dict[str, int] = {}

    entries = []
    curr_speaker = cues[0]["speaker"]
    curr_start = cues[0]["start"]
    curr_end = cues[0]["end"]
    curr_text_parts = [cues[0]["text"]]

    def flush_entry():
        nonlocal curr_start, curr_end, curr_speaker, curr_text_parts
        if not curr_text_parts:
            return
        full_text = " ".join(curr_text_parts).strip()
        words = len(full_text.split())
        spk = curr_speaker or "Speaker"
        speaker_counts[spk] = speaker_counts.get(spk, 0) + words

        preview = full_text[:95].rsplit(" ", 1)[0] if len(full_text) > 95 else full_text
        if len(full_text) > len(preview):
            preview += "..."

        entries.append({
            "time": format_seconds(curr_start),
            "speaker": spk,
            "duration": format_duration(curr_end - curr_start),
            "words": words,
            "preview": preview
        })
        curr_text_parts = []

    for cue in cues[1:]:
        speaker_change = bool(cue["speaker"] and cue["speaker"] != curr_speaker)
        pause_gap = (cue["start"] - curr_end) >= pause_threshold
        monologue_limit = (cue["end"] - curr_start) >= monologue_threshold

        if speaker_change or pause_gap or monologue_limit:
            flush_entry()
            curr_speaker = cue["speaker"]
            curr_start = cue["start"]
            curr_end = cue["end"]
            curr_text_parts = [cue["text"]]
        else:
            curr_end = cue["end"]
            curr_text_parts.append(cue["text"])

    flush_entry()
    total_words = sum(e["words"] for e in entries)

    return {
        "total_duration": format_duration(total_duration_sec),
        "total_duration_seconds": int(round(total_duration_sec)),
        "total_words": total_words,
        "speakers": speaker_counts,
        "entries": entries
    }


def parse_vtt_to_markdown(vtt_text: str, title: str = "Recording Transcript") -> str:
    """Convert WebVTT transcript to clean readable Markdown notes format."""
    lines = vtt_text.strip().splitlines()
    md_lines = [f"# {title}", "", "> Extracted automatically from Zoom Cloud Recording.", ""]

    timestamp_re = re.compile(
        r"(\d{2}:\d{2}:\d{2}(?:\.\d{3})?|\d{2}:\d{2}(?:\.\d{3})?)\s*-->\s*(\d{2}:\d{2}:\d{2}(?:\.\d{3})?|\d{2}:\d{2}(?:\.\d{3})?)"
    )

    current_speaker = None
    current_time = ""
    current_text_buf: List[str] = []

    def flush_block():
        nonlocal current_speaker, current_time, current_text_buf
        if current_text_buf:
            text = " ".join(current_text_buf).strip()
            if text:
                speaker_prefix = f"**{current_speaker}**" if current_speaker else "**Speaker**"
                md_lines.append(f"- `[{current_time}]` {speaker_prefix}: {text}")
            current_text_buf = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line or line.startswith("WEBVTT") or line.isdigit():
            continue

        m_time = timestamp_re.search(line)
        if m_time:
            flush_block()
            current_time = m_time.group(1).split(".")[0]
            continue

        if ":" in line:
            parts = line.split(":", 1)
            if len(parts[0]) < 40 and not any(p in parts[0] for p in ["http", "www", "/"]):
                flush_block()
                current_speaker = parts[0].strip()
                current_text_buf.append(parts[1].strip())
                continue

        current_text_buf.append(line)

    flush_block()
    return "\n".join(md_lines) + "\n"


def render_table(rows: List[Dict[str, Any]], columns: List[str], headers: Optional[List[str]] = None) -> str:
    """Render a list of dictionaries as a Markdown pipe table."""
    if not rows:
        return "*(no records)*\n"
    if headers is None:
        headers = [col.replace("_", " ").title() for col in columns]
    col_widths = [len(h) for h in headers]
    for r in rows:
        for idx, col in enumerate(columns):
            val_str = str(r.get(col, "")).replace("\n", " ")
            if len(val_str) > col_widths[idx]:
                col_widths[idx] = len(val_str)

    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * col_widths[i] for i in range(len(headers))) + " |"
    row_lines = []
    for r in rows:
        row_str = "| " + " | ".join(str(r.get(col, "")).replace("\n", " ").ljust(col_widths[i]) for i, col in enumerate(columns)) + " |"
        row_lines.append(row_str)
    return "\n".join([header_line, sep_line] + row_lines) + "\n"


def render_kv_table(data: Dict[str, Any], project_keys: Optional[List[str]] = None) -> str:
    """Render key-value dict as a 2-column Property/Value Markdown table."""
    items = []
    for k, v in data.items():
        if project_keys and k.lower() not in project_keys:
            continue
        label = k.replace("_", " ").title()
        items.append({"property": label, "value": str(v)})
    return render_table(items, ["property", "value"], ["Property", "Value"])


class ZoomRecorderClient:
    def __init__(self, session: Optional[Any] = None):
        if requests is None:
            raise RuntimeError("The 'requests' package is required for downloading zoom recordings: pip install requests")
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "*/*",
        })

    def get_recording_info(self, zoom_url: str, passcode: Optional[str] = None) -> Dict[str, Any]:
        """Unlocks and retrieves complete recording info, play links, and transcript URLs."""
        unwrapped = unwrap_protected_url(zoom_url)
        parsed = urllib.parse.urlparse(unwrapped)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        self.session.headers.update({"Referer": unwrapped})
        resp = self.session.get(unwrapped)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to access URL: HTTP {resp.status_code}")

        is_share = "/rec/share/" in unwrapped or "/rec/share" in parsed.path

        meeting_id_match = re.search(r'meetingId:\s*[\'"]([^\'"]+)[\'"]', resp.text)
        if not meeting_id_match:
            meeting_id_match = re.search(r'\"meetingId\":\s*\"([^\"]+)\"', resp.text)

        meeting_id = meeting_id_match.group(1) if meeting_id_match else ""

        if is_share:
            share_info_url = f"{base_url}/nws/recording/1.0/play/share-info/{meeting_id}"
            share_info_resp = self.session.get(share_info_url).json()
            if not share_info_resp.get("status"):
                raise RuntimeError(f"Share info error: {share_info_resp.get('errorMessage')}")

            result = share_info_resp.get("result", {})
            need_password = result.get("componentName") == "need-password" or (
                result.get("needRedirect") and "need-password" in result.get("redirectUrl", "")
            )

            if need_password:
                if not passcode:
                    raise ValueError("Recording requires a passcode. Provide --passcode <passcode>")

                target_meeting_id = result.get("meetingId") or meeting_id

                ctx_url = f"{base_url}/nws/recording/1.0/validate-context"
                ctx_payload = {
                    "meetingId": target_meeting_id,
                    "fileId": "",
                    "useWhichPasswd": "meeting",
                    "sharelevel": "meeting",
                    "iet": "",
                }
                ctx_res = self.session.post(ctx_url, data=ctx_payload).json()
                encrypt_meet_id = ctx_res.get("result", {}).get("encryptMeetId", target_meeting_id)

                val_url = f"{base_url}/nws/recording/1.0/validate-meeting-passwd"
                val_payload = {
                    "id": encrypt_meet_id,
                    "passwd": passcode.strip(),
                    "action": "viewdetailpage",
                    "recaptcha": "",
                }
                val_res = self.session.post(val_url, data=val_payload).json()
                if not val_res.get("status"):
                    raise RuntimeError(f"Passcode rejected: {val_res.get('errorMessage', 'Incorrect passcode')}")

                share_info_resp = self.session.get(share_info_url).json()
                result = share_info_resp.get("result", {})

            redirect_url = result.get("redirectUrl", "")
            if not redirect_url:
                raise RuntimeError("Could not retrieve playback redirect URL from share info.")
            play_url = urllib.parse.urljoin(base_url, redirect_url)
            play_resp = self.session.get(play_url)
        else:
            play_resp = resp
            play_url = unwrapped

        file_id_match = re.search(r'fileId:\s*[\'"]([^\'"]*)[\'"]', play_resp.text)
        if not file_id_match or not file_id_match.group(1):
            file_id_match = re.search(r'\"fileId\":\s*\"([^\"]+)\"', play_resp.text)

        file_id = file_id_match.group(1) if file_id_match else ""
        if not file_id:
            if "need-password" in play_resp.text and passcode:
                m_meet = re.search(r'meetingId:\s*[\'"]([^\'"]+)[\'"]', play_resp.text)
                if m_meet:
                    ctx_res = self.session.post(f"{base_url}/nws/recording/1.0/validate-context", data={
                        "meetingId": m_meet.group(1),
                        "fileId": "",
                        "useWhichPasswd": "meeting",
                        "sharelevel": "meeting",
                        "iet": ""
                    }).json()
                    enc_id = ctx_res.get("result", {}).get("encryptMeetId", m_meet.group(1))
                    self.session.post(f"{base_url}/nws/recording/1.0/validate-meeting-passwd", data={
                        "id": enc_id,
                        "passwd": passcode.strip(),
                        "action": "viewdetailpage",
                        "recaptcha": ""
                    })
                    play_resp = self.session.get(play_url)
                    file_id_match = re.search(r'fileId:\s*[\'"]([^\'"]*)[\'"]', play_resp.text)
                    file_id = file_id_match.group(1) if file_id_match else ""

        if not file_id:
            raise RuntimeError("Unable to extract playback fileId from Zoom player.")

        info_api_url = f"{base_url}/nws/recording/1.0/play/info/{file_id}?continueMode=true"
        info_res = self.session.get(info_api_url).json()
        if not info_res.get("status"):
            raise RuntimeError(f"Play info API error: {info_res.get('errorMessage')}")

        data = info_res.get("result", {})

        if data.get("componentName") == "need-password" or (data.get("needRedirect") and "need-password" in str(data.get("redirectUrl"))):
            if not passcode:
                raise ValueError("Recording requires a passcode. Provide --passcode <passcode>")
            target_meeting_id = data.get("meetingId") or meeting_id
            ctx_res = self.session.post(f"{base_url}/nws/recording/1.0/validate-context", data={
                "meetingId": target_meeting_id,
                "fileId": "",
                "useWhichPasswd": "meeting",
                "sharelevel": "meeting",
                "iet": "",
            }).json()
            encrypt_meet_id = ctx_res.get("result", {}).get("encryptMeetId", target_meeting_id)
            val_res = self.session.post(f"{base_url}/nws/recording/1.0/validate-meeting-passwd", data={
                "id": encrypt_meet_id,
                "passwd": passcode.strip(),
                "action": "viewdetailpage",
                "recaptcha": "",
            }).json()
            if not val_res.get("status"):
                raise RuntimeError(f"Passcode rejected: {val_res.get('errorMessage', 'Incorrect passcode')}")

            info_res = self.session.get(info_api_url).json()
            data = info_res.get("result", {})

        topic = data.get("meet", {}).get("topic") or "Zoom Cloud Recording"
        duration = data.get("duration", 0)

        transcript_url = None
        if data.get("transcriptUrl"):
            transcript_url = urllib.parse.urljoin(base_url, data["transcriptUrl"])

        video_url = data.get("viewMp4WithshareUrl") or data.get("viewMp4Url") or data.get("shareMp4Url")

        return {
            "topic": topic,
            "duration": duration,
            "duration_str": format_duration(duration),
            "file_id": file_id,
            "has_transcript": data.get("hasTranscript", False),
            "transcript_url": transcript_url,
            "video_url": video_url,
            "raw_result": data,
            "base_url": base_url,
        }

    def fetch_transcript(self, transcript_url: str) -> str:
        """Fetch VTT transcript content."""
        resp = self.session.get(transcript_url)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download transcript: HTTP {resp.status_code}")
        return resp.text

    def download_video(self, video_url: str, output_path: str, chunk_size: int = 1024 * 1024) -> str:
        """Download MP4 video stream to disk."""
        resp = self.session.get(video_url, stream=True)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to stream video: HTTP {resp.status_code}")
        total_size = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        mb_done = downloaded / (1024 * 1024)
                        mb_total = total_size / (1024 * 1024)
                        sys.stdout.write(f"\r[*] Downloading MP4: {mb_done:.1f} MB / {mb_total:.1f} MB ({percent:.1f}%)")
                    else:
                        mb_done = downloaded / (1024 * 1024)
                        sys.stdout.write(f"\r[*] Downloading MP4: {mb_done:.1f} MB")
                    sys.stdout.flush()
        print()
        return output_path

    def extract_keyframes(self, video_url: str, output_dir: str, scene_threshold: float = 0.35, max_frames: int = 50):
        """Extract visual keyframes from video stream using ffmpeg."""
        os.makedirs(output_dir, exist_ok=True)
        out_pattern = os.path.join(output_dir, "slide_%03d.png")
        filter_str = f"select='gt(scene,{scene_threshold})',scale=1280:-1"
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel", "warning",
            "-i", "pipe:0",
            "-vf", filter_str,
            "-vsync", "vfr",
            "-vframes", str(max_frames),
            out_pattern,
        ]
        print(f"[*] Extracting keyframes to {output_dir} via streaming ffmpeg pipeline...")
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            resp = self.session.get(video_url, stream=True)
            for chunk in resp.iter_content(chunk_size=65536):
                try:
                    proc.stdin.write(chunk)
                except (BrokenPipeError, OSError):
                    break
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            proc.wait()
        print("[+] Keyframe extraction complete.")

def main():
    parser = argparse.ArgumentParser(description="Download Zoom recording transcripts and keyframes without full video downloads.")
    parser.add_argument("--url", required=True, help="Zoom recording URL (utsmeet.zoom.us/rec/share/... or /rec/play/...)")
    parser.add_argument("--passcode", "-p", default="", help="Recording passcode if protected")
    parser.add_argument("--out-dir", "-o", default=".", help="Output directory for saved files")
    parser.add_argument("--format", choices=["md", "vtt", "txt", "all"], default="md", help="Transcript format")
    parser.add_argument("--video", action="store_true", help="Download the full MP4 video file")
    parser.add_argument("--keyframes", action="store_true", help="Extract presentation slide keyframes using ffmpeg")
    parser.add_argument("--scene-threshold", type=float, metavar="RATIO", default=0.35, help="Scene change sensitivity for keyframes (0.0 - 1.0)")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument("--table", "-t", action="store_true", help="Output Markdown table format")
    parser.add_argument("--project", default="", help="Comma-separated fields to project in output")
    parser.add_argument("--outline", "--agenda", action="store_true", help="Extract high-density chronological agenda/outline table")
    parser.add_argument("--info-only", "--info", action="store_true", help="Retrieve recording metadata only without downloading files")
    parser.add_argument("--limit", "-n", type=int, metavar="LIMIT", default=0, help="Cap number of outline rows returned")

    args = parser.parse_args()

    client = ZoomRecorderClient()
    try:
        info = client.get_recording_info(args.url, args.passcode)
    except Exception as e:
        print(f"[-] Error retrieving recording info: {e}", file=sys.stderr)
        sys.exit(1)

    project_keys = [k.strip().lower() for k in args.project.split(",") if k.strip()] if args.project else None

    # 1. Info-only mode
    if args.info_only:
        meta_payload = {
            "topic": info["topic"],
            "duration": info["duration_str"],
            "duration_seconds": info["duration"],
            "has_transcript": info["has_transcript"],
            "transcript_url": info["transcript_url"] or "",
            "video_url_available": bool(info["video_url"]),
            "file_id": info["file_id"],
        }
        if project_keys:
            meta_payload = {k: v for k, v in meta_payload.items() if k.lower() in project_keys}

        if args.table or not args.json:
            print(render_kv_table(meta_payload, project_keys))
        else:
            print(json.dumps(meta_payload, indent=2))
        return

    # 2. Outline mode
    if args.outline:
        if not info.get("transcript_url"):
            print("[-] No native transcript available to build outline.", file=sys.stderr)
            sys.exit(1)
        vtt_content = client.fetch_transcript(info["transcript_url"])
        cues = parse_vtt_cues(vtt_content)
        outline = build_vtt_outline(cues)
        entries = outline["entries"]
        if args.limit and args.limit > 0:
            entries = entries[:args.limit]

        cols = ["time", "speaker", "duration", "words", "preview"]
        if project_keys:
            cols = [c for c in cols if c in project_keys]
            if not cols:
                cols = ["time", "speaker", "preview"]

        if args.json:
            out_json = {
                "topic": info["topic"],
                "total_duration": outline["total_duration"],
                "total_words": outline["total_words"],
                "speakers": outline["speakers"],
                "entries": entries,
            }
            if project_keys:
                out_json = {k: v for k, v in out_json.items() if k.lower() in project_keys}
            print(json.dumps(out_json, indent=2))
        else:
            header_summary = (
                f"### Outline: {info['topic']}\n"
                f"- **Duration**: {outline['total_duration']} | **Words**: {outline['total_words']:,} | "
                f"**Speakers**: {', '.join(outline['speakers'].keys())}\n"
            )
            print(header_summary)
            print(render_table(entries, cols))
        return

    # 3. Standard download flow
    os.makedirs(args.out_dir, exist_ok=True)
    slug = re.sub(r'[^a-zA-Z0-9_\-]+', '_', info["topic"]).strip("_") or "zoom_recording"
    saved_files = []

    if info.get("transcript_url"):
        if not (args.json or args.table):
            print(f"[*] Found native Zoom transcript for: {info['topic']}")
        vtt_content = client.fetch_transcript(info["transcript_url"])
        words_count = len(vtt_content.split())

        if args.format in ["vtt", "all"]:
            vtt_path = os.path.join(args.out_dir, f"{slug}.vtt")
            with open(vtt_path, "w", encoding="utf-8") as f:
                f.write(vtt_content)
            saved_files.append({"format": "vtt", "path": vtt_path, "words": words_count})
            if not (args.json or args.table):
                print(f"[+] Saved VTT transcript: {vtt_path}")

        if args.format in ["md", "all"]:
            md_content = parse_vtt_to_markdown(vtt_content, title=info["topic"])
            md_words = len(md_content.split())
            md_path = os.path.join(args.out_dir, f"{slug}_transcript.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            saved_files.append({"format": "md", "path": md_path, "words": md_words})
            if not (args.json or args.table):
                print(f"[+] Saved Markdown transcript: {md_path}")

        if args.format == "txt":
            txt_lines = []
            for line in vtt_content.splitlines():
                if not line or line.startswith("WEBVTT") or line.isdigit() or "-->" in line:
                    continue
                txt_lines.append(line)
            txt_path = os.path.join(args.out_dir, f"{slug}_transcript.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(txt_lines) + "\n")
            saved_files.append({"format": "txt", "path": txt_path, "words": len(" ".join(txt_lines).split())})
            if not (args.json or args.table):
                print(f"[+] Saved TXT transcript: {txt_path}")
    else:
        if not (args.json or args.table):
            print("[-] No native VTT transcript found hosted on Zoom for this recording.")
            if info.get("video_url"):
                print("[*] Video stream URL is available for keyframe extraction or local ASR.")

    # Video download
    if args.video:
        if info.get("video_url"):
            mp4_path = os.path.join(args.out_dir, f"{slug}.mp4")
            if not (args.json or args.table):
                print(f"[*] Downloading MP4 video to {mp4_path}...")
            client.download_video(info["video_url"], mp4_path)
            size_mb = os.path.getsize(mp4_path) / (1024 * 1024) if os.path.exists(mp4_path) else 0
            saved_files.append({"format": "mp4", "path": mp4_path, "words": int(size_mb)})
            if not (args.json or args.table):
                print(f"[+] Successfully saved MP4 video ({size_mb:.1f} MB): {mp4_path}")
        else:
            print("[-] Cannot download video: MP4 stream URL not available.", file=sys.stderr)

    # Keyframes extraction
    # OCR deliberately lives in the `ocr` skill, not here: point it at the
    # extracted PNGs (`ocr <png>`) instead of rebuilding a vision stack in a
    # downloader.
    if args.keyframes:
        if info.get("video_url"):
            slides_dir = os.path.join(args.out_dir, f"{slug}_slides")
            client.extract_keyframes(info["video_url"], slides_dir, scene_threshold=args.scene_threshold)
        else:
            print("[-] Cannot extract keyframes: video URL not found.", file=sys.stderr)

    # Output receipts if table or json requested
    if args.table:
        print(f"### Recording: {info['topic']}")
        print(render_table(saved_files, ["format", "path", "words"], ["Format", "File Path", "Words"]))
    elif args.json:
        receipt = {
            "status": "ok",
            "topic": info["topic"],
            "duration": info["duration_str"],
            "saved_files": saved_files,
        }
        if project_keys:
            receipt = {k: v for k, v in receipt.items() if k.lower() in project_keys}
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
