"""Skill and tool discovery for the omnicli catalog.

Two responsibilities:

1. **Skills** — find every skill directory on the workstation and parse its
   ``SKILL.md`` frontmatter (name, description).
2. **Tools** — find every *executable* surface belonging to a skill: python
   and shell scripts anywhere in the skill tree, the ``~/.local/bin`` shim,
   and the local inference endpoints. Each becomes a tool with a
   machine-readable contract extracted from ``--help``.

The contract extraction matters because it is what lets ``describe`` hand the
agent the input contract for exactly one tool, instead of a whole SKILL.md.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]

# Where skills live. First hit wins; mirrors of the same collection live in
# the later entries and must never be indexed twice.
CANDIDATE_SKILL_DIRS = [
    Path("/run/media/rodri/AI/skills"),
    REPO_ROOT / "surface",
    Path.home() / "my-agent-skills" / "surface",
    Path.home() / "my-agent-skills",
    Path.home() / ".gemini" / "config" / "skills",
    Path.home() / ".config" / "opencode" / "skills",
    Path.home() / ".pi" / "agent" / "skills",
    Path.cwd() / ".agents" / "skills",
]

SIDELINED_DIRS = {"glitch-cat", "archived", "docs", "launchers", ".git", "node_modules"}

SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".git", ".mypy_cache", ".pytest_cache"}
SKIP_FILE_RE = re.compile(r"(^test_.*|.*_test)\.py$", re.IGNORECASE)

# Vendored bundles (a skill that embeds another skill's modules) are library
# code, not a CLI surface. Indexing them would flood the tool registry with
# internal helpers.
SKIP_DIR_NAMES = {"modules", "tests"}

# Local inference endpoints exposed as first-class tools.
ENDPOINTS = {
    "local/llm": {
        "summary": "Query the local dual-GPU Qwen3.6-35B Genesis coder (:8080).",
        "argv": ["{python}", "{skill}/scripts/llm_client.py"],
    },
    "local/ocr": {
        "summary": "Local document/slide/image OCR via LightOnOCR-3-0.8B (:8085).",
        "argv": ["{python}", "{skill}/scripts/ocr.py"],
    },
    "local/decide": {
        "summary": "Calibrated decision primitives (bool/choice/score) via the decision model on :8083.",
        "argv": ["{python}", "{skill}/scripts/decide.py"],
    },
    "local/asr": {
        "summary": "Local speech-to-text transcription via audio.cpp Nemotron-3.5 ASR (:8081).",
        "argv": ["{python}", "{skill}/scripts/asr.py"],
    },
}

# The local inference endpoints have no directory of their own, but they are a
# legitimate routing target ("use the local llm to ..."). Registering them as
# a virtual skill gives them a description and aliases to match against.
VIRTUAL_SKILLS = {
    "local": {
        "name": "local",
        "dir_name": "local",
        "path": "",
        "md_path": None,
        "description": (
            "Local LLM and inference endpoints on this workstation: Genesis 35B "
            "coder for writing code (:8080), LightOnOCR document vision (:8085), "
            "calibrated decisions (:8083), Nemotron speech-to-text "
            "(:8081), and the optional embedding server (:8087) used to re-rank "
            "catalog search. Use for running a model locally, offline, or on device."
        ),
        "status": "active",
        "cli": None,
    },
}


# --------------------------------------------------------------------------
# skill discovery
# --------------------------------------------------------------------------

def resolve_skills_dir() -> Path:
    """Return the directory that holds the canonical skill collection."""
    for p in CANDIDATE_SKILL_DIRS:
        try:
            if not p.is_dir():
                continue
            for s in p.iterdir():
                if s.is_dir() and (s / "SKILL.md").is_file():
                    return p
        except OSError:
            continue
    if REPO_ROOT.is_dir():
        return REPO_ROOT
    return CANDIDATE_SKILL_DIRS[0]


_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL | re.MULTILINE)


def parse_frontmatter(content: str) -> tuple[str, str]:
    """Return (name, description) from a SKILL.md's YAML frontmatter.

    Deliberately not a YAML parser: the frontmatter in this collection uses
    folded scalars, quoted strings and nested maps, and a full YAML loader
    would be a dependency we do not want in the control plane. We only need
    two scalar fields, and the fallback is safe.
    """
    name = ""
    desc = ""
    m = _FRONT_RE.search(content)
    if not m:
        return name, desc
    fm = m.group(1)

    n = re.search(r"^name:\s*(\S+)\s*$", fm, re.MULTILINE)
    if n:
        name = n.group(1).strip().strip("\"'")

    # description may be a folded/literal block (>) or (|) or a quoted scalar
    d = re.search(
        r"^description:\s*(?:[>|][-+]?\s*\n((?:[ \t]+[^\n]*\n?)+))?([^\n]*)",
        fm,
        re.MULTILINE,
    )
    if d:
        if d.group(1):
            desc = " ".join(line.strip() for line in d.group(1).splitlines() if line.strip())
        else:
            desc = d.group(2).strip()
    desc = desc.strip().strip("\"'")
    if desc.endswith("..."):
        desc = desc[:-3].rstrip()
    return name, desc


_METADATA_BLOCK_RE = re.compile(r"^metadata:[ \t]*\n(?P<meta>(?:[ \t]+[^\n]*\n?)*)", re.MULTILINE)


def parse_doc_globs(content: str) -> list[str]:
    """Return the ``metadata.docs`` glob patterns declared by a SKILL.md.

    A skill that vendors a body of guidance — rubrics, playbooks, checklists —
    needs those files searchable, but a blanket "index every markdown file in
    the skill" dilutes the BM25 index for every other skill. So the skill
    declares what it wants indexed, and nothing is indexed that was not asked
    for.

    Deliberately not a YAML parser, in line with the rest of this module: the
    frontmatter here uses folded scalars and nested maps, and the control
    plane carries no dependencies. Both a block list and an inline list are
    accepted.
    """
    m = _METADATA_BLOCK_RE.search(content)
    if not m:
        return []
    meta = m.group("meta")

    d = re.search(r"^[ \t]+docs:[ \t]*(?P<inline>\[[^\]]*\])?[ \t]*(?P<scalar>[^\n]*)$", meta, re.MULTILINE)
    if not d:
        return []
    globs: list[str] = []

    inline = d.group("inline")
    if inline:
        globs.extend(g.strip().strip("\"'") for g in inline.strip("[]").split(",") if g.strip())
        return globs

    # A scalar value. The collection's frontmatter convention keeps every
    # metadata value a string, so the patterns are comma separated.
    scalar = (d.group("scalar") or "").strip().strip("\"'")
    if scalar:
        globs.extend(g.strip().strip("\"'") for g in scalar.split(",") if g.strip())
        return globs

    # A block list: the "- item" lines that follow the key, at its indent.
    tail = meta[d.end():]
    key_indent = len(re.match(r"[ \t]*", d.group(0)).group(0))
    for line in tail.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= key_indent:
            break
        item = re.match(r"^[ \t]*-[ \t]*(.+?)[ \t]*$", line)
        if item:
            value = item.group(1).strip().strip("\"'")
            if value:
                globs.append(value)
    return globs


def parse_bins(content: str) -> list[str]:
    """Return the extra command names declared by ``metadata.bins``.

    A skill whose command is not named after the skill (``model-layer`` ships
    ``llama-rig``) cannot be found by ``_resolve_shim`` today. The alias is
    a property of the skill, so it lives in the skill's frontmatter — inside
    the ``metadata`` map, which the collection already uses and the spec audit
    already allows, rather than as a new top-level key.

    Deliberately not a YAML parser, in line with the rest of this module. Both
    an inline list, a comma/space separated scalar and a block list are read.
    """
    m = _METADATA_BLOCK_RE.search(content)
    if not m:
        return []
    meta = m.group("meta")

    d = re.search(r"^[ \t]+bins:[ \t]*(?P<inline>\[[^\]]*\])?[ \t]*(?P<scalar>[^\n]*)$", meta, re.MULTILINE)
    if not d:
        return []

    names: list[str] = []

    def add(values) -> None:
        for value in values:
            name = value.strip().strip("\"'")
            if name and name not in names:
                names.append(name)

    inline = d.group("inline")
    if inline:
        add(inline.strip("[]").split(","))
        return names

    scalar = (d.group("scalar") or "").strip().strip("\"'")
    if scalar:
        add(re.split(r"[,\s]+", scalar))
        return names

    tail = meta[d.end():]
    key_indent = len(re.match(r"[ \t]*", d.group(0)).group(0))
    for line in tail.splitlines():
        if not line.strip():
            continue
        if len(line) - len(line.lstrip()) <= key_indent:
            break
        item = re.match(r"^[ \t]*-[ \t]*(.+?)[ \t]*$", line)
        if item:
            add([item.group(1)])
    return names


def _iter_skill_dirs(root: Path, include_sidelined: bool):
    if not root.is_dir():
        return
    seen: set[str] = set()
    for item in sorted(root.iterdir()):
        if not item.is_dir() or item.name.startswith(".") or item.name in SKIP_DIRS or item.name in {"surface"}:
            continue
        if (item / "SKILL.md").is_file():
            if item.name in SIDELINED_DIRS:
                if include_sidelined and item.name in ("glitch-cat", "archived"):
                    seen.add(item.name)
                    yield item, item.name
            else:
                seen.add(item.name)
                yield item, "active"
            continue
        if item.name not in {"docs", "launchers", "site-packages", ".venv", "tests"}:
            for sub in sorted(item.iterdir()):
                if sub.is_dir() and (sub / "SKILL.md").is_file() and sub.name not in seen:
                    seen.add(sub.name)
                    sub_status = item.name if item.name in ("glitch-cat", "archived") else "active"
                    if sub_status == "active" or include_sidelined:
                        yield sub, sub_status
    if include_sidelined:
        for sub in ("glitch-cat", "archived"):
            subdir = root / sub
            if not subdir.is_dir():
                continue
            for item in sorted(subdir.iterdir()):
                if item.is_dir() and (item / "SKILL.md").is_file() and item.name not in seen:
                    seen.add(item.name)
                    yield item, sub


def load_all_skills(include_sidelined: bool = False) -> dict[str, dict[str, Any]]:
    """Discover every skill and its metadata."""
    root = resolve_skills_dir()
    skills: dict[str, dict[str, Any]] = {}
    for item, status in _iter_skill_dirs(root, include_sidelined):
        md = item / "SKILL.md"
        try:
            content = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name, desc = parse_frontmatter(content)
        name = name or item.name
        shim = _resolve_shim(name, item.name, *parse_bins(content))
        skills[name] = {
            "name": name,
            "dir_name": item.name,
            "path": str(item),
            "md_path": str(md),
            "description": desc,
            "doc_globs": parse_doc_globs(content),
            "status": status,
            "cli": shim,
        }
    for name, spec in VIRTUAL_SKILLS.items():
        skills.setdefault(name, dict(spec))
    return skills


def _resolve_shim(*names: str, bindir: Path | None = None) -> str | None:
    """Find a ~/.local/bin shim for a skill, if one exists.

    ``names`` is the skill name, its directory name, and any
    ``metadata.bins`` aliases, in that order. ``bindir`` exists so the
    resolver can be tested against a fixture instead of this machine.
    """
    bindir = bindir or (Path.home() / ".local" / "bin")
    for n in names:
        if not n:
            continue
        cand = bindir / n
        try:
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
        except OSError:
            continue
    return None


# --------------------------------------------------------------------------
# contract extraction
# --------------------------------------------------------------------------

def _docstring_summary(path: Path) -> str:
    """First meaningful line of a python module docstring."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        doc = ast.get_docstring(tree) or ""
    except (OSError, SyntaxError, ValueError):
        return ""
    for line in doc.splitlines():
        line = line.strip()
        if line and not line.startswith(("-", "=")):
            return line
    return ""


