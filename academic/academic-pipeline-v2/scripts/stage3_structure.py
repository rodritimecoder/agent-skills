"""Stage 3: OKF v0.2 structure assembly.

No model calls, no network. Reads 01_ingest/meta.json (contracts/meta.schema.json)
and 02_sift/ (cleaned notes + sift_report.json), then writes a deterministic
week/topic layout, an index and agent state under 03_structure/. Returns a dict
matching contracts/step.schema.json.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGE = 3
STAGE_NAME = "structure"
KINDS = ("topic", "tutorial")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "untitled"


def _course_slug(course: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", course.lower()).strip("_") or "course"


def _week_num(raw: Any) -> int:
    if isinstance(raw, bool):
        return 1
    if isinstance(raw, int):
        return max(1, raw)
    match = re.search(r"\d+", str(raw))
    return max(1, int(match.group())) if match else 1


def _week_label(num: int) -> str:
    return f"Week_{num:02d}"


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key in sorted(fields):
        value = fields[key]
        if isinstance(value, list):
            if value:
                lines.append(f"{key}:")
                lines.extend(f"  - {item}" for item in value)
            else:
                lines.append(f"{key}: []")
        elif value is None:
            lines.append(f"{key}: null")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _parse_note(path: Path, sift_dir: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].strip("\n").splitlines():
                key, sep, value = line.partition(":")
                if sep:
                    meta[key.strip()] = value.strip()
            body = text[end + 4 :].lstrip("\n")
    title = meta.get("title") or path.stem
    return {
        "id": str(meta.get("id") or path.stem),
        "rel": path.relative_to(sift_dir).as_posix(),
        "title": title,
        "week": _week_num(meta.get("week", "1")),
        "kind": str(meta.get("kind", "topic")).lower(),
        "meta": meta,
        "body": body.rstrip() + "\n",
    }


def _kept_ids(sift_dir: Path) -> set[str]:
    report_path = sift_dir / "sift_report.json"
    if not report_path.is_file():
        return set()
    try:
        report = _read_json(report_path) or {}
    except (json.JSONDecodeError, OSError):
        return set()
    kept: set[str] = set()
    for item in report.get("items") or []:
        if isinstance(item, dict) and str(item.get("route", "keep")) != "drop":
            if item.get("id"):
                kept.add(str(item["id"]))
    raw = report.get("kept") or report.get("kept_notes") or []

    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, str):
            kept.add(entry)
        elif isinstance(entry, dict):
            for key in ("id", "path", "note", "name"):
                if entry.get(key):
                    kept.add(str(entry[key]))
                    break
    return kept


def _load_notes(sift_dir: Path) -> tuple[list[dict[str, Any]], list[Path]]:
    kept = _kept_ids(sift_dir)
    notes: list[dict[str, Any]] = []
    read: list[Path] = []
    for path in sorted(sift_dir.rglob("*.md")):
        read.append(path)
        try:
            note = _parse_note(path, sift_dir)
        except OSError:
            continue
        if kept:
            if note["id"] in kept or note["rel"] in kept:
                notes.append(note)
        elif str(note["meta"].get("status", "")).lower() not in {"dropped", "rejected", "discard"}:
            notes.append(note)
    notes.sort(key=lambda n: (n["week"], n["kind"], n["rel"]))
    return notes, read


def run(
    workspace: Path,
    dry_run: bool = False,
    deps: dict | None = None,
) -> dict:
    started_at = _now()
    workspace = Path(workspace)
    meta_path = workspace / "01_ingest" / "meta.json"
    sift_dir = workspace / "02_sift"
    out_root = workspace / "03_structure"
    outputs: list[str] = []
    evidence: list[str] = []
    errors: list[str] = []

    def result(status: str, inputs: dict | None = None) -> dict:
        return {
            "stage": STAGE,
            "stage_name": STAGE_NAME,
            "step_type": "D",
            "status": status,
            "started_at": started_at,
            "finished_at": _now(),
            "inputs": inputs or {},
            "outputs": outputs,
            "evidence": evidence,
            "errors": errors,
        }

    inputs: dict[str, Any] = {"meta": str(meta_path), "sift_dir": str(sift_dir)}
    if not meta_path.is_file():
        evidence.append(f"missing required input: {meta_path}")
        evidence.append("stage skipped: no meta.json to structure")
        return result("skipped", inputs)

    try:
        meta = _read_json(meta_path) or {}
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"unreadable meta.json: {exc}")
        return result("failed", inputs)
    if not isinstance(meta, dict):
        errors.append("meta.json is not an object")
        return result("failed", inputs)

    course = str(meta.get("course") or "course")
    course_slug = _course_slug(course)
    course_root = out_root / course_slug
    meta_weeks = meta.get("weeks") if isinstance(meta.get("weeks"), list) else []
    notes, read_paths = _load_notes(sift_dir) if sift_dir.is_dir() else ([], [])

    inputs["notes"] = [p.relative_to(sift_dir).as_posix() for p in read_paths]
    evidence.append(f"course={course}")
    evidence.append(f"meta_weeks={len(meta_weeks)}")
    evidence.append(f"notes_read={len(read_paths)}")
    evidence.append(f"notes_kept={len(notes)}")
    evidence.append(f"dry_run={bool(dry_run)}")

    weeks: dict[int, dict[str, list[dict[str, Any]]]] = {}
    for entry in meta_weeks:
        if isinstance(entry, dict):
            weeks.setdefault(_week_num(entry.get("week")), {k: [] for k in KINDS})
    for note in notes:
        kind = "tutorial" if "tutorial" in note["kind"] else "topic"
        weeks.setdefault(note["week"], {k: [] for k in KINDS})[kind].append(note)

    week_dirs: list[str] = []
    nodes: list[str] = []
    weeks_root = course_root / "01_weeks"
    for num in sorted(weeks):
        label = _week_label(num)
        week_dir = weeks_root / label
        week_dirs.append(f"{course_slug}/01_weeks/{label}")
        for kind in KINDS:
            used = weeks[num].get(kind, [])
            sources = [n["rel"] for n in used]
            title = used[0]["title"] if len(used) == 1 else f"{label} {kind.title()}"
            body = "\n\n".join(n["body"].strip() for n in used)
            if not body:
                body = f"_No kept {kind} notes for {label}._"
            content = (
                _frontmatter({"week": num, "kind": kind, "sources": sources})
                + f"\n# {title}\n\n{body}\n"
            )
            path = week_dir / f"{kind}.md"
            if not dry_run:
                _write(path, content)
            outputs.append(str(path))
            nodes.append(f"{course_slug}/01_weeks/{label}/{kind}.md")

    index_lines = ["# Index", "", f"course: {course_slug}", "", "## Weeks", ""]
    index_lines.extend(f"- {d}" for d in week_dirs)
    index_lines.extend(["", "## Nodes", ""])
    index_lines.extend(f"- {n}" for n in nodes)
    index_path = course_root / "02_index" / "index.md"
    if not dry_run:
        _write(index_path, "\n".join(index_lines) + "\n")
    outputs.append(str(index_path))

    facts = [
        ("stage", STAGE),
        ("stage_name", STAGE_NAME),
        ("course", course),
        ("weeks", [_week_label(n) for n in sorted(weeks)]),
        ("nodes", nodes),
        ("status", "ok"),
    ]
    state = {
        "stage": STAGE,
        "stage_name": STAGE_NAME,
        "course": course,
        "facts": [{"fact": f"{k} = {v}", "superseded_by": None} for k, v in facts],
        "superseded_by": None,
        "updated_at": _now(),
    }
    state_json = course_root / "03_state" / ".agent_state.json"
    if not dry_run:
        _write(state_json, json.dumps(state, indent=2, sort_keys=True) + "\n")
    outputs.append(str(state_json))

    state_md_lines: list[str] = []
    for key, value in facts:
        state_md_lines.append(f"{key}: {value} | superseded-by: none")
    state_md = course_root / "03_state" / "STATE.md"
    if not dry_run:
        _write(state_md, "\n".join(state_md_lines) + "\n")
    outputs.append(str(state_md))

    root = workspace.resolve()
    for path in outputs:
        if not Path(path).resolve().is_relative_to(root):
            errors.append(f"write outside workspace blocked: {path}")

    evidence.append(f"weeks={len(weeks)}")
    evidence.append(f"outputs_written={0 if dry_run else len(outputs)}")
    return result("failed" if errors else "ok", inputs)
