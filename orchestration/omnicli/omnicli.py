#!/usr/bin/env python3
"""
omnicli — the Uber OmniCLI: one late-binding gateway to every local tool.

One gateway, two surfaces over one catalog:

  CLI        omnicli search | describe | invoke | status
  Code Mode  omnicli exec plan.py  (typed SDK, sandboxed, one turn)

The catalog is a BM25 (SQLite FTS5) index over the full body of every skill,
with hand-curated aliases in a separately weighted column. An agent discovers
a tool by *intent*, then pulls exactly one tool's contract, then invokes it
with a bounded response. Nothing else ever enters the context window.

Native local inference (llm / ocr / decide / asr) is available as first-class
tools, and as a direct subcommand for interactive use.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
if SCRIPT_PATH.parent.name == "scripts":
    SKILL_DIR = SCRIPT_PATH.parent.parent
else:
    SKILL_DIR = SCRIPT_PATH.parent

SCRIPTS_DIR = SKILL_DIR / "scripts"
VENV_PYTHON = SKILL_DIR / ".venv" / "bin" / "python"

sys.path.insert(0, str(SKILL_DIR))

try:
    from catalog import aliases as aliases_mod
    from catalog import argspec as argspec_mod
    from catalog import bindings as bindings_mod
    from catalog import bridge as bridge_mod
    from catalog import harness as harness_mod
    from catalog import resolve as resolve_mod
    from catalog import builder, health, invoke, policy, registry, search, vectors  # noqa: E402
except ImportError:  # pragma: no cover - degraded install
    aliases_mod = bindings_mod = bridge_mod = argspec_mod = harness_mod = None
    builder = registry = search = health = invoke = policy = None  # type: ignore

# The response cap. An agent must never be able to pull an unbounded payload
# into its context window, even by forgetting the flags. The implementation
# lives in catalog.invoke so the CLI and the Code Mode bindings share one ceiling.
DEFAULT_MAX_BYTES = invoke.DEFAULT_MAX_BYTES if invoke else 8000

_SINCE_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _trace_identity():
    if bindings_mod is None:
        return "cli", f"ppid:{os.getppid()}"
    return bindings_mod.trace_identity()


def _user_trace_path() -> Path:
    if bindings_mod is None:
        return Path.home() / ".local" / "share" / "omnicli" / "trace.jsonl"
    return Path(bindings_mod.user_trace_path())


def _trace_append(path: Path, event: dict) -> None:
    """Telemetry must never break a call, so every failure is swallowed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


@contextmanager
def _traced(verb: str, tool: str):
    """Record one catalogue call, unless Code Mode already owns the row.

    Under `omnicli exec` the bindings write the row and set `OMNICLI_TRACE`, so
    the CLI stays silent there. Without that guard a single Code Mode call would
    be counted twice, once by the bindings and once by the child process.
    """
    if os.environ.get("OMNICLI_TRACE"):
        yield
        return
    path = _user_trace_path()
    harness, session = _trace_identity()
    base = {"call": verb, "tool": tool, "harness": harness, "session": session, "via": "cli"}
    _trace_append(path, {"kind": "call", "t": time.time(), **base})
    started = time.perf_counter()
    rc = 0
    try:
        yield
    except BaseException:
        rc = -1
        raise
    finally:
        _trace_append(path, {
            "kind": "done", "ms": int((time.perf_counter() - started) * 1000), "rc": rc, **base,
        })


def _parse_since(spec: str) -> float:
    """Cutoff epoch for '30m', '24h', '7d', '2w' or an ISO timestamp."""
    raw = str(spec or "7d").strip().lower()
    match = re.fullmatch(r"(\d+)([smhdw])", raw)
    if match:
        return time.time() - int(match.group(1)) * _SINCE_UNITS[match.group(2)]
    try:
        return datetime.datetime.fromisoformat(raw).timestamp()
    except ValueError:
        sys.exit(f"❌ Error: --since wants 30m, 24h, 7d, 2w or an ISO date, got {spec!r}")


def _merge_exec_trace(trace: Path, start: int) -> None:
    """Copy the rows a plan wrote into the per-user usage trace.

    The sandbox has `/` read-only, so the child can only write inside its
    workspace. The parent process is unsandboxed and owns the merge, which also
    keeps Code Mode rows from being counted twice.
    """
    try:
        lines = trace.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return
    fresh = [line for line in lines[start:] if line.strip()]
    if not fresh:
        return
    target = _user_trace_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as fh:
            for line in fresh:
                fh.write(line.rstrip("\n") + "\n")
    except OSError:
        pass


def _load_trace(path: Path) -> list:
    rows = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def cmd_usage(trace=None, since="7d", as_json=False, limit=10):
    """Who calls omnicli, what they call, and whether a search goes anywhere."""
    path = Path(trace).expanduser() if trace else _user_trace_path()
    if not path.is_file():
        sys.exit(f"❌ Error: no trace at {path}. Make one with `omnicli search`, or pass --trace.")

    cutoff = _parse_since(since)
    calls = []
    for row in _load_trace(path):
        if row.get("kind") != "call":
            continue
        try:
            ts = float(row.get("t") or 0)
        except (TypeError, ValueError):
            continue
        if ts >= cutoff:
            calls.append(row)

    by_harness = collections.Counter(r.get("harness") or "unknown" for r in calls)
    by_verb = collections.Counter(r.get("call") or "?" for r in calls)
    by_tool = collections.Counter(
        str(r.get("tool") or "?") for r in calls if r.get("call") in ("describe", "invoke", "do")
    )
    by_query = collections.Counter(
        str(r.get("tool") or "?") for r in calls if r.get("call") == "search"
    )
    sessions: dict[str, list] = {}
    for row in calls:
        sessions.setdefault(str(row.get("session") or "unknown"), []).append(row)

    searched = {s: rows for s, rows in sessions.items()
                if any(x.get("call") == "search" for x in rows)}
    acted, gaps = 0, []
    for rows in searched.values():
        first = min(float(x.get("t") or 0) for x in rows if x.get("call") == "search")
        actions = [float(x.get("t") or 0) for x in rows
                   if x.get("call") in ("describe", "invoke", "do") and float(x.get("t") or 0) >= first]
        if actions:
            acted += 1
            gaps.append(min(actions) - first)
    median_gap = statistics.median(gaps) if gaps else None

    payload = {
        "trace": str(path),
        "since": since,
        "calls": len(calls),
        "sessions": len(sessions),
        "harness": dict(by_harness.most_common()),
        "verbs": dict(by_verb.most_common()),
        "tools": dict(by_tool.most_common(limit)),
        "queries": dict(by_query.most_common(limit)),
        "search_sessions": len(searched),
        "search_acted": acted,
        "search_acted_rate": round(acted / len(searched), 4) if searched else None,
        "search_median_gap_s": round(median_gap, 1) if median_gap is not None else None,
    }
    if as_json:
        print(json.dumps(payload, indent=2))
        return

    print(f"📊 omnicli usage — last {since} · {len(calls)} call{'s' if len(calls) != 1 else ''}"
          f" · {len(sessions)} session{'s' if len(sessions) != 1 else ''}")
    print(f"   {path}")
    if not calls:
        print("\n  no calls in this window")
        return
    print("\n  harness        calls   share")
    for name, count in by_harness.most_common():
        print(f"  {name:<14} {count:>5}   {count / len(calls):>5.1%}")
    print("\n  verb           calls")
    for name, count in by_verb.most_common():
        print(f"  {name:<14} {count:>5}")
    if by_tool:
        print("\n  top tools")
        for name, count in by_tool.most_common(min(limit, 8)):
            print(f"    {name[:46]:<48} {count:>3}")
    if by_query:
        print("\n  top queries")
        for name, count in by_query.most_common(min(limit, 5)):
            print(f"    {name[:46]:<48} {count:>3}")
    if searched:
        rate = acted / len(searched)
        tail = f" · median {median_gap:.1f}s" if median_gap is not None else ""
        print(f"\n  search → action   {acted}/{len(searched)} sessions ({rate:.0%}){tail}")


# --------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------

def get_python_for_script() -> str:
    if VENV_PYTHON.is_file() and os.access(VENV_PYTHON, os.X_OK):
        return str(VENV_PYTHON)
    return sys.executable


def exec_internal_script(script_name: str, args: list[str]) -> None:
    script_path = SCRIPTS_DIR / script_name
    if not script_path.is_file():
        sys.exit(f"❌ Error: Internal engine script not found at {script_path}")
    cmd = [get_python_for_script(), str(script_path)] + args
    sys.exit(subprocess.run(cmd).returncode)


def _require_catalog():
    if builder is None:
        sys.exit("❌ Error: omnicli catalog package not importable from %s" % SKILL_DIR)
    con = builder.connect()
    if os.environ.get("OMNICLI_TRUST_INDEX"):
        row = con.execute("SELECT count(*) FROM tools").fetchone()
        if row and row[0]:
            return con
    builder.ensure_built(con, progress=False)
    return con


# --------------------------------------------------------------------------
# invoke argument parsing
# --------------------------------------------------------------------------
#
# `invoke` is parsed manually rather than by argparse. Two reasons:
#
# 1. argparse.REMAINDER swallows every token after the first positional, so
#    `omnicli invoke <tool> --out FILE` would silently lose --out.
# 2. Tool flags and gateway flags collide. --out, --project and --json are
#    all real flags on real tools in this collection. The gateway's own
#    flags are therefore prefixed `--omni-`, and anything else after the
#    tool id is passed to the tool untouched. "--" also forces the split.

INVOKE_VALUE_FLAGS = {
    "--omni-buffer": "buffer",
    "--omni-project": "project",
    "--omni-jq": "jq",
    "--omni-grep": "grep",
    "--omni-max-bytes": "max_bytes",
    "--omni-timeout": "timeout",
}
INVOKE_BOOL_FLAGS = {"--omni-json": "json"}


