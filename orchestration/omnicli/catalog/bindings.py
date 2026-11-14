"""Generate the Python binding module used by `omnicli exec`.

The bindings are deliberately thin at the transport layer: every call shells
out to the `omnicli` CLI, so a plan inherits the enable gate, field
projection, byte cap and disk buffer rather than reimplementing them. What
the sandbox buys is not a second policy engine — it is the ability to keep
intermediate values in variables instead of the model's context window.

The surface layer is not thin. Each catalogued tool gets one annotated
function, generated from its extracted `--help`, so a plan calls
`zoom_recording(url=...)` and an unknown or misspelled argument fails at
import time instead of halfway through a fifty-call run.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

from . import argspec

BINDINGS_VERSION = "4"

MODULE_HEAD = '''"""omnicli bindings — generated file, do not edit.

One plan, one turn. `search()` picks a tool by intent, `spec()` queries the
whole catalog without loading it, and every tool also exists as an annotated
function (`zoom_recording(url=...)`). Intermediate values stay in Python
variables; only what you print comes back to the model.

Every call goes through the `omnicli` CLI, so the enable gate, projection,
byte cap and buffer behave exactly as they do from the shell. One call is one
process, so independent calls are worth overlapping: the `a*` twins do the
same work without blocking, and `parallel()` fans them out.