_SUBCMD_BLOCK_RE = re.compile(
    r"positional arguments:\n(?P<body>(?:[ \t]+[^\n]*\n)+)", re.MULTILINE
)
# A subcommand entry in the "positional arguments" block. argparse puts
# the summary on the same line when the subparser was given help= (the
# usual case) and on the following line when it was not, so both are
# accepted here. The indent is 2 spaces for a top-level subparser list
# and 4 for a list nested under a <command> placeholder.
_SUBCMD_NAME_RE = re.compile(
    r"^\s{2,6}([a-z][a-z0-9_-]*)(?:\s+\(([^)]*)\))?(?:\s{2,}(.+?))?\s*$",
    re.MULTILINE,
)


def _usage_subcommands(usage: str) -> list[str]:
    """Subcommand names from the usage line's bare ``{a,b,c}`` group.

    argparse prints every subcommand in the usage group, but only the ones it
    has a description for in the "positional arguments" section. Reading only
    the latter would miss most commands, so both sources are used and
    unioned by the caller.

    Choice *values* (``[--format {md,vtt,txt,all}]``) are excluded: they are
    always enclosed in brackets, and a bare ``{...}`` group is a subcommand
    list.
    """
    text = re.sub(r"\[[^\]]*\]", " ", usage)
    m = re.search(r"\{([a-z0-9_, -]+)\}", text, re.IGNORECASE)
    if not m:
        return []
    return [t.strip() for t in m.group(1).split(",") if t.strip()]


