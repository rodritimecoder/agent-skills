#!/usr/bin/env python3
"""videomine shared state: volume paths, stage contracts, endpoints, commands.

`videomine.py` owns the CLI, `videomine_stages.py` the six stages, and
`videomine_visual.py` the frame/OCR gates. They all read this module, so an
env override or an endpoint changes in exactly one place.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_DIR / "_templates" / "workspace"


def _drive_root() -> Path:
    """The AI volume root: $AI_ROOT, else the nearest ancestor holding models/.

    Weights, the llama.cpp binaries and sibling skills all live under it, so
    resolving from here keeps the skill working wherever the volume is mounted.
    """
    env = os.environ.get("AI_ROOT")
    if env:
        return Path(env).expanduser()
    for parent in Path(__file__).resolve().parents:
        if (parent / "models").is_dir():
            return parent
    return Path("/run/media/rodri/AI")


DRIVE = _drive_root()

STAGES = [
    "01_acquire",
    "02_audio_asr",
    "03_visual_sample",
    "04_visual_gate",
    "05_visual_ocr",
    "06_synthesize",
]

# The stream that carries machine-readable output. main() rebinds this to the
# real stdout before redirecting sys.stdout to stderr for --json runs, so a
# log line can never corrupt the JSON document.
_STDOUT = sys.stdout


def emit_json(payload: object) -> None:
    """Print JSON to the real stdout, bypassing any log redirection."""
    print(json.dumps(payload, indent=2, ensure_ascii=False), file=_STDOUT or sys.stdout)


# Service Endpoints
DECISION_URL = os.environ.get("JEV_URL", "http://127.0.0.1:8083/v1/systemone")


def _decision_model_is_h2o() -> bool:
    models_url = DECISION_URL.rsplit("/v1/systemone", 1)[0] + "/v1/models"
    try:
        req = urllib.request.Request(models_url)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("data") or []
        return bool(models and "h2o-lightning-4b" in str(models[0].get("id", "")).lower())
    except Exception:
        return False

LIGHTON_MODEL = Path(os.environ.get("LIGHTON_MODEL", DRIVE / "models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.Q4_K_M.gguf"))
LIGHTON_MMPROJ = Path(os.environ.get("LIGHTON_MMPROJ", DRIVE / "models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.mmproj-q8_0.gguf"))
LLAMA_SERVER_BIN = Path(os.environ.get("LLAMA_SERVER_BIN", DRIVE / "llama.cpp/build/bin/llama-server"))
LLAMA_MTMD_CLI = Path(os.environ.get("LLAMA_MTMD_CLI", DRIVE / "llama.cpp/build/bin/llama-mtmd-cli"))
LIGHTON_PORT = int(os.environ.get("LIGHTON_PORT", "8085"))
LIGHTON_URL = os.environ.get("LIGHTON_URL", f"http://127.0.0.1:{LIGHTON_PORT}/v1/chat/completions")

MINICPM_MODEL = Path(os.environ.get("MINICPM_OCR_MODEL", DRIVE / "models/openbmb/MiniCPM-OCR-1.0-gguf/MiniCPM-OCR-1_0-Q8_0.gguf"))
MINICPM_MMPROJ = Path(os.environ.get("MINICPM_OCR_MMPROJ", DRIVE / "models/openbmb/MiniCPM-OCR-1.0-gguf/mmproj-model-f16-4x.gguf"))
MINICPM_SERVER_BIN = Path(os.environ.get("MINICPM_SERVER_BIN", DRIVE / "llama.cpp/build-vulkan/bin/llama-server"))
MINICPM_PORT = int(os.environ.get("MINICPM_PORT", "18499"))
MINICPM_URL = os.environ.get("MINICPM_URL", f"http://127.0.0.1:{MINICPM_PORT}/v1/chat/completions")
KEM_SCRIPTS = Path(os.environ.get("KEM_OCR_SCRIPTS", Path(__file__).resolve().parents[2] / "kem-ocr" / "scripts"))

GATE_MODE = os.environ.get("VIDEOMINE_GATE", "hash")
OCR_BACKEND = os.environ.get("VIDEOMINE_OCR", "lighton")
OCR_SLOT = os.environ.get("VIDEOMINE_OCR_SLOT", "ocr")
OCR_WAIT_S = float(os.environ.get("VIDEOMINE_OCR_WAIT", "90"))
HASH_DISTANCE = int(os.environ.get("VIDEOMINE_HASH_DISTANCE", "20"))
TEXT_SIMILARITY = float(os.environ.get("VIDEOMINE_TEXT_SIMILARITY", "0.9"))
# audiocpp's own default is now nemotron, which returns text without word
# timings: stage 02 would lose every timestamp and the diarization split. Name
# the verbatim model explicitly; --asr-model nemotron is still available.
ASR_MODEL = os.environ.get("VIDEOMINE_ASR_MODEL", "crisperwhisper")
DIARIZE = os.environ.get("VIDEOMINE_DIARIZE", "") not in ("", "0", "false")
SPEAKER_NAMES = [n.strip() for n in os.environ.get("VIDEOMINE_SPEAKERS", "").split(",") if n.strip()] or None
SAMPLE_MODE = os.environ.get("VIDEOMINE_SAMPLE", "auto")
SAMPLE_FPS = float(os.environ.get("VIDEOMINE_SAMPLE_FPS", "1.0"))
KEYFRAME_THRESHOLD_S = float(os.environ.get("VIDEOMINE_KEYFRAME_AFTER", "600"))
GRID = 4
BLOCK_W = 17
BLOCK_H = 16



def get_asr_cmd(audio_wav: Path, details: bool = True, offline: bool = False, words_out: Path | None = None,
                model: str = "") -> list[str]:
    audiocpp_cli = shutil.which("audiocpp") or str(DRIVE / "skills/audiocpp/scripts/audiocpp_cli.py")
    if shutil.which("audiocpp") or Path(audiocpp_cli).is_file():
        cmd = ["audiocpp" if shutil.which("audiocpp") else sys.executable]
        if not shutil.which("audiocpp"):
            cmd.append(audiocpp_cli)
        cmd.extend(["transcribe", str(audio_wav), "--metrics"])
        if model:
            cmd.extend(["--model", model])
        if words_out:
            cmd.extend(["--words-out", str(words_out)])
        return cmd

    candidates = [
        DRIVE / "skills/audiocpp/scripts/audiocpp_cli.py",
        DRIVE / "skills/hardware/audiocpp/scripts/audiocpp_cli.py",
        Path.home() / ".gemini" / "config" / "skills" / "audiocpp" / "scripts" / "audiocpp_cli.py",
        Path.home() / ".config" / "opencode" / "skills" / "audiocpp" / "scripts" / "audiocpp_cli.py",
        Path.home() / ".pi" / "agent" / "skills" / "audiocpp" / "scripts" / "audiocpp_cli.py",
    ]
    for c in candidates:
        if c.is_file():
            cmd = [sys.executable, str(c), "asr", "transcribe", str(audio_wav)]
            if words_out:
                cmd.extend(["--words-out", str(words_out)])
            return cmd
    raise FileNotFoundError("Could not locate the audiocpp skill (audiocpp_cli.py) on the system.")




def format_timestamp(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def get_latest_mtime(folder: Path) -> float:
    """Get the latest modification time of files in a directory."""
    if not folder.exists():
        return 0.0
    latest = 0.0
    for p in folder.rglob("*"):
        if p.is_file() and p.name != ".gitkeep":
            mtime = p.stat().st_mtime
            if mtime > latest:
                latest = mtime
    return latest


def stage_status(workspace: Path, stage_idx: int) -> str:
    """Compute ICM status: PENDING, COMPLETE, or STALE."""
    stage_name = STAGES[stage_idx]
    out_dir = workspace / "stages" / stage_name / "output"
    files = [f for f in out_dir.glob("*") if f.is_file() and f.name != ".gitkeep"]
    dirs = [d for d in out_dir.glob("*") if d.is_dir()]
    
    if not files and not dirs:
        return "PENDING"
    
    current_mtime = get_latest_mtime(out_dir)
    if current_mtime == 0.0:
        return "PENDING"
        
    if stage_idx > 0:
        prev_stage = STAGES[stage_idx - 1]
        prev_out = workspace / "stages" / prev_stage / "output"
        prev_mtime = get_latest_mtime(prev_out)
        if prev_mtime > current_mtime:
            return "STALE"
            
    return "COMPLETE"


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


def stage_artifacts(workspace: Path, stage_name: str) -> str:
    out_dir = workspace / "stages" / stage_name / "output"
    if not out_dir.exists():
        return "none"
    files = [f.name for f in out_dir.glob("*") if f.is_file() and f.name != ".gitkeep"]
    dirs = [d.name for d in out_dir.glob("*") if d.is_dir()]
    parts = []
    if files:
        parts.append(", ".join(files[:3]) + (f" (+{len(files)-3})" if len(files) > 3 else ""))
    if dirs:
        parts.append(f"{len(dirs)} dir(s)")
    return "; ".join(parts) or "none"


def get_pipeline_status(workspace: Path) -> list[dict]:
    res = []
    for i, s in enumerate(STAGES):
        st = stage_status(workspace, i)
        arts = stage_artifacts(workspace, s)
        res.append({
            "stage": s,
            "status": st,
            "artifacts": arts
        })
    return res


def print_status(workspace: Path, as_table: bool = False, as_json: bool = False, project_keys: list[str] | None = None) -> None:
    """Print the ICM pipeline status diagram or table."""
    statuses = get_pipeline_status(workspace)
    if project_keys:
        statuses = [{k: v for k, v in row.items() if k.lower() in project_keys} for row in statuses]

    if as_json:
        emit_json({"workspace": workspace.name, "stages": statuses})
        return

    if as_table:
        cols = list(statuses[0].keys()) if statuses else ["stage", "status", "artifacts"]
        print(f"### Pipeline Status: {workspace.name}\n")
        print(render_table(statuses, cols))
        return

    # Default ASCII status
    print(f"\nPipeline Status: {workspace.name}")
    print("=" * 60)
    raw_statuses = [stage_status(workspace, i) for i in range(len(STAGES))]
    header = "  " + " -> ".join(f"[{s}]" for s in STAGES)
    cols = []
    for s, st in zip(STAGES, raw_statuses):
        bracket_len = len(s) + 2
        cols.append(st.center(bracket_len))
    status_line = "  " + "    ".join(cols)

    print(header)
    print(status_line)
    print("-" * 60)
    for s, st in zip(STAGES, raw_statuses):
        print(f"  {s:18} : {st}")
    print()