def parse_invoke_args(argv: list[str]) -> tuple[str | None, dict, list[str]]:
    """Split `invoke` arguments into (tool_id, gateway options, tool args)."""
    opts: dict[str, Any] = {
        "buffer": None, "project": None, "jq": None, "grep": None,
        "max_bytes": DEFAULT_MAX_BYTES, "json": False, "timeout": 300.0,
    }
    tool_args: list[str] = []
    tool_id: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            tool_args.extend(argv[i + 1:])
            break
        if a in INVOKE_VALUE_FLAGS:
            key = INVOKE_VALUE_FLAGS[a]
            if i + 1 >= len(argv):
                sys.exit(f"❌ Error: {a} needs a value.")
            val = argv[i + 1]
            if key in ("max_bytes", "timeout"):
                try:
                    opts[key] = int(val) if key == "max_bytes" else float(val)
                except ValueError:
                    sys.exit(f"❌ Error: {a} expects a number, got {val!r}.")
            else:
                opts[key] = val
            i += 2
            continue
        if a in INVOKE_BOOL_FLAGS:
            opts[INVOKE_BOOL_FLAGS[a]] = True
            i += 1
            continue
        if a.startswith("--omni-"):
            # Silently dropping an unknown gateway flag is how a typo becomes
            # a silently unfiltered 8 KB payload. Say so and keep going: the
            # tool itself never sees `--omni-*`, so nothing else breaks.
            print(f"⚠️  omnicli: unknown gateway flag {a!r} ignored "
                  f"(known: {', '.join(sorted(INVOKE_VALUE_FLAGS | INVOKE_BOOL_FLAGS))})",
                  file=sys.stderr)
            i += 1
            continue
        if tool_id is None and not a.startswith("-"):
            tool_id = a
            i += 1
            continue
        tool_args.append(a)
        i += 1
    return tool_id, opts, tool_args


# `do` is parsed manually for the same two reasons as `invoke`: REMAINDER
# would swallow the intent, and tool flags collide with gateway flags. The
# split here is stricter — the intent is ONE token, and tool arguments only
# ever arrive after `--`. Anything else is a malformed call, refused rather
# than guessed at, because "the third word was probably a filename" is how a
# correct refusal turns into a wrong execution.

DO_VALUE_FLAGS = {
    **INVOKE_VALUE_FLAGS,
    "--skill": "skill",
    "--tool": "tool",
    "--margin": "margin",
}
DO_BOOL_FLAGS = {
    "--dry-run": "dry_run",
    "--omni-json": "json",
}


def parse_do_args(argv: list[str]) -> tuple[str | None, dict, list[str]]:
    """Split `do` arguments into (intent, gateway options, tool args)."""
    opts: dict[str, Any] = {
        "buffer": None, "project": None, "jq": None, "grep": None,
        "max_bytes": DEFAULT_MAX_BYTES, "json": False, "timeout": 300.0,
        "skill": None, "tool": None, "margin": None, "dry_run": False,
    }
    intent: str | None = None
    tool_args: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            tool_args.extend(argv[i + 1:])
            break
        if a in DO_VALUE_FLAGS:
            key = DO_VALUE_FLAGS[a]
            if i + 1 >= len(argv):
                sys.exit(f"❌ Error: {a} needs a value.")
            val = argv[i + 1]
            if key in ("max_bytes", "timeout"):
                try:
                    opts[key] = int(val) if key == "max_bytes" else float(val)
                except ValueError:
                    sys.exit(f"❌ Error: {a} expects a number, got {val!r}.")
            elif key == "margin":
                try:
                    opts[key] = float(val)
                except ValueError:
                    sys.exit(f"❌ Error: {a} expects a number, got {val!r}.")
            else:
                opts[key] = val
            i += 2
            continue
        if a in DO_BOOL_FLAGS:
            opts[DO_BOOL_FLAGS[a]] = True
            i += 1
            continue
        if a.startswith("--omni-"):
            print(f"⚠️  omnicli: unknown gateway flag {a!r} ignored "
                  f"(known: {', '.join(sorted(DO_VALUE_FLAGS))})",
                  file=sys.stderr)
            i += 1
            continue
        if intent is None and not a.startswith("-"):
            intent = a
            i += 1
            continue
        if intent is not None and not a.startswith("-"):
            sys.exit(f"❌ Error: `omnicli do` takes ONE intent token; got {a!r} after "
                     f"{intent!r}. Quote the intent as a single argument and pass "
                     f"tool arguments after `--`.")
        sys.exit(f"❌ Error: `omnicli do` does not accept flag {a!r} before the "
                 f"intent. Gateway flags: {', '.join(sorted(DO_VALUE_FLAGS))}.")
    return intent, opts, tool_args


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------

def cmd_status(as_json: bool = False):
    probe = health.probe_all()
    ts_addr = probe["tailscale_address"]
    results = probe["services"]

    catalog_info = {}
    tier = "unavailable"
    if builder is not None:
        try:
            con = builder.connect()
            built = builder.ensure_built(con, progress=False)
            catalog_info = {
                "skills": built.get("skills"),
                "tools": built.get("tools"),
                "docs": built.get("docs"),
                "built_at": built.get("built_at"),
                "rebuilt": built.get("rebuilt"),
                "db": str(builder.db_path()),
            }
            vstatus = vectors.status(con)
            catalog_info["vectors"] = vstatus
            if vstatus.get("vectors"):
                tier = "bm25+dense(rrf)" if search.embedding_available() else "bm25 (dense offline)"
            else:
                tier = "bm25 (no vectors)"
        except Exception as exc:  # pragma: no cover
            catalog_info = {"error": str(exc)}

    payload = {
        "tailscale_address": ts_addr,
        "services": results,
        "catalog": catalog_info,
        "retrieval_tier": tier,
    }

    if as_json:
        print(json.dumps(payload, indent=2))
        return

    print("\n🌐 [omnicli — Workstation Inference & Tailnet]")
    print(f"   Tailnet address: {ts_addr or 'offline'}")
    print()
    print("   " + f"{'SERVICE':<42} │ {'STATUS':<10} │ ENDPOINT")
    print("   " + "─" * 43 + "┼" + "─" * 12 + "┼" + "─" * 26)
    for r in results:
        icon = {"ONLINE": "🟢 ONLINE", "DEGRADED": "🟡 DEGRADED"}.get(r["status"], "⚪ OFFLINE")
        ep = r["local_url"] if r["status"] != "OFFLINE" else ""
        print(f"   {r['service']:<42} │ {icon:<10} │ {ep}")

    print()
    if catalog_info.get("skills") is not None:
        print(f"   📇 Catalog : {catalog_info['skills']} skills · {catalog_info['tools']} tools · "
              f"{catalog_info['docs']} docs")
        print(f"   🔎 Retrieval tier: {tier}")
        print(f"   💾 Index   : {catalog_info.get('db')}")
    print("   💡 Tip: `tailscale-ops serve-mesh` exposes all services over private HTTPS.")
    print()


# --------------------------------------------------------------------------
# harness — first-party harness support
# --------------------------------------------------------------------------

def cmd_harness(subaction: str = "list", target: str | None = None, as_json: bool = False):
    if harness_mod is None:
        sys.exit("❌ Error: omnicli catalog.harness package not importable.")

    subaction = (subaction or "list").lower()
    if subaction == "list":
        items = harness_mod.list_harnesses()
        if as_json:
            print(json.dumps(items, indent=2))
            return
        active_list = [h["name"] for h in items if h["active"]]
        active_str = ", ".join(active_list) if active_list else "None detected"
        print(f"\n🌐 [omnicli — First-Party Harness Adapters]")
        print(f"   Active runtime: {active_str}\n")
        print(f"   {'HARNESS':<12} │ {'STATUS':<12} │ {'PROTOCOLS':<32} │ CONFIG PATH")
        print("   " + "─" * 13 + "┼" + "─" * 14 + "┼" + "─" * 34 + "┼" + "─" * 28)
        for h in items:
            if h["active"]:
                status = "🟢 ACTIVE"
            elif h["installed"]:
                status = "⚪ INSTALLED"
            else:
                status = "⚫ NOT FOUND"
            proto = ", ".join(h["protocols"])[:30]
            first_path = h["config_paths"][0]
            print(f"   {h['id']:<12} │ {status:<12} │ {proto:<32} │ {first_path}")
        print("\n   Guides: omnicli harness info <name>  ·  Verify: omnicli harness verify\n")

    elif subaction == "detect":
        detected = harness_mod.detect_active_harnesses()
        if as_json:
            print(json.dumps(detected, indent=2))
            return
        print("\n🔍 [omnicli — Harness Detection]")
        if not detected:
            print("   No specific agent harness detected from current environment variables.")
        else:
            for d in detected:
                print(f"   🟢 {d['name']} ({d['id']})")
                for ind in d["matched_indicators"]:
                    print(f"      • {ind}")
        print()

    elif subaction in ("info", "show"):
        if not target:
            sys.exit("❌ Error: specify harness name (e.g. `omnicli harness info t3-code`).")
        h = harness_mod.get_harness(target)
        if not h:
            sys.exit(f"❌ Error: unknown harness {target!r}. Available: {', '.join(harness_mod.HARNESS_SPECS.keys())}")
        doc = harness_mod.get_doc(target)
        if as_json:
            print(json.dumps({**h, "doc": doc}, indent=2))
            return
        print(f"\n📖 [omnicli harness — {h['name']}]")
        print(f"   Summary  : {h['summary']}")
        print(f"   Protocols: {', '.join(h['protocols'])}")
        print(f"   Configs  : {', '.join(h['config_paths'])}")
        print(f"   Guide    : {h['doc_file']}\n")
        print("--- Configuration Snippet ---")
        print(h.get("config_snippet", "").strip())
        print("\n-----------------------------\n")
        print(f"   Verify: omnicli harness verify {h['id']}\n")

    elif subaction == "config":
        if not target:
            sys.exit("❌ Error: specify harness name (e.g. `omnicli harness config opencode`).")
        snippet = harness_mod.get_config(target)
        if snippet is None:
            sys.exit(f"❌ Error: unknown harness {target!r}.")
        print(snippet.strip())

    elif subaction == "verify":
        if target:
            report = harness_mod.verify_harness(target)
            if as_json:
                print(json.dumps(report, indent=2))
                sys.exit(0 if report["status"] == "PASS" else 1)
            icon = "✅" if report["status"] == "PASS" else "❌"
            print(f"\n🧪 [omnicli — Harness Verification: {report['name']}]")
            print(f"   Result: {icon} {report['status']} ({report['passed']}/{report['total']} checks passed)\n")
            for c in report["checks"]:
                c_icon = "✓" if c["passed"] else "✗"
                print(f"   {c_icon} {c['check']:<28} : {c['detail']}")
            print()
            sys.exit(0 if report["status"] == "PASS" else 1)
        else:
            report = harness_mod.verify_all()
            if as_json:
                print(json.dumps(report, indent=2))
                sys.exit(0 if report["status"] == "PASS" else 1)
            icon = "✅" if report["status"] == "PASS" else "❌"
            print(f"\n🧪 [omnicli — Workstation Harness Verification Matrix]")
            print(f"   Overall Status: {icon} {report['status']}\n")
            for h_id, res in report["harnesses"].items():
                h_icon = "✅" if res["status"] == "PASS" else "❌"
                print(f"   {h_icon} {res['name']:<24} [{res['passed']}/{res['total']} checks]")
                for c in res["checks"]:
                    c_icon = "✓" if c["passed"] else "✗"
                    print(f"      {c_icon} {c['check']:<26}: {c['detail']}")
                print()
            sys.exit(0 if report["status"] == "PASS" else 1)
    else:
        sys.exit(f"❌ Error: unknown harness action {subaction!r}. Use: list, detect, info, config, verify.")


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------

