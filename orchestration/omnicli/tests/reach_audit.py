#!/usr/bin/env python3
"""Advisory hybrid audit: run Google skill-reach's offline checks beside omnicli's gates.

This does NOT gate commits. It writes a timestamped artifact so drift in skill
frontmatter and lexical collisions are visible without blocking on reach's
conventions (which target LLM-trigger 'shelf' harnesses, not our gateway).

Usage:
    python3 reach_audit.py --repo /path/to/checkout
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

OUT_ROOT = Path.home() / ".local/share/omnicli/reach-audit"


def collect_skills(repo: Path) -> list[Path]:
    out = []
    for p in repo.rglob("SKILL.md"):
        parts = set(p.parts)
        if parts & {"archived", ".venv", "node_modules", "__pycache__", "surface", ".git"}:
            continue
        out.append(p)
    return sorted(out)


def run(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"reach_audit: not a directory: {repo}", file=sys.stderr)
        return 0  # advisory: never block

    bin = shutil.which("reach")
    if not bin:
        print("reach_audit: reach CLI not installed; skipped (advisory)")
        return 0

    skills = collect_skills(repo)
    artifact_dir = OUT_ROOT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "at": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "skills_scanned": len(skills),
        "reach_version": run([bin, "--version"])[1].strip(),
    }

    for name, cmd in (
        ("lint", [bin, "lint", str(repo), "--format", "json"]),
        ("overlap", [bin, "overlap", str(repo), "--format", "json"]),
    ):
        rc, out, err = run(cmd)
        (artifact_dir / f"{name}.json").write_text(out or "{}", encoding="utf-8")
        report[name] = {
            "exit": rc,
            "findings": len(json.loads(out).get("issues", [])) if out.strip().startswith("{") else None,
            "error": err.strip().splitlines()[-1] if err.strip() else None,
        }

    (artifact_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"reach_audit: {report['skills_scanned']} skills | "
        f"lint={report['lint']['exit']} overlap={report['overlap']['exit']} | "
        f"artifact={artifact_dir}"
    )
    return 0  # advisory: never block a push


if __name__ == "__main__":
    sys.exit(main())