A plan is bounded. `omnicli exec --max-calls` caps nested calls and fails at
the call site rather than after the run, and `emit_result()` hands one value
back on its own channel instead of printing it into stdout.
"""

from __future__ import annotations

import asyncio
import collections
import json
import os
import subprocess
import threading
import time
from typing import Any, Literal

OMNICLI = os.environ.get("OMNICLI_BIN", "omnicli")
TOOL_IDS = __TOOL_IDS__
SPEC: list[dict[str, Any]] = json.loads(__SPEC__)
SIGNATURES: dict[str, str] = {row["id"]: row["sig"] for row in SPEC}

DEFAULT_MAX_CALLS = 100
_CALL_LOCK = threading.Lock()
_CALLS = 0
_RECENT: collections.deque = collections.deque(maxlen=20)

_HARNESS_MARKERS = (
    # Liveness markers are set by the harness running *this* process, so they
    # beat variables inherited from an outer agent: a shell in T3 Code that
    # launches `agy` still carries T3CODE_CLI_PATH.
    ("agy", ("ANTIGRAVITY_AGENT",)),
    ("pi", ("PI_AGENT",)),
    ("boxxy", ("BOXXY_TERMINAL",)),
    ("t3-code", ("T3CODE_CLI_PATH",)),
    ("opencode", ("OPENCODE_SESSION_ID", "OPENCODE")),
)

_SESSION_ENV = {
    "agy": "ANTIGRAVITY_CONVERSATION_ID",
    "t3-code": "OPENCODE_SESSION_ID",
    "opencode": "OPENCODE_SESSION_ID",
}


def trace_identity():
    """(harness, session) for one trace row: explicit env, then liveness markers.

    Nesting is the hard case. A T3 Code shell that launches `agy` inherits
    T3CODE_CLI_PATH, so a first-match table that tests the outer harness first
    blames the wrong one; per-process liveness variables go first instead. A
    harness nested inside another (opencode inside agy) is still ambiguous —
    set OMNICLI_HARNESS to settle it.
    """
    harness = (os.environ.get("OMNICLI_HARNESS") or "").strip()
    if not harness:
        for name, markers in _HARNESS_MARKERS:
            if any(os.environ.get(m) for m in markers):
                harness = name
                break
        else:
            harness = "cli"
    session = (os.environ.get("OMNICLI_SESSION")
               or os.environ.get(_SESSION_ENV.get(harness, ""), "")
               or f"ppid:{os.getppid()}")
    return harness, session


def user_trace_path() -> str:
    """Where usage rows live: one per user, not per workspace.

    Returns a string: the generated module stays import-light so a sandbox
    cannot fail on a library the plan never needed.
    """
    override = os.environ.get("OMNICLI_USER_TRACE")
    if override:
        return os.path.expanduser(override)
    return os.path.join(os.path.expanduser("~"), ".local", "share", "omnicli", "trace.jsonl")


def emit_result(value):
    """Publish one value as `exec --json`'s `result`, separate from stdout.

    stdout stays the plan's own prose and the result travels on its own file,
    so neither side has to parse the other. No-op without the env var.
    """
    path = os.environ.get("OMNICLI_RESULT")
    if not path:
        return
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(value, ensure_ascii=False))


def _log(event):
    """Append one row to the exec trace, tagged with harness and session.

    Only the workspace trace is written here: the sandbox has `/` read-only, so
    the parent `omnicli exec` merges these rows into the per-user usage trace
    once the plan is done.
    """
    harness, session = trace_identity()
    event.setdefault("harness", harness)
    event.setdefault("session", session)
    event.setdefault("via", "exec")
    path = os.environ.get("OMNICLI_TRACE")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\\n")
    except OSError:
        pass


def _endpoint(argv):
    return (argv[1] if len(argv) > 1 else "", argv[2] if len(argv) > 2 else "")


def _max_calls():
    raw = os.environ.get("OMNICLI_MAX_CALLS")
    if not raw:
        return DEFAULT_MAX_CALLS
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MAX_CALLS


def _reserve(argv):
    """Take one slot of the call budget before a subprocess exists.

    Reserved before dispatch, so a fan-out cannot overshoot by its own width.
    A slot is never returned: a call that raises still counts.
    """
    global _CALLS
    verb, target = _endpoint(argv)
    limit = _max_calls()
    with _CALL_LOCK:
        _CALLS += 1
        count = _CALLS
        _RECENT.append(f"{verb} {target!r}")
        if limit and count > limit:
            raise RuntimeError(
                f"call {count} of {limit} (max-calls); recent calls: "
                + ", ".join(_RECENT))


def _open_call(argv):
    verb, target = _endpoint(argv)
    _log({"kind": "call", "call": verb, "tool": target, "t": time.time()})
    return verb, target, time.perf_counter()


def _close_call(verb, target, started, rc):
    _log({"kind": "done", "call": verb, "tool": target,
          "ms": int((time.perf_counter() - started) * 1000), "rc": rc})


def _run(argv):
    verb, target, started = _open_call(argv)
    _reserve(argv)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True)
    except BaseException:
        _close_call(verb, target, started, -1)
        raise
    _close_call(verb, target, started, proc.returncode)
    return proc


async def _arun(argv):
    verb, target, started = _open_call(argv)
    _reserve(argv)
    try:
        proc = await asyncio.to_thread(subprocess.run, argv, capture_output=True, text=True)
    except BaseException:
        _close_call(verb, target, started, -1)
        raise
    _close_call(verb, target, started, proc.returncode)
    return proc


def _payload(proc, label):
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"{label} failed")
    return json.loads(proc.stdout)


def _envelope(proc, tool_id):
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(proc.stderr.strip() or f"{tool_id} failed")
    return json.loads(proc.stdout)


def _argv_search(intent, limit):
    return [OMNICLI, "search", intent, "--json", "--limit", str(limit)]


def _argv_skills():
    return [OMNICLI, "list", "--json"]


def _argv_tools(skill):
    return [OMNICLI, "tools", skill, "--json"]


def _argv_describe(tool_id):
    return [OMNICLI, "describe", tool_id, "--json"]


def _argv_invoke(tool_id, args, project=None, grep=None, max_bytes=None, timeout=300.0):
    argv = [OMNICLI, "invoke", tool_id, *[str(a) for a in args], "--omni-json"]
    if project:
        argv += ["--omni-project", project]
    if grep:
        argv += ["--omni-grep", grep]
    if max_bytes is not None:
        argv += ["--omni-max-bytes", str(max_bytes)]
    argv += ["--omni-timeout", str(timeout)]
    return argv


def search(intent, limit=6):
    """Route by intent. Returns compact rows: skill, score, matched, why."""
    return _payload(_run(_argv_search(intent, limit)), "search").get("results", [])


def skills():
    """Every skill the catalog knows about."""
    return _payload(_run(_argv_skills()), "list")


def tools(skill):
    """The executable tools inside one skill."""
    return _payload(_run(_argv_tools(skill)), "tools")


def describe(tool_id):
    """One tool's exact contract (usage, flags, state)."""
    return _payload(_run(_argv_describe(tool_id)), "describe")


