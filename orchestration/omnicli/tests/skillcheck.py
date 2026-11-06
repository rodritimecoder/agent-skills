#!/usr/bin/env python3
"""skillcheck.py — the collection's two correctness checks.

Both checks answer the same question from opposite ends: *does the
documentation of a tool match what the tool actually does?* The catalog's
contract is extracted from the code, so it is the reference. These checks
hold everything written by hand against it.

    python3 tests/skillcheck.py contracts   # catalog contract vs the real --help
    python3 tests/skillcheck.py drift       # every SKILL.md vs the catalog
    python3 tests/skillcheck.py all         # both

``contracts`` asks whether the catalog itself is telling the truth.
``drift`` asks whether each skill's SKILL.md agrees with the catalog.

Exit code is 0 when the check passes, 1 when it does not.

Stdlib only.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# --------------------------------------------------------------------------
# catalog


def catalog_path() -> Path:
    root = os.environ.get("OMNICLI_ROOT", "/run/media/rodri/AI/workstation-clis/omnicli")
    p = Path(root) / "catalog" / "catalog.db"
    if p.is_file():
        return p
    xdg = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(xdg) / "omnicli" / "catalog.db"


class Catalog:
    """A read-only view of the omnicli catalog."""

    def __init__(self) -> None:
        self.ok = False
        self.by_path: dict[str, dict] = {}
        self.by_id: dict[str, dict] = {}
        self.by_skill: dict[str, list[dict]] = {}
        self.skill_dirs: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        path = catalog_path()
        if not path.is_file():
            return
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.Error:
            return
        try:
            for tid, skill, kind, tpath, contract in con.execute(
                "select id, skill, kind, path, contract from tools"
            ):
                flags: list[str] = []
                subcommands: list[str] = []
                usage = ""
                if contract:
                    try:
                        data = json.loads(contract)
                        flags = [f.lstrip("-") for f in (data.get("flags") or [])]
                        for sc in data.get("subcommands") or []:
                            if isinstance(sc, dict) and sc.get("name"):
                                subcommands.append(sc["name"])
                        usage = str(data.get("usage") or "")
                    except (ValueError, AttributeError):
                        flags = []
                tool = {
                    "id": tid, "skill": skill, "kind": kind, "path": tpath,
                    "flags": flags, "subcommands": subcommands, "usage": usage,
                    # argparse prints a REMAINDER positional as "..." in the
                    # usage line. Everything after it belongs to another
                    # program.
                    "remainder": "..." in usage,
                }
                self.by_id[tid] = tool
                if tpath:
                    key = os.path.normpath(tpath)
                    prev = self.by_path.get(key)
                    if prev is None or (":" in prev["id"] and ":" not in tid):
                        self.by_path[key] = tool
                self.by_skill.setdefault(skill, []).append(tool)
            for name, spath in con.execute("select name, path from skills"):
                if spath:
                    self.skill_dirs[name] = spath
        except sqlite3.Error:
            return
        finally:
            con.close()
        self.ok = True

    def tool_for_path(self, path: str) -> dict | None:
        return self.by_path.get(os.path.normpath(path))

    def tool_for_name(self, name: str) -> dict | None:
        stem = name[:-3] if name.endswith(".py") else name
        for tool in self.by_id.values():
            base = tool["id"].split("/")[-1]
            if base == stem or base.split(":")[0] == stem:
                return tool
        return None

    def skill_flags(self, skill: str) -> set[str]:
        out: set[str] = set()
        for tool in self.by_skill.get(skill, []):
            out.update(tool["flags"])
        return out


# --------------------------------------------------------------------------
# check 1: does the catalog tell the truth?

FLAG_RE = re.compile(r"(--[a-zA-Z][a-zA-Z0-9-]*)")


def _real_flags(argv: list[str], timeout: float = 25.0) -> set[str] | None:
    try:
        p = subprocess.run(argv + ["--help"], capture_output=True,
                           text=True, timeout=timeout)
    except Exception:
        return None
    out = (p.stdout or "") + (p.stderr or "")
    if len(out.strip()) < 20:
        return None
    return {f.lstrip("-") for f in FLAG_RE.findall(out)}


def check_contracts(catalog: Catalog) -> list[dict]:
    """Every tool's catalog contract vs the tool's own --help.

    Two kinds of finding, and they are not the same severity.

    A *mismatch* is a contract that claims some flags and omits others the
    tool accepts. That is a contract that is actively misleading: it looks
    complete and is not.

    An *undescribed* tool has no contract at all. The extractor declines to
    run a script it cannot prove is safe, so a hand-rolled shell CLI has
    no parsed contract. That is a gap, but it is not a wrong answer — the
    empty contract says nothing false.
    """
    findings: list[dict] = []
    for tool in catalog.by_id.values():
        if not tool["path"]:
            continue
        argv = ([sys.executable, tool["path"]] if tool["path"].endswith(".py")
                else [tool["path"]])
        actual = _real_flags(argv)
        if actual is None:
            continue
        actual = {f for f in actual if f != "help"}
        claimed = {f for f in tool["flags"] if f != "help"}
        if not tool["usage"]:
            # No usage line means the extractor never described the tool.
            # A tool whose only flag is --help *is* described; it simply
            # takes no options.
            findings.append({
                "tool": tool["id"],
                "severity": "warning",
                "detail": "no contract extracted — it has no --help interface, "
                          "or the extractor declined to run it",
            })
            continue

        missing = sorted(actual - claimed)
        if missing:
            findings.append({
                "tool": tool["id"],
                "severity": "error",
                "detail": "contract omits " + ", ".join("--" + m for m in missing),
            })
    return findings


# --------------------------------------------------------------------------
# check 2: does each SKILL.md agree with the catalog?

PYTHON_BINARIES = ("python3", "python", "python3.14", "python3.12")
BINDING_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+?)\s*$", re.MULTILINE)
FENCE_RE = re.compile(r"^```([^\n]*)\n(.*?)^```", re.MULTILINE | re.DOTALL)
FLAG_MENTION_RE = re.compile(r"(?<![\w-])--([a-zA-Z][a-zA-Z0-9-]*)")
FLAG_TABLE_RE = re.compile(r"^\s*\|\s*`?--([a-zA-Z][a-zA-Z0-9-]*)`?", re.MULTILINE)


def parse_bindings(content: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in BINDING_RE.finditer(content):
        parts = m.group(2).strip().strip("\"'").split()
        if not parts:
            continue
        if parts[0] in PYTHON_BINARIES and len(parts) > 1:
            out[m.group(1)] = parts[1]
        else:
            out[m.group(1)] = parts[0]
    return out


def expand(arg: str, bindings: dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        return bindings.get(m.group(1) or m.group(2), m.group(0))
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", repl, arg)


def extract_flags(args: list[str], remainder: bool = False) -> list[str]:
    out: list[str] = []
    seen_positional = False
    for a in args:
        if a == "--":
            break
        m = re.match(r"^--([a-zA-Z][a-zA-Z0-9-]*)(?:=.*)?$", a)
        if m:
            if seen_positional:
                break
            out.append(m.group(1))
            continue
        if a.startswith("-"):
            continue
        seen_positional = True
        if remainder:
            break
    return out


def flag_accepted(flag: str, contract_flags: list[str]) -> bool:
    """Exactly, or as an unambiguous prefix — argparse accepts abbreviations."""
    if flag in contract_flags:
        return True
    hits = [f for f in contract_flags if f.startswith(flag)]
    return len(hits) == 1


def resolve_target(args: list[str], skill_dir: Path, catalog: Catalog):
    """The catalog tool a command invokes, and the flags it passes."""
    if not args:
        return None, []
    tok, rest = args[0], args[1:]

    if tok == "omnicli" and rest and rest[0] == "invoke":
        if len(rest) < 2:
            return None, []
        tool = catalog.by_id.get(rest[1])
        if not tool:
            return None, []
        tail = rest[2:]
        if "--" in tail:
            tail = tail[tail.index("--") + 1:]
        return tool, extract_flags(tail, tool.get("remainder"))

    if tok in PYTHON_BINARIES and rest:
        script = rest[0]
        path = script if os.path.isabs(script) else str(skill_dir / script)
        tool = catalog.tool_for_path(path)
        if not tool:
            return None, []
        tail = rest[1:]
        if tail and ":" not in tool["id"]:
            sub = f"{tool['id']}:{tail[0]}"
            if sub in catalog.by_id:
                tool, tail = catalog.by_id[sub], tail[1:]
        return tool, extract_flags(tail, tool.get("remainder"))

    if tok.endswith(".py") or "/" in tok:
        path = tok if os.path.isabs(tok) else str(skill_dir / tok)
        tool = catalog.tool_for_path(path)
        if not tool:
            return None, []
        tail = rest
        if tail and ":" not in tool["id"]:
            sub = f"{tool['id']}:{tail[0]}"
            if sub in catalog.by_id:
                tool, tail = catalog.by_id[sub], tail[1:]
        return tool, extract_flags(tail, tool.get("remainder"))

    tool = catalog.tool_for_name(tok)
    if not tool:
        return None, []
    tail = rest
    if tail and ":" not in tool["id"]:
        sub = f"{tool['id']}:{tail[0]}"
        if sub in catalog.by_id:
            tool, tail = catalog.by_id[sub], tail[1:]
    return tool, extract_flags(tail, tool.get("remainder"))


def commands_of(skill_md: Path) -> list[dict]:
    """The commands a SKILL.md shows, with the flags each passes."""
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
    skill_dir = skill_md.parent
    out: list[dict] = []
    bindings: dict[str, str] = {}
    for m in FENCE_RE.finditer(body):
        lang, content = m.group(1), m.group(2)
        if lang.strip() and lang.strip() not in ("bash", "sh", "shell", "console"):
            continue
        bindings.update(parse_bindings(content))
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or BINDING_RE.match(line):
                continue
            if line.startswith("export "):
                continue
            if "|" in line:
                line = line.split("|")[0].strip()
            if not line or not line[0].isalnum() and line[0] not in "_$.\"'/":
                continue
            try:
                args = [expand(a, bindings) for a in __import__("shlex").split(line)]
            except ValueError:
                args = line.split()
            out.append({"args": args, "raw": line})
    return out


def reference_flags(skill_dir: Path) -> set[str]:
    """Every --flag mentioned anywhere in the skill's references/."""
    out: set[str] = set()
    refdir = skill_dir / "references"
    if not refdir.is_dir():
        return out
    for p in sorted(refdir.rglob("*.md")):
        try:
            out |= set(FLAG_MENTION_RE.findall(p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


def reference_tables(skill_dir: Path) -> set[str]:
    """Every --flag presented in a markdown table inside references/."""
    out: set[str] = set()
    refdir = skill_dir / "references"
    if not refdir.is_dir():
        return out
    for p in sorted(refdir.rglob("*.md")):
        try:
            out |= set(FLAG_TABLE_RE.findall(p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


def check_drift(catalog: Catalog) -> list[dict]:
    """Every skill's SKILL.md against the catalog."""
    findings: list[dict] = []
    for skill, sdir in sorted(catalog.skill_dirs.items()):
        skill_md = Path(sdir) / "SKILL.md"
        if not skill_md.is_file():
            continue
        skill_dir = skill_md.parent
        documented = reference_flags(skill_dir)
        tables = reference_tables(skill_dir)
        skill_flags = catalog.skill_flags(skill)
        for cmd in commands_of(skill_md):
            tool, used = resolve_target(cmd["args"], skill_dir, catalog)
            if tool is None or not tool["flags"]:
                continue
            for flag in used:
                if flag == "help":
                    continue
                if not flag_accepted(flag, tool["flags"]):
                    findings.append({
                        "skill": skill, "severity": "error", "rule": "flag-drift",
                        "detail": f"--{flag} is not a flag of {tool['id']} "
                                  f"({cmd['raw'][:60]})",
                    })
                if tool["skill"] != skill or not documented:
                    continue
                if flag not in documented:
                    findings.append({
                        "skill": skill, "severity": "warning", "rule": "undocumented-flag",
                        "detail": f"--{flag} is used on {tool['id']} but no references/ "
                                  f"file in {skill} documents it",
                    })
        for flag in sorted(tables - skill_flags):
            findings.append({
                "skill": skill, "severity": "warning", "rule": "stale-flag-doc",
                "detail": f"a references/ table documents --{flag}, which no tool "
                          f"of {skill} accepts",
            })
    return findings


# --------------------------------------------------------------------------


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    catalog = Catalog()
    if not catalog.ok:
        print(f"❌ no catalog at {catalog_path()} — run `omnicli index --rebuild` first")
        return 1

    failed = False
    if mode in ("contracts", "all"):
        findings = check_contracts(catalog)
        errors = [f for f in findings if f["severity"] == "error"]
        warnings = [f for f in findings if f["severity"] == "warning"]
        print(f"\nCONTRACTS   {len(errors)} mismatch(es), {len(warnings)} undescribed")
        for f in errors:
            print(f"  ❌ {f['tool']:<48} {f['detail']}")
        for f in warnings:
            print(f"  ⚠️  {f['tool']:<48} {f['detail']}")
        failed |= bool(errors)

    if mode in ("drift", "all"):
        findings = check_drift(catalog)
        errors = [f for f in findings if f["severity"] == "error"]
        warnings = [f for f in findings if f["severity"] == "warning"]
        print(f"\nDRIFT       {len(errors)} error(s), {len(warnings)} warning(s)")
        for f in errors + warnings:
            mark = "❌" if f["severity"] == "error" else "⚠️ "
            print(f"  {mark} {f['skill']:<20} {f['rule']:<19} {f['detail']}")
        failed |= bool(errors)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
