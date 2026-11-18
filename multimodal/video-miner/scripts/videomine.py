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

The stages live in `videomine_stages.py`, the frame gates in
`videomine_visual.py`, and the shared state in `videomine_core.py`. The names
below stay importable from this module so `videomine.<name>` keeps working.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))
import videomine_core as core
import videomine_stages as stages
from videomine_core import (
    HASH_DISTANCE,
    STAGES,
    TEMPLATES_DIR,
    _decision_model_is_h2o,
    emit_json,
    format_timestamp,
    get_pipeline_status,
    print_status,
    render_table,
)
from videomine_stages import resolve_sample_mode, run_pipeline
from videomine_visual import (
    frame_signature,
    frame_signatures,
    hash_distance,
    kem_gate,
    signature_distance,
    text_similarity,
)


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
    p_step.add_argument("--max-res", type=int, metavar="P", help="download resolution cap in lines (default: 1080)")
    p_step.add_argument("--diarize", action="store_true", help="label speakers with Nemotron 3 diarization (one extra pass)")
    p_step.add_argument("--speaker-names", metavar="A,B", help="names for speakers in arrival order (implies --diarize)")

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
    p_run.add_argument("--max-res", type=int, metavar="P", help="download resolution cap in lines (default: 1080)")
    p_run.add_argument("--diarize", action="store_true", help="label speakers with Nemotron 3 diarization (one extra pass)")
    p_run.add_argument("--speaker-names", metavar="A,B", help="names for speakers in arrival order (implies --diarize)")

    args = parser.parse_args()

    # Line-buffered: a piped run must stream its progress, not dump everything
    # at exit. A 20 s run that prints nothing reads as a hang to an agent.
    if not getattr(args, "json", False):
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except (AttributeError, ValueError):
            pass
    if getattr(args, "max_res", None):
        os.environ["VIDEOMINE_MAX_RES"] = str(args.max_res)

    # In --json mode every log line belongs on stderr: capture the real stdout
    # for the JSON document, then point sys.stdout at stderr so all existing
    # print() progress/notification calls are rerouted without touching them.
    if getattr(args, "json", False):
        core._STDOUT = sys.stdout
        sys.stdout = sys.stderr

    # The stages read their options from their own module globals; rebinding
    # them here is what makes `--gate`, `--ocr`, and friends take effect.
    requested = {
        "GATE_MODE": getattr(args, "gate", None),
        "OCR_BACKEND": getattr(args, "ocr", None),
        "ASR_MODEL": getattr(args, "asr_model", None),
        "SAMPLE_MODE": getattr(args, "sample", None),
        "SAMPLE_FPS": getattr(args, "sample_fps", None),
    }
    for name, value in requested.items():
        if value is not None:
            setattr(stages, name, value)
    if getattr(args, "diarize", False) or getattr(args, "speaker_names", None):
        stages.DIARIZE = True
    if getattr(args, "speaker_names", None):
        stages.SPEAKER_NAMES = [n.strip() for n in args.speaker_names.split(",") if n.strip()] or None

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
