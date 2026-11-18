#!/usr/bin/env python3
"""notes-index — ranked local search over a Markdown notes folder.

Derives from Kem Glitch's "Half the Tokens" artifact
(https://claude.ai/artifact/MdwChkFxkCKwwnToGVJXGX, reel DezGALzNCuf).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "modules"))

from notes_index_core import (  # noqa: E402
    DEFAULT_CHUNK,
    DEFAULT_LIMIT,
    LEVER_NAMES,
    LockBusy,
    NotesIndex,
    apply_rule,
    install_timer,
    plan,
    rule_block,
    timer_status,
    uninstall_timer,
)
from cite_check import check as check_citations, render as render_citations  # noqa: E402


def _project(obj, fields):
    """Project a dict or list-of-dicts to comma-separated field names.

    Unknown names are reported on stderr with the available keys and skipped,
    so a mistyped field never crashes the command.
    """
    if not fields:
        return obj
    requested = [f.strip() for f in fields.split(",") if f.strip()]
    if not requested:
        return obj
    if isinstance(obj, dict):
        available = list(obj)
        unknown = [f for f in requested if f not in obj]
        if unknown:
            print(f"warning: unknown field(s): {', '.join(unknown)}; available: {', '.join(available)}",
                  file=sys.stderr)
        return {k: obj[k] for k in requested if k in obj}
    if isinstance(obj, list) and obj and all(isinstance(row, dict) for row in obj):
        available = list(obj[0])
        unknown = [f for f in requested if f not in available]
        if unknown:
            print(f"warning: unknown field(s): {', '.join(unknown)}; available: {', '.join(available)}",
                  file=sys.stderr)
        return [{k: row[k] for k in requested if k in row} for row in obj]
    return obj


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notes-index",
        description="Build and query a local FTS5 index over a Markdown notes folder.",
    )
    parser.add_argument("--folder", default=".", help="Notes folder to index (default: current directory)")
    parser.add_argument("--db", default=None, help="Path to the SQLite index file (default: <folder>/notes.db)")
    parser.add_argument("--chunk", type=int, default=DEFAULT_CHUNK, metavar="N", help="Characters per raw row (default: 4000)")
    parser.add_argument("--workers", type=int, default=6, metavar="WORKERS", help="Parallel summarizer calls (default: 6)")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--folder", default=argparse.SUPPRESS)
    common.add_argument("--db", default=argparse.SUPPRESS)
    common.add_argument("--chunk", type=int, default=argparse.SUPPRESS, metavar="N")
    common.add_argument("--workers", type=int, default=argparse.SUPPRESS, metavar="WORKERS")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", parents=[common], help="Scaffold the index, the CLAUDE.md rule and the timer")
    p_init.add_argument("--yes", action="store_true", help="Run the first full ingest without confirmation")
    p_init.add_argument("--rule-variant", default="full", choices=["full", "lean", "trust-snippet"])
    p_init.add_argument("--target", default="agents", choices=["agents", "claude"], help="Rule file to write (default: AGENTS.md)")
    p_init.add_argument("--lever", action="append", choices=list(LEVER_NAMES), default=None, help="Add one optimisation lever to the rule (repeatable)")
    p_init.add_argument("--timer", action="store_true", help="Install the 6-hour refresh timer")
    p_init.add_argument("--every-hours", type=int, default=6, metavar="N")
    p_init.add_argument("--no-summaries", action="store_true", help="Index raw and note rows only")
    p_init.add_argument("--dry-run", action="store_true",
                        help="Print the planned init and exit without writing any file")

    p_update = sub.add_parser("update", parents=[common], help="Re-index new, changed and removed notes")
    p_update.add_argument("--strict", action="store_true", help="Treat summary failures as run failures")
    p_update.add_argument("--no-summaries", action="store_true", help="Skip the summarizer pass")
    p_update.add_argument("--dry-run", action="store_true",
                          help="Print the planned re-index and exit without writing any file")

    p_search = sub.add_parser("search", parents=[common], help="Rank notes against a query")
    p_search.add_argument("words", nargs="+", help="Query words")
    p_search.add_argument("--after", default=None, help="Only notes dated on/after YYYY-MM-DD")
    p_search.add_argument("--limit", type=int, default=DEFAULT_LIMIT, metavar="LIMIT", help="Hits to print (default: 5)")
    p_search.add_argument("--fields", metavar="NAME[,NAME...]", default=None,
                          help="Project each ranked hit to these fields (comma-separated)")

    sub.add_parser("status", parents=[common], help="Files, rows, freshness and last error")

    p_plan = sub.add_parser("plan", parents=[common], help="Estimate the one-off first pass")

    p_rule = sub.add_parser("rule", parents=[common], help="Print or apply the CLAUDE.md rule block")
    p_rule.add_argument("--apply", action="store_true", help="Write the block into <folder>/CLAUDE.md")
    p_rule.add_argument("--variant", default="full", choices=["full", "lean", "trust-snippet"])
    p_rule.add_argument("--target", default="agents", choices=["agents", "claude"], help="Rule file to write (default: AGENTS.md)")
    p_rule.add_argument("--lever", action="append", choices=list(LEVER_NAMES), default=None, help="Add one optimisation lever to the rule (repeatable)")

    p_timer = sub.add_parser("timer", parents=[common], help="Manage the refresh timer")
    p_timer.add_argument("action", choices=["install", "status", "uninstall"])
    p_timer.add_argument("--every-hours", type=int, default=6, metavar="N")

    p_cite = sub.add_parser("cite", parents=[common], help="Prove an answer's citations: paths resolve, lines exist, quotes are verbatim")
    p_cite.add_argument("file", help="Markdown answer to check")
    p_cite.add_argument("--root", default=None, help="Base folder for relative citations (default: the answer's folder)")
    p_cite.add_argument("--transcript", default=None, help="Transcript for [MM:SS] citations (default: transcript.md beside the answer)")
    p_cite.add_argument("--strict-lines", action="store_true", help="Require a quote to sit inside the cited line range")
    p_cite.add_argument("--coverage-chars", type=int, default=80, metavar="N", help="Flag uncited prose blocks at or above this length (default: 80)")
    p_cite.add_argument("--fail-on-warn", action="store_true", help="Treat uncited paragraphs as failures")

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "dry_run", False):
        plan = {"command": args.command, "dry_run": True, "folder": args.folder}
        for key in ("yes", "rule_variant", "target", "timer", "every_hours",
                    "no_summaries", "strict"):
            if hasattr(args, key):
                plan[key] = getattr(args, key)
        print(json.dumps(plan, indent=2) if args.json else
              f"[dry-run] {args.command}: {json.dumps(plan, sort_keys=True)}")
        return 0
    folder = Path(args.folder).expanduser().resolve()

    if args.command == "cite":
        try:
            report = check_citations(
                Path(args.file),
                root=Path(args.root) if args.root else None,
                transcript=Path(args.transcript) if args.transcript else None,
                strict_lines=args.strict_lines,
                coverage_chars=args.coverage_chars,
            )
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(render_citations(report))
        if not report["pass"]:
            return 1
        if args.fail_on_warn and report["warnings"]:
            return 1
        return 0

    index = NotesIndex(folder, db_path=Path(args.db) if args.db else None, chunk=args.chunk, workers=args.workers)
    script = Path(__file__).resolve()

    try:
        if args.command == "plan":
            result = plan(folder, chunk=args.chunk)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"folder        : {result['folder']}")
                print(f"notes found   : {result['files']}")
                print(f"to summarise  : {result['long_files']} (files over {args.chunk} chars)")
                print(f"est. minutes  : {result['estimated_minutes']}")
            return 0

        if args.command == "init":
            result = plan(folder, chunk=args.chunk)
            index.connect()
            levers = tuple(args.lever) if args.lever else None
            rule_file = apply_rule(folder, script, args.rule_variant, args.target, levers)
            result["levers"] = list(levers) if levers else []
            result["rule_file"] = str(rule_file)
            result["rule_variant"] = args.rule_variant
            result["rule_target"] = args.target
            if args.timer:
                result["timer"] = install_timer(folder, index, args.every_hours)
            if not args.yes:
                result["needs_yes"] = True
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(f"folder        : {result['folder']}")
                    print(f"notes found   : {result['files']}")
                    print(f"to summarise  : {result['long_files']}")
                    print(f"est. minutes  : {result['estimated_minutes']}")
                    print(f"rule written  : {rule_file}")
                    print("run `notes-index init --yes` to do the first ingest")
                return 0
            report = index.update(use_summarizer=not args.no_summaries)
            result["report"] = report.as_line()
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"rule written  : {rule_file}")
                print(f"ingest        : {report.as_line()}")
            return 0

        if args.command == "update":
            report = index.update(strict=args.strict, use_summarizer=not args.no_summaries)
            if args.json:
                print(json.dumps({"report": report.as_line(), "health": index.health_line()}, indent=2))
            else:
                print(report.as_line())
                print(index.health_line())
            return 0

        if args.command == "search":
            query = " ".join(args.words)
            hits = index.search(query, after=args.after, limit=args.limit)
            rows = _project([hit.__dict__ for hit in hits], getattr(args, "fields", None))
            if args.json:
                print(json.dumps({"health": index.health_line(), "hits": rows}, indent=2))
                return 0
            print(index.health_line())
            if not rows:
                print("no hits")
                return 1
            for row in rows:
                if getattr(args, "fields", None):
                    print("- " + " | ".join(f"{k}={row[k]}" for k in row))
                else:
                    print(f"- {row['date'] or 'undated'} | {row['kind']:5s} | {row['path']}  (score {row['score']:.5f})")
                    print(f"    {row['snippet'].strip()}")
                    print(f"    {row['full_path']}")
            return 0

        if args.command == "status":
            result = index.status()
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"folder        : {result['folder']}")
                print(f"db            : {result['db']}")
                print(f"files         : {result['files']}")
                print(f"rows          : {result['rows']} {result['rows_by_kind']}")
                print(f"last refreshed: {result['last_refreshed']}")
                print(f"last error    : {result['last_error'] or 'none'}")
                print(f"last log line : {result['last_log_line'] or 'none'}")
                print(f"summarizer    : {result['summarizer']}")
            return 0

        if args.command == "rule":
            levers = tuple(args.lever) if args.lever else None
            block = rule_block(script, args.variant, args.target, levers)
            if args.apply:
                path = apply_rule(folder, script, args.variant, args.target, levers)
                print(f"wrote {path}")
            else:
                print(block)
            return 0

        if args.command == "timer":
            if args.action == "install":
                result = install_timer(folder, index, args.every_hours)
            elif args.action == "uninstall":
                result = uninstall_timer(folder)
            else:
                result = timer_status(folder)
            print(json.dumps(result, indent=2))
            return 0
    except LockBusy as exc:
        index.set_state("last_error", str(exc))
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        index.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
