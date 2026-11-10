#!/usr/bin/env python3
"""observer — transcripts in, memory notes out.

The second agent from the top layer of the hierarchy: it watches the event log
and writes short, linkable observations. It never edits the wiki and never
touches the injected header.

Deterministic by default: no model call, same input gives the same note. The
salience heuristic keeps what would be painful to rediscover — failures, state
changing commands, edits — and drops reads of files it only glanced at.

`--llm` is opt-in and degrades to the heuristic when the local model is
offline. Salience is the one judgement the evidence says to leave to a model
(Anthropic, "components of agent memory": fixed rules cost Opus 5 -0.234), but
a missing model must never stop capture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mem import (MAX_HEADER_BYTES, MAX_HEADER_LINES, doc_id, dump_frontmatter,  # noqa: E402
                 reindex, root_path, slug)

STATE_FILE = ".observer_state.json"
MIN_EVENTS = 3
BATCH_EVENTS = 10

STATE_CHANGING = re.compile(
    r"\b(git (commit|push|merge|rebase)|rm |mv |mkdir |pytest|npm (i|install)|"
    r"pip install|apt install|systemctl|docker|rsync|chmod|sed -i)\b")


def load_state(root: Path) -> dict:
    path = root / "01_transcripts" / STATE_FILE
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_state(root: Path, state: dict) -> None:
    path = root / "01_transcripts" / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def read_events(path: Path, offset: int) -> tuple[list[dict], int]:
    events: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        fh.seek(offset)
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events, fh.tell()


def salient(event: dict) -> bool:
    """The floor: capture what would be expensive to rediscover."""
    if event.get("err"):
        return True
    if event.get("ok") is False:
        return True
    action = str(event.get("action") or event.get("tool") or "").lower()
    if action in ("edit", "write", "patch", "create"):
        return True
    cmd = str(event.get("cmd") or "")
    if STATE_CHANGING.search(cmd):
        return True
    return False


def llm_rank(events: list[dict], timeout: float = 20.0) -> list[dict]:
    """Ask the local model which events are worth remembering.

    Degrades to the whole list on any failure: capture must not depend on a
    server being up.
    """
    if not events:
        return events
    listing = "\n".join(
        f"{i}. tool={e.get('action') or e.get('tool')} path={e.get('path') or '-'} "
        f"cmd={(e.get('cmd') or '-')[:120]} err={(e.get('err') or '-')[:120]}"
        for i, e in enumerate(events))
    prompt = (
        "You are the observer of a coding agent's memory. Keep only the events a "
        "future session would be expensive to rediscover: decisions, failures and "
        "their causes, state changes, and non-obvious discoveries. Drop routine "
        "reads and repeated successes.\n\n"
        f"Events:\n{listing}\n\n"
        "Reply with only the kept indices as a comma separated list."
    )
    payload = json.dumps({"model": "local", "prompt": prompt, "max_tokens": 200}).encode()
    req = urllib.request.Request("http://127.0.0.1:8080/v1/completions", data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = json.loads(resp.read().decode()).get("choices", [{}])[0].get("text", "")
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
        return events
    keep = {int(n) for n in re.findall(r"\d+", text)}
    if not keep:
        return events
    return [e for i, e in enumerate(events) if i in keep]


def summarise(events: list[dict]) -> tuple[str, dict]:
    files: dict[str, str] = {}
    commands: list[str] = []
    failures: list[str] = []
    notes: list[str] = []
    for event in events:
        path = event.get("path")
        if path:
            files[path] = str(event.get("action") or event.get("tool") or "touch")
        cmd = str(event.get("cmd") or "").strip()
        if cmd:
            commands.append(cmd)
        err = str(event.get("err") or "").strip()
        if err:
            failures.append(f"{cmd or path or 'step'} → {err[:180]}")
        note = str(event.get("note") or "").strip()
        if note:
            notes.append(note)

    lines = []
    if files:
        lines.append("## Files")
        for path, action in sorted(files.items()):
            lines.append(f"- `{path}` — {action}")
    if commands:
        lines.append("\n## Commands")
        for cmd in commands[:20]:
            lines.append(f"- `{cmd[:160]}`")
    if failures:
        lines.append("\n## Failures")
        for fail in failures[:10]:
            lines.append(f"- {fail}")
    if notes:
        lines.append("\n## Discoveries")
        for note in notes[:10]:
            lines.append(f"- {note}")

    meta_bits = {
        "files": sorted(files),
        "commands": commands[:20],
        "failures": failures[:10],
        "events": len(events),
    }
    return "\n".join(lines), meta_bits


def observe(root: Path, project: str | None, use_llm: bool, force: bool) -> int:
    transcripts = root / "01_transcripts"
    if not transcripts.is_dir():
        sys.exit(f"❌ observer: no transcript log at {transcripts}")
    state = load_state(root)
    written = 0

    for path in sorted(transcripts.rglob("*.jsonl")):
        rel = str(path.relative_to(root))
        offset = 0 if force else int(state.get(rel, {}).get("offset", 0))
        events, new_offset = read_events(path, offset)
        if not events:
            continue
        state[rel] = {"offset": new_offset, "checked": time.time()}
        if len(events) < MIN_EVENTS and not any(salient(e) for e in events):
            continue

        chosen = [e for e in events if salient(e)]
        if use_llm:
            chosen = llm_rank(chosen)
        if not chosen:
            continue

        body, meta_bits = summarise(chosen)
        if not body.strip():
            continue
        day = time.strftime("%Y-%m-%d")
        session = path.stem
        folder = root / "02_notes" / (project or path.parent.name or "global")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{day}-session-{slug(session)}.md"

        digest = hashlib.sha1(
            (body + rel + str(new_offset)).encode()).hexdigest()[:8]
        meta = {
            "id": f"{slug(folder.name)[:12]}-{digest}",
            "title": f"Session {session} ({len(chosen)} salient / {len(events)} events)",
            "type": "session",
            "project": folder.name,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": "observer",
            "entities": sorted({_entity(f) for f in meta_bits["files"] if _entity(f)}),
            "sources": [rel],
            "confidence": 0.7,
            "verified": False,
        }
        header = dump_frontmatter(meta)
        if target.exists():
            target = folder / f"{day}-session-{slug(session)}-{digest}.md"
        target.write_text(f"{header}\n# {meta['title']}\n\n{body}\n", encoding="utf-8")
        written += 1

    save_state(root, state)
    if written:
        reindex(root, quiet=True)
    print(f"👁️  observer: {written} note(s) written"
          f"{' (llm salience)' if use_llm else ' (heuristic salience)'}")
    return 0


def _entity(path: str) -> str:
    name = Path(path).name
    return name if name and not name.startswith(".") else ""


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="observer", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root")
    p.add_argument("--project")
    p.add_argument("--llm", action="store_true",
                   help="let the local model judge salience (falls back on failure)")
    p.add_argument("--force", action="store_true", help="re-read from the start")
    p.add_argument("--limit-bytes", type=int, default=MAX_HEADER_BYTES)
    a = p.parse_args(argv)
    sys.exit(observe(root_path(a.root), a.project, a.llm, a.force))


if __name__ == "__main__":
    main()
