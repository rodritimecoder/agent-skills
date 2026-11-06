#!/usr/bin/env python3
"""Real dependencies for academic-pipeline-v2 stages 1 and 2.

The lanes (``stage1_canvas``, ``stage1_zoom``, ``stage2_sift``) never touch the
network or a subprocess themselves: every external call arrives through a
``deps`` dict.  This module builds those dicts for a real course.

Adapters provided:

* :func:`canvas_source` - ``canvas(query) -> [item]`` backed by ``canvas-cli``
* :func:`stage1_deps`   - canvas + classifier + Zoom recording stream
* :func:`stage2_deps`   - text classifier for the sift lane
* :func:`course_name`   - Canvas course name for ``meta.json``

Two facts about this Canvas instance shape the implementation:

1. The Pages tool is disabled course-wide, so ``/pages/*`` returns 404 and a
   module item of type ``Page`` yields a title and nothing else.  Such items
   are still ingested (they are the constellation's nodes) but carry a note
   saying the body was unreachable, and the sift classifier routes them to
   ``review`` rather than pretending they are content.
2. ``File`` module items are readable one-by-one through ``/files/<id>``, so
   those are downloaded and converted with ``markitdown-cli``.

Model use is opportunistic: when the decision service on :8083 answers, the
ambiguous items are put to it; when it does not, deterministic rules decide and
the evidence says so.  ``PIPELINE_JEV=1`` forces the model path,
``PIPELINE_JEV=0`` forbids it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

CANVAS_CLI = "canvas-cli"
MARKITDOWN_CLI = "markitdown-cli"
JEV_BIN = "jev"
JEV_TIMEOUT = 60
CLI_TIMEOUT = 180
DOWNLOAD_TIMEOUT = 120

WEEK_RE = re.compile(r"\bweek[ _-]*(\d{1,2})\b", re.IGNORECASE)

ADMIN_TITLE_RE = re.compile(
    r"(learning guide|subject overview|subject outline|getting started"
    r"|\bwelcome\b|\bannouncement\b|\bquiz\b|\bassessment\b|\bmarking\b"
    r"|\bplagiarism\b|\bfaq\b|textbook|orientation|how to )",
    re.IGNORECASE,
)

TUTORIAL_TITLE_RE = re.compile(
    r"(tutorial|\blab\b|solutions?\b|worked|answers\b|recap)",
    re.IGNORECASE,
)

PAGE_BODY_UNAVAILABLE = (
    "Canvas Pages is disabled for this course, so this item's body is not "
    "readable through the API; only its title is stored."
)

# Files the pipeline writes into 01_ingest itself.  They are scaffolding, not
# course material, and must never be sifted or rendered as notes.
PIPELINE_ARTEFACT_NAMES = {"CONTEXT.md", "STATE.md", ".agent_state.json"}

# Items whose body is missing still deserve review, not silent acceptance.
THIN_BODY_CHARS = 200


def _json_command(args, timeout=CLI_TIMEOUT):
    """Run a CLI that prints JSON and return the decoded payload."""
    completed = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args[:2])} failed ({completed.returncode}): "
            f"{(completed.stderr or completed.stdout).strip()[:400]}"
        )
    text = (completed.stdout or "").strip()
    if not text:
        return []
    return json.loads(text)


def _strip_html(raw):
    """Reduce an HTML fragment to readable text, keeping paragraph breaks."""
    if not raw:
        return ""
    text = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6])>", "\n\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def course_name(course_id):
    """Return the Canvas course name for ``course_id``."""
    courses = _json_command(
        [CANVAS_CLI, "-f", "json", "--project", "id,name", "courses"]
    )
    for course in courses or []:
        if str(course.get("id")) == str(course_id):
            return str(course.get("name") or f"course {course_id}")
    raise RuntimeError(f"course {course_id} not found in Canvas enrollments")


class CanvasCourse:
    """Thin, cached reader over one Canvas course."""

    def __init__(self, course_id):
        self.course_id = str(course_id)
        self._modules = None
        self._items = {}
        self._file_cache = {}
        self._asset_dir = None

    # -- discovery ---------------------------------------------------------
    def modules(self):
        if self._modules is None:
            self._modules = _json_command(
                [CANVAS_CLI, "-f", "json", "modules", self.course_id]
            )
        return self._modules or []

    def module_items(self, module_id):
        key = str(module_id)
        if key not in self._items:
            self._items[key] = _json_command(
                [
                    CANVAS_CLI,
                    "-f",
                    "json",
                    "modules",
                    self.course_id,
                    "--module-id",
                    key,
                    "--items",
                ]
            )
        return self._items[key] or []

    def assignments(self):
        if "_assignments" not in self._items:
            self._items["_assignments"] = _json_command(
                [
                    CANVAS_CLI,
                    "-f",
                    "json",
                    "--project",
                    "id,name,description",
                    "assignments",
                    self.course_id,
                ]
            )
        return self._items["_assignments"] or []

    # -- files -------------------------------------------------------------
    def file_meta(self, file_id):
        key = str(file_id)
        if key not in self._file_cache:
            self._file_cache[key] = _json_command(
                [
                    CANVAS_CLI,
                    "-f",
                    "json",
                    "files",
                    self.course_id,
                    "--file-id",
                    key,
                ]
            )
        return self._file_cache[key] or {}

    def download(self, file_id, asset_dir):
        """Download one course file into ``asset_dir`` and return its path."""
        meta = self.file_meta(file_id)
        url = meta.get("url")
        if not url:
            raise RuntimeError(f"file {file_id} has no download url")
        name = meta.get("display_name") or meta.get("filename") or f"{file_id}.bin"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or f"{file_id}.bin"
        asset_dir = Path(asset_dir)
        asset_dir.mkdir(parents=True, exist_ok=True)
        target = asset_dir / safe
        if target.is_file() and target.stat().st_size:
            return target, meta
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response:
            payload = response.read()
        target.write_bytes(payload)
        return target, meta

    def file_markdown(self, file_id, asset_dir):
        """Download a file and convert it to Markdown with markitdown-cli."""
        path, meta = self.download(file_id, asset_dir)
        if shutil.which(MARKITDOWN_CLI) is None:
            return "", meta
        completed = subprocess.run(
            [MARKITDOWN_CLI, str(path), "--no-metadata"],
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT,
            check=False,
        )
        if completed.returncode != 0:
            return "", meta
        return (completed.stdout or "").strip(), meta


def _week_of(module_name):
    match = WEEK_RE.search(str(module_name))
    return int(match.group(1)) if match else None


def _kind_of(title):
    return "tutorial" if TUTORIAL_TITLE_RE.search(str(title)) else "topic"


def _item_id(prefix, raw):
    return f"{prefix}-{raw}"


def canvas_source(course_id, asset_dir=None, include_files=True, on_event=None):
    """Return ``canvas(query) -> [item]`` for one course.

    Items are keyed by week.  Modules that carry no week number (``Get started``,
    ``Refreshing your Maths``) are offered to week 1 as kind ``admin`` so the
    classifier is the thing that drops them, rather than the adapter.
    """
    course = CanvasCourse(course_id)
    asset_dir = Path(asset_dir) if asset_dir else None
    by_week = {}
    admin_items = []

    for module in course.modules():
        week = _week_of(module.get("name"))
        bucket = None
        for raw in course.module_items(module.get("id")):
            item_type = str(raw.get("type") or "")
            if item_type == "SubHeader":
                continue
            title = str(raw.get("title") or "").strip()
            if not title:
                continue

            body = ""
            body_status = ""
            kind = _kind_of(title)
            if item_type == "Page":
                item_type = "page"
                body_status = PAGE_BODY_UNAVAILABLE
            elif item_type == "File":
                item_type = "file"
                if include_files and asset_dir is not None and raw.get("content_id"):
                    try:
                        body, meta = course.file_markdown(raw["content_id"], asset_dir)
                        if body:
                            title = title or meta.get("display_name", "")
                        if on_event:
                            on_event(f"converted {title or raw.get('content_id')}")
                    except Exception as exc:  # noqa: BLE001 - evidence, not a crash
                        body = ""
                        if on_event:
                            on_event(f"file {raw.get('id')} failed: {exc}")
            elif item_type == "Assignment":
                item_type = "assignment"
                body = ""
            else:
                item_type = item_type.lower() or "item"

            entry = {
                "id": _item_id("canvas", raw.get("id")),
                "title": title,
                "type": item_type,
                "kind": kind,
                "week": week,
                "url": raw.get("html_url") or raw.get("external_url") or "",
                "body": body,
                "body_status": body_status,
            }
            if week is None:
                admin_items.append(entry)
            else:
                by_week.setdefault(week, []).append(entry)

    for assignment in course.assignments():
        name = str(assignment.get("name") or "").strip()
        if not name:
            continue
        match = WEEK_RE.search(name)
        entry = {
            "id": _item_id("assignment", assignment.get("id")),
            "title": name,
            "type": "assignment",
            "kind": _kind_of(name),
            "week": int(match.group(1)) if match else None,
            "url": "",
            "body": _strip_html(assignment.get("description") or ""),
        }
        if entry["week"] is None:
            admin_items.append(entry)
        else:
            by_week.setdefault(entry["week"], []).append(entry)

    def canvas(query):
        week = int(query.get("week") or 1)
        items = list(by_week.get(week, []))
        if week == 1:
            items.extend(admin_items)
        return items

    return canvas


# --------------------------------------------------------------------------- #
# classifiers
# --------------------------------------------------------------------------- #
class DecisionService:
    """Opportunistic access to the local decision model on :8083."""

    def __init__(self, port=None):
        self.port = int(port or os.environ.get("PIPELINE_JEV_PORT") or 8083)
        self._state = None
        self.calls = 0

    @property
    def available(self):
        if self._state is None:
            forced = os.environ.get("PIPELINE_JEV", "").strip().lower()
            if forced in ("0", "false", "no"):
                self._state = False
            elif forced in ("1", "true", "yes"):
                self._state = True
            else:
                self._state = self._healthy()
        return self._state

    def _healthy(self):
        if shutil.which(JEV_BIN) is None:
            return False
        try:
            completed = subprocess.run(
                [JEV_BIN, "--port", str(self.port), "doctor"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0

    def ask_bool(self, context, question):
        """Ask one boolean question; ``None`` when the model cannot answer."""
        if not self.available:
            return None
        try:
            completed = subprocess.run(
                [
                    JEV_BIN,
                    "--port",
                    str(self.port),
                    "--json",
                    "bool",
                    "--context",
                    context,
                    "--question",
                    question,
                ],
                capture_output=True,
                text=True,
                timeout=JEV_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            self._state = False
            return None
        if completed.returncode != 0:
            return None
        self.calls += 1
        try:
            payload = json.loads(completed.stdout or "{}")
        except ValueError:
            return None
        for key in ("answer", "value", "label", "result"):
            value = payload.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lower() in ("true", "yes", "1"):
                return True
            if isinstance(value, str) and value.lower() in ("false", "no", "0"):
                return False
        return None


def _rule_admin(title):
    return bool(ADMIN_TITLE_RE.search(str(title)))


def make_item_classifier(service=None, budget=12):
    """Stage-1 classifier: ``item -> True`` means drop.

    Rules decide the clear cases.  The model is consulted only for an item that
    no rule matches and that carries no body, which is the ambiguous case in
    practice.  ``budget`` caps model calls so a 100-item course stays cheap.
    """
    service = service or DecisionService()
    left = {"n": int(budget)}
    log = []

    def classify(item):
        title = str(item.get("title") or "")
        body = str(item.get("body") or "")
        if item.get("kind") == "admin":
            log.append({"id": item.get("id"), "drop": True, "by": "kind=admin"})
            return True
        if _rule_admin(title):
            log.append({"id": item.get("id"), "drop": True, "by": "title rule"})
            return True
        if body.strip() and not item.get("body_status"):
            log.append({"id": item.get("id"), "drop": False, "by": "has body"})
            return False
        if left["n"] > 0 and service.available:
            verdict = service.ask_bool(
                context=f"Canvas course item titled: {title}",
                question=(
                    "Is this item administrative or orientation material rather "
                    "than course teaching content?"
                ),
            )
            if verdict is not None:
                left["n"] -= 1
                log.append({"id": item.get("id"), "drop": verdict, "by": "model"})
                return bool(verdict)
        log.append({"id": item.get("id"), "drop": False, "by": "default keep"})
        return False

    classify.log = log
    return classify


def make_text_classifier(service=None, budget=12):
    """Stage-2 classifier: ``{"id","text"} -> {"admin_fluff","confidence"}``."""
    service = service or DecisionService()
    left = {"n": int(budget)}
    log = []

    def classify(payload):
        text = str(payload.get("text") or "")
        title = next(
            (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("# ")),
            "",
        )
        body = text.split("\n", 1)[1] if "\n" in text else ""
        if _rule_admin(title):
            log.append({"id": payload.get("id"), "admin_fluff": True, "by": "title rule"})
            return {"admin_fluff": True, "confidence": 0.9}
        if len(body.strip()) >= THIN_BODY_CHARS:
            log.append({"id": payload.get("id"), "admin_fluff": False, "by": "body"})
            return {"admin_fluff": False, "confidence": 0.9}
        thin = {"admin_fluff": False, "confidence": 0.5}
        if not body.strip():
            log.append({"id": payload.get("id"), "admin_fluff": False, "by": "body unavailable"})
            return thin
        if left["n"] > 0 and service.available and body.strip():
            verdict = service.ask_bool(
                context=body.strip()[:1500],
                question="Is this text administrative rather than teaching content?",
            )
            if verdict is not None:
                left["n"] -= 1
                log.append({"id": payload.get("id"), "admin_fluff": verdict, "by": "model"})
                return {"admin_fluff": bool(verdict), "confidence": 0.85}
        log.append({"id": payload.get("id"), "admin_fluff": False, "by": "thin body"})
        return thin

    classify.log = log
    return classify


# --------------------------------------------------------------------------- #
# Zoom
# --------------------------------------------------------------------------- #
ZOOM_RE = re.compile(r"https?://[^\s)\"'<>]*zoom\.us/rec/(?:share|play)/[^\s)\"'<>]+", re.I)
PASSCODE_RE = re.compile(r"passcode[:\s]*([A-Za-z0-9!@#$%^&*._-]{4,})", re.I)


def zoom_recordings(course_id, extra_sources=()):
    """List Zoom recordings referenced by the course, with passcodes."""
    found = {}
    texts = list(extra_sources)

    course = CanvasCourse(course_id)
    for module in course.modules():
        for raw in course.module_items(module.get("id")):
            title = str(raw.get("title") or "")
            url = str(raw.get("external_url") or "")
            if url:
                texts.append(url)
            if "passcode" in title.lower():
                texts.append(title)

    for text in texts:
        for url in ZOOM_RE.findall(str(text)):
            passcode = ""
            match = PASSCODE_RE.search(str(text))
            if match:
                passcode = match.group(1)
            found.setdefault(url, {"id": url, "url": url, "passcode": passcode})
    return list(found.values())


def _default_asset_dir(workspace):
    return Path(workspace) / "01_ingest" / "_assets"


def stage1_deps(workspace, course_id, include_files=True, events=None):
    """Build the stage-1 ``deps`` dict for a real course."""
    workspace = Path(workspace)
    asset_dir = _default_asset_dir(workspace)
    service = DecisionService()
    recordings = zoom_recordings(course_id)
    notes = list(events or [])

    def list_recordings():
        return recordings

    def fetch(recording_id):
        """Download one recording's transcript + keyframes via zoom-recorder."""
        record = next((r for r in recordings if r["id"] == recording_id), None)
        if record is None:
            raise RuntimeError(f"unknown recording {recording_id}")
        out_dir = workspace / "01_ingest" / "_zoom"
        out_dir.mkdir(parents=True, exist_ok=True)
        command = [
            "zoom-recorder",
            "--url",
            record["url"],
            "--out-dir",
            str(out_dir),
            "--format",
            "all",
            "--keyframes",
            "--json",
        ]
        if record.get("passcode"):
            command.extend(["--passcode", record["passcode"]])
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=600, check=False
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"zoom-recorder failed for {recording_id}: "
                f"{(completed.stderr or completed.stdout).strip()[:300]}"
            )
        payload = json.loads(completed.stdout or "{}")
        vtt_path = payload.get("transcript") or payload.get("vtt")
        transcript = ""
        if vtt_path and Path(vtt_path).is_file():
            transcript = Path(vtt_path).read_text(encoding="utf-8", errors="replace")
        keyframes = payload.get("keyframes") or []
        if isinstance(keyframes, str):
            keyframes = [keyframes]
        return {"transcript_vtt": transcript, "keyframes": keyframes}

    return {
        "canvas": canvas_source(
            course_id,
            asset_dir=asset_dir,
            include_files=include_files,
            on_event=notes.append,
        ),
        "classify": make_item_classifier(service),
        "list_recordings": list_recordings,
        "fetch": fetch,
        "course": course_name(course_id),
        "_notes": notes,
        "_service": service,
    }


def stage2_deps(workspace=None):
    """Build the stage-2 ``deps`` dict (text classifier only)."""
    service = DecisionService()
    classify = make_text_classifier(service)
    return {"classify": classify, "_service": service}
