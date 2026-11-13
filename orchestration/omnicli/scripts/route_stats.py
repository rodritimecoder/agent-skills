#!/usr/bin/env python3
"""Bypass metrics for the omnicli-route plugin.

Reads ~/.local/share/omnicli/route.jsonl (one row per tool call) and reports,
per session: native calls, catalogue calls, skill-directory hits, denials, and
whether the session consulted the catalogue before reaching into a skill dir.

    python3 scripts/route_stats.py
    python3 scripts/route_stats.py --json
    python3 scripts/route_stats.py --log /tmp/route.jsonl

A "tool-shaped" session is one with a catalogue call or a skill-directory hit.
The bypass rate is tool-shaped sessions with skill hits and zero catalogue calls
divided by all tool-shaped sessions with skill hits.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_LOG = Path(os.path.expanduser("~/.local/share/omnicli/route.jsonl"))


def load(path: Path) -> list[dict]:
    rows = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return rows


def summarise(rows: list[dict]) -> dict:
    sessions: dict[str, dict] = defaultdict(
        lambda: {"native": 0, "omnicli": 0, "skill_hits": 0, "denied": 0}
    )
    for row in rows:
        session = sessions[str(row.get("session") or "unknown")]
        if row.get("kind") == "omnicli":
            session["omnicli"] += 1
            continue
        session["native"] += 1
        if row.get("skills"):
            session["skill_hits"] += 1
        if row.get("decision") == "deny":
            session["denied"] += 1

    tool_shaped = [s for s in sessions.values() if s["skill_hits"] or s["omnicli"]]
    with_hits = [s for s in tool_shaped if s["skill_hits"]]
    bypass = [s for s in with_hits if s["omnicli"] == 0]
    rate = (len(bypass) / len(with_hits)) if with_hits else None
    return {
        "log": str(DEFAULT_LOG),
        "sessions": len(sessions),
        "tool_shaped": len(tool_shaped),
        "sessions_with_skill_hits": len(with_hits),
        "bypass_sessions": len(bypass),
        "bypass_rate": rate,
        "native_calls": sum(s["native"] for s in sessions.values()),
        "omnicli_calls": sum(s["omnicli"] for s in sessions.values()),
        "denials": sum(s["denied"] for s in sessions.values()),
        "detail": {k: dict(v) for k, v in sessions.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    rows = load(args.log)
    summary = summarise(rows)
    summary["log"] = str(args.log)

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print(f"omnicli-route  log={args.log}  rows={len(rows)}")
    print(f"  sessions            {summary['sessions']}")
    print(f"  tool-shaped         {summary['tool_shaped']}")
    print(f"  skill-dir hits      {summary['sessions_with_skill_hits']} session(s)")
    print(f"  catalogue calls     {summary['omnicli_calls']}")
    print(f"  native calls        {summary['native_calls']}")
    print(f"  denials             {summary['denials']}")
    rate = summary["bypass_rate"]
    print(f"  bypass rate         {'n/a' if rate is None else f'{rate:.0%}'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