def spec(skill=None, grep=None, kind=None, limit=None):
    """Query every catalogued tool: id, fn, required args, flags, commands.

    Filtering happens here, in the plan, so 481 contracts never cross into
    the model's window. `grep` is a case-insensitive regular expression over
    the id and the summary.
    """
    import re

    pattern = re.compile(grep, re.IGNORECASE) if grep else None
    rows = []
    for row in SPEC:
        if skill and row["skill"] != skill:
            continue
        if kind and row["kind"] != kind:
            continue
        if pattern and not (pattern.search(row["id"]) or pattern.search(row["summary"])):
            continue
        rows.append(row)
        if limit and len(rows) >= int(limit):
            break
    return rows


def invoke(tool_id, *args, project=None, grep=None, max_bytes=None, timeout=300.0):
    """Run one enabled tool. Returns the CLI envelope: output, exit_code, bytes."""
    proc = _run(_argv_invoke(tool_id, args, project=project, grep=grep,
                             max_bytes=max_bytes, timeout=timeout))
    return _envelope(proc, tool_id)


def output(tool_id, *args, **kwargs):
    """invoke() and return only the shaped stdout, not the envelope."""
    return invoke(tool_id, *args, **kwargs).get("output", "")


async def asearch(intent, limit=6):
    """search() without blocking the plan."""
    return _payload(await _arun(_argv_search(intent, limit)), "search").get("results", [])


async def askills():
    """skills() without blocking the plan."""
    return _payload(await _arun(_argv_skills()), "list")


async def atools(skill):
    """tools() without blocking the plan."""
    return _payload(await _arun(_argv_tools(skill)), "tools")


async def adescribe(tool_id):
    """describe() without blocking the plan."""
    return _payload(await _arun(_argv_describe(tool_id)), "describe")


async def ainvoke(tool_id, *args, **kwargs):
    """invoke() without blocking the plan."""
    return _envelope(await _arun(_argv_invoke(tool_id, args, **kwargs)), tool_id)


async def aoutput(tool_id, *args, **kwargs):
    """output() without blocking the plan."""
    return (await ainvoke(tool_id, *args, **kwargs)).get("output", "")


async def parallel(calls, limit=8):
    """Run independent calls at once. Results keep input order.

    Each item is either a zero-arg callable or a `(fn, args, kwargs)` tuple;
    at most `limit` are in flight. Exceptions surface through `gather`, so one
    failure fails the batch. Pass the `a*` twins: a sync callable runs inline
    and holds the loop for its whole subprocess.
    """
    gate = asyncio.Semaphore(limit)

    async def one(call):
        fn, args, kwargs = (call, (), {}) if callable(call) else call
        async with gate:
            value = fn(*args, **kwargs)
            if hasattr(value, "__await__"):
                value = await value
            return value

    return await asyncio.gather(*[one(call) for call in calls])

