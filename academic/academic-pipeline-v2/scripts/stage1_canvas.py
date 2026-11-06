#!/usr/bin/env python3
"""Stage 1 — Canvas ingestion (stdlib only, dependency-injected).

Lists Canvas items for weeks 1-12 through ``deps["canvas"]``, drops
admin/orientation/quiz-administration items according to ``deps["classify"]``,
writes kept items to ``01_ingest/markdown/<Week_NN>/<slug>.md`` and merges
constellation nodes into ``01_ingest/meta.json``.

Every external call goes through ``deps`` (a dict of callables).  A missing
dependency yields ``status == "skipped"`` instead of an exception.

Interface::

    run(workspace: Path, dry_run: bool = False, deps: dict | None = None) -> dict

The returned dict validates against ``contracts/step.schema.json``.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

STAGE = 1
STAGE_NAME = "ingest"
WEEKS = tuple(range(1, 13))
INGEST_DIR = "01_ingest"
MARKDOWN_DIR = "markdown"
META_NAME = "meta.json"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _slug(text, fallback="item"):
    """Lowercase, hyphen-separated filesystem-safe slug."""
    value = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower()).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    if len(value) > 80:
        value = value[:80].rstrip("-")
    return value or fallback


def _week_name(week):
    return f"Week_{int(week):02d}"


def _item_text(item):
    for key in ("body", "content", "text", "markdown"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _frontmatter(fields):
    """Render a YAML frontmatter block.

    Stage 3 routes notes by reading ``id``, ``week``, ``kind`` and ``title``
    from this block, so it is written for every item rather than kept in prose
    the parser would have to guess at.
    """
    lines = ["---"]
    for key, value in fields:
        text = str(value if value is not None else "").replace("\n", " ").strip()
        lines.append(f"{key}: {text}")
    lines.append("---")
    return "\n".join(lines)


def _render_markdown(item, week):
    title = str(item.get("title") or item.get("id") or "untitled")
    kind = str(item.get("kind") or "topic").strip().lower()
    header = _frontmatter(
        [
            ("id", item.get("id", "")),
            ("title", title),
            ("week", int(week)),
            ("kind", kind),
            ("type", item.get("type", "")),
            ("url", item.get("url", "")),
            ("body_status", item.get("body_status", "")),
        ]
    )
    lines = [header, "", f"# {title}", ""]
    body = _item_text(item)
    if body:
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def _node_for(item):
    return {
        "id": str(item.get("id") or ""),
        "label": str(item.get("title") or item.get("id") or "untitled"),
        "kind": str(item.get("type") or "page"),
    }


def _load_meta(meta_path, course):
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


def _merge_week(meta, week, nodes):
    """Merge nodes into the week entry, deduplicating by node id."""
    name = _week_name(week)
    entry = None
    for candidate in meta["weeks"]:
        if isinstance(candidate, dict) and candidate.get("week") == name:
            entry = candidate
            break
    if entry is None:
        entry = {"week": name, "topic": "", "tutorial": "", "nodes": []}
        meta["weeks"].append(entry)
    entry.setdefault("nodes", [])
    if not isinstance(entry["nodes"], list):
        entry["nodes"] = []

    existing = {}
    for node in entry["nodes"]:
        if isinstance(node, dict) and "id" in node:
            existing[str(node["id"])] = node

    for node in nodes:
        current = existing.get(node["id"])
        if current is None:
            entry["nodes"].append(node)
            existing[node["id"]] = node
        else:
            current.update(node)

    for node in entry["nodes"]:
        if not isinstance(node, dict):
            continue
        kind = str(node.get("kind", "")).lower()
        if not entry["topic"] and "tutorial" not in kind and "solution" not in kind:
            entry["topic"] = str(node.get("label", ""))
        if not entry["tutorial"] and ("tutorial" in kind or "solution" in kind):
            entry["tutorial"] = str(node.get("label", ""))
    entry.setdefault("topic", "")
    entry.setdefault("tutorial", "")
    meta["weeks"].sort(key=lambda w: str(w.get("week", "")))
    return entry


def _payload(started_at, inputs, status, outputs, evidence, errors):
    return {
        "stage": STAGE,
        "stage_name": STAGE_NAME,
        "step_type": "P",
        "status": status,
        "started_at": started_at,
        "finished_at": _now(),
        "inputs": inputs,
        "outputs": list(outputs),
        "evidence": list(evidence),
        "errors": list(errors),
    }


def run(workspace, dry_run=False, deps=None):
    """Ingest Canvas items for weeks 1-12 into the workspace."""
    started_at = _now()
    workspace = Path(workspace)
    deps = dict(deps or {})
    canvas = deps.get("canvas")
    classify = deps.get("classify")

    inputs = {
        "workspace": str(workspace),
        "weeks": list(WEEKS),
        "dry_run": bool(dry_run),
    }

    if not callable(canvas):
        return _payload(
            started_at,
            inputs,
            "skipped",
            [],
            ["canvas-cli unavailable"],
            [],
        )
    if not callable(classify):
        return _payload(
            started_at,
            inputs,
            "skipped",
            [],
            ["classifier unavailable"],
            [],
        )

    course = str(deps.get("course") or workspace.name or "course")
    ingest_dir = workspace / INGEST_DIR
    markdown_dir = ingest_dir / MARKDOWN_DIR
    meta_path = ingest_dir / META_NAME

    outputs = []
    evidence = []
    errors = []
    kept_total = 0
    skipped_total = 0
    listed_total = 0
    meta = _load_meta(meta_path, course)

    for week in WEEKS:
        week_name = _week_name(week)
        try:
            items = canvas({"week": week, "weeks": [week], "scope": "weeks-1-12"})
        except Exception as exc:  # noqa: BLE001 - surface as evidence, never raise
            errors.append(f"canvas listing failed for {week_name}: {exc}")
            continue
        if items is None:
            items = []
        if not isinstance(items, (list, tuple)):
            errors.append(f"canvas returned non-list for {week_name}")
            continue

        seen_slugs = set()
        week_nodes = []
        week_kept = 0
        for item in items:
            listed_total += 1
            if not isinstance(item, dict):
                errors.append(f"skipping non-object item in {week_name}")
                continue
            try:
                drop = bool(classify(item))
            except Exception as exc:  # noqa: BLE001 - keep item, record error
                errors.append(f"classify failed for item {item.get('id')!r}: {exc}")
                drop = False
            if drop:
                skipped_total += 1
                continue

            node = _node_for(item)
            if not node["id"]:
                errors.append(f"skipping item without id in {week_name}")
                continue
            week_nodes.append(node)
            week_kept += 1
            kept_total += 1

            slug = _slug(item.get("title") or node["id"], fallback=_slug(node["id"], "item"))
            if slug in seen_slugs:
                slug = f"{slug}-{_slug(node['id'], 'item')}"
            seen_slugs.add(slug)

            rel_path = f"{INGEST_DIR}/{MARKDOWN_DIR}/{week_name}/{slug}.md"
            if dry_run:
                evidence.append(f"dry-run: would write {rel_path}")
                continue
            target = workspace / rel_path
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(_render_markdown(item, week), encoding="utf-8")
            except OSError as exc:
                errors.append(f"write failed for {rel_path}: {exc}")
                continue
            outputs.append(rel_path)

        evidence.append(f"{week_name}: listed {len(items)}, kept {week_kept}")
        if week_nodes:
            _merge_week(meta, week, week_nodes)

    if not dry_run:
        try:
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            outputs.append(f"{INGEST_DIR}/{META_NAME}")
        except OSError as exc:
            errors.append(f"write failed for {INGEST_DIR}/{META_NAME}: {exc}")

    evidence.insert(
        0,
        f"canvas items listed: {listed_total}, kept: {kept_total}, "
        f"skipped by classifier: {skipped_total}",
    )
    if dry_run:
        evidence.append("dry-run: no files written")

    status = "failed" if errors else "ok"
    return _payload(started_at, inputs, status, outputs, evidence, errors)
