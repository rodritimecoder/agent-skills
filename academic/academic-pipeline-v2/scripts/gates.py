#!/usr/bin/env python3
"""Stage 5 verification micro-gates for academic-pipeline-v2 (stdlib only).

Each gate is a pure disk check: ``gateN_*(workspace, deps) -> (ok, evidence)``
where ``ok`` is ``True`` (pass), ``False`` (fail) or ``None`` (skipped, e.g. a
missing dependency).  Nothing here raises: every failure is serialized as
evidence, and ``run()`` writes ``05_verify/step_05.json``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

STAGE = 5
STAGE_NAME = "verify"
STEP_TYPE = "P"  # the judge is a model call: probabilistic
STEP_FILE = ("05_verify", "step_05.json")

EXPECTED_HTML = ("graph.html", "anki.html", "cornell.html")
CONFIDENCE_FLOOR = 0.3
CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
META_SCHEMA = CONTRACTS / "meta.schema.json"

# Fresh-context judge invoked through the local opencode CLI.  Kept as module
# constants so a caller can see exactly what will be shelled.
JUDGE_BIN = "opencode"
JUDGE_AGENT = "judge"
JUDGE_MODEL = "opencode-go/claude-haiku-5-5"
JUDGE_TIMEOUT = 300
JUDGE_ARTEFACT_CHARS = 4000

_EXTERNAL_SCRIPT = re.compile(
    r"""<script\b[^>]*\bsrc\s*=\s*["']?\s*(?:https?:)?//""", re.IGNORECASE
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _now():
    return datetime.now(timezone.utc).isoformat()


def _fail(evidence, message):
    evidence.append(message)
    return False, evidence


def _validate(node, schema, path="$"):
    """Tiny JSON-Schema-subset validator (type/required/enum/items/properties)."""
    if "enum" in schema:
        if node not in schema["enum"]:
            raise ValueError(f"{path}: {node!r} not in {schema['enum']}")
    node_type = schema.get("type")
    if node_type == "object":
        if not isinstance(node, dict):
            raise ValueError(f"{path}: expected object, got {type(node).__name__}")
        for key in schema.get("required", []):
            if key not in node:
                raise ValueError(f"{path}: missing required key {key!r}")
        props = schema.get("properties", {})
        for key, value in node.items():
            if key in props:
                _validate(value, props[key], f"{path}.{key}")
    elif node_type == "array":
        if not isinstance(node, list):
            raise ValueError(f"{path}: expected array, got {type(node).__name__}")
        items = schema.get("items")
        if items is not None:
            for i, item in enumerate(node):
                _validate(item, items, f"{path}[{i}]")
    elif node_type == "integer":
        if not isinstance(node, int) or isinstance(node, bool):
            raise ValueError(f"{path}: expected integer, got {type(node).__name__}")
    elif node_type == "number":
        if not isinstance(node, (int, float)) or isinstance(node, bool):
            raise ValueError(f"{path}: expected number, got {type(node).__name__}")
    elif node_type == "string":
        if not isinstance(node, str):
            raise ValueError(f"{path}: expected string, got {type(node).__name__}")
    return True


def _walk_confidence(node):
    """Yield every numeric value stored under a 'confidence' key, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "confidence" and isinstance(value, (int, float)):
                yield float(value)
            else:
                yield from _walk_confidence(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_confidence(item)


def _course_roots(workspace):
    structure = Path(workspace) / "03_structure"
    if not structure.is_dir():
        return []
    return sorted(p for p in structure.iterdir() if p.is_dir())


# --------------------------------------------------------------------------- #
# gate 1 - asset doctor: every meta.json vs contracts/meta.schema.json
# --------------------------------------------------------------------------- #
def gate1_assets(workspace, deps):
    evidence = []
    workspace = Path(workspace)
    metas = sorted(p for p in workspace.rglob("meta.json") if p.is_file())
    if not metas:
        return _fail(evidence, "gate1_assets: failed - no meta.json found in workspace")
    try:
        schema = json.loads(META_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail(evidence, f"gate1_assets: failed - cannot load meta schema: {exc}")

    errors = []
    for meta in metas:
        rel = meta.relative_to(workspace)
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{rel}: unreadable ({exc})")
            continue
        try:
            _validate(data, schema)
        except ValueError as exc:
            errors.append(f"{rel}: {exc}")

    if errors:
        for err in errors:
            evidence.append(f"gate1_assets: failed - {err}")
        return False, evidence
    evidence.append(f"gate1_assets: ok - {len(metas)} meta.json validated")
    return True, evidence


# --------------------------------------------------------------------------- #
# gate 2 - sift doctor: markdown/KaTeX balance + classifier confidence floor
# --------------------------------------------------------------------------- #
def gate2_sift(workspace, deps):
    evidence = []
    workspace = Path(workspace)
    sift_dir = workspace / "02_sift"
    if not sift_dir.is_dir():
        return _fail(evidence, "gate2_sift: failed - 02_sift/ is missing")
    markdowns = sorted(sift_dir.rglob("*.md"))
    if not markdowns:
        return _fail(evidence, "gate2_sift: failed - no markdown under 02_sift/")

    ok = True
    for md in markdowns:
        text = md.read_text(encoding="utf-8", errors="replace")
        rel = md.relative_to(workspace)
        if text.count("```") % 2:
            ok, evidence = _fail(evidence, f"gate2_sift: failed - {rel}: unbalanced code fence")
        if text.count("$$") % 2:
            ok, evidence = _fail(evidence, f"gate2_sift: failed - {rel}: unbalanced $$ math block")

    report_path = sift_dir / "sift_report.json"
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return _fail(evidence, f"gate2_sift: failed - sift_report.json unreadable: {exc}")
        low = [c for c in _walk_confidence(report) if c < CONFIDENCE_FLOOR]
        if low:
            ok, evidence = _fail(
                evidence,
                f"gate2_sift: failed - {len(low)} confidence value(s) below "
                f"floor {CONFIDENCE_FLOOR} (route to review queue)",
            )
        else:
            evidence.append("gate2_sift: sift_report.json confidence floor honoured")
    else:
        evidence.append("gate2_sift: no sift_report.json (confidence floor not checked)")

    if ok:
        evidence.append(f"gate2_sift: ok - {len(markdowns)} markdown file(s) balanced")
    return ok, evidence


# --------------------------------------------------------------------------- #
# gate 3 - OKF: index.md must list every week directory
# --------------------------------------------------------------------------- #
def gate3_okf(workspace, deps):
    evidence = []
    roots = _course_roots(workspace)
    if not roots:
        return _fail(evidence, "gate3_okf: failed - no 03_structure/<course>/ directory")

    ok = True
    for course in roots:
        weeks_dir = course / "01_weeks"
        index = course / "02_index" / "index.md"
        if not weeks_dir.is_dir():
            ok, evidence = _fail(evidence, f"gate3_okf: failed - {course.name}/01_weeks missing")
            continue
        if not index.is_file():
            ok, evidence = _fail(
                evidence, f"gate3_okf: failed - {course.name}/02_index/index.md missing"
            )
            continue
        weeks = sorted(p.name for p in weeks_dir.iterdir() if p.is_dir())
        if not weeks:
            ok, evidence = _fail(
                evidence, f"gate3_okf: failed - {course.name}/01_weeks has no week dirs"
            )
            continue
        text = index.read_text(encoding="utf-8", errors="replace")
        missing = [w for w in weeks if w not in text]
        if missing:
            ok, evidence = _fail(
                evidence,
                f"gate3_okf: failed - {course.name}/02_index/index.md omits week(s): "
                + ", ".join(missing),
            )
        else:
            evidence.append(
                f"gate3_okf: {course.name} index.md lists all {len(weeks)} week dir(s)"
            )

    if ok:
        evidence.append(f"gate3_okf: ok - {len(roots)} course root(s) checked")
    return ok, evidence


# --------------------------------------------------------------------------- #
# gate 4 - render smoke: expected HTML exists and ships no external script src
# --------------------------------------------------------------------------- #
def gate4_render(workspace, deps):
    evidence = []
    workspace = Path(workspace)
    render = workspace / "04_render"
    if not render.is_dir():
        return _fail(evidence, "gate4_render: failed - 04_render/ is missing")

    ok = True
    for name in EXPECTED_HTML:
        page = render / name
        if not page.is_file():
            ok, evidence = _fail(evidence, f"gate4_render: failed - missing {name}")
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            ok, evidence = _fail(evidence, f"gate4_render: failed - {name} is empty")
            continue
        hits = _EXTERNAL_SCRIPT.findall(text)
        if hits:
            ok, evidence = _fail(
                evidence,
                f"gate4_render: failed - {name} references {len(hits)} external script src",
            )
            continue
        if "<html" not in text.lower():
            ok, evidence = _fail(evidence, f"gate4_render: failed - {name} is not an HTML document")
            continue
        evidence.append(f"gate4_render: {name} present, standalone (no external script src)")

    ok, evidence = _check_week_coverage(workspace, render, ok, evidence)

    if ok:
        evidence.append(f"gate4_render: ok - {len(EXPECTED_HTML)} standalone page(s)")
    return ok, evidence


def _declared_weeks(workspace):
    """Week labels the course declares in 01_ingest/meta.json."""
    meta_path = Path(workspace) / "01_ingest" / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    weeks = meta.get("weeks") if isinstance(meta, dict) else None
    return [str(e["week"]) for e in weeks or [] if isinstance(e, dict) and e.get("week")]


def _check_week_coverage(workspace, render, ok, evidence):
    """Every study page must name every week the course has.

    A page that silently drops Week_03 looks complete and is not.  Naming a week
    with no retrievable text is allowed; leaving it out is not.
    """
    weeks = _declared_weeks(workspace)
    if not weeks:
        return ok, evidence
    for name in ("anki.html", "cornell.html"):
        page = render / name
        if not page.is_file():
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        missing = []
        for label in weeks:
            match = re.search(r"(\d+)$", label)
            friendly = "Week %d" % int(match.group(1)) if match else label
            if label not in text and friendly not in text:
                missing.append(label)
        if missing:
            ok, evidence = _fail(
                evidence,
                f"gate4_render: failed - {name} omits week(s): " + ", ".join(missing),
            )
        else:
            evidence.append(
                f"gate4_render: {name} names all {len(weeks)} declared week(s)"
            )
    return ok, evidence


# --------------------------------------------------------------------------- #
# gate 5 - fresh-context judge (deps["judge"], or opt-in cli_judge)
# --------------------------------------------------------------------------- #
def _visible_text(path, limit=JUDGE_ARTEFACT_CHARS):
    """Flatten one HTML artefact to the text a judge needs to read."""
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"<unreadable: {exc}>"
    raw = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) > limit:
        # Keep the head AND the tail: a summary or a static card list lives at
        # the end of the page, and a head-only cut would hide exactly the part
        # the rubric asks the judge to check.
        head = max(0, limit - 1200)
        tail = 900
        omitted = len(text) - head - tail
        if omitted > 0:
            text = (
                text[:head].rstrip()
                + f"\n[... {omitted} characters omitted from the middle of this page ...]\n"
                + text[-tail:].lstrip()
            )
        else:
            text = text[:limit]
    return text


def judge_rubric(workspace):
    """Assemble the fresh-context judge prompt from the render artefacts.

    Only disk state is read, so this is safe to call in tests: it never shells
    anything and never touches the network.
    """
    workspace = Path(workspace)
    render = workspace / "04_render"
    weeks = []
    weeks_dir = workspace / "03_structure"
    if weeks_dir.is_dir():
        for course in sorted(p for p in weeks_dir.iterdir() if p.is_dir()):
            week_root = course / "01_weeks"
            if week_root.is_dir():
                weeks = sorted(p.name for p in week_root.iterdir() if p.is_dir())
                break

    lines = [
        "You are an independent, fresh-context judge for a study-material pipeline.",
        "You have no memory of producing these artefacts. Judge only what is below.",
        "",
        "Rubric - check every item:",
        "1. Standalone: judge only that each page reads as a complete document.",
        "   Ignore external references - gate4 checks those deterministically.",
        "2. Coverage: graph.html, anki.html and cornell.html are all present,",
        "   non-empty, and describe the same course weeks. A week the pipeline",
        "   could not retrieve text for must be named as such on the page;",
        "   naming a gap is honesty, silently omitting the week is a defect.",
        f"3. Weeks: the pages cover these week directories: {', '.join(weeks) or '(none found)'}.",
        "4. Faithfulness: no invented facts, formulas or citations; content must",
        "   stay consistent with the rendered notes.",
        "5. Anki: cards are atomic (one fact per card) and answerable without",
        "   the graph page open.",
        "6. Cornell: each page carries cues, notes and a summary section.",
        "   A page longer than the excerpt budget shows its head and tail with",
        "   an explicit 'characters omitted' marker; that omission is not a",
        "   defect, and missing artefacts are already caught before you run.",
        "",
        "Answer with exactly one word on the first line - PASS or FAIL - then a",
        "single short line of reason. Reply FAIL if any artefact is missing.",
        "",
    ]
    for name in EXPECTED_HTML:
        page = render / name
        lines.append(f"===== {name} =====")
        if not page.is_file():
            lines.append("MISSING - this artefact was not rendered.")
        else:
            lines.append(_visible_text(page))
        lines.append("")
    return "\n".join(lines)


def _parse_judge_verdict(stdout):
    """True only when the judge's last PASS/FAIL token is PASS.

    The rubric itself contains the words PASS and FAIL, so an echoed prompt is
    harmless: the last token is the verdict.  No token at all means not
    accepted.
    """
    if not isinstance(stdout, str):
        return False
    tokens = re.findall(r"\b(PASS|FAIL)\b", stdout, re.IGNORECASE)
    if not tokens:
        return False
    return tokens[-1].upper() == "PASS"


def cli_judge(workspace):
    """Fresh-context judge backed by the local ``opencode`` CLI.

    Shells ``opencode run --standalone --agent judge -m
    opencode-go/claude-haiku-5-5`` with a rubric built from the render
    artefacts (see :func:`judge_rubric`) and parses PASS/FAIL from stdout.

    Contract: returns ``True`` only on an explicit PASS.  A missing binary, a
    non-zero exit, a timeout, undecodable output or a missing verdict all
    return ``False``.  It never raises and never retries.
    """
    try:
        if shutil.which(JUDGE_BIN) is None:
            return False
        rubric = judge_rubric(workspace)
        command = [
            JUDGE_BIN,
            "run",
            "--standalone",
            "--agent",
            JUDGE_AGENT,
            "-m",
            JUDGE_MODEL,
            rubric,
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=JUDGE_TIMEOUT,
            check=False,
        )
        if completed.returncode != 0:
            return False
        return _parse_judge_verdict(completed.stdout or "")
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    except Exception:  # noqa: BLE001 - a judge is a dep, a dep never crashes a gate
        return False


def gate5_judge(workspace, deps):
    evidence = []
    deps = deps or {}
    judge = deps.get("judge")
    if judge is None and deps.get("use_cli_judge"):
        judge = cli_judge
    if judge is None:
        evidence.append(
            "gate5_judge: skipped - missing dependency: no fresh-context judge "
            "provided (deps['judge'] is absent)"
        )
        return None, evidence
    try:
        verdict = judge(Path(workspace))
    except Exception as exc:  # noqa: BLE001 - a dep failure is gate evidence, not a crash
        return _fail(evidence, f"gate5_judge: failed - judge raised: {exc}")

    accepted = bool(verdict)
    reason = ""
    if isinstance(verdict, dict):
        accepted = bool(verdict.get("accepted", verdict.get("ok", False)))
        reason = str(verdict.get("reason", ""))

    if not accepted:
        msg = "gate5_judge: failed - judge rejected the final sample"
        if reason:
            msg += f": {reason}"
        return _fail(evidence, msg)
    msg = "gate5_judge: ok - independent judge accepted the final sample"
    if reason:
        msg += f": {reason}"
    evidence.append(msg)
    return True, evidence


GATES = (
    ("gate1_assets", gate1_assets),
    ("gate2_sift", gate2_sift),
    ("gate3_okf", gate3_okf),
    ("gate4_render", gate4_render),
    ("gate5_judge", gate5_judge),
)


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #
def run(workspace, dry_run=False, deps=None):
    """Run all five gates, write 05_verify/step_05.json, return a step payload.

    Gate 5 is dependency-driven: pass ``deps={"judge": callable}`` for a fake or
    custom judge, or ``deps={"use_cli_judge": True}`` to wire in
    :func:`cli_judge`.  With neither, gate 5 is skipped - tests never shell out
    and never touch the network.
    """
    workspace = Path(workspace)
    deps = deps or {}
    started_at = _now()
    evidence = []
    errors = []
    results = []
    failed = False
    skipped = False

    for name, gate in GATES:
        if dry_run:
            evidence.append(f"{name}: would run (dry run)")
            results.append({"gate": name, "status": "skipped", "evidence": []})
            continue
        try:
            ok, gate_evidence = gate(workspace, deps)
        except Exception as exc:  # noqa: BLE001 - never raise out of run()
            ok, gate_evidence = False, [f"{name}: failed - unexpected error: {exc}"]
        if ok is None:
            status = "skipped"
            skipped = True
            detail = gate_evidence[-1] if gate_evidence else f"{name}: skipped"
            detail = detail.split(" - ", 1)[-1] if " - " in detail else "missing dependency"
            errors.append(f"{name}: skipped - {detail}")
        elif ok:
            status = "ok"
        else:
            status = "failed"
            failed = True
        evidence.extend(gate_evidence)
        results.append({"gate": name, "status": status, "evidence": list(gate_evidence)})

    if dry_run:
        status = "skipped"
    elif failed:
        status = "failed"
    elif skipped:
        status = "skipped"
    else:
        status = "ok"

    if not dry_run:
        evidence.append("gates: " + ", ".join(f"{r['gate']}={r['status']}" for r in results))

    payload = {
        "stage": STAGE,
        "stage_name": STAGE_NAME,
        "step_type": STEP_TYPE,
        "status": status,
        "started_at": started_at,
        "finished_at": _now(),
        "inputs": {"workspace": str(workspace.resolve())},
        "outputs": [],
        "evidence": list(evidence),
        "errors": errors,
        "gates": results,
    }

    if not dry_run:
        step_path = workspace / STEP_FILE[0] / STEP_FILE[1]
        try:
            step_path.parent.mkdir(parents=True, exist_ok=True)
            step_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            payload["outputs"] = [str(step_path)]
        except OSError as exc:
            payload["status"] = "failed"
            status = "failed"
            payload["errors"] = errors + [f"cannot write {step_path}: {exc}"]

    payload["ok"] = status == "ok"
    return payload


if __name__ == "__main__":  # pragma: no cover - manual smoke run
    import sys

    result = run(Path(sys.argv[1] if len(sys.argv) > 1 else "."), dry_run="--dry-run" in sys.argv)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)