'''


# The generated module cannot import from `catalog`, so the identity helpers
# exist twice: once in the template above (for plan runs) and once here (for the
# CLI). Keep the marker table in sync — `test_usage` asserts they agree.
_HARNESS_MARKERS = (
    # Liveness markers are set by the harness running *this* process, so they
    # beat variables inherited from an outer agent: a shell in T3 Code that
    # launches `agy` still carries T3CODE_CLI_PATH.
    ("agy", ("ANTIGRAVITY_AGENT",)),
    ("pi", ("PI_AGENT",)),
    ("boxxy", ("BOXXY_TERMINAL",)),
    ("t3-code", ("T3CODE_CLI_PATH",)),
    ("opencode", ("OPENCODE_SESSION_ID", "OPENCODE")),
)

_SESSION_ENV = {
    "agy": "ANTIGRAVITY_CONVERSATION_ID",
    "t3-code": "OPENCODE_SESSION_ID",
    "opencode": "OPENCODE_SESSION_ID",
}


def trace_identity():
    """(harness, session) for one trace row; see the copy in MODULE_HEAD."""
    harness = (os.environ.get("OMNICLI_HARNESS") or "").strip()
    if not harness:
        for name, markers in _HARNESS_MARKERS:
            if any(os.environ.get(m) for m in markers):
                harness = name
                break
        else:
            harness = "cli"
    session = (os.environ.get("OMNICLI_SESSION")
               or os.environ.get(_SESSION_ENV.get(harness, ""), "")
               or f"ppid:{os.getppid()}")
    return harness, session


def user_trace_path() -> str:
    """Where usage rows live: one per user, not per workspace.

    Returns a string: the generated module stays import-light so a sandbox
    cannot fail on a library the plan never needed.
    """
    override = os.environ.get("OMNICLI_USER_TRACE")
    if override:
        return os.path.expanduser(override)
    return os.path.join(os.path.expanduser("~"), ".local", "share", "omnicli", "trace.jsonl")


def _spec_rows(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT id, skill, kind, summary, contract FROM tools ORDER BY id"
    ).fetchall()
    sigs = argspec.signatures(rows)
    payload = []
    for sig in sigs:
        payload.append({
            "id": sig.id,
            "fn": sig.func,
            "skill": sig.skill,
            "kind": sig.kind,
            "summary": sig.summary[:160],
            "sig": sig.line(),
            "args": [p.name for p in sig.ordered_positionals()],
            "required": [p.name for p in sig.ordered_positionals() if p.required]
                        + [p.name for p in sig.params if p.required],
            "params": {
                p.name: {
                    "flag": p.flag,
                    "type": p.kind if p.kind != "choices" else p.choices,
                }
                for p in sig.params
            },
            "commands": sig.commands[:32],
        })
    return payload, sigs


def module_source(con: sqlite3.Connection) -> str:
    payload, sigs = _spec_rows(con)
    ids = [sig.id for sig in sigs]
    source = MODULE_HEAD.replace("__TOOL_IDS__", json.dumps(ids, ensure_ascii=False, indent=0))
    source = source.replace("__SPEC__", repr(json.dumps(payload, ensure_ascii=False)))

    generated = [
        "\n# " + "-" * 70 + "\n# one function per catalogued tool\n# " + "-" * 70 + "\n"
    ]
    for sig in sigs:
        generated.append("\n" + argspec.emit_module(sig))
    generated.append("\n\nTOOLS = {\n" + "".join(
        f"    {sig.id!r}: {sig.func},\n" for sig in sigs
    ) + "}\n")
    return source + "".join(generated)


def stubs(con: sqlite3.Connection, skill: str | None = None, grep: str | None = None) -> list[str]:
    import re

    pattern = re.compile(grep, re.IGNORECASE) if grep else None
    rows = con.execute(
        "SELECT id, skill, kind, summary, contract FROM tools ORDER BY id"
    ).fetchall()
    lines = []
    for sig in argspec.signatures(rows):
        if skill and sig.skill != skill:
            continue
        if pattern and not (pattern.search(sig.id) or pattern.search(sig.summary)):
            continue
        lines.append(f"{sig.line()}\n    # {sig.summary[:100]}")
    return lines


def bindings_dir() -> Path:
    return Path.home() / ".local" / "share" / "omnicli" / "bindings"


def write(con: sqlite3.Connection, out_dir: Path | None = None) -> Path:
    out = Path(out_dir) if out_dir else bindings_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "omnicli_tools.py").write_text(module_source(con), encoding="utf-8")
    return out


def ensure(con: sqlite3.Connection, fingerprint: str, out_dir: Path | None = None) -> Path:
    """Write the module when its generated source differs from what is cached.

    Comparing the source rather than a fingerprint means a change to the
    generator invalidates the cache as reliably as a change to the catalog.
    Generation costs about 20 ms; a stale surface costs a wrong call.
    """
    out = Path(out_dir) if out_dir else bindings_dir()
    out.mkdir(parents=True, exist_ok=True)
    source = module_source(con)
    module = out / "omnicli_tools.py"
    if module.is_file() and module.read_text(encoding="utf-8") == source:
        return out
    module.write_text(source, encoding="utf-8")
    (out / ".fingerprint").write_text(f"{fingerprint}:{BINDINGS_VERSION}", encoding="utf-8")
    return out
