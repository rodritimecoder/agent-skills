#!/usr/bin/env python3
"""Acquisition and model-service helpers shared by videomine.py and vault_mine.py.

Two failures this module removes.

1. A stopped OCR slot reported as "the server is down". `llama-rig up ocr`
   answers on :8085 in well under a second, so the pipeline starts the slot
   itself and says so. A registered slot is left running: that warm server is
   what makes the next run fast. Only an unregistered backend (MiniCPM on
   :18499) is spawned as a throwaway child, and the caller owns its lifetime.

2. A slow download. yt-dlp's default ladder takes the largest stream on offer
   (4K AV1 on YouTube), merges two DASH streams over one connection, and then
   every later stage pays to decode those pixels. Measured on a 117 s video:
   default 33 MB / 6.2 s download / 4.4 s frame extraction; `res:1080` cap,
   eight fragments and a stream-copy remux 7.4 MB / 3.0 s / 0.9 s.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

# Short-form pages: one muxed vertical stream, no separate audio track, and no
# subtitle track to fall back on. Matched against the URL, not the extractor,
# because yt-dlp reports all of them as "Instagram", "TikTok", "Youtube".
SHORT_FORM_MARKERS = (
    "/shorts/",
    "/reel/",
    "/reels/",
    "/p/",
    "tiktok.com/",
    "/share/",
    "snapchat.com/",
    "threads.net/",
    "youtube.com/clip/",
)

DEFAULT_MAX_RES = 1080
DEFAULT_FRAGMENTS = 8


def is_short_form(url: str) -> bool:
    """True for a vertical short-form page (Shorts, Reels, TikTok, Spotlight)."""
    lowered = (url or "").lower()
    return any(marker in lowered for marker in SHORT_FORM_MARKERS)


def max_res() -> int:
    """Vertical-orientation-safe resolution cap; `VIDEOMINE_MAX_RES` overrides."""
    try:
        value = int(os.environ.get("VIDEOMINE_MAX_RES", DEFAULT_MAX_RES))
    except ValueError:
        return DEFAULT_MAX_RES
    return value if value > 0 else DEFAULT_MAX_RES


def cookies_args() -> list[str]:
    """`--cookies` for the first cookie jar that exists, if any.

    Instagram and TikTok serve the media only to a logged-in session often
    enough that an unauthenticated attempt looks like a hang: yt-dlp retries,
    then fails after the timeout. `YTDLP_COOKIES` points at a jar explicitly;
    the standard yt-dlp location is used otherwise.
    """
    explicit = os.environ.get("YTDLP_COOKIES")
    candidates = [Path(explicit).expanduser()] if explicit else []
    candidates.append(Path.home() / ".config" / "yt-dlp" / "cookies.txt")
    for candidate in candidates:
        if candidate.is_file():
            return ["--cookies", str(candidate)]
    return []


def download_args(url: str = "", res: int | None = None) -> list[str]:
    """yt-dlp flags that finish fast and stay legible for frame OCR.

    `-S res:N` sorts by the *smaller* dimension, so a 720x1280 reel is capped
    at 720 wide and a 2160p landscape video at 1080 tall, without guessing the
    orientation. `bv*+ba/b` keeps the merge path for YouTube and still lands on
    the single muxed stream that Reels and TikTok only ever offer.
    """
    return [
        "-f", "bv*+ba/b",
        "-S", f"res:{res or max_res()}",
        "--concurrent-fragments", str(DEFAULT_FRAGMENTS),
        "--merge-output-format", "mp4",
        "--remux-video", "mp4",
        *cookies_args(),
    ]


def http_up(url: str, timeout: float = 0.5) -> bool:
    """True when `url` answers ready.

    llama-server answers `/health` with 503 while the weights are still
    loading and 200 once it can serve, so a 5xx is "not ready" and must not
    be reported as up: the first request after a false positive fails and the
    caller records "no text". A 404 still means something is listening.
    """
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code == 404
    except Exception:
        return False


def health_url_for(endpoint: str) -> str:
    """Derive `/health` from a chat-completions endpoint."""
    return endpoint.replace("/v1/chat/completions", "/health")


def wait_until_up(url: str, timeout_s: float, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if http_up(url):
            return True
        time.sleep(interval)
    return http_up(url)


def ensure_service(
    endpoint: str,
    *,
    slot: str | None = None,
    spawn_cmd: list[str] | None = None,
    wait_s: float = 90.0,
    log=print,
) -> tuple[bool, str, subprocess.Popen | None]:
    """Make the model behind `endpoint` answer, starting it if it is down.

    Returns `(ok, how, child)` where `how` is one of `already-up`, `llama-rig`,
    `spawned` or `unavailable`, and `child` is the throwaway process the caller
    must stop when `how == "spawned"`.

    A registered slot is started through `llama-rig up <slot>` and left
    running: llama-swap owns it, `llama-rig down <slot>` frees the VRAM, and a
    later run reuses the loaded weights instead of paying the load again.
    """
    health = health_url_for(endpoint)
    if http_up(health):
        return True, "already-up", None

    rig = shutil.which("llama-rig")
    if slot and rig:
        log(f"[model] {health} is down — starting slot '{slot}' (llama-rig up {slot})...")
        started = time.monotonic()
        failure = ""
        try:
            res = subprocess.run(
                [rig, "up", slot], capture_output=True, text=True, timeout=max(wait_s, 30.0)
            )
            failure = ((res.stderr or res.stdout or "").strip().splitlines() or [""])[-1]
            if res.returncode != 0 and not http_up(health):
                # An unknown slot or a full GPU: llama-rig already said why.
                # Polling a slot it refused to start only burns the timeout.
                log(f"[model] llama-rig refused '{slot}': {failure}")
                return False, "unavailable", None
        except subprocess.TimeoutExpired:
            failure = f"llama-rig up {slot} timed out"
        if wait_until_up(health, wait_s):
            log(f"[model] {health} ready in {time.monotonic() - started:.1f}s.")
            return True, "llama-rig", None
        log(f"[model] {health} still down after {wait_s:.0f}s: {failure}")
    elif slot:
        log(f"[model] {health} is down and llama-rig is not on PATH.")

    if spawn_cmd:
        log(f"[model] Spawning {spawn_cmd[0]} on {health}...")
        child = subprocess.Popen(spawn_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if wait_until_up(health, wait_s):
            log(f"[model] {health} ready.")
            return True, "spawned", child
        child.terminate()
        log(f"[model] {health} did not come up; the spawned process was stopped.")

    return False, "unavailable", None


def stop_child(child: subprocess.Popen | None) -> None:
    """Stop a throwaway server the caller spawned (never a llama-rig slot)."""
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
