"""Extract a real JSON Schema from a live ``argparse`` parser.

``--help`` text is what the catalog stored; a schema is what a caller needs.
Argparse knows every parameter's type, requiredness and default, and throws
them away when it prints help. This module recovers them by running the script
under a probe that hooks ``ArgumentParser.print_help`` and serialises the
parser it was actually asked about. Everything else (non-argparse help, shell
scripts, older contracts) falls back to :func:`contract_to_input_schema`.
Stdlib only: the probe runs under the *skill's* interpreter, a virtualenv that
has nothing of ours installed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_SCALAR_TYPES = {int: "integer", float: "number", bool: "boolean", str: "string"}
_HELP_FLAGS = {"--help", "--version"}
_UNSAFE = object()


# The probe. Run as ``python -c PROBE <script> [args...] --help`` in a scratch
# directory, so indexing cannot create a workspace in the caller's checkout.
_PROBE_CODE = r'''
import argparse
import importlib.util
import json
import os
import runpy
import sys
from pathlib import Path

def _load_converter():
    lib = os.environ.get("OMNICLI_SCHEMA_LIB") or ""
    try:
        spec = importlib.util.spec_from_file_location("omnicli_schema_extract", lib)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "parser_to_input_schema", None)
    except Exception:
        return None

_target = os.environ.get("OMNICLI_SCHEMA_OUT") or ""
_convert = _load_converter()
_written = [False]
_original = argparse.ArgumentParser.print_help

def _print_help(self, file=None):
    if _target and not _written[0] and _convert is not None:
        _written[0] = True
        try:
            schema = _convert(self)
            Path(_target).write_text(json.dumps(schema, indent=1), encoding="utf-8")
        except Exception:
            pass
    return _original(self, file)

argparse.ArgumentParser.print_help = _print_help

script = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path[0] = str(Path(script).resolve().parent)
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit:
    pass
'''


def _json_type(value_type: Any) -> str:
    return _SCALAR_TYPES.get(value_type, "string")


def _is_array(action: argparse.Action) -> bool:
    nargs = action.nargs
    return (isinstance(action, argparse._AppendAction)
            or (isinstance(nargs, str) and nargs in ("+", "*"))
            or nargs is argparse.REMAINDER
            or (isinstance(nargs, int) and not isinstance(nargs, bool) and nargs > 1))


def _is_boolean(action: argparse.Action) -> bool:
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        return True
    if isinstance(action, argparse._CountAction):
        # `-vvv` is an integer even though argparse models it with nargs=0.
        return False
    if isinstance(action, getattr(argparse, "BooleanOptionalAction", ())):
        return True
    return action.nargs == 0


def _json_safe(value: Any) -> Any:
    if value is argparse.SUPPRESS:
        return _UNSAFE
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        items = [_json_safe(item) for item in value]
        return _UNSAFE if any(item is _UNSAFE for item in items) else items
    if isinstance(value, dict):
        out = {str(key): _json_safe(item) for key, item in value.items()}
        return _UNSAFE if any(item is _UNSAFE for item in out.values()) else out
    return _UNSAFE


def _choices(action: argparse.Action) -> list[Any]:
    try:
        raw = list(action.choices or [])
    except TypeError:
        return []
    safe = [_json_safe(choice) for choice in raw]
    return [] if any(choice is _UNSAFE for choice in safe) else safe


def _describe(action: argparse.Action) -> str:
    """The help text of one action, with argparse's ``%(default)s`` filled in."""
    text = action.help
    if not text or text is argparse.SUPPRESS:
        return ""
    if "%(" in text:
        try:
            text = text % vars(action)
        except (KeyError, TypeError, ValueError):
            pass
    return " ".join(str(text).split())


def _property_name(raw: str, taken: set[str]) -> str:
    name = re.sub(r"[^0-9a-zA-Z_]", "_", str(raw).lstrip("-")).strip("_").lower()
    if not name:
        name = "arg"
    if name[0].isdigit():
        name = f"f_{name}"
    base, suffix = name, 2
    while name in taken:
        name = f"{base}_{suffix}"
        suffix += 1
    return name


def _flag_for(action: argparse.Action) -> str:
    """The flag to invoke: the longest long option, else the only short one."""
    longs = [s for s in action.option_strings if s.startswith("--")]
    return max(longs, key=len) if longs else (action.option_strings or [""])[0]


def _declared_type(action: argparse.Action) -> dict[str, Any]:
    if _is_boolean(action):
        return {"type": "boolean"}
    if _is_array(action):
        return {"type": "array", "items": {"type": _json_type(action.type)}}
    if isinstance(action, argparse._CountAction):
        return {"type": "integer"}
    return {"type": _json_type(action.type)}


def _annotate(prop: dict[str, Any], action: argparse.Action) -> dict[str, Any]:
    choices = _choices(action)
    if choices:
        prop["enum"] = choices
    description = _describe(action)
    if description:
        prop["description"] = description
    return prop