# Bumped whenever the *parser* changes, not the scripts. The contract cache
# is keyed on the script's mtime, so a parser fix would otherwise keep
# serving the contracts the old parser produced.
CONTRACT_PARSER_VERSION = 7


def parse_help_contract(help_text: str) -> dict[str, Any]:
    """Turn argparse ``--help`` output into a structured contract.

    argparse's own help output *is* the contract, and models read it well.
    We parse it anyway so the registry can expose subcommands as individually
    addressable tools (``audiocpp/scripts/audiocpp_cli:asr``) and so that
    ``describe`` can summarise a tool without echoing 200 lines.
    """
    if not help_text.strip():
        return {"usage": "", "flags": [], "positionals": [], "subcommands": [], "help": ""}

    usage = ""
    usage_lines: list[str] = []
    in_usage = False
    for line in help_text.splitlines():
        # The usage line is matched case-insensitively: argparse prints
        # "usage:" but hand-written help often prints "Usage:". A missing
        # usage line meant the contract fell back to the parent's, so a
        # subcommand's own flags were thrown away and its contract claimed
        # to describe a program that had never printed it.
        if line.lower().startswith("usage:"):
            in_usage = True
            usage = line.strip()
            usage_lines.append(line)
            continue
        if in_usage:
            if line.startswith(" ") and line.strip():
                usage_lines.append(line)
            else:
                in_usage = False

    flags: list[str] = []
    for m in re.finditer(r"(?<![\w-])--[a-zA-Z][\w-]*", help_text):
        if m.group(0) not in flags:
            flags.append(m.group(0))

    positionals: list[str] = []
    usage_text = " ".join(part.strip() for part in usage_lines) if usage_lines else usage
    for m in re.finditer(r"(?<![\w-])([a-z][\w-]*)\s*(?:STATE|QUESTION|\.\.\.|$)", usage_text):
        tok = m.group(1)
        if tok not in positionals and not tok.startswith("-"):
            positionals.append(tok)

    # Detailed entries from the "positional arguments" section, with summaries.
    detailed: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    block = _SUBCMD_BLOCK_RE.search(help_text)
    if block:
        lines = block.group("body").splitlines()
        for i, line in enumerate(lines):
            m = _SUBCMD_NAME_RE.match(line)
            if not m:
                continue
            name = m.group(1)
            aliases = [a.strip() for a in (m.group(2) or "").split(",") if a.strip()]
            summary = (m.group(3) or "").strip()
            if not summary:
                for nxt in lines[i + 1:]:
                    if not nxt.strip():
                        continue
                    if nxt.startswith(" " * 8) and not _SUBCMD_NAME_RE.match(nxt):
                        summary = nxt.strip()
                    break
            # A plain positional argument is listed in this block too, and
            # it never carries a summary. Requiring one keeps a positional
            # from being mistaken for a subcommand.
            if not summary and name not in _usage_subcommands(" ".join(usage_lines)):
                continue
            if name not in detailed:
                order.append(name)
            detailed[name] = {"name": name, "aliases": aliases, "summary": summary}

    # Union with the usage-line group, which lists every subcommand.
    subcommands: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in order:
        seen.add(name)
        subcommands.append(detailed[name])
    for name in _usage_subcommands(" ".join(usage_lines)):
        if name in seen:
            continue
        seen.add(name)
        subcommands.append({"name": name, "aliases": [], "summary": ""})

    return {
        # `usage` stays the first line: it is what the search index embeds, and
        # widening it shifted the golden routing eval from 59/61 to 57/61.
        # `usage_full` carries the wrapped continuation lines for argument
        # parsing, where the truncated line loses every positional.
        "usage": usage,
        "usage_full": " ".join(part.strip() for part in usage_lines) if usage_lines else usage,
        "flags": flags,
        "positionals": positionals,
        "subcommands": subcommands,
        "help": help_text.strip(),
    }


