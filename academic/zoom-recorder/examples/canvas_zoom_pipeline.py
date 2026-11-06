#!/usr/bin/env python3
"""
canvas_zoom_pipeline.py - Extract Zoom recordings & passcodes from Canvas LMS and download transcripts.

Integrates:
- `canvas-cli` (to fetch course modules, pages, or announcements).
- `zoom_download.py` (to unlock Zoom recordings and extract clean Markdown/VTT transcripts).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from typing import List, Dict, Any, Optional

CANVAS_CLI_PATH = os.path.expanduser("~/.gemini/config/skills/canvas-cli/scripts/canvas_cli.py")
ZOOM_DOWNLOAD_SCRIPT = os.path.expanduser("~/.gemini/config/skills/zoom-recorder/scripts/zoom_download.py")


def run_canvas_cmd(args: List[str]) -> Any:
    """Run canvas_cli.py command and parse JSON output."""
    cmd = ["python3", CANVAS_CLI_PATH] + args
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"canvas_cli error: {result.stderr.strip() or result.stdout.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout


def extract_zoom_links_and_passcode(html_or_text: str) -> List[Dict[str, str]]:
    """
    Search text/HTML for Zoom recording URLs and nearby passcodes.
    """
    results = []
    
    # 1. First, search for direct Zoom URLs (e.g. https://utsmeet.zoom.us/rec/...)
    direct_zoom_pattern = re.compile(
        r'https?://[a-zA-Z0-9_\-\.]*zoom\.us/rec/(?:share|play)/[a-zA-Z0-9_\-\.]+',
        re.IGNORECASE
    )
    direct_urls = direct_zoom_pattern.findall(html_or_text)
    
    # 2. Passcode regex
    passcode_pattern = re.compile(r'Passcode:\s*([^\s<>"\']+)', re.IGNORECASE)
    passcode_match = passcode_pattern.search(html_or_text)
    passcode = passcode_match.group(1).strip() if passcode_match else ""
    
    unique_urls = list(dict.fromkeys(direct_urls))
    
    # If no direct Zoom URL, check if there's a protected wrapper that encodes a target URL
    if not unique_urls:
        wrapped_pattern = re.compile(
            r'https?://[^\s"\'<>]+(?:mimecastprotect\.com|protection\.outlook\.com)[^\s"\'<>]+',
            re.IGNORECASE
        )
        for u in wrapped_pattern.findall(html_or_text):
            clean_u = u.rstrip(').,;"\'')
            if clean_u not in unique_urls:
                unique_urls.append(clean_u)

    for u in unique_urls:
        results.append({
            "url": u,
            "passcode": passcode
        })
        
    return results


def process_course_recordings(course_id: int, out_dir: str, format_type: str = "md", keyframes: bool = False):
    """
    Scan all modules and pages for a course in Canvas, find recordings, and download transcripts.
    """
    print(f"[*] Scanning modules for Canvas Course ID: {course_id}...")
    modules = run_canvas_cmd(["modules", str(course_id)])
    if not isinstance(modules, list):
        print(f"[-] No modules found or invalid format: {modules}")
        return

    recordings_to_process = []

    for mod in modules:
        mod_id = mod.get("id")
        mod_name = mod.get("name", f"Module_{mod_id}")
        
        # Only check modules that might have content
        items = run_canvas_cmd(["modules", str(course_id), "--module-id", str(mod_id), "--items"])
        if not isinstance(items, list):
            continue

        for item in items:
            title = item.get("title", "")
            item_type = item.get("type")
            page_url = item.get("page_url")
            
            # Check if title mentions recording or tutorial or zoom
            is_recording_candidate = any(k in title.lower() for k in ["recording", "zoom", "tutorial video", "lecture video"])
            
            if item_type == "Page" and page_url:
                try:
                    page_data = run_canvas_cmd(["pages", str(course_id), "--url", page_url])
                    body = page_data.get("body", "") or ""
                    full_text = f"{title}\n{body}"
                    found = extract_zoom_links_and_passcode(full_text)
                    for f in found:
                        recordings_to_process.append({
                            "module": mod_name,
                            "title": title,
                            "url": f["url"],
                            "passcode": f["passcode"],
                        })
                except Exception as err:
                    # Non-fatal error for individual page fetch
                    pass

    print(f"[+] Discovered {len(recordings_to_process)} Zoom recording(s) in course {course_id}.")
    for idx, rec in enumerate(recordings_to_process, 1):
        print(f"\n--- [{idx}/{len(recordings_to_process)}] Processing: {rec['title']} ---")
        print(f"    Module:   {rec['module']}")
        print(f"    URL:      {rec['url']}")
        print(f"    Passcode: {rec['passcode']}")
        
        # Determine output subdirectory for module
        safe_mod = re.sub(r'[^a-zA-Z0-9_\-]+', '_', rec['module']).strip("_")
        mod_out_dir = os.path.join(out_dir, safe_mod)
        os.makedirs(mod_out_dir, exist_ok=True)
        
        cmd = [
            "python3", ZOOM_DOWNLOAD_SCRIPT,
            "--url", rec["url"],
            "--out-dir", mod_out_dir,
            "--format", format_type,
        ]
        if rec["passcode"]:
            cmd.extend(["--passcode", rec["passcode"]])
        if keyframes:
            cmd.append("--keyframes")

        res = subprocess.run(cmd)
        if res.returncode == 0:
            print(f"    [OK] Downloaded transcript to {mod_out_dir}")
        else:
            print(f"    [WARN] Failed downloading transcript for {rec['title']}")


def main():
    parser = argparse.ArgumentParser(description="Fetch Zoom lecture recordings from Canvas LMS and download transcripts.")
    parser.add_argument("--course-id", type=int, required=True, help="Canvas Course ID (e.g. 41088)")
    parser.add_argument("--out-dir", "-o", default=os.path.expanduser("~/Downloads/notes/zoom_transcripts"), help="Target output folder")
    parser.add_argument("--format", choices=["md", "vtt", "txt", "all"], default="md", help="Transcript format")
    parser.add_argument("--keyframes", action="store_true", help="Extract video keyframes with ffmpeg")

    args = parser.parse_args()
    process_course_recordings(args.course_id, args.out_dir, format_type=args.format, keyframes=args.keyframes)


if __name__ == "__main__":
    main()
