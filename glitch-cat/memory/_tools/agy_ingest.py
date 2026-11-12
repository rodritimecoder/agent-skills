#!/usr/bin/env python3
"""agy_ingest — ingest Antigravity (agy) session transcripts into Memory Layer 1.

Scans Antigravity conversation brain directories:
  ~/.gemini/antigravity-cli/brain/*/
  ~/.t3/userdata/providers/antigravity/*/antigravity-acp/brain/*/

Extracts tool execution steps and maps them to standard memory events:
  run_command           -> action="bash", cmd=...
  view_file             -> action="read", path=...
  replace_file_content  -> action="edit", path=...
  write_to_file         -> action="write", path=...
  other tools           -> action=<tool_name>, path/cmd=...

Outputs to:
  $MEMORY_ROOT/01_transcripts/<project>/<sessionID>.jsonl

Maintains .agy_state.json so runs are incremental and idempotent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mem import root_path  # noqa: E402

MAX_FIELD = 400
PRIVATE_RE = re.compile(r"<private>[\s\S]*?</private>", re.IGNORECASE)
SECRET_RE = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
)
STATE_FILE = ".agy_state.json"

READ_TOOLS = {"read", "grep", "glob", "list", "search", "view_file"}


def scrub(text: Any) -> str:
    if not isinstance(text, str) or not text:
        return ""
    clean = PRIVATE_RE.sub("[private]", text)
    clean = SECRET_RE.sub("[redacted]", clean)
    if len(clean) > MAX_FIELD:
        return clean[:MAX_FIELD] + "…"
    return clean


def unwrap_val(val: Any) -> Any:
    if isinstance(val, str):
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            try:
                return json.loads(val)
            except Exception:
                return val[1:-1]
    return val


def find_brain_dirs(explicit: list[str] | None = None) -> list[Path]:
    dirs: list[Path] = []
    if explicit:
        for p in explicit:
            resolved = Path(p).expanduser().resolve()
            if resolved.is_dir():
                dirs.append(resolved)
        return dirs

    # Standard Antigravity locations
    cli_brain = Path.home() / ".gemini" / "antigravity-cli" / "brain"
    if cli_brain.is_dir():
        dirs.append(cli_brain)

    t3_agy = Path.home() / ".t3" / "userdata" / "providers" / "antigravity"
    if t3_agy.is_dir():
        for acp_brain in t3_agy.glob("*/antigravity-acp/brain"):
            if acp_brain.is_dir():
                dirs.append(acp_brain)

    return dirs


def load_state(root: Path) -> dict[str, dict]:
    state_file = root / "01_transcripts" / STATE_FILE
    if state_file.is_file():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(root: Path, state: dict[str, dict]) -> None:
    state_file = root / "01_transcripts" / STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def detect_project(steps: list[dict]) -> str:
    # 1. Search Cwd in run_command calls
    for s in steps:
        for tc in s.get("tool_calls") or []:
            args = tc.get("args") or {}
            cwd = unwrap_val(args.get("Cwd"))
            if isinstance(cwd, str) and cwd and cwd != "/home/rodri" and cwd != str(Path.home()):
                name = Path(cwd).name
                if name:
                    return name

    # 2. Search target files / absolute paths
    for s in steps:
        for tc in s.get("tool_calls") or []:
            args = tc.get("args") or {}
            p = unwrap_val(args.get("TargetFile") or args.get("AbsolutePath"))
            if isinstance(p, str) and p:
                parts = Path(p).parts
                if len(parts) >= 3:
                    # Take parent folder name
                    candidate = parts[-2]
                    if candidate and candidate not in (".", "..", "tmp"):
                        return candidate

    return "global"


def parse_transcript_events(
    transcript_file: Path,
    seen_reads: set[str],
    last_step: int = -1
) -> tuple[list[dict], int, str]:
    events: list[dict] = []
    max_step = last_step
    project = "global"

    try:
        raw_lines = transcript_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return [], last_step, project

    steps: list[dict] = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            steps.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not steps:
        return [], last_step, project

    project = detect_project(steps)

    for i, step in enumerate(steps):
        step_idx = step.get("step_index", i)
        if step_idx <= last_step:
            continue
        if step_idx > max_step:
            max_step = step_idx

        tool_calls = step.get("tool_calls") or []
        if not tool_calls:
            continue

        created_at = step.get("created_at") or ""
        # Check next step for execution status / result if available
        next_step = steps[i + 1] if i + 1 < len(steps) else {}
        ok = next_step.get("status") != "ERROR"
        err = ""
        if not ok:
            err = scrub(str(next_step.get("content") or "tool error"))

        for tc in tool_calls:
            name = str(tc.get("name") or "").lower()
            args = tc.get("args") or {}

            # Action mapping
            action = name
            if name == "run_command":
                action = "bash"
            elif name in ("view_file", "read_file"):
                action = "read"
            elif name in ("replace_file_content", "edit_file"):
                action = "edit"
            elif name in ("write_to_file", "create_file"):
                action = "write"
            elif name == "search_web":
                action = "search"

            path_val = unwrap_val(
                args.get("TargetFile") or args.get("AbsolutePath") or
                args.get("filePath") or args.get("path") or args.get("file")
            )
            cmd_val = unwrap_val(
                args.get("CommandLine") or args.get("command") or
                args.get("cmd") or args.get("script")
            )
            note_val = unwrap_val(args.get("toolSummary") or args.get("toolAction"))

            # Dedup read tools per session
            if action in READ_TOOLS and isinstance(path_val, str) and path_val:
                key = f"{action}:{path_val}"
                if key in seen_reads:
                    continue
                seen_reads.add(key)

            ev: dict[str, Any] = {
                "ts": created_at,
                "action": action,
                "ok": ok,
            }
            if isinstance(path_val, str) and path_val:
                ev["path"] = scrub(path_val)
            if isinstance(cmd_val, str) and cmd_val:
                ev["cmd"] = scrub(cmd_val)
            if err:
                ev["err"] = err
            if isinstance(note_val, str) and note_val:
                ev["note"] = scrub(note_val)

            # Drop bare tools without context
            if not ev.get("path") and not ev.get("cmd") and not ev.get("err") and not ev.get("note"):
                continue

            events.append(ev)

    return events, max_step, project


def ingest_all(
    root: Path,
    brain_dirs: list[Path],
    force: bool = False,
    verbose: bool = False,
) -> tuple[int, int]:
    state = {} if force else load_state(root)
    total_events = 0
    sessions_updated = 0

    transcripts_dir = root / "01_transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    for bdir in brain_dirs:
        for t_file in bdir.glob("*/.system_generated/logs/transcript.jsonl"):
            session_id = t_file.parents[2].name
            try:
                mtime = t_file.stat().st_mtime
            except OSError:
                continue

            prev = state.get(session_id, {})
            last_step = -1 if force else prev.get("last_step", -1)
            prev_mtime = prev.get("mtime", 0)

            # Skip unchanged files unless forced
            if not force and mtime <= prev_mtime and last_step >= 0:
                continue

            seen_reads: set[str] = set()
            events, new_max_step, project = parse_transcript_events(t_file, seen_reads, last_step)

            if events:
                out_dir = transcripts_dir / project
                out_dir.mkdir(parents=True, exist_ok=True)
                out_file = out_dir / f"{session_id}.jsonl"

                mode = "w" if force else "a"
                with out_file.open(mode, encoding="utf-8") as fh:
                    for ev in events:
                        fh.write(json.dumps(ev) + "\n")

                total_events += len(events)
                sessions_updated += 1
                if verbose:
                    print(f"  ingested {len(events)} events from {session_id} ({project})")

            state[session_id] = {
                "mtime": mtime,
                "last_step": new_max_step,
                "events_count": prev.get("events_count", 0) + len(events),
                "project": project,
            }

    save_state(root, state)
    return total_events, sessions_updated


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", help="memory root directory (default $MEMORY_ROOT or ~/.memory)")
    p.add_argument("--brain-dir", action="append", help="explicit Antigravity brain directory (repeatable)")
    p.add_argument("--force", action="store_true", help="re-ingest all sessions from start")
    p.add_argument("-v", "--verbose", action="store_true", help="verbose output")
    args = p.parse_args()

    root = root_path(args.root)
    brain_dirs = find_brain_dirs(args.brain_dir)
    if not brain_dirs:
        print("agy_ingest: no Antigravity brain directories found.")
        return 0

    total_events, sessions = ingest_all(root, brain_dirs, force=args.force, verbose=args.verbose)
    print(f"agy_ingest: processed {total_events} new event(s) across {sessions} session(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
