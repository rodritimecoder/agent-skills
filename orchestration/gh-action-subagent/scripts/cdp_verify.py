#!/usr/bin/env python3
"""
cdp_verify.py — Lightweight Chrome DevTools Protocol (CDP) verification helper.
Connects to headless Chrome on port 9222 to navigate, snapshot, and screenshot.
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error


def get_websocket_url(cdp_host="127.0.0.1", cdp_port=9222):
    url = f"http://{cdp_host}:{cdp_port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("webSocketDebuggerUrl")
    except Exception as e:
        sys.stderr.write(f"❌ Could not connect to Chrome CDP at {url}: {e}\n")
        return None


def take_screenshot_and_snapshot(target_url, output_dir="./artifacts", name="snapshot"):
    os.makedirs(output_dir, exist_ok=True)
    screenshot_path = os.path.abspath(os.path.join(output_dir, f"{name}.png"))
    text_path = os.path.abspath(os.path.join(output_dir, f"{name}.txt"))

    import shutil
    import subprocess
    from pathlib import Path

    fast_cdp_candidates = [
        shutil.which("fast-cdp"),
        str(Path.home() / ".local/bin/fast-cdp"),
        # The sibling skill in this collection, without assuming where the
        # collection is mounted: scripts/ -> skill -> domain -> <skills root>.
        str(Path(__file__).resolve().parents[3] / "multimodal" / "playwright" / "bin" / "fast-cdp"),
        str(Path(__file__).resolve().parents[3] / "multimodal" / "playwright" / "bin" / "playwright-rs"),
        "./playwright/bin/fast-cdp",
        "./multimodal/playwright/bin/fast-cdp",
    ]
    fast_cdp_bin = next((c for c in fast_cdp_candidates if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)

    if fast_cdp_bin:
        t0 = time.time()
        cmd_verify = [fast_cdp_bin, "verify", target_url, "--screenshot", screenshot_path, "--json"]
        res_v = subprocess.run(cmd_verify, capture_output=True, text=True)
        if res_v.returncode == 0:
            cmd_snap = [fast_cdp_bin, "snap", target_url]
            res_s = subprocess.run(cmd_snap, capture_output=True, text=True)
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(res_s.stdout)
            dur_ms = round((time.time() - t0) * 1000, 1)
            print(f"✅ [fast-cdp] Verified {target_url} in {dur_ms}ms")
            print(f"  • Screenshot: {screenshot_path}")
            print(f"  • Snapshot:   {text_path}")
            return True

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            page = browser.new_page()
            page.goto(target_url, timeout=30000, wait_until="networkidle")
            page.screenshot(path=screenshot_path, full_page=True)
            text_content = page.inner_text("body")
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(text_content)
            page.close()
            print(f"✅ Verified {target_url}")
            print(f"  • Screenshot saved: {screenshot_path}")
            print(f"  • Content snapshot: {text_path}")
            return True
    except ImportError:
        pass
    except Exception as e:
        sys.stderr.write(f"Playwright CDP error: {e}\n")

    try:
        new_page_url = f"http://127.0.0.1:9222/json/new?{urllib.parse.quote(target_url)}"
        req = urllib.request.Request(new_page_url, method="PUT")
        with urllib.request.urlopen(req, timeout=10) as resp:
            page_data = json.loads(resp.read().decode("utf-8"))
            page_id = page_data.get("id")
            print(f"✅ Opened page in Chrome (Page ID: {page_id})")
            return True
    except Exception as e:
        sys.stderr.write(f"Direct CDP navigation error: {e}\n")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify webpage via Chrome DevTools Protocol")
    parser.add_argument("--url", required=True, help="URL to navigate to and verify")
    parser.add_argument("--out", default="./artifacts", help="Output directory for screenshots/logs")
    parser.add_argument("--name", default="verify", help="Base name for screenshot output")
    args = parser.parse_args()

    success = take_screenshot_and_snapshot(args.url, args.out, args.name)
    sys.exit(0 if success else 1)
