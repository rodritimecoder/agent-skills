#!/usr/bin/env python3
"""videomine visual gates: perceptual frame signatures, dedup, and OCR truth.

Nothing here touches the pipeline state; every function is a pure measurement
over frames, so the gates are testable without a workspace.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from videomine_core import (
    BLOCK_H,
    BLOCK_W,
    DECISION_URL,
    GRID,
    KEM_SCRIPTS,
)


def frame_signatures(paths: list[Path]) -> list[dict]:
    """Sign every frame in one ffmpeg pass instead of one process per frame.

    Same decode and scale as `frame_signature`, but a single short-lived
    process instead of N — on 96 frames the process spawn alone cost ~5 s.
    The batch pass needs the whole directory in name order, so anything
    irregular (a missing frame, mixed extensions) falls back to per-frame.
    """
    w, h = GRID * BLOCK_W, GRID * BLOCK_H
    frame_bytes = w * h
    ordered = sorted(p for p in paths if p.exists())
    if not ordered:
        return []
    suffixes = {p.suffix.lower() for p in ordered}
    if len(suffixes) == 1:
        suffix = next(iter(suffixes))
        sibling_files = sorted(ordered[0].parent.glob(f"*{suffix}"))
        if sibling_files == ordered:
            res = subprocess.run(
                ["ffmpeg", "-v", "error", "-pattern_type", "glob",
                 "-i", str(ordered[0].parent / f"*{suffix}"),
                 "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                capture_output=True,
            )
            raw = res.stdout
            if len(raw) >= frame_bytes * len(ordered):
                signatures = []
                for index in range(len(ordered)):
                    px = raw[index * frame_bytes:(index + 1) * frame_bytes]
                    hashes = []
                    for gy in range(GRID):
                        for gx in range(GRID):
                            bits = 0
                            for r in range(BLOCK_H):
                                for c in range(BLOCK_W - 1):
                                    i = (gy * BLOCK_H + r) * w + gx * BLOCK_W + c
                                    bits = (bits << 1) | (px[i] < px[i + 1])
                            hashes.append(bits)
                    signatures.append({"hashes": hashes, "luma": round(sum(px) / len(px), 1),
                                       "spread": float(max(px) - min(px))})
                return signatures
    return [frame_signature(p) for p in ordered]


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


def kem_gate(text: str, block_type: str = "text"):
    try:
        scripts = str(KEM_SCRIPTS)
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from kem_ocr import assert_structure
        return assert_structure(text, block_type)
    except Exception:
        return None
