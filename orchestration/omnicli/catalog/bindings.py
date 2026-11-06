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
import shutil
import sqlite3
from pathlib import Path

from . import argspec

BINDINGS_VERSION = "2"

MODULE_HEAD = '''"""omnicli bindings — generated file, do not edit.

One plan, one turn. `search()` picks a tool by intent, `spec()` queries the
whole catalog without loading it, and every tool also exists as an annotated
function (`zoom_recording(url=...)`). Intermediate values stay in Python
variables; only what you print comes back to the model.

Every call goes through the `omnicli` CLI, so the enable gate, projection,
byte cap and buffer behave exactly as they do from the shell.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Literal

OMNICLI = os.environ.get("OMNICLI_BIN", "omnicli")
TOOL_IDS = __TOOL_IDS__
SPEC: list[dict[str, Any]] = json.loads(__SPEC__)
SIGNATURES: dict[str, str] = {row["id"]: row["sig"] for row in SPEC}


def _log(event):
    path = os.environ.get("OMNICLI_TRACE")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\\n")


def _run(argv):
    _log({"call": argv[1] if len(argv) > 1 else "", "tool": argv[2] if len(argv) > 2 else ""})
    return subprocess.run(argv, capture_output=True, text=True)


def search(intent, limit=6):
    """Route by intent. Returns compact rows: skill, score, matched, why."""
    proc = _run([OMNICLI, "search", intent, "--json", "--limit", str(limit)])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "search failed")
    return json.loads(proc.stdout).get("results", [])


def skills():
    """Every skill the catalog knows about."""
    proc = _run([OMNICLI, "list", "--json"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "list failed")
    return json.loads(proc.stdout)


def tools(skill):
    """The executable tools inside one skill."""
    proc = _run([OMNICLI, "tools", skill, "--json"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "tools failed")
    return json.loads(proc.stdout)


def describe(tool_id):
    """One tool's exact contract (usage, flags, state)."""
    proc = _run([OMNICLI, "describe", tool_id, "--json"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "describe failed")
    return json.loads(proc.stdout)


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
    argv = [OMNICLI, "invoke", tool_id, *[str(a) for a in args], "--omni-json"]
    if project:
        argv += ["--omni-project", project]
    if grep:
        argv += ["--omni-grep", grep]
    if max_bytes is not None:
        argv += ["--omni-max-bytes", str(max_bytes)]
    argv += ["--omni-timeout", str(timeout)]
    proc = _run(argv)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(proc.stderr.strip() or f"{tool_id} failed")
    return json.loads(proc.stdout)


def output(tool_id, *args, **kwargs):
    """invoke() and return only the shaped stdout, not the envelope."""
    return invoke(tool_id, *args, **kwargs).get("output", "")

'''


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