def _mentions_help(path: Path) -> bool:
    """True when the script looks like it handles ``--help`` itself.

    Running ``--help`` is not free of side effects: a script that ignores the
    flag goes ahead and does its real job. ``decide.sh --help`` would query a
    model. So the source is inspected first, and only scripts that mention
    "help" are executed during indexing.
    """
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if len(src) > 400_000:
        return False
    low = src.lower()
    if path.suffix == ".py":
        # argparse generates --help internally, so the literal string
        # "help" need not appear in the source.
        if ("help" in low or "argparse" in low
                or "argumentparser" in low or "getopt" in low):
            return True
        # A thin wrapper delegates to a sibling module's main(). It has no
        # mention of help, but the CLI it forwards to handles the flag.
        return len(src) < 4096 and "__main__" in src
    # A shell script has no such machinery, so demand an explicit handler.
    return ("--help" in low or "usage()" in low or "help)" in low)


# A path to a Python file, quoted or not. Quotes are excluded from the
# character class so a quoted path is captured without them.
_PY_DELEGATE_RE = re.compile(r"([^\s'\"`|;&]+\.py)")


def shell_delegate(path: Path) -> Path | None:
    """The Python script a shell wrapper forwards to, if there is exactly one.

    A wrapper like ``exec "$VENV/bin/python" "$SCRIPT" "$@"`` never mentions
    ``--help``, so the guard below refuses to run it — correct, because
    running an unknown shell script is not free of side effects.

    But the wrapper's contract *is* the contract of the script it wraps,
    and that script can be inspected and run safely on its own. The
    wrapper is therefore never executed: its source is read, the delegate
    is found, and the delegate is what gets the --help.
    """
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if len(src) > 100_000:
        return None
    candidates: list[Path] = []
    for m in _PY_DELEGATE_RE.finditer(src):
        raw = m.group(1)
        cand = Path(raw)
        if not cand.is_absolute():
            cand = path.parent / cand.name
        try:
            if cand.is_file():
                resolved = cand.resolve()
                if resolved not in candidates:
                    candidates.append(resolved)
        except OSError:
            continue
    return candidates[0] if len(candidates) == 1 else None