def cmd_search(query: str, as_json: bool = False, limit: int = 6,
               explain: bool = False, no_rerank: bool = False, rerank: str = "auto",
               chunks: bool = False, fusion: str = "auto"):
    con = _require_catalog()
    mode = "never" if no_rerank else rerank
    res = search.search(con, query, limit=limit, rerank_enabled=mode,
                        fusion=fusion, explain=explain)

    if as_json:
        # Routing needs names and scores; the chunk archive is opt-in. The
        # full shape is ~25 KB (~6.3k tokens) for ten results, which is more
        # context than the skill being routed to.
        if not chunks:
            res = dict(res)
            res["results"] = search.compact(res["results"])
            res["shape"] = "compact"
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if not res["results"]:
        print(f"\n🔍 No match for: {query!r}")
        if res.get("note"):
            print(f"   {res['note']}")
        print("   Try a different phrasing, or `omnicli list` to browse the registry.\n")
        return

    print(f"\n🔍 [omnicli] intent: {query!r}   tier={res['tier']}   "
          f"candidates={res['candidate_chunks']}\n")
    for i, r in enumerate(res["results"], 1):
        print(f"  {i}. {r['skill']}   score={r['score']:.2f}  "
              f"lex={r['lexical_score']:.2f}  coord={r['coordination']:.2f}  "
              f"chunks={r['coverage']}")
        if explain:
            print(f"       matched : {', '.join(r.get('matched_terms', []))}")
            print(f"       top hit : [{r['chunks'][0]['kind']}] {r['chunks'][0]['title']}")
            print(f"       {r['chunks'][0]['snippet'][:180]}")
        else:
            print(f"       {r['chunks'][0]['snippet'][:150]}")
        top = r["chunks"][0]
        if top.get("kind") == "doc":
            rel = top["path"].split("/suites/")[-1]
            print(f"       → omnicli describe {r['skill']} --doc \"{rel}\"")
        else:
            print(f"       → omnicli tools {r['skill']}")
        print()
    print("   Next: `omnicli describe <tool_id>` for one contract, "
          "`omnicli invoke <tool_id> --args ...` to run it.\n")


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

def cmd_list(as_json: bool = False, show_all: bool = False):
    con = _require_catalog()
    rows = con.execute(
        "SELECT name, dir_name, description, status, cli, tools FROM skills ORDER BY name"
    ).fetchall()
    if as_json:
        print(json.dumps([dict(r) for r in rows], indent=2, ensure_ascii=False))
        return
    print(f"\n📦 [omnicli registry] {len(rows)} skills\n")
    for r in rows:
        tag = "" if r["status"] == "active" else f" [{r['status'].upper()}]"
        cli = "  cli:" + Path(r["cli"]).name if r["cli"] else ""
        print(f"  • {r['name']:<28}{tag} {r['tools']:>3} tools{cli}")
        if r["description"]:
            print(f"    {r['description'][:120]}")
    print()


def cmd_tools(skill_name: str, as_json: bool = False):
    con = _require_catalog()
    rows = con.execute(
        "SELECT id, kind, summary, enabled FROM tools WHERE skill = ? ORDER BY id",
        (skill_name,),
    ).fetchall()
    if not rows:
        matches = con.execute(
            "SELECT DISTINCT skill FROM tools WHERE skill LIKE ?", (f"%{skill_name}%",)
        ).fetchall()
        if matches:
            print(f"❌ No skill named {skill_name!r}. Did you mean: "
                  f"{', '.join(m['skill'] for m in matches)}?")
            sys.exit(1)
        sys.exit(f"❌ Error: Skill '{skill_name}' not found.")

    if as_json:
        print(json.dumps([dict(r) for r in rows], indent=2, ensure_ascii=False))
        return
    print(f"\n🛠️  [omnicli tools] {skill_name}  ({len(rows)} tools)\n")
    for r in rows:
        gate = "" if r["enabled"] else "   [disabled]"
        print(f"   - {r['id']}   [{r['kind']}]{gate}")
        if r["summary"]:
            print(f"       {r['summary'][:150]}")
    hidden = sum(1 for r in rows if not r["enabled"])
    print(f"\n   Contract:  omnicli describe <tool_id>")
    print(f"   Execute :  omnicli invoke <tool_id> [args...]")
    if hidden:
        print(f"   Gate    :  {hidden} tool(s) disabled; "
              f"`omnicli enable <tool_id>` after reviewing the contract\n")
    else:
        print()