def parser_to_input_schema(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """Convert one ``ArgumentParser`` into an MCP-compatible JSON Schema."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    taken: set[str] = set()
    commands: list[str] | None = None
    positional_index = 0

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            # A subparser is a dispatch target, not an argument: the caller
            # passes its name as `argv[0]`, not as `--command=`.
            commands = sorted(str(name) for name in action.choices)
            continue
        # `_VersionAction` subclasses `_HelpAction`, so this covers both.
        if isinstance(action, argparse._HelpAction):
            continue

        if not action.option_strings:
            name = _property_name(action.dest, taken)
            taken.add(name)
            prop = _annotate(_declared_type(action), action)
            prop["x-positional"] = True
            prop["x-positional-index"] = positional_index
            positional_index += 1
            properties[name] = prop
            # `nargs="?"` and `nargs="*"` may be omitted; everything else may not.
            if action.nargs not in ("?", "*"):
                required.append(name)
            continue

        flag = _flag_for(action)
        if not flag or flag in _HELP_FLAGS:
            continue
        name = _property_name(flag, taken)
        taken.add(name)
        prop = _annotate(_declared_type(action), action)
        prop["x-flag"] = flag
        aliases = [s for s in action.option_strings
                   if s.startswith("--") and s != flag]
        if aliases:
            prop["x-aliases"] = aliases
        default = _json_safe(action.default)
        if default is not _UNSAFE:
            prop["default"] = default
        properties[name] = prop
        if action.required:
            required.append(name)

    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False, "x-command": commands is not None,
            "x-commands": commands or []}


def extract_argparse_schema(
    script_path: Path,
    args: list[str] | None = None,
    python: str | None = None,
    timeout: float = 12.0,
) -> tuple[dict[str, Any] | None, str]:
    """Run ``--help`` under a probe and return ``(schema_or_none, output)``.

    ``args`` selects a subcommand's own parser. Help text comes back alongside
    so both halves come from a single run of a possibly slow script.
    """
    interp = python or sys.executable
    out = ""
    schema: Any = None

    with tempfile.TemporaryDirectory(prefix="omnicli-schema-") as scratch:
        schema_path = Path(scratch) / "schema.json"
        env = dict(os.environ,
                   OMNICLI_SCHEMA_OUT=str(schema_path),
                   OMNICLI_SCHEMA_LIB=str(Path(__file__).resolve()))
        cmd = [interp, "-c", _PROBE_CODE, str(script_path),
               *(args or []), "--help"]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL, cwd=scratch, env=env,
                errors="replace")
            out = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            out = ""
        except OSError:
            out = ""
        try:
            if schema_path.is_file():
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            schema = None

    return (schema, out) if isinstance(schema, dict) else (None, out)


def _kind_type(kind: str) -> str:
    return {"int": "integer", "float": "number", "bool": "boolean"}.get(kind, "string")


def contract_to_input_schema(contract: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a schema from a ``--help`` contract.

    The fallback for everything argparse cannot describe for us: shell
    scripts, hand-written usage text, and contracts extracted before this
    module existed. Types are the ones :mod:`catalog.argspec` inferred, so a
    ``--limit N`` stays an integer instead of degrading to a string.
    """
    from . import argspec

    usage = str(contract.get("usage_full") or contract.get("usage") or "")
    usage = usage.replace("\n", " ").strip()
    flags = argspec.parse_flags(contract)
    has_commands, commands = argspec._commands(contract, usage)
    positionals = argspec._positionals(
        contract, usage, {param.name for param in flags})

    properties: dict[str, Any] = {}
    required: list[str] = []
    for index, param in enumerate(positionals):
        prop: dict[str, Any] = {"type": _kind_type(param.kind),
                                "x-positional": True,
                                "x-positional-index": index}
        if param.choices:
            prop["enum"] = list(param.choices)
        properties[param.name] = prop
        if param.required:
            required.append(param.name)

    for param in flags:
        prop = {"type": _kind_type(param.kind)}
        if param.flag:
            prop["x-flag"] = param.flag
        if param.choices:
            prop["enum"] = list(param.choices)
        properties[param.name] = prop
        if param.required:
            required.append(param.name)

    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False, "x-command": has_commands,
            "x-commands": list(commands) if has_commands else []}


def merge_parent_schema(child_schema: dict[str, Any],
                        parent_schema: dict[str, Any]) -> dict[str, Any]:
    """Add the parent's options to a subcommand's schema.

    A subparser accepts every global its parent declared but lists none of
    them in its own ``--help``. Properties the child declares itself win: a
    ``parents=[common]`` subparser re-declares them, after the subcommand.
    """
    merged = json.loads(json.dumps(child_schema))
    child_props = merged.get("properties")
    if not isinstance(child_props, dict):
        child_props = {}
        merged["properties"] = child_props
    parent_props = parent_schema.get("properties")
    if not isinstance(parent_props, dict):
        return merged

    names = set(child_props)
    flags = {prop.get("x-flag") for prop in child_props.values()
             if isinstance(prop, dict) and prop.get("x-flag")}
    for key, prop in parent_props.items():
        if not isinstance(prop, dict) or not prop.get("x-flag"):
            continue
        if key in names or prop["x-flag"] in flags:
            continue
        child_props[key] = json.loads(json.dumps(prop))
        names.add(key)
        flags.add(prop["x-flag"])
    return merged