def extract_contract(path: Path, timeout: float = 12.0,
                     python: str | None = None,
                     args: list[str] | None = None) -> dict[str, Any]:
    """Run ``--help`` on a script and parse the resulting contract.

    ``args`` runs the script with extra positional arguments before
    ``--help`` — that is how a *subcommand's* own contract is obtained.
    A subcommand is a different parser with a different flag set, and
    inheriting the parent's flags gives an agent a contract that omits the
    flags the subcommand actually takes.

    Two safety rules, both learned the hard way:

    * Only scripts that mention "help" are executed. A script that ignores
      the flag would otherwise perform its real task during indexing.
    * Output without a "usage:" line is rejected. A shell script that ran a
      model instead of printing usage would otherwise have its model output
      stored as if it were a contract.
    """
    empty: dict[str, Any] = {
        "usage": "", "flags": [], "positionals": [], "subcommands": [], "help": "",
    }
    if not _mentions_help(path):
        if path.suffix == ".py":
            empty["summary"] = _docstring_summary(path)
            return empty
        # A shell wrapper that forwards to exactly one Python script: take
        # the contract of that script rather than running the wrapper.
        delegate = shell_delegate(path)
        if delegate is not None:
            sub = extract_contract(delegate, timeout=timeout, python=python)
            if sub.get("usage"):
                sub = dict(sub)
                sub["summary"] = _docstring_summary(delegate) if not sub.get("summary") else sub["summary"]
                return sub
        return empty

    interp = python or sys.executable
    try:
        if path.suffix == ".py":
            cmd = [interp, str(path)] + list(args or []) + ["--help"]
        else:
            cmd = [str(path)] + list(args or []) + ["--help"]
        # Run in a scratch directory. A script whose first positional is a
        # workspace will treat "--help" as one and create it; inheriting the
        # caller's cwd drops that directory into whatever repo omnicli was
        # invoked from.
        with tempfile.TemporaryDirectory(prefix="omnicli-contract-") as scratch:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL, cwd=scratch,
            )
        out = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        out = ""
    except OSError:
        out = ""

    if "usage:" not in out.lower():
        # Not a usage message. Keep the docstring as a summary but do not
        # pretend the output is a contract.
        summary = _docstring_summary(path) if path.suffix == ".py" else ""
        return {"usage": "", "flags": [], "positionals": [], "subcommands": [],
                "help": "", "summary": summary}

    contract = parse_help_contract(out)
    if path.suffix == ".py" and not contract.get("summary"):
        contract["summary"] = _docstring_summary(path)
    return contract


