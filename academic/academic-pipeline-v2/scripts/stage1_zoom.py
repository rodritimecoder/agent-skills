#!/usr/bin/env python3
"""Stage 1 - Zoom ingestion for academic-pipeline-v2.

Fetches recording transcripts (VTT) and slide keyframe references through
injected dependencies. No network, subprocess, or third-party import happens
in this module: every external call goes through ``deps``.

Interface::

    run(workspace: Path, dry_run: bool = False, deps: dict | None = None) -> dict

``deps`` may contain:

* ``list_recordings`` -- callable ``() -> [{"id", "week", "title"}]``
* ``fetch`` -- callable ``recording_id -> {"transcript_vtt": str,
  "keyframes": [paths]}``
* ``course`` -- optional course name string (defaults to the workspace name)

The returned dict validates against ``contracts/step.schema.json``.

Only transcripts and keyframe references are requested; the hour-long video
file is never fetched.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

STAGE = 1
STAGE_NAME = "ingest"

# Directories this stage is allowed to write.
INGEST_DIR = "01_ingest"
TRANSCRIPTS_DIR = "transcripts"
META_NAME = "meta.json"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _safe_component(value, fallback="recording"):
    """Reduce an arbitrary id/week/title to a single safe path component."""
    text = str(value if value is not None else "").strip()
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_-")
    return text or fallback


def _week_dir(week):
    """Normalize a week identifier to ``Week_NN`` when it is numeric."""
    match = re.fullmatch(r"(?:week[ _-]?)?0*(\d+)", str(week).strip(), re.IGNORECASE)
    if match:
        return f"Week_{int(match.group(1)):02d}"
    return _safe_component(week, "Week_unknown")


def _relative(path, workspace):
    try:
        return Path(path).resolve().relative_to(Path(workspace).resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def _payload(started_at, status, inputs, outputs=None, evidence=None, errors=None):
    return {
        "stage": STAGE,
        "stage_name": STAGE_NAME,
        "step_type": "P",
        "status": status,
        "started_at": started_at,
        "finished_at": _now(),
        "inputs": inputs,
        "outputs": list(outputs or []),
        "evidence": list(evidence or []),
        "errors": list(errors or []),
    }


def _load_meta(meta_path, course):
    """Read the meta.json another lane may already have written."""
    if meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            data.setdefault("course", course)
            if not isinstance(data.get("weeks"), list):
                data["weeks"] = []
            return data
    return {"course": course, "weeks": []}


def _merge_meta(meta_path, course, zoom_weeks):
    """Merge recording nodes into meta.json instead of overwriting it.

    Canvas and Zoom both feed ``01_ingest/meta.json``.  Whichever lane runs
    second must add to the file, not replace it: an overwrite deletes every
    Canvas node and leaves the constellation empty.
    """
    meta = _load_meta(meta_path, course)
    for entry in zoom_weeks:
        if not isinstance(entry, dict):
            continue
        name = entry.get("week")
        target = None
        for candidate in meta["weeks"]:
            if isinstance(candidate, dict) and candidate.get("week") == name:
                target = candidate
                break
        if target is None:
            meta["weeks"].append(entry)
            continue
        if not isinstance(target.get("nodes"), list):
            target["nodes"] = []
        known = {str(node.get("id")) for node in target["nodes"] if isinstance(node, dict)}
        for node in entry.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            if str(node.get("id")) not in known:
                target["nodes"].append(node)
                known.add(str(node.get("id")))
        for key in ("topic", "tutorial"):
            if not target.get(key) and entry.get(key):
                target[key] = entry[key]
    meta["weeks"].sort(key=lambda w: str(w.get("week", "")))
    return meta


def _skipped(workspace, dry_run, started_at, missing):
    evidence = [
        "skipped: missing dep " + ", ".join(missing) + " (callable(s) not provided)",
        "zoom-recorder needs the requests package to reach Zoom cloud recordings; "
        "no network call was attempted",
        "pass deps={'list_recordings': ..., 'fetch': ...} to enable ingestion",
    ]
    inputs = {
        "workspace": str(Path(workspace)),
        "dry_run": bool(dry_run),
        "deps": {"list_recordings": False, "fetch": False},
        "missing_deps": missing,
    }
    return _payload(started_at, "skipped", inputs, evidence=evidence)


def run(workspace: Path, dry_run: bool = False, deps: dict | None = None) -> dict:
    """Ingest Zoom transcripts/keyframe references, returning a step payload."""
    started_at = _now()
    workspace = Path(workspace)
    deps = deps or {}

    list_recordings = deps.get("list_recordings")
    fetch = deps.get("fetch")
    if not callable(list_recordings) or not callable(fetch):
        missing = [
            name
            for name, fn in (("list_recordings", list_recordings), ("fetch", fetch))
            if not callable(fn)
        ]
        return _skipped(workspace, dry_run, started_at, missing)

    inputs = {
        "workspace": str(workspace),
        "dry_run": bool(dry_run),
        "deps": {"list_recordings": True, "fetch": True},
    }

    try:
        recordings = list(list_recordings() or [])
    except Exception as exc:  # noqa: BLE001 - serialize any failure as evidence
        return _payload(
            started_at, "failed", inputs, errors=[f"list_recordings failed: {exc}"]
        )

    evidence = [
        f"listed {len(recordings)} recording(s) via deps['list_recordings']",
        "transcripts and keyframe references only; full video is never fetched",
    ]
    errors = []
    outputs = []
    planned = []
    weeks = {}
    transcript_count = 0
    keyframe_count = 0

    ingest_dir = workspace / INGEST_DIR

    for rec in recordings:
        if not isinstance(rec, dict) or not rec.get("id"):
            errors.append(f"skipped malformed recording entry: {rec!r}")
            continue

        recording_id = str(rec["id"])
        week = _week_dir(rec.get("week") or "Week_unknown")
        title = str(rec.get("title") or recording_id)

        vtt_path = ingest_dir / TRANSCRIPTS_DIR / week / f"{_safe_component(recording_id, 'recording')}.vtt"

        if dry_run:
            planned.append(_relative(vtt_path, workspace))
            continue

        try:
            data = fetch(recording_id)
        except Exception as exc:  # noqa: BLE001 - keep going, report as evidence
            errors.append(f"fetch failed for {recording_id}: {exc}")
            continue

        if not isinstance(data, dict):
            errors.append(f"fetch returned {type(data).__name__} for {recording_id}")
            continue

        vtt = data.get("transcript_vtt")
        if vtt is None:
            errors.append(f"no transcript_vtt returned for {recording_id}")
            vtt = ""

        vtt_path.parent.mkdir(parents=True, exist_ok=True)
        vtt_path.write_text(str(vtt), encoding="utf-8")
        outputs.append(_relative(vtt_path, workspace))
        transcript_count += 1

        keyframes = [str(k) for k in (data.get("keyframes") or [])]
        keyframe_count += len(keyframes)

        week_entry = weeks.setdefault(
            week, {"week": week, "topic": "", "tutorial": "", "nodes": []}
        )
        if not week_entry["topic"]:
            week_entry["topic"] = title

        week_entry["nodes"].append(
            {
                "id": _safe_component(recording_id, "recording"),
                "label": title,
                "kind": "transcript",
                "recording_id": recording_id,
                "transcript": _relative(vtt_path, workspace),
                "keyframes": keyframes,
            }
        )
        for index, keyframe in enumerate(keyframes, start=1):
            week_entry["nodes"].append(
                {
                    "id": f"{_safe_component(recording_id, 'recording')}-keyframe-{index:02d}",
                    "label": f"{title} keyframe {index}",
                    "kind": "keyframe",
                    "path": keyframe,
                }
            )

        evidence.append(f"wrote {_relative(vtt_path, workspace)} ({len(str(vtt))} chars)")

    counts = {
        "recordings": len(recordings),
        "transcripts": transcript_count,
        "keyframes": keyframe_count,
        "weeks": len(weeks),
    }

    if dry_run:
        evidence.append("dry_run: no files written, no fetch calls made")
        return _payload(
            started_at,
            "skipped" if errors else "ok",
            inputs,
            outputs=[],
            evidence=evidence + [f"would write {path}" for path in planned],
            errors=errors,
        )

    meta_path = ingest_dir / META_NAME
    course = str(deps.get("course") or workspace.name or "course")
    zoom_weeks = [weeks[key] for key in sorted(weeks)]
    if zoom_weeks or not meta_path.is_file():
        merged = _merge_meta(meta_path, course, zoom_weeks)
        ingest_dir.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        outputs.append(_relative(meta_path, workspace))
        evidence.append(
            f"merged {len(zoom_weeks)} recording week(s) into {_relative(meta_path, workspace)} "
            f"({len(merged['weeks'])} week(s) total)"
        )
    else:
        evidence.append(
            f"kept existing {_relative(meta_path, workspace)}: no recordings to merge"
        )

    status = "failed" if errors else "ok"
    inputs["counts"] = counts
    evidence.append(
        "counts: recordings={recordings} transcripts={transcripts} "
        "keyframes={keyframes} weeks={weeks}".format(**counts)
    )
    return _payload(started_at, status, inputs, outputs=outputs, evidence=evidence, errors=errors)
