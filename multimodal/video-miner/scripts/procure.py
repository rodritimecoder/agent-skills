#!/usr/bin/env python3
"""Acquisition, model-service and speaker helpers shared by the video skills.

Three failures this module removes.

1. A stopped OCR slot reported as "the server is down". `llama-rig up ocr`
   answers on :8082 in well under a second, so the pipeline starts the slot
   itself and says so. A registered slot is left running: that warm server is
   what makes the next run fast. Only an unregistered backend (MiniCPM on
   :18499) is spawned as a throwaway child, and the caller owns its lifetime.

2. A slow download. yt-dlp's default ladder takes the largest stream on offer
   (4K AV1 on YouTube), merges two DASH streams over one connection, and then
   every later stage pays to decode those pixels. Measured on a 117 s video:
   default 33 MB / 6.2 s download / 4.4 s frame extraction; `res:1080` cap,
   eight fragments and a stream-copy remux 7.4 MB / 3.0 s / 0.9 s.

3. An interview transcribed as one anonymous voice. Nemotron 3 Diarization
   runs through `audiocpp diarize` at ~21x+ real time and needs no server, so
   who-spoke-when costs a second on a reel and is worth having on a talk.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


# ── Speaker diarization (Nemotron 3, no server) ─────────────────────────────

DIAR_SAMPLE_RATE = 16000


def _ai_root() -> Path:
    """The AI volume root: $AI_ROOT, else the nearest ancestor holding models/."""
    env = os.environ.get("AI_ROOT")
    if env:
        return Path(env).expanduser()
    for parent in Path(__file__).resolve().parents:
        if (parent / "models").is_dir():
            return parent
    return Path("/run/media/rodri/AI")


def find_audiocpp_cmd() -> list[str] | None:
    """Locate the `audiocpp` CLI wrapper."""
    on_path = shutil.which("audiocpp")
    if on_path:
        return [on_path]
    root = _ai_root()
    candidates = [
        Path(__file__).resolve().parents[3] / "hardware" / "audiocpp" / "scripts" / "audiocpp_cli.py",
        root / "skills" / "audiocpp" / "scripts" / "audiocpp_cli.py",
        root / "skills" / "hardware" / "audiocpp" / "scripts" / "audiocpp_cli.py",
        Path.home() / ".gemini" / "config" / "skills" / "audiocpp" / "scripts" / "audiocpp_cli.py",
        Path.home() / ".config" / "opencode" / "skills" / "audiocpp" / "scripts" / "audiocpp_cli.py",
        Path.home() / ".pi" / "agent" / "skills" / "audiocpp" / "scripts" / "audiocpp_cli.py",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return [sys.executable, str(candidate)]
    return None


def find_diarization_script() -> Path | None:
    """Locate `run-diarization.sh` if present (compatibility fallback)."""
    explicit = os.environ.get("AUDIOCPP_DIAR")
    candidates: list[Path] = [Path(explicit).expanduser()] if explicit else []
    on_path = shutil.which("run-diarization")
    if on_path:
        candidates.append(Path(on_path))
    root = _ai_root()
    candidates += [
        root / "sh" / "run-diarization.sh",
        root / "skills" / "audiocpp" / "scripts" / "run-diarization.sh",
        root / "workstation-clis" / "launchers" / "run-diarization.sh",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def run_diarization(
    media: Path,
    out_dir: Path,
    *,
    names: list[str] | None = None,
    timeout_s: float = 1800.0,
    log=print,
) -> list[dict] | None:
    """Who spoke when for `media` (audio or video), or None if it cannot run.

    Ids are arrival order — `speaker_0` is whoever spoke first — so pass
    `names=[...]` only after checking the first line of the transcript.
    """
    explicit = os.environ.get("AUDIOCPP_DIAR")
    audiocpp_cmd = None if explicit else find_audiocpp_cmd()
    if audiocpp_cmd is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [*audiocpp_cmd, "diarize", str(media), "--out", str(out_dir), "--json", "--quiet"]
        if names:
            cmd += ["--names", ",".join(names)]
    else:
        script = find_diarization_script()
        if script is None:
            log("[diar] audiocpp diarize not found; no speaker labels.")
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = ["bash", str(script), str(media), "--out", str(out_dir), "-q"]
        if names:
            cmd += ["--names", ",".join(names)]

    started = time.monotonic()
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        log(f"[diar] diarization timed out after {timeout_s:.0f}s; no speaker labels.")
        return None

    turns_file = out_dir / media.stem / "turns.json"
    if res.returncode != 0:
        detail = ((res.stderr or res.stdout or "").strip().splitlines() or ["no output"])[-1]
        log(f"[diar] diarization failed: {detail}")
        return None

    turns: list[dict] | None = None
    if audiocpp_cmd is not None and res.stdout.strip():
        try:
            payload = json.loads(res.stdout)
            turns = [
                {
                    "start": float(turn["start"]),
                    "end": float(turn["end"]),
                    "speaker": turn["speaker"],
                    "confidence": turn.get("confidence"),
                }
                for turn in payload.get("turns", [])
                if "start" in turn and "end" in turn and "speaker" in turn
            ]
        except Exception:
            turns = None

    if turns is None:
        if not turns_file.is_file():
            detail = ((res.stderr or res.stdout or "").strip().splitlines() or ["no output"])[-1]
            log(f"[diar] diarization failed: {detail}")
            return None
        try:
            raw = json.loads(turns_file.read_text(encoding="utf-8"))
        except Exception as exc:
            log(f"[diar] unreadable turns.json ({exc}); no speaker labels.")
            return None
        turns = [
            {
                "start": turn["start_sample"] / DIAR_SAMPLE_RATE,
                "end": turn["end_sample"] / DIAR_SAMPLE_RATE,
                "speaker": turn["speaker_id"],
                "confidence": turn.get("confidence"),
            }
            for turn in raw
            if "start_sample" in turn and "end_sample" in turn
        ]

    speakers = sorted({turn["speaker"] for turn in turns})
    log(f"[diar] {len(turns)} turns, {len(speakers)} speakers in {time.monotonic() - started:.1f}s.")
    return turns


def speaker_labels(turns: list[dict], names: list[str] | None = None) -> dict[str, str]:
    """Map model ids to display names in arrival order (`speaker_0` → names[0])."""
    ordered: list[str] = []
    for turn in turns:
        if turn["speaker"] not in ordered:
            ordered.append(turn["speaker"])
    labels = {}
    for index, speaker in enumerate(ordered):
        if names and index < len(names) and names[index]:
            labels[speaker] = names[index].strip()
        else:
            labels[speaker] = f"Speaker {index + 1}"
    return labels


def speaker_at(turns: list[dict], start: float, end: float | None = None) -> str | None:
    """The speaker holding most of `[start, end)`; None when nothing overlaps."""
    end = start + 0.5 if end is None else max(end, start + 0.01)
    best, best_overlap = None, 0.0
    for turn in turns:
        overlap = min(end, turn["end"]) - max(start, turn["start"])
        if overlap > best_overlap:
            best, best_overlap = turn["speaker"], overlap
    return best


def talk_time(turns: list[dict], labels: dict[str, str] | None = None) -> list[tuple[str, float]]:
    """Seconds spoken per speaker, longest first — the summary line of a talk."""
    labels = labels or speaker_labels(turns)
    totals: dict[str, float] = {}
    for turn in turns:
        totals[turn["speaker"]] = totals.get(turn["speaker"], 0.0) + max(0.0, turn["end"] - turn["start"])
    return sorted(((labels[s], round(seconds, 1)) for s, seconds in totals.items()),
                  key=lambda item: item[1], reverse=True)