# --------------------------------------------------------------------------
# tool discovery
# --------------------------------------------------------------------------

def _iter_scripts(skill_dir: Path):
    """Yield every candidate script in a skill tree, recursively.

    Recursive on purpose: ``ocr/ocr.py`` lives at the skill root, not under
    ``scripts/``. A flat ``scripts/`` scan would miss it entirely.
    """
    for root, dirs, files in os.walk(skill_dir):
        dirs[:] = [d for d in dirs
                   if d not in SKIP_DIRS and d not in SKIP_DIR_NAMES
                   and not d.startswith(".")]
        for fname in sorted(files):
            if SKIP_FILE_RE.match(fname):
                continue
            if fname.endswith((".py", ".sh")):
                yield Path(root) / fname


def _is_cli_entry(path: Path) -> bool:
    """True when a script is a command-line surface rather than a library module.

    A skill directory also contains importable modules — the catalog's own
    builder, a vendored library, a helper. Those are not things an agent can
    meaningfully invoke, and registering them as tools floods the registry.

    Two signals, either is enough: a ``__main__`` guard, or the executable
    bit.
    """
    try:
        if os.access(path, os.X_OK) and path.suffix == ".sh":
            return True
    except OSError:
        pass
    if path.suffix == ".py":
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        if '__name__ == "__main__"' in src or "__name__ == '__main__'" in src:
            return True
        try:
            return os.access(path, os.X_OK)
        except OSError:
            return False
    try:
        return os.access(path, os.X_OK)
    except OSError:
        return False


def discover_tools(skill: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the tool records for one skill."""
    tools: list[dict[str, Any]] = []
    raw_path = skill.get("path")
    if not raw_path:
        # Virtual skills (the local inference endpoints) have no directory.
        # Walking an empty path would scan the *current working directory*,
        # which would silently register whatever happens to be there.
        return tools
    skill_dir = Path(raw_path)

    for script in _iter_scripts(skill_dir):
        if not _is_cli_entry(script):
            continue
        try:
            rel = script.relative_to(skill_dir)
        except ValueError:
            continue
        tool_id = f"{skill['name']}/{rel.with_suffix('').as_posix()}"
        summary = _docstring_summary(script) if script.suffix == ".py" else ""
        tools.append({
            "id": tool_id,
            "skill": skill["name"],
            "kind": "script",
            "summary": summary,
            "path": str(script),
            "argv": [sys.executable, str(script)] if script.suffix == ".py" else [str(script)],
            "contract": {},
            "parent": None,
        })

    shim = skill.get("cli")
    if shim:
        tools.append({
            "id": f"{skill['name']}/cli",
            "skill": skill["name"],
            "kind": "cli",
            "summary": skill.get("description", ""),
            "path": shim,
            "argv": [shim],
            "contract": {},
            "parent": None,
        })

    return tools


def endpoint_tools(skill_dir: Path | None = None) -> list[dict[str, Any]]:
    """The local inference endpoints, as first-class tools.

    Their contract is extracted from the script that backs them, exactly as a
    script tool's is. An endpoint with an empty contract tells the agent
    nothing about how to call it, which is the one thing a contract is for.
    """
    out = []
    for eid, meta in ENDPOINTS.items():
        argv = meta["argv"]
        contract: dict[str, Any] = {}
        if skill_dir is not None:
            backing = _endpoint_script(argv, skill_dir)
            if backing is not None:
                try:
                    contract = extract_contract(backing) or {}
                except Exception:
                    contract = {}
        out.append({
            "id": eid,
            "skill": "local",
            "kind": "endpoint",
            "summary": meta["summary"],
            "path": None,
            "argv": argv,
            "contract": contract,
            "parent": None,
        })
    return out


def _endpoint_script(argv: list[str], skill_dir: Path) -> Path | None:
    """Resolve an endpoint's argv template to the script that backs it."""
    for token in argv:
        if not token.endswith(".py"):
            continue
        candidate = token.replace("{skill}", str(skill_dir))
        path = Path(candidate)
        if path.is_file():
            return path
    return None
