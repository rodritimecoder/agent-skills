"""Stage 2 - Sifting.

Fingerprint and dedupe every markdown file ingested by Stage 1, optionally run
a classifier over each unique item, and route each item to keep / review /
drop.  Kept files are copied into ``<workspace>/02_sift/cleaned`` and the full
decision set is written to ``<workspace>/02_sift/sift_report.json``.

Interface::

    run(workspace: Path, dry_run: bool = False, deps: dict | None = None) -> dict

``deps`` may contain ``"classify"``: a callable taking ``{"id", "text"}`` and
returning ``{"admin_fluff": bool, "confidence": float}``.  All external
behaviour goes through ``deps``; anything missing yields evidence, never an
exception.

Deterministic routing rule (applied in order):

1. exact duplicate fingerprint      -> drop
2. ``admin_fluff`` is True           -> drop
3. classifier unavailable            -> keep (confidence 0.0)
4. ``admin_fluff`` False, confidence >= 0.75 -> keep
5. ``admin_fluff`` False, confidence <  0.75 -> review
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

STAGE = 2
STAGE_NAME = "sift"
INGEST_DIRNAME = "01_ingest"
SIFT_DIRNAME = "02_sift"
CLEANED_DIRNAME = "cleaned"
REPORT_NAME = "sift_report.json"
REVIEW_THRESHOLD = 0.75

# Scaffolding the dispatcher writes into 01_ingest: never course material.
PIPELINE_ARTEFACT_NAMES = {"CONTEXT.md", "STATE.md", ".agent_state.json"}
_WS = re.compile(r"\s+")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalise(text: str) -> str:
    """Normalise text for fingerprinting (line endings, whitespace, case)."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    return _WS.sub(" ", unified).strip().casefold()


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()


def note_id(text: str) -> str | None:
    """Return the ``id`` a note declares in its own frontmatter, if any.

    Stage 3 routes by the id printed inside the note, so the report has to use
    the same id.  Only a frontmatter block at the very top counts; a stray
    ``id:`` line in the body is not an identity.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].strip("\n").splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "id":
            value = value.strip()
            if value:
                return value
    return None


def _payload(started_at, status, inputs, outputs, evidence, errors):
    return {
        "stage": STAGE,
        "stage_name": STAGE_NAME,
        "step_type": "P",
        "status": status,
        "started_at": started_at,
        "finished_at": _now(),
        "inputs": inputs,
        "outputs": outputs,
        "evidence": evidence,
        "errors": errors,
    }


def _clamp(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:  # NaN
        return 0.0
    return max(0.0, min(1.0, number))


def _classify(classify, item_id: str, text: str, errors: list) -> tuple[dict, float, bool]:
    """Return (decisions, confidence, classifier_ok)."""
    try:
        raw = classify({"id": item_id, "text": text})
    except Exception as exc:  # noqa: BLE001 - deps are untrusted
        errors.append(f"classify failed for {item_id}: {exc}")
        return {"is_admin_fluff": None}, 0.0, False
    if not isinstance(raw, dict):
        errors.append(f"classify returned non-object for {item_id}")
        return {"is_admin_fluff": None}, 0.0, False
    fluff = raw.get("admin_fluff", raw.get("is_admin_fluff"))
    if fluff is None:
        errors.append(f"classify returned no admin_fluff for {item_id}")
        return {"is_admin_fluff": None}, 0.0, False
    confidence = _clamp(raw.get("confidence", 0.0))
    return {"is_admin_fluff": bool(fluff)}, confidence, True


def run(workspace: Path, dry_run: bool = False, deps: dict | None = None) -> dict:
    started_at = _now()
    deps = deps or {}
    workspace = Path(workspace)
    ingest_dir = workspace / INGEST_DIRNAME
    sift_dir = workspace / SIFT_DIRNAME
    cleaned_dir = sift_dir / CLEANED_DIRNAME
    report_path = sift_dir / REPORT_NAME

    inputs = {
        "workspace": str(workspace),
        "ingest_dir": str(ingest_dir),
        "report_path": str(report_path),
        "dry_run": bool(dry_run),
    }
    outputs: list = []
    evidence: list = []
    errors: list = []

    if not ingest_dir.is_dir():
        evidence.append(
            {
                "check": "ingest_dir",
                "status": "missing",
                "detail": f"{ingest_dir} does not exist; nothing to sift",
            }
        )
        return _payload(started_at, "skipped", inputs, outputs, evidence, errors)

    files = sorted(
        p
        for p in ingest_dir.rglob("*.md")
        if p.is_file() and p.name not in PIPELINE_ARTEFACT_NAMES
    )
    evidence.append({"check": "ingest_scan", "status": "ok", "files": len(files)})

    classify = deps.get("classify")
    classifier_available = callable(classify)
    evidence.append(
        {
            "check": "classifier",
            "status": "available" if classifier_available else "unavailable",
            "detail": (
                "deps['classify'] present"
                if classifier_available
                else "classifier unavailable: dedupe and routing only, confidence 0.0"
            ),
        }
    )

    seen: dict[str, str] = {}
    items: list = []
    kept: list = []

    for path in files:
        rel = path.relative_to(ingest_dir).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"read failed for {rel}: {exc}")
            continue

        fp = fingerprint(text)
        item_id = note_id(text) or ("md-" + fp[:12])
        decisions: dict = {
            "is_duplicate": fp in seen,
            "duplicate_of": seen.get(fp),
            "is_admin_fluff": None,
            "classifier": "unavailable",
        }
        confidence = 0.0

        if fp in seen:
            route = "drop"
        elif classifier_available:
            verdict, confidence, ok = _classify(classify, item_id, text, errors)
            decisions["is_admin_fluff"] = verdict.get("is_admin_fluff")
            decisions["classifier"] = "ok" if ok else "failed"
            if not ok:
                route = "keep"
            elif decisions["is_admin_fluff"]:
                route = "drop"
            elif confidence >= REVIEW_THRESHOLD:
                route = "keep"
            else:
                route = "review"
        else:
            route = "keep"

        if fp not in seen:
            seen[fp] = item_id

        items.append(
            {
                "id": item_id,
                "source": rel,
                "decisions": decisions,
                "confidence": confidence,
                "route": route,
            }
        )
        if route == "keep":
            kept.append((rel, path))

    report = {"items": items}

    if not dry_run:
        cleaned_dir.mkdir(parents=True, exist_ok=True)
        for rel, src in kept:
            dest = cleaned_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(src, dest)
                outputs.append(str(dest))
            except OSError as exc:
                errors.append(f"copy failed for {rel}: {exc}")
        try:
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            outputs.append(str(report_path))
        except OSError as exc:
            errors.append(f"report write failed: {exc}")
    else:
        evidence.append(
            {"check": "dry_run", "status": "ok", "detail": "no files written"}
        )

    counts = {"keep": 0, "review": 0, "drop": 0}
    for item in items:
        counts[item["route"]] += 1
    evidence.append(
        {
            "check": "routing",
            "status": "ok",
            "rule": (
                "duplicate->drop; admin_fluff->drop; classifier_unavailable->keep; "
                f"confidence>={REVIEW_THRESHOLD}->keep; else review"
            ),
            "items": len(items),
            "counts": counts,
            "duplicates": sum(1 for i in items if i["decisions"]["is_duplicate"]),
        }
    )

    status = "failed" if errors and not items else "ok"
    return _payload(started_at, status, inputs, outputs, evidence, errors)


if __name__ == "__main__":  # pragma: no cover
    import sys

    result = run(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("workspace"))
    print(json.dumps(result, indent=2))