def _describe_doc(con, name: str, query: str, as_json: bool = False):
    """Read one document the skill declared as part of its searchable body.

    The query is matched loosely: an exact title, a path suffix, a path
    fragment, or the file's stem. An agent that saw a snippet in a search
    result should be able to name the document the way the result named it.
    """
    q = query.strip().lower()
    rows = con.execute(
        "SELECT title, path, body, kind FROM docs WHERE skill = ? AND kind IN ('doc', 'reference')",
        (name,),
    ).fetchall()
    if not rows:
        sys.exit(f"❌ Error: {name!r} declares no documents. "
                 "Use `omnicli describe " + name + "` to see the skill itself.")

    scored = []
    for title, path, body, kind in rows:
        t = (title or "").lower()
        p = (path or "").lower()
        stem = Path(p).stem.lower()
        rel = "/".join(p.split("/suites/")[-1].split("/")) if "/suites/" in p else p
        score = 0
        if t == q or rel == q:
            score = 100
        elif t.startswith(q) or rel.startswith(q):
            score = 80
        elif t.endswith("/" + q) or rel.endswith("/" + q):
            score = 70
        elif q and q in t:
            score = 50
        elif q and q in p:
            score = 40
        elif stem == q:
            score = 30
        if score:
            scored.append((score, title, path, body))
    if not scored:
        sys.exit(f"❌ Error: no document matching {query!r} in {name!r}.")

    scored.sort(key=lambda r: -r[0])
    best = scored[0]
    _, title, path, body = best
    payload = {"skill": name, "title": title, "path": path,
               "tokens": len(body) // 4, "body": body}
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(f"\n📖 [{name}] document: {title}  (~{payload['tokens']} tokens)\n")
    print(body)
    print(f"\n   source: {path}")
    if len(scored) > 1:
        others = ", ".join(sorted({t for _, t, _, _ in scored[1:5]}))
        print(f"   also matched: {others}")


def _describe_skill(con, name: str, section_name: str, as_json: bool = False, doc_name: str = ""):
    """A skill id: frontmatter + outline, or one section on request."""
    from catalog import skilldoc

    row = con.execute("SELECT * FROM skills WHERE name = ?", (name,)).fetchone()
    if row is None:
        sys.exit(f"❌ Error: no skill named {name!r}.")
    md_path = row["md_path"]
    if not md_path or not Path(md_path).is_file():
        sys.exit(f"❌ Error: skill {name!r} has no readable SKILL.md.")

    doc = skilldoc.load_skill_doc(md_path)
    tools = con.execute(
        "SELECT id, kind FROM tools WHERE skill = ? ORDER BY kind, id", (name,)
    ).fetchall()

    if doc_name:
        return _describe_doc(con, name, doc_name, as_json)

    if section_name:
        section = skilldoc.pick_section(doc, section_name)
        if section is None:
            sys.exit(f"❌ Error: no section {section_name!r} in {name!r}. Available: "
                     + ", ".join(s["heading"] for s in doc["sections"] if s["heading"]))
        if as_json:
            print(json.dumps({
                "skill": name, "section": section["heading"],
                "tokens": section["tokens"], "body": section["body"],
            }, indent=2, ensure_ascii=False))
            return
        print(f"\n📖 [{name}] section: {section['heading']}  (~{section['tokens']} tokens)\n")
        print(section["body"])
        return

    payload = {
        "skill": name,
        "kind": "skill",
        "path": doc["path"],
        "frontmatter": doc["frontmatter"],
        "body_tokens": doc["tokens"],
        "outline": skilldoc.outline(doc),
        "tools": [{"id": t["id"], "kind": t["kind"]} for t in tools],
    }
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    print(f"\n📖 [{name}]  ~{doc['tokens']} tokens, {len(doc['sections'])} sections, {len(tools)} tools")
    print(f"   {doc['path']}\n")
    print("   Sections:")
    for s in skilldoc.outline(doc):
        indent = "   " + "  " * s["level"]
        print(f"{indent}{s['heading'] or '(preamble)':<58} {s['tokens']:>5} tok")
    print(f"\n   Read one:  omnicli describe {name} --section \"<heading>\"")
    print(f"   Tool ids:  omnicli tools {name}")


def cmd_describe(tool_id: str, as_json: bool = False, section: str = "", doc: str = ""):
    """Return the exact input contract for ONE tool, or a skill's body."""
    con = _require_catalog()
    row = con.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone()
    if row is None:
        # A skill name gives the skill itself, checked before the legacy
        # "fall back to the skill's primary script" path.
        if con.execute("SELECT 1 FROM skills WHERE name = ?", (tool_id,)).fetchone():
            return _describe_skill(con, tool_id, section, as_json, doc)
        cands = con.execute(
            "SELECT id FROM tools WHERE skill = ? AND kind = 'script' LIMIT 1", (tool_id,)
        ).fetchall()
        if not cands:
            sys.exit(f"❌ Error: no tool named {tool_id!r}. "
                     f"Use `omnicli tools <skill>` to list a skill's tools.")
        row = con.execute("SELECT * FROM tools WHERE id = ?", (cands[0]["id"],)).fetchone()

    contract = json.loads(row["contract"] or "{}")
    skill = con.execute("SELECT * FROM skills WHERE name = ?", (row["skill"],)).fetchone()

    payload = {
        "id": row["id"],
        "skill": row["skill"],
        "kind": row["kind"],
        "enabled": bool(row["enabled"]),
        "summary": row["summary"],
        "path": row["path"],
        "argv": json.loads(row["argv"] or "[]"),
        "aliases": json.loads(skill["aliases"] or "[]") if skill else [],
        "contract": contract,
    }

    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    state = "enabled" if row["enabled"] else f"DISABLED (run `omnicli enable {row['id']}`)"
    print(f"\n📄 [omnicli describe] {row['id']}\n")
    print(f"   skill   : {row['skill']}")
    print(f"   kind    : {row['kind']}")
    print(f"   state   : {state}")
    if row["summary"]:
        print(f"   summary : {row['summary']}")
    if skill and skill["description"]:
        print(f"   about   : {skill['description'][:200]}")
    if payload["aliases"]:
        print(f"   aliases : {', '.join(payload['aliases'])}")

    if contract.get("usage"):
        print(f"\n   {contract['usage']}")
    if contract.get("flags"):
        print(f"\n   flags      : {' '.join(contract['flags'])}")
    if contract.get("positionals"):
        print(f"   positionals: {' '.join(contract['positionals'])}")
    if contract.get("subcommands"):
        print("\n   subcommands:")
        for sub in contract["subcommands"]:
            alias = f" ({', '.join(sub['aliases'])})" if sub.get("aliases") else ""
            desc = f" — {sub['summary']}" if sub.get("summary") else ""
            print(f"      {sub['name']}{alias}{desc}")
    if contract.get("help"):
        print("\n" + "\n".join("   | " + ln for ln in contract["help"].splitlines()[:40]))
    print(f"\n   Run: omnicli invoke {row['id']} [args...]\n")


# --------------------------------------------------------------------------
# invoke
# --------------------------------------------------------------------------

def cmd_invoke(tool_id: str, extra_args: list[str], out_path: str | None = None,
               project_fields: str | None = None, jq_expr: str | None = None,
               grep: str | None = None, max_bytes: int = DEFAULT_MAX_BYTES,
               as_json: bool = False, timeout: float = 300.0):
    con = _require_catalog()
    row = con.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone()
    if row is None:
        sys.exit(f"❌ Error: no tool named {tool_id!r}. "
                 f"Use `omnicli tools <skill>` to list a skill's tools.")

    # Discovery does not imply exposure. The catalog knows the tool; the
    # policy decides whether an agent may run it. `describe` still works, so
    # the contract can be reviewed before the gate is opened.
    if not row["enabled"]:
        sys.exit(f"❌ Error: tool {tool_id!r} is disabled.\n"
                 f"   Review it:  omnicli describe {tool_id}\n"
                 f"   Enable it:  omnicli enable {tool_id}")

    argv = json.loads(row["argv"] or "[]")
    parent_params = json.loads(row["contract"] or "{}").get("parent_params") if row["parent"] else None
    cmd = invoke.build_cmd(argv, extra_args, python=sys.executable, skill_dir=SKILL_DIR,
                           parent_params=parent_params)
    run = invoke.execute(cmd, timeout=timeout)

    fields = invoke.parse_fields(project_fields)
    # Reserve one byte for the newline that terminates a plain reply. The JSON
    # branch re-shapes against its measured envelope instead (fit_envelope).
    budget = max(0, max_bytes - (0 if as_json else 1))
    try:
        shaped = invoke.shape(
            run["stdout"], fields=fields, jq_expr=jq_expr,
            grep_pattern=grep, max_bytes=budget,
        )
    except re.error as exc:
        sys.exit(f"❌ Error: invalid --omni-grep pattern: {exc}")

    if shaped["projection_requested"] and not shaped["projection_applied"]:
        print("⚠️  omnicli: projection could not be applied "
              "(output was not JSON, or no requested field matched); "
              "returning the unfiltered payload.", file=sys.stderr)

    # The buffer preserves what the cap discards, so it holds the *unfiltered*
    # stdout, written before projection, grep and truncation.
    if out_path:
        p = Path(out_path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(run["stdout"], encoding="utf-8")
        print(f"💾 Full stdout buffered to: {p}  ({shaped['raw_bytes']} bytes)")
        if shaped["projection_applied"] or shaped["grep_applied"]:
            print("📊 The preview below is filtered; the buffer is not.")
        print()

    if run["stderr"]:
        print(run["stderr"], file=sys.stderr, end="" if run["stderr"].endswith("\n") else "\n")

    if as_json:
        def build(shaped: dict[str, Any]) -> dict[str, Any]:
            payload = {
                "tool": tool_id,
                "exit_code": run["exit_code"],
                "bytes": shaped["bytes"],
                "raw_bytes": shaped["raw_bytes"],
                "truncated": shaped["truncated"],
                "projection_applied": shaped["projection_applied"],
                "output": shaped["output"],
            }
            if run["stderr"]:
                payload["stderr"] = run["stderr"][-2000:]
            return payload

        payload, encoded, _ = invoke.fit_envelope(
            run["stdout"], build, fields=fields, jq_expr=jq_expr,
            grep_pattern=grep, max_bytes=max_bytes,
        )
        if len(encoded.encode("utf-8")) > max_bytes:
            # The envelope itself cannot fit (very small cap). Say why in a
            # reply that does fit, rather than printing past the ceiling.
            sys.stdout.write(invoke.refusal(len(encoded.encode()), max_bytes) + "\n")
            sys.exit(1)
        sys.stdout.write(encoded + ("\n" if len(encoded.encode()) < max_bytes else ""))
        sys.exit(run["exit_code"])

    sys.stdout.write(shaped["output"])
    if not shaped["output"].endswith("\n") and shaped["bytes"] < budget:
        sys.stdout.write("\n")
    sys.exit(run["exit_code"])

# --------------------------------------------------------------------------
# do — search, describe and invoke collapsed into one hop
# --------------------------------------------------------------------------

# Exit codes are part of the contract: a caller that only reads the status
# must be able to tell "refused because ambiguous" from "refused because the
# contract needs an argument". They are stable so scripts can branch on them.
DO_EXIT = {
    "ok": 0,
    "no_match": 2,
    "ambiguous": 3,
    "missing_args": 4,
    "no_tool": 5,
}


def cmd_do(intent: str, opts: dict, tool_args: list[str]):
    con = _require_catalog()
    decision = resolve_mod.resolve(
        con, intent,
        skill_hint=opts.get("skill"),
        tool_hint=opts.get("tool"),
        do_margin=opts.get("margin"),
    )
    status = decision.get("status", "no_match")

    if status == "ok":
        if opts.get("dry_run"):
            # Resolve without executing: this is what the measurement harness
            # calls, so a probe never runs a tool to learn where it would go.
            print(json.dumps({
                "status": "ok",
                "skill": decision.get("skill"),
                "tool": decision.get("tool"),
                "argv": decision.get("argv"),
                "supplied": tool_args,
                "would_execute": True,
            }, indent=2, ensure_ascii=False))
            return
        cmd_invoke(
            decision["tool"], tool_args,
            out_path=opts.get("buffer"), project_fields=opts.get("project"),
            jq_expr=opts.get("jq"), grep=opts.get("grep"),
            max_bytes=opts["max_bytes"], as_json=opts.get("json", False),
            timeout=float(opts["timeout"]),
        )
        return

    if opts.get("json"):
        payload = {k: v for k, v in decision.items() if k != "contract"}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif status == "missing_args":
        # Loud by design: print the contract stub the caller needs to retry.
        print(resolve_mod.stub_for(decision))
    else:
        reason = decision.get("reason") or status
        level = decision.get("level")
        # `no_tool` is a lookup miss, not a judgement call, so it does not get
        # the "refusing to guess" framing or the narrowing advice — there is
        # nothing to narrow toward.
        if status == "no_tool":
            print(f"❌ omnicli do: no tool — {reason}.")
            print(f"   intent : {intent!r}")
            print("   Browse: `omnicli list`  |  `omnicli tools <skill>`")
        else:
            gate = f"{status} ({level})" if level else status
            print(f"❌ omnicli do: {gate} — refusing to guess.")
            print(f"   intent : {intent!r}")
            print(f"   reason : {reason}")
            for i, cand in enumerate((decision.get("candidates") or [])[:4], 1):
                name = cand.get("name", "?")
                score = cand.get("score", 0.0)
                print(f"   {i}. {name}   score={score}")
            if status == "no_match":
                print('   Try `omnicli search "<intent>"` to browse matches.')
            else:
                print('   Narrow the intent, or run `omnicli search "<intent>" --explain`.')
    sys.exit(DO_EXIT.get(status, 2))

# --------------------------------------------------------------------------
# policy — discovery does not imply exposure
# --------------------------------------------------------------------------

def _tool_row(con, tool_id: str):
    row = con.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone()
    if row is None:
        sys.exit(f"❌ Error: no tool named {tool_id!r}. "
                 f"Use `omnicli tools <skill>` to list a skill's tools.")
    return row


def cmd_gate(tool_id: str | None, enabled: bool, as_json: bool = False,
             all_tools: bool = False):
    """Enable or disable a tool, recording the decision against its contract."""
    con = _require_catalog()
    if all_tools:
        rows = con.execute("SELECT id, contract, enabled FROM tools ORDER BY id").fetchall()
    elif tool_id:
        rows = [_tool_row(con, tool_id)]
    else:
        sys.exit("❌ Error: name a tool id, or pass --all.")

    changed = []
    for row in rows:
        if bool(row["enabled"]) == enabled:
            continue
        contract = json.loads(row["contract"] or "{}")
        policy.set_enabled(row["id"], enabled, contract=contract)
        con.execute("UPDATE tools SET enabled = ? WHERE id = ?",
                    (1 if enabled else 0, row["id"]))
        changed.append(row["id"])
    con.commit()

    verb = "enabled" if enabled else "disabled"
    if as_json:
        print(json.dumps({"action": verb, "changed": len(changed),
                          "tools": changed if not all_tools else None,
                          "scanned": len(rows)}, indent=2))
        return
    if all_tools:
        print(f"✅ {verb} {len(changed)} of {len(rows)} tools.")
    elif changed:
        print(f"✅ {verb} {changed[0]}")
    else:
        print(f"ℹ️  {rows[0]['id']} was already {verb}.")


def cmd_policy(tool_id: str | None = None, as_json: bool = False):
    """Show the gate: what is runnable, what is not, and why it changed."""
    con = _require_catalog()
    if tool_id:
        row = _tool_row(con, tool_id)
        payload = {
            "tool": tool_id,
            "enabled": bool(row["enabled"]),
            "decision": policy.entry(tool_id),
            "history": policy.history(tool_id),
        }
    else:
        rows = con.execute("SELECT id, skill, enabled FROM tools ORDER BY skill, id").fetchall()
        disabled = [r["id"] for r in rows if not r["enabled"]]
        payload = {
            "tools": len(rows),
            "enabled": len(rows) - len(disabled),
            "disabled": disabled,
            "recent_decisions": policy.history(limit=10),
        }

    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if tool_id:
        print(f"\n🔐 [omnicli policy] {tool_id}\n")
        print(f"   state: {'enabled' if payload['enabled'] else 'disabled'}")
        decision = payload["decision"]
        if decision:
            print(f"   since: {decision.get('at')}  contract:{decision.get('contract')}")
        if payload["history"]:
            print("   history:")
            for rec in payload["history"]:
                print(f"      {rec.get('at')}  {rec.get('before')} → {rec.get('after')}")
        print()
        return

    print(f"\n🔐 [omnicli policy] {payload['enabled']}/{payload['tools']} tools enabled\n")
    if payload["disabled"]:
        shown = payload["disabled"][:40]
        print("   disabled: " + ", ".join(shown)
              + (f" … (+{len(payload['disabled']) - len(shown)} more)"
                 if len(payload["disabled"]) > len(shown) else ""))
    for rec in payload["recent_decisions"]:
        print(f"   {rec.get('at')}  {rec.get('tool')}: {rec.get('before')} → {rec.get('after')}")
    print()


def cmd_alias(skill: str = None, aliases: str = None, tags: str = None,
              remove: bool = False, show_all: bool = False, as_json: bool = False):
    """Read or write a skill's curated routing metadata.

    The alias set is the routing surface of a skill: the words a user would
    type that appear in no document. It lives behind this command so that a
    publisher never needs to know where the file is.
    """
    if builder is None or aliases_mod is None:
        sys.exit("❌ Error: omnicli catalog package not importable.")

    if show_all or not skill:
        data = aliases_mod.load()
        if as_json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return
        print(f"\n🏷️  [curated routing metadata] {len(data)} skills\n")
        for name, rec in sorted(data.items()):
            al = rec.get("aliases", [])
            tg = rec.get("tags", [])
            flag = "  (body not indexed)" if rec.get("index_body") is False else ""
            print(f"  • {name}{flag}")
            if al:
                print(f"      aliases: {', '.join(al)}")
            if tg:
                print(f"      tags   : {', '.join(tg)}")
        print()
        return

    if remove:
        if aliases_mod.remove(skill):
            print(f"🗑️  Removed curated metadata for {skill}")
        else:
            print(f"ℹ️  No curated metadata for {skill}")
        return

    if aliases is None and tags is None:
        rec = aliases_mod.get(skill)
        if as_json:
            print(json.dumps(rec, indent=2, ensure_ascii=False))
            return
        if not rec:
            print(f"ℹ️  No curated metadata for {skill}")
            return
        print(f"\n🏷️  {skill}")
        print(f"   aliases: {', '.join(rec.get('aliases', [])) or '—'}")
        print(f"   tags   : {', '.join(rec.get('tags', [])) or '—'}")
        if rec.get("index_body") is False:
            print("   body    : not indexed (router skills opt out)")
        print()
        return

    al = [a for a in aliases.split(",")] if aliases is not None else None
    tg = [t for t in tags.split(",")] if tags is not None else None
    rec = aliases_mod.set_aliases(skill, al, tg)
    print(f"🏷️  {skill}: {len(rec.get('aliases', []))} aliases, "
          f"{len(rec.get('tags', []))} tags")
    print("   Reindex with `omnicli index --rebuild` to apply.")


# --------------------------------------------------------------------------
# index / eval
# --------------------------------------------------------------------------

def cmd_index(rebuild: bool = False, with_contracts: bool = True, as_json: bool = False,
              check: bool = False, with_vectors: bool = True):
    con = builder.connect()

    if check:
        # Report freshness without doing any work. Used by the skill factory
        # to skip a rebuild when nothing changed.
        stale = builder.is_stale(con)
        version_ok = builder.meta_get(con, "schema_version") == builder.SCHEMA_VERSION
        fresh = (not stale) and version_ok
        payload = {
            "fresh": fresh,
            "stale": stale,
            "schema_version_ok": version_ok,
            "skills": int(builder.meta_get(con, "skill_count", "0") or 0),
            "tools": int(builder.meta_get(con, "tool_count", "0") or 0),
            "docs": int(builder.meta_get(con, "doc_count", "0") or 0),
            "built_at": float(builder.meta_get(con, "built_at", "0") or 0),
            "db": str(builder.db_path()),
        }
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            state = "✅ fresh" if fresh else "⚠️  stale"
            print(f"{state}  {payload['skills']} skills · {payload['tools']} tools · "
                  f"{payload['docs']} docs")
            print(f"   {payload['db']}")
        sys.exit(0 if fresh else 1)

    t0 = time.monotonic()
    summary = builder.ensure_built(con, rebuild=rebuild, with_contracts=with_contracts, progress=True)
    if with_vectors:
        from catalog import vectors as vectors_mod
        summary["vectors"] = vectors_mod.ensure(con)
    elapsed = time.monotonic() - t0
    if as_json:
        summary["elapsed_seconds"] = round(elapsed, 3)
        print(json.dumps(summary, indent=2))
        return
    verb = "rebuilt" if summary.get("rebuilt") else "up to date"
    extracted = summary.get("contracts_extracted", 0)
    detail = f" · {extracted} contracts extracted" if extracted else " · 0 contracts extracted (cached)"
    print(f"\n📇 Catalog {verb}: {summary['skills']} skills · {summary['tools']} tools · "
          f"{summary['docs']} docs{detail}")
    v = summary.get("vectors") or {}
    if v:
        if v.get("error"):
            print(f"   🧭 Dense leg: {v['error']} (BM25 only)")
        else:
            print(f"   🧭 Dense leg: {v.get('built', 0)} embedded · {v.get('dim', 0)}d "
                  f"· {v.get('skipped', 0)} unchanged")
    print(f"   {builder.db_path()}")
    print(f"   {elapsed * 1000:.0f} ms\n")


def cmd_eval(verbose: bool = False, as_json: bool = False, rerank: str = "never",
             fusion: str = "never", eval_set: str = "golden"):
    runner = SKILL_DIR / "tests" / "eval_runner.py"
    if not runner.is_file():
        sys.exit("❌ Error: tests/eval_runner.py not found next to omnicli.")
    args = [sys.executable, str(runner), f"--rerank={rerank}",
            f"--fusion={fusion}", f"--set={eval_set}"]
    if verbose:
        args.append("--verbose")
    if as_json:
        args.append("--json")
    sys.exit(subprocess.run(args).returncode)


def cmd_questions(skill_id: str | None = None, build: str | None = None,
                  as_json: bool = False):
    """Inspect the distilled-question snapshot, or curate a new one.

    The snapshot is what the dense leg embeds as ``kind='question'`` rows. It is
    opt-in: ``OMNICLI_QUESTIONS=1`` makes the index build them. Off by default
    because this catalog's descriptions already carry the user's vocabulary and
    the measured effect on routing was zero (see SKILL.md, "Distilled questions").
    """
    from catalog import questions, question_build, vectors

    if build:
        directory = Path(build)
        if not directory.is_dir():
            sys.exit(f"❌ Not a directory: {directory}")
        res = question_build.from_dir(directory)
        accepted = res["accepted"]
        rejected = res["rejected"]
        if res.get("error"):
            print(f"⚠️  {res['error']}")
        histogram: dict[str, int] = {}
        for entry in rejected:
            key = entry["reason"].split(" ")[0]
            histogram[key] = histogram.get(key, 0) + 1
        meta = {
            "generator": f"batches in {directory.name}",
            "proposed": sum(len(v) for v in accepted.values()) + len(rejected),
            "accepted": sum(len(v) for v in accepted.values()),
            "rejected": histogram,
            "self_floor": questions.SELF_FLOOR,
        }
        path = questions.write_snapshot(accepted, meta=meta)
        if as_json:
            print(json.dumps({"snapshot": str(path), **meta,
                              "rejected_detail": rejected}, indent=2, ensure_ascii=False))
            return
        print(f"\n📝 Snapshot: {path}")
        print(f"   accepted {meta['accepted']} / {meta['proposed']} "
              f"across {len(accepted)} skills")
        if histogram:
            print("   rejected : " + ", ".join(f"{k}={v}" for k, v in sorted(histogram.items())))
        print("   enable   : OMNICLI_QUESTIONS=1 omnicli index\n")
        return

    snapshot = questions.load()
    if not snapshot:
        print("\n📝 No question snapshot loaded.")
        print("   Build one:  omnicli questions --build <dir-of-batches>")
        print("   Enable it : OMNICLI_QUESTIONS=1 omnicli index")
        print("   Status    : the dense leg is description-only (the tuned default).\n")
        return

    if as_json:
        print(json.dumps(
            {"skills": len(snapshot),
             "questions": sum(len(v) for v in snapshot.values()),
             "enabled": bool(os.environ.get("OMNICLI_QUESTIONS") not in ("0", "false", "off")),
             "entries": snapshot if skill_id else {}},
            indent=2, ensure_ascii=False))
        return

    if skill_id:
        entries = snapshot.get(skill_id)
        if not entries:
            sys.exit(f"❌ No questions for {skill_id!r}; `omnicli questions` lists which have them.")
        from catalog import registry
        meta = registry.load_all_skills().get(skill_id) or {}
        source = " ".join((meta.get("description") or "").split())
        print(f"\n❓ [{skill_id}] {len(entries)} distilled question(s)\n")
        for i, entry in enumerate(entries, 1):
            ok, reason = questions.gate(entry["question"], entry["quote"], source, skill_id)
            flag = "✓" if ok else f"✗ {reason}"
            print(f"  {i}. {entry['question']}")
            print(f"     quote: \"{entry['quote']}\"  {flag}")
        print()
        return

    total = sum(len(v) for v in snapshot.values())
    enabled = questions.enabled()
    print(f"\n❓ Question snapshot: {len(snapshot)} skills · {total} questions"
          f" · {'ENABLED' if enabled else 'disabled (set OMNICLI_QUESTIONS=1)'}")
    print(f"   {questions.SNAPSHOT_PATH}")
    for name in sorted(snapshot):
        print(f"     {name:<26} {len(snapshot[name])} questions")
    print("\n   Inspect one : omnicli questions <skill>")
    print("   Rebuild     : OMNICLI_QUESTIONS=1 omnicli index\n")


# --------------------------------------------------------------------------
# exec / bindings
# --------------------------------------------------------------------------

def _bwrap_works() -> bool:
    exe = shutil.which("bwrap")
    if not exe:
        return False
    try:
        probe = subprocess.run([exe, "--ro-bind", "/", "/", "true"],
                               capture_output=True, timeout=5)
        return probe.returncode == 0
    except Exception:
        return False


def _clip(text: str, max_bytes: int, hint: str) -> str:
    data = text.encode("utf-8", errors="replace")
    if len(data) <= max_bytes:
        return text
    banner = f"\n… [omnicli] truncated at {max_bytes} bytes. {hint}\n"
    budget = max(0, max_bytes - len(banner.encode("utf-8")))
    return data[:budget].decode("utf-8", errors="ignore") + banner


def cmd_spec(skill: str | None = None, grep: str | None = None, kind: str | None = None,
             stubs: bool = False, only_enabled: bool = False, as_json: bool = False,
             limit: int | None = None, max_bytes: int = DEFAULT_MAX_BYTES):
    """Query the whole catalog without loading it.

    This is the CLI half of `spec()` in a plan: filter 481 contracts down to
    the ones a job needs, and read their signatures rather than their prose.
    """
    con = _require_catalog()
    if argspec_mod is None:
        sys.exit("❌ Error: omnicli catalog package not importable.")

    sql = "SELECT id, skill, kind, summary, contract, enabled FROM tools"
    clauses, params = [], []
    if skill:
        clauses.append("skill = ?")
        params.append(skill)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if only_enabled:
        clauses.append("enabled = 1")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    rows = con.execute(sql + " ORDER BY id", params).fetchall()

    pattern = re.compile(grep, re.IGNORECASE) if grep else None
    if pattern:
        rows = [r for r in rows if pattern.search(r["id"]) or pattern.search(r["summary"] or "")]
    if limit:
        rows = rows[: int(limit)]

    sigs = argspec_mod.signatures(rows)
    if as_json:
        payload = [{
            "id": s.id,
            "fn": s.func,
            "skill": s.skill,
            "kind": s.kind,
            "summary": s.summary[:200],
            "signature": s.line(),
            "required": [p.name for p in s.ordered_positionals() if p.required]
                        + [p.name for p in s.params if p.required],
            "params": {p.name: {"flag": p.flag, "type": p.kind if p.kind != "choices" else p.choices}
                       for p in s.params},
            "positionals": [p.name for p in s.ordered_positionals()],
            "commands": s.commands[:40],
            "enabled": bool(rows[i]["enabled"]),
        } for i, s in enumerate(sigs)]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    lines = [f"🔎 [omnicli spec] {len(sigs)} of {con.execute('SELECT COUNT(*) FROM tools').fetchone()[0]} tools"]
    for sig in sigs:
        if stubs:
            lines.append(f"  {sig.line()}")
            if sig.summary:
                lines.append(f"      # {sig.summary[:110]}")
        else:
            lines.append(f"  {sig.id:<58} {sig.kind:<10} {sig.func}")
    text = _clip("\n".join(lines) + "\n", max_bytes,
                 "Narrow with --skill/--grep/--limit, or raise --omni-max-bytes.")
    sys.stdout.write(text)

def cmd_bindings(out_dir: str | None = None, as_json: bool = False,
                 stubs: bool = False, skill: str | None = None, grep: str | None = None):
    con = _require_catalog()
    if builder is None or bindings_mod is None:
        sys.exit("❌ Error: omnicli catalog package not importable.")

    if stubs:
        lines = bindings_mod.stubs(con, skill=skill, grep=grep)
        sys.stdout.write(_clip("\n".join(lines) + "\n", DEFAULT_MAX_BYTES,
                               "Narrow with --skill/--grep."))
        return
    built = builder.ensure_built(con, progress=False)
    fingerprint = builder.meta_get(con, "fingerprint", "")
    target = bindings_mod.write(con, Path(out_dir) if out_dir else None)
    if not out_dir:
        target = bindings_mod.ensure(con, fingerprint, target)
    payload = {
        "dir": str(target),
        "module": str(target / "omnicli_tools.py"),
        "tools": built.get("tools"),
        "skills": built.get("skills"),
        "fingerprint": fingerprint,
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"🐍 Bindings written to {payload['module']}")
        print(f"   {payload['tools']} tools · {payload['skills']} skills · fingerprint {fingerprint[:12]}")


def cmd_exec(script: str | None = None, code: str | None = None,
             workspace: str | None = None, out_path: str | None = None,
             sandbox: str = "write", timeout: float = 300.0, as_json: bool = False,
             max_calls: int = 100, mem_limit: int | None = None):
    con = _require_catalog()
    if builder is None or bindings_mod is None:
        sys.exit("❌ Error: omnicli catalog package not importable.")
    if sandbox not in ("write", "strict", "none"):
        sys.exit(f"❌ Error: unknown sandbox mode {sandbox!r}")
    if max_calls < 0:
        sys.exit(f"❌ Error: --max-calls must be 0 (unlimited) or positive, not {max_calls}")
    if mem_limit is not None and mem_limit <= 0:
        sys.exit(f"❌ Error: --mem-limit must be a positive number of MiB, not {mem_limit}")
    if mem_limit is not None and sandbox == "none":
        sys.exit("❌ Error: --mem-limit needs a sandbox; --sandbox none runs without an rlimit")

    if not script and code is None:
        sys.exit("❌ Error: exec requires a plan script, -c/--code, or '-' from stdin.")
    if script and code is not None:
        sys.exit("❌ Error: cannot pass both a plan script and -c/--code.")

    inline_code: str | None = None
    if code is not None:
        inline_code = code
    elif script == "-":
        inline_code = sys.stdin.read()

    is_inline = inline_code is not None

    work = Path(workspace).resolve() if workspace else (
        Path.cwd().resolve() if is_inline else Path(script).resolve().parent
    )
    if not work.is_dir():
        sys.exit(f"❌ Error: workspace {work} is not a directory")

    script_path: Path
    if is_inline:
        temp_plan = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix=".omnicli_inline_plan_",
            dir=str(work),
            delete=False,
            encoding="utf-8",
        )
        temp_plan.write(inline_code)
        temp_plan.flush()
        temp_plan.close()
        script_path = Path(temp_plan.name).resolve()
    else:
        script_path = Path(script).resolve()
        if not script_path.is_file():
            sys.exit(f"❌ Error: no plan script at {script_path}")

    built = builder.ensure_built(con, progress=False)
    fingerprint = builder.meta_get(con, "fingerprint", "")
    bindings_dir = bindings_mod.ensure(con, fingerprint)

    trace = work / ".omnicli_trace.jsonl"
    seen = 0
    if trace.is_file():
        # One workspace keeps one trace log; count only rows this run appends.
        seen = sum(1 for line in trace.read_text(encoding="utf-8").splitlines() if line.strip())
    result_file = work / ".omnicli_result.json"
    if result_file.exists():
        result_file.unlink()

    env = os.environ.copy()
    env["OMNICLI_BIN"] = shutil.which("omnicli") or str(SCRIPT_PATH)
    env["OMNICLI_TRACE"] = str(trace)
    env["OMNICLI_RESULT"] = str(result_file)
    env["OMNICLI_MAX_CALLS"] = str(max_calls)
    env["OMNICLI_TRUST_INDEX"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(bindings_dir) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    cmd = [sys.executable, str(script_path)]
    runtime: Path | None = None
    serving = None
    bridge_server = None
    sandboxed = False

    if sandbox != "none":
        if not _bwrap_works():
            sys.exit("❌ Error: bubblewrap is not available; pass --sandbox none to run unsandboxed.")
        sandboxed = True
        base = [
            "bwrap", "--die-with-parent", "--unshare-pid", "--unshare-ipc",
            "--unshare-uts", "--ro-bind", "/", "/", "--tmpfs", "/tmp",
            "--dev", "/dev", "--proc", "/proc",
        ]
        tail: list[str] = []

        if sandbox == "strict":
            if bridge_mod is None:
                sys.exit("❌ Error: omnicli catalog package not importable.")
            runtime = Path(tempfile.mkdtemp(prefix="omnicli-strict-"))
            shim = bridge_mod.write_shim(runtime / "bin")
            shim_dir = shim.parent
            serving = bridge_mod.Serving(runtime / "bridge.sock", SCRIPT_PATH, timeout)
            bridge_server = serving.__enter__()
            base += [
                "--unshare-net",
                "--tmpfs", str(Path.home()),
                "--bind", str(work), str(work),
                "--dir", "/tmp/omnicli",
                "--ro-bind", str(bindings_dir), "/tmp/omnicli/bindings",
                "--ro-bind", str(shim_dir), "/tmp/omnicli/bin",
                "--bind", str(runtime), "/tmp/omnicli/bridge",
            ]
            tail = [
                "--setenv", "OMNICLI_BRIDGE", "/tmp/omnicli/bridge/bridge.sock",
                "--setenv", "OMNICLI_BIN", "/tmp/omnicli/bin/omnicli",
                "--setenv", "PYTHONPATH", "/tmp/omnicli/bindings",
            ]
        cmd = base + [
            "--bind", str(work), str(work), "--chdir", str(work),
            "--setenv", "HOME", str(work),
        ] + tail + [sys.executable, str(script_path)]

        if mem_limit is not None:
            if not shutil.which("prlimit"):
                sys.exit("❌ Error: --mem-limit needs prlimit (util-linux) to set RLIMIT_AS")
            # bwrap has no --rlimit-* option, so the cap is set on bwrap itself;
            # the plan and every process it spawns inherit it. Soft = hard, so the
            # plan cannot raise its own ceiling back up.
            cap = mem_limit * 1024 * 1024
            cmd = ["prlimit", f"--as={cap}:{cap}", "--"] + cmd

    started = time.time()
    if os.environ.get("OMNICLI_EXEC_DEBUG"):
        print(" ".join(cmd), file=sys.stderr)
    try:
        proc = subprocess.run(cmd, cwd=str(work), env=env, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        sys.exit(f"❌ Error: plan exceeded {timeout:g}s")
    finally:
        if is_inline and script_path.is_file():
            script_path.unlink(missing_ok=True)
        if serving is not None:
            serving.__exit__()
        if runtime is not None:
            shutil.rmtree(runtime, ignore_errors=True)
    elapsed = time.time() - started

    stderr_text = proc.stderr
    if proc.returncode != 0 and mem_limit is not None and (
        "MemoryError" in proc.stderr or "can't start new thread" in proc.stderr
    ):
        stderr_text += (
            f"\n[omnicli] this plan ran under --mem-limit {mem_limit} MiB (RLIMIT_AS). "
            "A MemoryError or thread-creation failure above is the cap, not the plan's logic.\n"
        )

    calls = 0
    if trace.is_file():
        rows = [line for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
        for line in rows[seen:]:
            try:
                kind = json.loads(line).get("kind")
            except (ValueError, AttributeError):
                kind = None
            if kind in (None, "call"):
                calls += 1

    result = None
    if result_file.is_file():
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = None
        result_file.unlink(missing_ok=True)

    if out_path:
        target = Path(out_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(proc.stdout, encoding="utf-8")

    bridge_calls = getattr(bridge_server, "calls", 0)
    bridge_denied = getattr(bridge_server, "denied", [])
    if as_json:
        plan_desc = "<stdin>" if script == "-" else ("<inline>" if code is not None else str(script_path))
        print(json.dumps({
            "plan": plan_desc,
            "sandboxed": sandboxed,
            "sandbox": sandbox,
            "mem_limit": mem_limit,
            "exit_code": proc.returncode,
            "seconds": round(elapsed, 3),
            "tool_calls": calls,
            "bridge_calls": bridge_calls,
            "bridge_denied": bridge_denied,
            "tools": built.get("tools"),
            "result": result,
            "stdout": proc.stdout,
            "stderr": stderr_text[-2000:],
        }, indent=2))
        if proc.returncode != 0 and stderr_text:
            sys.stderr.write(stderr_text if stderr_text.endswith("\n") else stderr_text + "\n")
    else:
        sys.stdout.write(proc.stdout)
        if stderr_text:
            sys.stderr.write(stderr_text if stderr_text.endswith("\n") else stderr_text + "\n")
        detail = f"sandbox={sandbox}"
        if bridge_calls:
            detail += f" · bridge={bridge_calls} call(s)"
        print(f"🐍 [exec] {calls} tool call(s) in one turn · {elapsed:.2f}s · {detail}",
              file=sys.stderr)
    _merge_exec_trace(trace, seen)
    sys.exit(proc.returncode)


# --------------------------------------------------------------------------
# compat
# --------------------------------------------------------------------------

def cmd_inspect(skill_name: str):
    """Legacy: dump a skill's SKILL.md body."""
    skills = registry.load_all_skills(include_sidelined=True)
    target = None
    for name, s in skills.items():
        if name == skill_name or s["dir_name"] == skill_name:
            target = s
            break
    if not target:
        sys.exit(f"❌ Error: Skill '{skill_name}' not found.")
    status_tag = f" [{target.get('status').upper()}]" if target.get("status") != "active" else ""
    print(f"\n📖 [omnicli inspect] {target['name']}{status_tag}\n")
    print(f"   Path: {target['path']}")
    print(f"   Tools: omnicli tools {target['name']}\n")
    import re
    content = Path(target["md_path"]).read_text(encoding="utf-8")
    print(re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL))


def cmd_run(skill_name: str, extra_args: list[str], out_path: str | None = None,
            project_fields: str | None = None, jq_expr: str | None = None):
    """Legacy: run a skill by name, with projection and disk buffering."""
    if skill_name in ("llm", "llm-cli"):
        exec_internal_script("llm_client.py", extra_args)
    elif skill_name in ("ocr", "ocr-cli"):
        exec_internal_script("ocr.py", extra_args)
    elif skill_name in ("decide", "jev", "jev-cli"):
        exec_internal_script("decide.py", extra_args)
    elif skill_name in ("asr", "audiocpp-asr"):
        exec_internal_script("asr.py", extra_args)

    con = _require_catalog()
    row = con.execute(
        "SELECT id FROM tools WHERE skill = ? AND kind = 'script' ORDER BY id LIMIT 1",
        (skill_name,),
    ).fetchone()
    if row is None:
        row = con.execute(
            "SELECT id FROM tools WHERE id = ?", (f"{skill_name}/cli",)
        ).fetchone()
    if row is None:
        sys.exit(f"❌ Error: Skill '{skill_name}' not found.")
    cmd_invoke(row["id"], extra_args, out_path=out_path,
               project_fields=project_fields, jq_expr=jq_expr)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    if len(sys.argv) > 1:
        subcmd = sys.argv[1]
        if subcmd == "invoke":
            # Parsed manually: see parse_invoke_args.
            tool_id, opts, tool_args = parse_invoke_args(sys.argv[2:])
            if not tool_id:
                sys.exit("❌ Error: `omnicli invoke` needs a tool id. "
                         "Use `omnicli tools <skill>` to list them.")
            with _traced("invoke", tool_id):
                cmd_invoke(
                    tool_id, tool_args,
                    out_path=opts["buffer"], project_fields=opts["project"],
                    jq_expr=opts["jq"], grep=opts["grep"],
                    max_bytes=opts["max_bytes"], as_json=opts["json"],
                    timeout=float(opts["timeout"]),
                )
        if subcmd == "do":
            # Parsed manually: see parse_do_args.
            intent, do_opts, do_args = parse_do_args(sys.argv[2:])
            if not intent:
                sys.exit("❌ Error: `omnicli do` needs an intent. "
                         'Example: omnicli do "transcribe this recording"')
            with _traced("do", intent):
                cmd_do(intent, do_opts, do_args)
        if subcmd == "llm":
            exec_internal_script("llm_client.py", sys.argv[2:])
        elif subcmd == "ocr":
            exec_internal_script("ocr.py", sys.argv[2:])
        elif subcmd in ("decide", "jev"):
            exec_internal_script("decide.py", sys.argv[2:])
        elif subcmd == "asr":
            exec_internal_script("asr.py", sys.argv[2:])
        elif subcmd in ("cdp", "browser"):
            fast_cdp = shutil.which("fast-cdp") or str(
                registry.resolve_skills_dir() / "hybrid-browser" / "scripts" / "fast-cdp")
            sys.exit(subprocess.run([fast_cdp] + sys.argv[2:]).returncode)

    prog_name = Path(sys.argv[0]).name
    if prog_name not in ("omnicli", "uber", "local-hub", "skills-hub"):
        prog_name = "omnicli"

    if prog_name in ("local-hub", "skills-hub"):
        print("⚠️  'local-hub'/'skills-hub' are deprecated aliases for 'omnicli'. "
              "Use `omnicli` directly.", file=sys.stderr)

    parser = argparse.ArgumentParser(
        prog=prog_name,
        description="omnicli — unified late-binding gateway to every local tool",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # --- native local inference -------------------------------------
    p = sub.add_parser("llm", help="Query the local dual-GPU Genesis 35B on :8080")
    p.add_argument("args", nargs=argparse.REMAINDER)

    p = sub.add_parser("ocr", help="Local document/slide/image OCR on :8085")
    p.add_argument("args", nargs=argparse.REMAINDER)

    p = sub.add_parser("decide", help="Calibrated decisions (bool/choice/score) on :8083")
    p.add_argument("args", nargs=argparse.REMAINDER)

    p = sub.add_parser("jev", help="Alias for decide")
    p.add_argument("args", nargs=argparse.REMAINDER)

    p = sub.add_parser("asr", help="Local speech-to-text via audio.cpp on :8081")
    p.add_argument("args", nargs=argparse.REMAINDER)

    p = sub.add_parser("cdp", aliases=["browser"], help="Fast CDP browser control on :9222")
    p.add_argument("args", nargs=argparse.REMAINDER)

    # --- catalog -----------------------------------------------------
    p = sub.add_parser("do", help="One hop: intent -> runnable tool (search+describe+invoke)",
                       add_help=False)
    p.add_argument("args", nargs=argparse.REMAINDER)

    p = sub.add_parser("search", help="Find tools by intent (BM25 over every skill body)")
    p.add_argument("query", help="Natural-language intent")
    p.add_argument("--json", action="store_true")
    p.add_argument("--limit", type=int, default=6)
    p.add_argument("--explain", action="store_true", help="Show matched terms and the winning chunk")
    p.add_argument("--no-rerank", action="store_true", help="Skip the optional embedding re-ranker")
    p.add_argument("--rerank", choices=["auto", "always", "never"], default="auto",
                   help="auto=only re-rank when the lexical ranking is unsure (default), "
                        "always=re-rank every query, never=never re-rank")
    p.add_argument("--fusion", choices=["auto", "always", "never"], default="auto",
                   help="auto=fuse the dense leg only when BM25 is unsure (default), "
                        "always=fuse on every query (best on unseen phrasing), "
                        "never=lexical leg only")
    p.add_argument("--chunks", action="store_true",
                   help="With --json: include every matching chunk (default is the "
                        "compact routing view: skill, score, why, top hit)")

    p = sub.add_parser("list", help="List every skill in the registry")
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true", help="Include sidelined and archived skills")

    p = sub.add_parser("tools", help="List the tools belonging to a skill")
    p.add_argument("skill")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("describe", help="Show the exact input contract for ONE tool, or a skill's body")
    p.add_argument("tool_id")
    p.add_argument("--json", action="store_true")
    p.add_argument("--section", default="", help="With a skill name: the heading of the section to read")
    p.add_argument("--doc", default="", help="With a skill name: the path or title of a document to read")

    p = sub.add_parser("invoke", help="Execute a tool with bounded output",
                       add_help=False)
    p.add_argument("tool_id")
    p.add_argument("--omni-buffer", default=None, help="Buffer the full output to a file")
    p.add_argument("--omni-project", default=None, help="Comma-separated fields to keep from JSON output")
    p.add_argument("--omni-jq", default=None, help="JQ filter expression")
    p.add_argument("--omni-grep", default=None, help="Keep only lines matching this regex")
    p.add_argument("--omni-max-bytes", type=int, metavar="N", default=DEFAULT_MAX_BYTES,
                   help=f"Hard cap on returned bytes (default {DEFAULT_MAX_BYTES})")
    p.add_argument("--omni-json", action="store_true")
    p.add_argument("--omni-timeout", type=float, default=300.0)
    p.add_argument("args", nargs=argparse.REMAINDER)

    p = sub.add_parser("enable", help="Expose a discovered tool to agents (gate)")
    p.add_argument("tool_id", nargs="?")
    p.add_argument("--all", action="store_true", help="Enable every catalogued tool")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("disable", help="Withdraw a tool without deleting it")
    p.add_argument("tool_id", nargs="?")
    p.add_argument("--all", action="store_true", help="Disable every tool")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("policy", help="Show the enable gate and its audit log")
    p.add_argument("tool_id", nargs="?")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("index", help="Build or refresh the catalog index")
    p.add_argument("--rebuild", action="store_true", help="Force a full rebuild")
    p.add_argument("--no-contracts", action="store_true", help="Skip --help contract extraction")
    p.add_argument("--check", action="store_true",
                   help="Report whether the index is fresh, without rebuilding")
    p.add_argument("--no-vectors", action="store_true",
                   help="Skip refreshing the dense-leg vectors (skill descriptions)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("alias", help="Read or write a skill's curated routing metadata")
    p.add_argument("skill", nargs="?", help="Skill name; omit with --list to show all")
    p.add_argument("--aliases", default=None, help="Comma-separated alias list (replaces)")
    p.add_argument("--tags", default=None, help="Comma-separated tag list (replaces)")
    p.add_argument("--remove", action="store_true", help="Delete a skill's curated metadata")
    p.add_argument("--list", action="store_true", help="Show every skill's curated metadata")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("eval", help="Run the golden routing evaluation")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--rerank", choices=["auto", "always", "never"], default="never",
                   help="re-ranker mode used during the eval (default: never; the "
                        "catalog's own default is auto)")
    p.add_argument("--fusion", choices=["auto", "always", "never"], default="never",
                   help="dense-leg fusion used during the eval (default: never)")
    p.add_argument("--set", dest="eval_set", choices=["golden", "paraphrase"],
                   default="golden", help="golden=tuned routes, paraphrase=blind "
                                          "user prompts harvested from this machine")

    p = sub.add_parser("questions",
                       help="Inspect or curate the distilled-question snapshot")
    p.add_argument("skill", nargs="?", default=None,
                   help="Show one skill's questions and their verbatim quotes")
    p.add_argument("--build", default=None, metavar="DIR",
                   help="Gate a directory of generated batch files into the snapshot")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("spec", help="Query the catalog surface without loading it")
    p.add_argument("--skill", default=None)
    p.add_argument("--grep", default=None, help="Case-insensitive regex over id and summary")
    p.add_argument("--kind", default=None, choices=["script", "cli", "subcommand", "endpoint"])
    p.add_argument("--enabled", action="store_true", help="Only tools that passed the gate")
    p.add_argument("--stubs", action="store_true", help="Print annotated signatures instead of ids")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--omni-max-bytes", type=int, metavar="N", default=DEFAULT_MAX_BYTES)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("bindings", help="Write the Python bindings used by `omnicli exec`")
    p.add_argument("--out", default=None, help="Output directory (default ~/.local/share/omnicli/bindings)")
    p.add_argument("--stubs", action="store_true", help="Print the generated signatures instead of writing")
    p.add_argument("--skill", default=None, help="With --stubs: only this skill")
    p.add_argument("--grep", default=None, help="With --stubs: only matching ids or summaries")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("exec", aliases=["plan"],
                       help="Run one plan script with tool bindings, in a sandbox")
    p.add_argument("script", nargs="?", default=None,
                   help="Path to the Python plan, or '-' to read from stdin")
    p.add_argument("-c", "--code", default=None,
                   help="Inline Python code string to execute as a plan")
    p.add_argument("--workspace", default=None, help="Writable directory (default: the script's folder or cwd)")
    p.add_argument("--out", default=None, help="Also write the plan's stdout to this file")
    p.add_argument("--sandbox", choices=["write", "strict", "none"], default="write",
                   help="write: writable workspace, open network. "
                        "strict: no network, home masked, every tool call crosses the bridge. "
                        "none: unsandboxed.")
    p.add_argument("--no-sandbox", action="store_true", help="Alias for --sandbox none")
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--max-calls", type=int, default=100, metavar="N",
                   help="Tool calls one plan may make; 0 = unlimited (default 100)")
    p.add_argument("--mem-limit", type=int, default=None, metavar="MiB",
                   help="Address-space cap in MiB (RLIMIT_AS) on the plan process and "
                        "every child it spawns; unset = no cap, needs a sandbox")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("status", aliases=["health"],
                       help="Health of every local service, the catalog, and the retrieval tier")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("usage", help="Telemetry: calls per harness, top tools, and search→action rate")
    p.add_argument("--trace", default=None, help="Trace file (default: ~/.local/share/omnicli/trace.jsonl)")
    p.add_argument("--since", default="7d", help="30m, 24h, 7d, 2w or an ISO date (default 7d)")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("harness", help="First-party harness support (t3-code, agy, opencode, pi, boxxy)")
    p.add_argument("subaction", nargs="?", choices=["list", "detect", "info", "show", "config", "verify"], default="list")
    p.add_argument("target", nargs="?", default=None, help="Harness name (t3-code, agy, opencode, pi, boxxy)")
    p.add_argument("--json", action="store_true")

    # --- compat ------------------------------------------------------
    p = sub.add_parser("inspect", help="(legacy) Print a skill's SKILL.md body")
    p.add_argument("skill")

    p = sub.add_parser("run", help="(legacy) Run a skill by name")
    p.add_argument("skill")
    p.add_argument("--out", default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--jq", default=None)
    p.add_argument("args", nargs=argparse.REMAINDER)

    args = parser.parse_args()

    if args.action == "llm":
        exec_internal_script("llm_client.py", args.args)
    elif args.action == "ocr":
        exec_internal_script("ocr.py", args.args)
    elif args.action in ("decide", "jev"):
        exec_internal_script("decide.py", args.args)
    elif args.action == "asr":
        exec_internal_script("asr.py", args.args)
    elif args.action in ("cdp", "browser"):
        fast_cdp = shutil.which("fast-cdp") or str(
            registry.resolve_skills_dir() / "hybrid-browser" / "scripts" / "fast-cdp")
        sys.exit(subprocess.run([fast_cdp] + args.args).returncode)
    elif args.action == "search":
        with _traced("search", " ".join(args.query) if isinstance(args.query, list) else str(args.query)):
            cmd_search(args.query, as_json=args.json, limit=args.limit,
                       explain=args.explain, no_rerank=args.no_rerank,
                       rerank=args.rerank, chunks=args.chunks, fusion=args.fusion)
    elif args.action == "list":
        cmd_list(as_json=args.json, show_all=args.all)
    elif args.action == "tools":
        cmd_tools(args.skill, as_json=args.json)
    elif args.action == "describe":
        with _traced("describe", args.tool_id):
            cmd_describe(args.tool_id, as_json=args.json, section=args.section, doc=args.doc)
    elif args.action == "index":
        cmd_index(rebuild=args.rebuild, with_contracts=not args.no_contracts,
                  as_json=args.json, check=args.check, with_vectors=not args.no_vectors)
    elif args.action == "enable":
        cmd_gate(args.tool_id, True, as_json=args.json, all_tools=args.all)
    elif args.action == "disable":
        cmd_gate(args.tool_id, False, as_json=args.json, all_tools=args.all)
    elif args.action == "policy":
        cmd_policy(args.tool_id, as_json=args.json)
    elif args.action == "alias":
        cmd_alias(skill=args.skill, aliases=args.aliases, tags=args.tags,
                  remove=args.remove, show_all=args.list, as_json=args.json)
    elif args.action == "eval":
        cmd_eval(verbose=args.verbose, as_json=args.json, rerank=args.rerank,
                 fusion=args.fusion, eval_set=args.eval_set)
    elif args.action == "questions":
        cmd_questions(skill_id=args.skill, build=args.build, as_json=args.json)
    elif args.action == "bindings":
        cmd_bindings(out_dir=args.out, as_json=args.json, stubs=args.stubs,
                     skill=args.skill, grep=args.grep)
    elif args.action == "spec":
        cmd_spec(skill=args.skill, grep=args.grep, kind=args.kind, stubs=args.stubs,
                 only_enabled=args.enabled, as_json=args.json, limit=args.limit,
                 max_bytes=args.omni_max_bytes)
    elif args.action in ("exec", "plan"):
        mode = "none" if args.no_sandbox else args.sandbox
        cmd_exec(script=args.script, code=args.code, workspace=args.workspace,
                 out_path=args.out, sandbox=mode, timeout=args.timeout,
                 as_json=args.json, max_calls=args.max_calls, mem_limit=args.mem_limit)
    elif args.action in ("status", "health"):
        cmd_status(as_json=args.json)
    elif args.action == "usage":
        cmd_usage(trace=args.trace, since=args.since, as_json=args.json, limit=args.limit)
    elif args.action == "harness":
        cmd_harness(subaction=args.subaction, target=args.target, as_json=args.json)
    elif args.action == "inspect":
        cmd_inspect(args.skill)
    elif args.action == "run":
        cmd_run(args.skill, args.args, out_path=args.out,
                project_fields=args.project, jq_expr=args.jq)


if __name__ == "__main__":
    main()
