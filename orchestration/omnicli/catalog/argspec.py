"""Parse a tool's extracted `--help` into typed parameters.

The catalog stores each contract as the raw argparse help text plus a flat
flag list. That is enough to describe a tool to a reader, and not enough to
write a typed call against it. This module recovers the missing half —
metavars, choices, required-vs-optional, positionals — so the generated
bindings can emit one annotated Python function per tool instead of a generic
`invoke(id, ...)`.

Parsing is deliberately conservative: an option it cannot read becomes
`str | None`, never a guess that would make a correct call look wrong.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

OPTION_ENTRY = re.compile(
    r"^(?:-\w,\s+)?(--[A-Za-z0-9][A-Za-z0-9_-]*)(?:\s+(\S+))?(?:\s{2,}.*)?$"
)
OPTION_START = re.compile(r"^\s{2,}(?:-\w,\s+)?--")
OPTIONS_SECTION = re.compile(r"^(?:options|optional arguments):\s*$", re.MULTILINE)
METAVAR_CHOICES = re.compile(r"^\{([^}]*)\}$")
USAGE_CHOICES = re.compile(r"\{([^}]+)\}")
INT_HINTS = {"N", "COUNT", "NUM", "LIMIT", "PORT", "RETRIES", "JOBS", "WORKERS", "PAGES"}
FLOAT_HINTS = {"TIMEOUT", "THRESHOLD", "SECS", "SECONDS", "RATIO", "ALPHA", "TEMPERATURE", "SCORE"}

RESERVED_PARAMS = {"argv", "invoke"}
MODULE_API = {
    "search", "skills", "tools", "describe", "invoke", "output", "spec",
    "TOOLS", "SIGNATURES", "SPEC", "TOOL_IDS", "OMNICLI", "json", "os",
    "subprocess", "Literal", "Any", "open", "print",
}
KEYWORDS = {
    "False", "None", "True", "and", "as", "assert", "async", "await", "break",
    "class", "continue", "def", "del", "elif", "else", "except", "finally",
    "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
    "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
}


@dataclass
class Param:
    name: str
    flag: str = ""
    kind: str = "str"
    choices: list[str] = field(default_factory=list)
    required: bool = False
    positional: bool = False

    def annotation(self) -> str:
        if self.kind == "bool":
            return "bool"
        if self.kind == "choices":
            return f"Literal[{', '.join(repr(c) for c in self.choices)}]"
        return self.kind

    def declaration(self) -> str:
        if self.kind == "bool":
            return f"{self.name}: bool = False"
        if self.required:
            return f"{self.name}: {self.annotation()}"
        return f"{self.name}: {self.annotation()} | None = None"


@dataclass
class Signature:
    id: str
    skill: str
    kind: str
    summary: str
    func: str
    params: list[Param]
    positionals: list[Param]
    command: bool
    commands: list[str]
    usage: str

    def ordered_positionals(self) -> list[Param]:
        return sorted(self.positionals, key=lambda p: not p.required)

    def line(self) -> str:
        pos = [p.declaration() for p in self.ordered_positionals()]
        required = [p.declaration() for p in self.params if p.required]
        optional = [p.declaration() for p in self.params if not p.required]
        if self.command:
            optional.insert(0, "command: str | None = None")
        parts = pos + required + (["*"] + optional if optional else [])
        return f"{self.func}({', '.join(parts)}) -> dict"


def _help_text(contract: dict[str, Any]) -> str:
    return str(contract.get("help") or "")


def _options_block(help_text: str) -> list[str]:
    match = None
    for match in OPTIONS_SECTION.finditer(help_text):
        pass
    if match is None:
        return []
    block = help_text[match.end():]
    stop = re.search(r"\n(?!\s)\S", block)
    if stop:
        block = block[: stop.start()]
    return block.splitlines()


def _entries(lines: list[str]) -> list[str]:
    """Option headers only: everything before the first 2+ space gutter."""
    headers: list[str] = []
    for line in lines:
        if OPTION_START.match(line):
            headers.append(re.split(r"\s{2,}", line.strip(), maxsplit=1)[0].strip())
    return headers


def _parse_header(header: str) -> tuple[str, str]:
    """Return (long flag, metavar) from a header such as `--url, -u URL`."""
    tokens = [t.rstrip(",") for t in header.split()]
    long_flags = [t for t in tokens if t.startswith("--")]
    if not long_flags:
        return "", ""
    flag = long_flags[0]
    tail = tokens[tokens.index(flag) + 1:]
    metavar = ""
    for token in tail:
        if token.startswith("-"):
            continue
        metavar = token
        break
    return flag, metavar


def _required_flags(usage: str) -> set[str]:
    return {name for name, depth in _flag_depths(usage) if depth == 0}


def _flag_depths(usage: str) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    depth = 0
    index = 0
    while index < len(usage):
        ch = usage[index]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif usage.startswith("--", index):
            match = re.match(r"--[A-Za-z0-9][A-Za-z0-9_-]*", usage[index:])
            if match:
                found.append((match.group(0), depth))
                index += len(match.group(0))
                continue
        index += 1
    return found


def _kind_for(metavar: str) -> tuple[str, list[str]]:
    choices = METAVAR_CHOICES.match(metavar or "")
    if choices:
        return "choices", [c.strip() for c in choices.group(1).split(",") if c.strip()]
    word = (metavar or "").strip("<>[]").upper()
    if word in INT_HINTS:
        return "int", []
    if word in FLOAT_HINTS:
        return "float", []
    return "str", []


def _param_name(raw: str, taken: set[str] | None = None) -> str:
    name = re.sub(r"[^0-9a-zA-Z_]", "_", raw.lstrip("-")).strip("_").lower()
    if not name:
        name = "arg"
    if name[0].isdigit():
        name = f"f_{name}"
    if name in KEYWORDS or name in RESERVED_PARAMS:
        name = f"{name}_"
    taken = taken or set()
    if name in taken:
        base = name
        suffix = 2
        while name in taken:
            name = f"{base}_{suffix}"
            suffix += 1
    return name


def parse_flags(contract: dict[str, Any]) -> list[Param]:
    usage = str(contract.get("usage") or "").replace("\n", " ")
    required = _required_flags(usage)
    params: list[Param] = []
    seen: set[str] = set()

    for header in _entries(_options_block(_help_text(contract))):
        flag, metavar = _parse_header(header)
        if not flag or flag in ("--help", "--version"):
            continue
        kind, choices = ("bool", []) if not metavar else _kind_for(metavar)
        name = _param_name(flag, seen)
        seen.add(name)
        params.append(Param(name=name, flag=flag, kind=kind, choices=choices,
                            required=flag in required and kind != "bool"))

    known = {p.flag for p in params}
    for flag in contract.get("flags") or []:
        if not isinstance(flag, str) or flag.startswith("--") is False or flag in known:
            continue
        if flag in ("--help", "--version"):
            continue
        name = _param_name(flag, seen)
        seen.add(name)
        params.append(Param(name=name, flag=flag, kind="str", required=flag in required))

    return params


def _commands(contract: dict[str, Any], usage: str) -> tuple[bool, list[str]]:
    listed = [s for s in (contract.get("subcommands") or []) if s.get("name")]
    braces = USAGE_CHOICES.search(usage)
    if braces:
        names = [n.strip() for n in braces.group(1).split(",") if n.strip()]
        return True, names
    names = [str(s["name"]) for s in listed if not str(s["name"]).endswith("_pos")]
    return bool(names), names


def _positionals(contract: dict[str, Any], usage: str, taken: set[str]) -> list[Param]:
    has_commands, commands = _commands(contract, usage)
    params: list[Param] = []
    for entry in contract.get("subcommands") or []:
        name = str(entry.get("name") or "")
        if not name.endswith("_pos") or name in commands:
            continue
        pretty = name[:-4]
        param = _param_name(pretty)
        if param in taken:
            param = _param_name(name)
        if param in taken:
            param = _param_name(param, taken)
        taken.add(param)
        bracketed = re.search(rf"\[\s*<?{re.escape(name)}>?\s*\]", usage) is not None
        params.append(Param(name=param, kind="str", required=not bracketed, positional=True))
    return params


def _function_name(tool_id: str) -> str:
    leaf = tool_id.split("/")[-1].split(":")[-1]
    name = re.sub(r"[^0-9a-zA-Z_]", "_", leaf).strip("_").lower()
    if not name:
        name = "tool"
    if name in {"cli", "main", "run", "tool", "script", "app"} or name in MODULE_API:
        skill = tool_id.split("/")[0]
        name = f"{re.sub(r'[^0-9a-zA-Z_]', '_', skill).strip('_').lower()}_{name}"
    if name[0].isdigit():
        name = f"t_{name}"
    if name in KEYWORDS:
        name = f"{name}_tool"
    return name


def signatures(rows: list[Any]) -> list[Signature]:
    taken: dict[str, str] = {}
    out: list[Signature] = []

    for row in rows:
        tool_id = row["id"]
        contract = row["contract"]
        if isinstance(contract, str):
            contract = json.loads(contract or "{}")
        usage = str(contract.get("usage") or "").replace("\n", " ").strip()

        func = _function_name(tool_id)
        holder = taken.get(func)
        if holder and holder != tool_id:
            skill = re.sub(r"[^0-9a-zA-Z_]", "_", str(row["skill"])).strip("_").lower()
            func = f"{skill}_{func}"[:60]
            suffix = 2
            base = func
            while func in taken:
                func = f"{base}_{suffix}"
                suffix += 1
        taken[func] = tool_id

        has_commands, commands = _commands(contract, usage)
        flags = parse_flags(contract)
        positionals = _positionals(contract, usage, {p.name for p in flags})
        out.append(Signature(
            id=tool_id,
            skill=str(row["skill"]),
            kind=str(row["kind"]),
            summary=str(row["summary"] or "").strip(),
            func=func,
            params=flags,
            positionals=positionals,
            command=has_commands,
            commands=commands,
            usage=usage,
        ))
    return out


def _docstring(sig: Signature) -> str:
    lines = [sig.summary or sig.id]
    if sig.usage:
        lines.append("")
        lines.append(sig.usage[:180])
    if sig.commands:
        lines.append("")
        lines.append("commands: " + ", ".join(sig.commands[:24]))
        if len(sig.commands) > 24:
            lines.append(f"... and {len(sig.commands) - 24} more")
    return "\n".join(lines)


def emit_module(sig: Signature) -> str:
    """One annotated function whose body builds argv and calls invoke()."""
    positionals = [p.declaration() for p in sig.ordered_positionals()]
    required = [p.declaration() for p in sig.params if p.required]
    optional = [p.declaration() for p in sig.params if not p.required]
    if sig.command:
        optional.insert(0, "command: str | None = None")
    params = positionals + required + (["*"] + optional if optional else [])

    if len(", ".join(params)) <= 96:
        head = f"def {sig.func}({', '.join(params)}) -> dict:"
    else:
        body = "".join(f"    {p},\n" for p in params)
        head = f"def {sig.func}(\n{body}) -> dict:"

    doc = _docstring(sig).replace("\\", "\\\\").replace('"""', "'''")
    body_lines = [f'    """{doc}"""', "    argv: list[str] = []"]
    if sig.command:
        body_lines.append("    if command is not None:")
        body_lines.append("        argv.append(str(command))")
    for param in sig.ordered_positionals():
        if param.required:
            body_lines.append(f"    argv.append(str({param.name}))")
        else:
            body_lines.append(f"    if {param.name} is not None:")
            body_lines.append(f"        argv.append(str({param.name}))")
    for param in sig.params:
        if param.kind == "bool":
            body_lines.append(f"    if {param.name}:")
            body_lines.append(f"        argv.append({param.flag!r})")
        else:
            body_lines.append(f"    if {param.name} is not None:")
            body_lines.append(f"        argv += [{param.flag!r}, str({param.name})]")
    body_lines.append(f"    return invoke({sig.id!r}, *argv)")

    return f"{head}\n" + "\n".join(body_lines) + "\n"
