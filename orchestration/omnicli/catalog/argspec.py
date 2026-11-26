"""Parse a tool's contract into typed parameters and TypeScript declarations.

The catalog stores each contract as a JSON Schema (`inputSchema`) when the tool
is argparse-based, plus the raw help text as a fallback. That is enough to
describe a tool to a reader, and not enough to write a typed call against it.
This module recovers the callable surface — types, choices, required-vs-
optional, positionals — so the generated bindings can emit one typed function
per tool instead of a generic `invoke(id, ...)`.

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
OPTIONS_SECTION = re.compile(
    r"^[A-Za-z0-9][^\n:]*:\s*$", re.MULTILINE
)
METAVAR_CHOICES = re.compile(r"^\{([^}]*)\}$")
USAGE_CHOICES = re.compile(r"\{([^}]+)\}")
INT_HINTS = {"N", "COUNT", "NUM", "LIMIT", "PORT", "RETRIES", "JOBS", "WORKERS", "PAGES"}
FLOAT_HINTS = {"TIMEOUT", "THRESHOLD", "SECS", "SECONDS", "RATIO", "ALPHA", "TEMPERATURE", "SCORE"}

RESERVED_PARAMS = {"argv", "invoke"}
MODULE_API = {
    "search", "skills", "tools", "describe", "invoke", "output", "spec",
    "parallel", "emitResult", "emit_result", "traceIdentity", "userTracePath",
    "TOOLS", "SIGNATURES", "SPEC", "TOOL_IDS", "OMNICLI", "json", "os",
    "subprocess", "Literal", "Any", "open", "print",
    # The plan globals added after the first surface. `_function_name` lowercases
    # before this check, so the lowercase spelling is the one that has to exist.
    "models", "text", "store", "load", "exit", "result", "planresult", "getstate",
    "emitstate", "emitresult", "traceidentity", "usertracepath", "rowfor",
}
# A generated function name has to be a legal identifier in both languages: a
# tool called `delete` produced `export async function delete(...)`, which node
# refuses to parse. Python's keywords and JavaScript's reserved words are one
# set here because the same name feeds both surfaces.
_PY_KEYWORDS = {
    "False", "None", "True", "and", "as", "assert", "async", "await", "break",
    "class", "continue", "def", "del", "elif", "else", "except", "finally",
    "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
    "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
}
_JS_KEYWORDS = {
    "arguments", "case", "catch", "const", "debugger", "default", "delete",
    "do", "enum", "eval", "export", "extends", "false", "function",
    "implements", "instanceof", "interface", "let", "new", "null", "package",
    "private", "protected", "public", "static", "super", "switch", "this",
    "throw", "true", "typeof", "var", "void",
}
# TypeScript's contextual keywords only break a declaration in some positions,
# but a prefixed name costs nothing and is always safe.
_TS_RESERVED = {
    "abstract", "any", "boolean", "declare", "infer", "keyof", "module",
    "namespace", "never", "number", "object", "readonly", "string", "symbol",
    "type", "undefined", "unknown",
}
KEYWORDS = _PY_KEYWORDS | _JS_KEYWORDS | _TS_RESERVED

JS_IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")

SCHEMA_KINDS = {"integer": "int", "number": "float", "boolean": "bool", "array": "list"}


@dataclass
class Param:
    name: str
    flag: str = ""
    kind: str = "str"
    choices: list[str] = field(default_factory=list)
    required: bool = False
    positional: bool = False
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    item_type: str = "string"
    positional_index: int = 0

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

    def ts_type(self) -> str:
        """The TypeScript type a plan passes, not the type argparse accepts."""
        if self.kind == "bool":
            return "boolean"
        if self.kind in ("int", "float"):
            return "number"
        if self.kind == "list":
            return "number[]" if self.item_type in ("integer", "number") else "string[]"
        if self.kind == "choices":
            return " | ".join(json.dumps(c) for c in self.choices) or "string"
        return "string"


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
    # A tool with no schema and no help-parsed surface has no named arguments
    # to validate. Give its binding an `argv?: string[]` escape hatch so raw
    # flags and positionals can still reach the CLI without a TypeError.
    argv_escape: bool = False

    def ordered_positionals(self) -> list[Param]:
        return sorted(self.positionals, key=lambda p: not p.required)

    def positional_order(self) -> list[Param]:
        """Positionals in the order the CLI expects them on argv.

        The schema carries `x-positional-index`; the help-text fallback has no
        index at all, so it keeps the old required-first ordering.
        """
        return sorted(self.positionals, key=lambda p: (p.positional_index, not p.required))

    def line(self) -> str:
        pos = [p.declaration() for p in self.ordered_positionals()]
        required = [p.declaration() for p in self.params if p.required]
        optional = [p.declaration() for p in self.params if not p.required]
        taken = {p.name for p in self.params} | {p.name for p in self.positionals}
        if self.command and "command" not in taken:
            optional.insert(0, "command: str | None = None")
        parts = pos + required + (["*"] + optional if optional else [])
        return f"{self.func}({', '.join(parts)}) -> dict"

    def ts_fields(self) -> list[tuple[str, bool, str]]:
        """(property, required, ts type) in the order a reader expects.

        Positionals first, then `command`, then required flags, then optional
        ones, so an optional field never hides between two required ones.
        """
        taken = {p.name for p in self.params} | {p.name for p in self.positionals}
        fields: list[tuple[str, bool, str]] = []
        for param in self.positional_order():
            fields.append((_ts_prop(param.name), param.required, param.ts_type()))
        if self.command and "command" not in taken:
            fields.append(("command", False, "string"))
        for params in ([p for p in self.params if p.required],
                       [p for p in self.params if not p.required]):
            for param in params:
                fields.append((_ts_prop(param.name), param.required, param.ts_type()))
        if self.argv_escape:
            fields.append(("argv", False, "string[]"))
        return fields

    def ts_sig(self) -> str:
        fields = self.ts_fields()
        body = "{ " + "; ".join(
            f"{name}{'' if required else '?'}: {ts_type}"
            for name, required, ts_type in fields) + " }"
        if not fields:
            return f"{self.func}(args?: InvokeOptions): Promise<InvokeEnvelope>"
        if any(required for _, required, _ in fields):
            return f"{self.func}(args: {body} & InvokeOptions): Promise<InvokeEnvelope>"
        return f"{self.func}(args?: {body} & InvokeOptions): Promise<InvokeEnvelope>"


def _help_text(contract: dict[str, Any]) -> str:
    return str(contract.get("help") or "")


def _ts_prop(name: str) -> str:
    """An object-type property name: bare when legal, quoted when not.

    JavaScript keywords (`default`, `delete`) are legal property names, so only
    punctuation and leading digits need quoting.
    """
    return name if JS_IDENT.match(name) else json.dumps(name)


def _input_schema(contract: dict[str, Any]) -> dict[str, Any] | None:
    """The contract's JSON Schema, when it has one with real properties.

    Preferred over the help text everywhere: the schema carries argparse's
    declared `type=` and `required=`, which the printed help threw away.
    """
    schema = contract.get("inputSchema")
    if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
        return schema
    return None


def _schema_kind(prop: dict[str, Any]) -> tuple[str, list[str]]:
    enum = prop.get("enum")
    if isinstance(enum, list) and enum:
        return "choices", list(enum)
    return SCHEMA_KINDS.get(str(prop.get("type") or ""), "str"), []


def _schema_item_type(prop: dict[str, Any]) -> str:
    items = prop.get("items")
    if isinstance(items, dict) and items.get("type"):
        return str(items["type"])
    return "string"


def _schema_param(key: str, prop: dict[str, Any], required: set[str],
                  positional: bool) -> Param:
    kind, choices = _schema_kind(prop)
    aliases = prop.get("x-aliases")
    return Param(
        name=str(key),
        flag=str(prop.get("x-flag") or "") if not positional else "",
        kind=kind,
        choices=choices,
        required=(str(key) in required) and (positional or kind != "bool"),
        positional=positional,
        aliases=[str(a) for a in aliases] if isinstance(aliases, list) else [],
        description=str(prop.get("description") or ""),
        item_type=_schema_item_type(prop),
        positional_index=int(prop.get("x-positional-index") or 0),
    )


def _options_block(help_text: str) -> list[str]:
    """Every option section, concatenated.

    argparse renders one section per `add_argument_group(...)`, and the group
    titles are free-form ("OCR / image description (local vision endpoint):",
    "token shielding / ICM inspection:"). Taking only the last
    `options:` block loses every flag a grouped CLI declared, so those flags
    degrade to `str | None` in the generated bindings.
    """
    lines: list[str] = []
    for match in OPTIONS_SECTION.finditer(help_text):
        block = help_text[match.end():]
        stop = re.search(r"\n(?!\s)\S", block)
        if stop:
            block = block[: stop.start()]
        lines.extend(block.splitlines())
    return lines


def _entries(lines: list[str]) -> list[str]:
    """Option headers only: everything before the first 2+ space gutter."""
    headers: list[str] = []
    for line in lines:
        if OPTION_START.match(line):
            headers.append(re.split(r"\s{2,}", line.strip(), maxsplit=1)[0].strip())
    return headers


def _parse_header(header: str) -> tuple[str, str, list[str]]:
    """Return (long flag, metavar, sibling long flags) for `--url, -u URL`."""
    tokens = [t.rstrip(",") for t in header.split()]
    long_flags = [t for t in tokens if t.startswith("--")]
    if not long_flags:
        return "", "", []
    flag = long_flags[0]
    tail = tokens[tokens.index(flag) + 1:]
    metavar = ""
    for token in tail:
        if token.startswith("-"):
            continue
        metavar = token
        break
    return flag, metavar, long_flags[1:]


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
    schema = _input_schema(contract)
    if schema is not None:
        return _schema_flags(contract, schema)

    usage = str(contract.get("usage") or "").replace("\n", " ")
    required = _required_flags(usage)
    params: list[Param] = []
    seen: set[str] = set()

    for header in _entries(_options_block(_help_text(contract))):
        flag, metavar, aliases = _parse_header(header)
        if not flag or flag in ("--help", "--version"):
            continue
        kind, choices = ("bool", []) if not metavar else _kind_for(metavar)
        name = _param_name(flag, seen)
        seen.add(name)
        params.append(Param(name=name, flag=flag, kind=kind, choices=choices,
                            required=flag in required and kind != "bool"))
        # `--outline, --agenda` declares one option twice. The alias carries the
        # same kind, so it must not be re-invented as a `str` flag from the raw
        # flag list — that produced bindings like `agenda: str` for a bool.
        for alias in aliases:
            params.append(Param(name=_param_name(alias, seen), flag=alias, kind=kind,
                                choices=choices, required=False))

    known = {p.flag for p in params}
    # A subcommand parser inherits its parent's globals (--json, --dir, --port),
    # and the builder carries their *typed* params here. Merging only the raw
    # flag names lost the kind, so `--json` came out as `str | None` and the
    # generated call passed `--json True` to a store_true flag.
    for parent_param in contract.get("parent_params") or []:
        flag = parent_param.get("flag")
        if not flag or flag in known:
            continue
        kind = parent_param.get("kind") or "str"
        choices = list(parent_param.get("choices") or [])
        name = _param_name(flag, seen)
        seen.add(name)
        params.append(Param(name=name, flag=flag, kind=kind, choices=choices,
                            required=flag in required and kind != "bool"))
        known.add(flag)

    # A parser with subparsers leaks its children's flags into the contract's
    # flat flag list: ``parse_help_contract`` scans the whole help text, and the
    # subcommand table names options that only that subcommand accepts. Those
    # phantoms became bindings the root parser rejects ("unrecognized
    # arguments"), so for a subcommand CLI only the option block is trusted —
    # argparse always prints the parent's own options there.
    if contract.get("subcommands"):
        return params

    for flag in contract.get("flags") or []:
        if not isinstance(flag, str) or flag.startswith("--") is False or flag in known:
            continue
        if flag in ("--help", "--version"):
            continue
        name = _param_name(flag, seen)
        seen.add(name)
        params.append(Param(name=name, flag=flag, kind="str", required=flag in required))

    return params


def _schema_flags(contract: dict[str, Any], schema: dict[str, Any]) -> list[Param]:
    """Flags straight from the schema: exact type, exact requiredness.

    The schema also carries the parent's merged globals, but an older contract
    may still rely on `parent_params`; those are added only for flags the
    schema does not already declare.
    """
    required = {str(key) for key in (schema.get("required") or [])}
    params: list[Param] = []
    known: set[str] = set()

    for key, prop in schema["properties"].items():
        if not isinstance(prop, dict):
            continue
        if not prop.get("x-flag") or prop.get("x-positional"):
            continue
        param = _schema_param(key, prop, required, positional=False)
        params.append(param)
        known.add(param.flag)

    seen = {p.name for p in params}
    for parent_param in contract.get("parent_params") or []:
        flag = parent_param.get("flag")
        if not flag or flag in known:
            continue
        kind = parent_param.get("kind") or "str"
        choices = list(parent_param.get("choices") or [])
        name = _param_name(flag, seen)
        seen.add(name)
        params.append(Param(name=name, flag=flag, kind=kind, choices=choices,
                            required=flag in required and kind != "bool"))
        known.add(flag)
    return params


def _depth0_choices(usage: str) -> list[str]:
    """Command names in an unbracketed ``{a,b,c}``.

    ``[--layer {note,wiki,context}]`` is an option's value set and sits inside
    brackets. Reading it as a command list inserted a bogus `command` parameter
    into every generated signature that had a choice-typed flag.
    """
    depth = 0
    for index, ch in enumerate(usage):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif ch == "{" and depth == 0:
            end = usage.find("}", index)
            if end < 0:
                return []
            return [n.strip() for n in usage[index + 1:end].split(",") if n.strip()]
    return []


def _commands(contract: dict[str, Any], usage: str) -> tuple[bool, list[str]]:
    schema = _input_schema(contract)
    if schema is not None and "x-command" in schema:
        return bool(schema["x-command"]), [str(c) for c in (schema.get("x-commands") or [])]
    listed = [s for s in (contract.get("subcommands") or []) if s.get("name")]
    names = _depth0_choices(usage)
    if names:
        return True, names
    # A name argparse listed in the "positional arguments" block is a
    # positional, even when the block parser recorded it beside real
    # sub-parsers. `apiv-loop dispatch` has both a `--command` flag and a `run`
    # positional; treating `run` as a command injected a second `command`
    # parameter and produced a signature Python refuses to define.
    positionals = {str(p) for p in (contract.get("positionals") or [])}
    names = [str(s["name"]) for s in listed
             if not str(s["name"]).endswith("_pos")
             and str(s["name"]) not in positionals]
    return bool(names), names


def _positionals(contract: dict[str, Any], usage: str, taken: set[str]) -> list[Param]:
    schema = _input_schema(contract)
    if schema is not None:
        return _schema_positionals(schema, taken)
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

    # argparse's usage line is the only place a bare positional appears, and the
    # registry already extracts it there. Without this union a tool like
    # `mem search <query>` generated `search()` with no way to pass the query:
    # the signature looked complete and every call would have failed.
    has_commands, commands = _commands(contract, usage)
    for entry in contract.get("positionals") or []:
        pretty = str(entry).strip()
        if not pretty or pretty in commands:
            continue
        param = _param_name(pretty)
        if param in taken:
            continue
        taken.add(param)
        bracketed = re.search(rf"\[\s*<?{re.escape(pretty)}>?\s*\]", usage) is not None
        params.append(Param(name=param, kind="str", required=not bracketed, positional=True))
    return params


def _schema_positionals(schema: dict[str, Any], taken: set[str]) -> list[Param]:
    """Schema-declared positionals, in `x-positional-index` order."""
    required = {str(key) for key in (schema.get("required") or [])}
    entries = [
        (int(prop.get("x-positional-index") or 0), str(key), prop)
        for key, prop in schema["properties"].items()
        if isinstance(prop, dict) and prop.get("x-positional")
    ]
    entries.sort(key=lambda entry: entry[0])
    params: list[Param] = []
    for index, key, prop in entries:
        name = key if key not in taken else _param_name(key, taken)
        param = _schema_param(name, prop, required, positional=True)
        param.positional_index = index
        taken.add(name)
        params.append(param)
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
        usage = str(contract.get("usage_full") or contract.get("usage") or "").replace("\n", " ").strip()

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
        # "empty/fallback inputSchema" in practice means nothing callable was
        # recovered: no flags, no positionals, no subcommands. The CLI still
        # takes raw argv, so the typed surface must offer a raw argv escape
        # hatch instead of rejecting every key as "unknown argument".
        argv_escape = not flags and not positionals and not has_commands
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
            argv_escape=argv_escape,
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
    if sig.argv_escape and not sig.params and not sig.positionals and not sig.command:
        doc = _docstring(sig).replace("\\", "\\\\").replace('"""', "'''")
        return (f"def {sig.func}(argv: list[str] | None = None) -> dict:\n"
                f'    """{doc}"""\n'
                f"    return invoke({sig.id!r}, *(argv or []))\n")

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


def _ts_comment(sig: Signature, limit: int = 160) -> str:
    text = " ".join((sig.summary or sig.id).split())[:limit]
    return f"/** {text.replace('*/', '* /')} ({sig.id}) */"


def ts_decl(sig: Signature, export: bool = False) -> str:
    """One ambient (or exported) TypeScript declaration for a tool."""
    prefix = "export function " if export else "declare function "
    return f"{_ts_comment(sig)}\n{prefix}{sig.ts_sig()};"


def ts_stub(sig: Signature) -> str:
    """The compact form `spec --stubs` prints: one declaration, one comment."""
    text = " ".join((sig.summary or sig.id).split())[:100].replace("*/", "* /")
    return f"/** {text} */\ndeclare function {sig.ts_sig()};"
