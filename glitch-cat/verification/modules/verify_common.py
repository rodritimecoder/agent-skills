from __future__ import annotations

import json
import re
from pathlib import Path

EXIT_PASS, EXIT_FAIL, EXIT_USAGE, EXIT_DEPENDENCY, EXIT_UNCONFIGURED = 0, 1, 2, 3, 4
QUESTIONS = [
    "Which journey does a person actually perform, and on which viewport?",
    "What must be on screen at the end, in the exact words that prove it?",
    "What must be true behind the screen — which request, status, or record?",
    "What did it look like before, and which pixels must not move?",
    "Which real-user error already happened, and how do we see the next one first?",
]

PROTECTED_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__"}
PROTECTED_SUFFIXES = {".pem", ".key", ".p12", ".keystore"}


class Dependency(RuntimeError):
    pass


def _json_line(value) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "app"


def _title(value: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_/]+", value) if part) or "Feature"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _json_or(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def init_config(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "pass.json"
    skeleton = {
        "name": out_dir.parent.name or "app",
        "api": {"url": "", "viewport": "390x844", "settle_ms": 800},
        "journey": [],
        "expect": {"text": "", "requests": [], "no_failed_requests": True},
        "pixels": {"baseline": "", "tolerance": 8, "max_changed": 0.0},
        "states": {"storybook": "", "filter": "", "max_stories": 30},
        "errors": {"sentry": {"org": "", "project": "", "stats_period": "24h", "max_issues": 0}},
        "artifacts": str(out_dir / "artifacts"),
    }
    if not path.exists():
        path.write_text(json.dumps(skeleton, indent=2))
    return path
