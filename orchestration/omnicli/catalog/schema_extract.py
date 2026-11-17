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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_SCALAR_TYPES = {int: "integer", float: "number", bool: "boolean", str: "string"}
_HELP_FLAGS = {"--help", "--version"}
# `parseArgs` option names, which carry no leading dashes.
_HELP_FLAGS_NAMES = {"help", "version"}
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


# The Node probe. Loaded with ``node --import <probe.mjs>`` so it runs before
# the script's own module graph. ``parseArgs`` is patched on the shared
# ``node:util`` export object and the ESM named exports are re-synced, so both
# ``import { parseArgs } from "node:util"`` and
# ``require("node:util").parseArgs`` hit the hook.
_NODE_PROBE = r'''
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const fs = require("node:fs");
const util = require("node:util");
const out = process.env.OMNICLI_SCHEMA_OUT || "";
const original = util.parseArgs;
let written = false;

util.parseArgs = function patchedParseArgs(config, ...rest) {
  if (!written && out && config && typeof config === "object") {
    const options = {};
    const raw = config.options;
    if (raw && typeof raw === "object") {
      for (const [name, spec] of Object.entries(raw)) {
        const entry = {};
        if (spec && typeof spec === "object") {
          if (spec.type) entry.type = spec.type;
          if (spec.short) entry.short = spec.short;
          if (spec.multiple) entry.multiple = true;
          if (Object.prototype.hasOwnProperty.call(spec, "default")) {
            entry.default = spec.default;
          }
          if (spec.description) entry.description = spec.description;
        }
        options[name] = entry;
      }
    }
    try {
      fs.writeFileSync(out, JSON.stringify({
        options,
        allowPositionals: Boolean(config.allowPositionals),
      }));
      written = true;
    } catch {
      // A probe that cannot write is a probe that reports nothing.
    }
  }
  return original.call(this, config, ...rest);
};

try {
  const mod = require("node:module");
  if (typeof mod.syncBuiltinESMExports === "function") {
    mod.syncBuiltinESMExports();
  }
} catch {
  // Older runtimes have no ESM sync; the CJS hook still applies.
}
'''


def _kind_type(kind: str) -> str:
    return {"int": "integer", "float": "number", "bool": "boolean"}.get(kind, "string")


def _copy_json(value: Any) -> Any:
    """A defensive copy: schemas are stored, diffed and returned to callers."""
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        return dict(value) if isinstance(value, dict) else value


def normalize_input_schema(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and normalise a runtime-emitted JSON Schema.

    ``--omni-schema`` is a convention, not a library, so whatever comes back
    over stdout is attacker-adjacent input from an arbitrary script. Only the
    shape a caller can rely on is kept, and anything else is rejected rather
    than stored as if it were a contract.
    """
    if not isinstance(raw, dict):
        return None
    if not isinstance(raw.get("properties"), dict):
        return None
    schema = dict(raw)
    schema["type"] = "object"
    schema["properties"] = _copy_json(raw["properties"])
    schema["required"] = list(raw.get("required") or [])
    schema["additionalProperties"] = bool(raw.get("additionalProperties", False))
    schema["x-command"] = bool(raw.get("x-command", False))
    schema["x-commands"] = list(raw.get("x-commands") or [])
    return schema


def extract_omni_schema(
    cmd_prefix: list[str],
    args: list[str] | None = None,
    timeout: float = 12.0,
) -> dict[str, Any] | None:
    """Ask a script for its own schema via the ``--omni-schema`` convention.

    Language-agnostic on purpose: the script decides what it can describe, and
    this side only validates the JSON it prints. Runs in a scratch directory
    with stdin closed, because a script that ignores the flag would otherwise
    perform its real job inside the caller's checkout.
    """
    cmd = [*cmd_prefix, *(args or []), "--omni-schema"]
    with tempfile.TemporaryDirectory(prefix="omnicli-omni-schema-") as scratch:
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL, cwd=scratch, errors="replace")
        except (subprocess.TimeoutExpired, OSError):
            return None
    if proc.returncode != 0:
        return None
    try:
        raw = json.loads(proc.stdout.strip())
    except (AttributeError, TypeError, ValueError):
        return None
    return normalize_input_schema(raw)


def node_config_to_input_schema(config: dict[str, Any]) -> dict[str, Any]:
    """Convert a ``node:util`` ``parseArgs`` config into MCP JSON Schema.

    ``parseArgs`` already knows each option's declared type, repeatability and
    default; ``--help`` throws that away. This is the typed half. Positionals
    are not declared by ``parseArgs``, so they arrive later via
    :func:`enrich_node_schema`.
    """
    raw_options = config.get("options") if isinstance(config, dict) else None
    if not isinstance(raw_options, dict):
        raw_options = {}
    properties: dict[str, Any] = {}
    taken: set[str] = set()

    for opt_name, spec in raw_options.items():
        if str(opt_name) in _HELP_FLAGS_NAMES:
            continue
        if not isinstance(spec, dict):
            spec = {}
        name = _property_name(opt_name, taken)
        taken.add(name)
        is_boolean = spec.get("type") == "boolean"
        if spec.get("multiple"):
            prop: dict[str, Any] = {
                "type": "array",
                "items": {"type": "boolean" if is_boolean else "string"},
            }
        elif is_boolean:
            prop = {"type": "boolean"}
        else:
            prop = {"type": "string"}
        prop["x-flag"] = f"--{opt_name}"
        if "default" in spec:
            default = _json_safe(spec.get("default"))
            if default is not _UNSAFE:
                prop["default"] = default
        description = spec.get("description")
        if isinstance(description, str) and description:
            prop["description"] = description
        properties[name] = prop

    return {"type": "object", "properties": properties, "required": [],
            "additionalProperties": False, "x-command": False, "x-commands": []}


def extract_node_schema(
    script_path: Path,
    args: list[str] | None = None,
    node: str | None = None,
    timeout: float = 12.0,
) -> tuple[dict[str, Any] | None, str]:
    """Run ``--help`` under a ``parseArgs`` probe; return schema and output.

    The probe records the first ``parseArgs`` config the script declares, which
    is the one that describes its flags, then lets the script print its own
    help. Both halves therefore come from a single run, as with the argparse
    probe.
    """
    node_exe = node or shutil.which("node") or "node"
    out = ""
    with tempfile.TemporaryDirectory(prefix="omnicli-node-schema-") as scratch:
        scratch_dir = Path(scratch)
        preload_path = scratch_dir / "probe.mjs"
        schema_path = scratch_dir / "schema.json"
        try:
            preload_path.write_text(_NODE_PROBE, encoding="utf-8")
        except OSError:
            return None, ""
        try:
            resolved = Path(script_path).resolve()
        except OSError:
            resolved = Path(script_path)
        cmd = [node_exe, "--import", str(preload_path), str(resolved),
               *(args or []), "--help"]
        env = dict(os.environ, OMNICLI_SCHEMA_OUT=str(schema_path))
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL, cwd=scratch, env=env,
                errors="replace")
            out = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return None, ""
        except OSError:
            return None, ""
        raw: Any = None
        try:
            if schema_path.is_file():
                raw = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
    if not isinstance(raw, dict):
        return None, out
    return node_config_to_input_schema(raw), out


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


def enrich_node_schema(node_schema: dict[str, Any],
                       contract: dict[str, Any]) -> dict[str, Any]:
    """Add positionals, subcommands and metavar intent to a probe's schema.

    ``parseArgs`` describes flags only; the printed help carries the rest. A
    declared string is refined (never replaced) where the help implies an
    integer, number or enum, and the inputs are left untouched.
    """
    schema = json.loads(json.dumps(node_schema))
    try:
        source = json.loads(json.dumps(contract))
    except (TypeError, ValueError):
        source = contract
    fallback = contract_to_input_schema(source)

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}
        schema["properties"] = properties
    fallback_props = fallback.get("properties")
    if not isinstance(fallback_props, dict):
        fallback_props = {}

    for name, prop in fallback_props.items():
        if not isinstance(prop, dict):
            continue
        if prop.get("x-positional") is True and name not in properties:
            properties[name] = json.loads(json.dumps(prop))

    by_flag = {
        prop["x-flag"]: prop
        for prop in properties.values()
        if isinstance(prop, dict) and prop.get("x-flag")
    }
    for prop in fallback_props.values():
        if not isinstance(prop, dict):
            continue
        target = by_flag.get(prop.get("x-flag"))
        if target is None or target.get("type") != "string":
            continue
        enum = prop.get("enum")
        if isinstance(enum, list) and enum:
            target["enum"] = list(enum)
            continue
        if prop.get("type") in ("integer", "number"):
            target["type"] = prop["type"]

    if fallback.get("x-command") is True:
        schema["x-command"] = True
        schema["x-commands"] = list(fallback.get("x-commands") or [])

    required = [name for name in (schema.get("required") or [])
                if name in properties]
    for name in fallback.get("required") or []:
        if name in properties and name not in required:
            required.append(name)
    schema["required"] = required
    return schema


def contract_from_input_schema(schema: dict[str, Any], *, usage: str = "",
                               help_text: str = "",
                               summary: str = "") -> dict[str, Any]:
    """A help-level contract derived from a schema alone.

    A runtime that answers ``--omni-schema`` may print no readable help at all.
    The catalog still needs flags, positionals and subcommands, so they are
    read back out of the schema the runtime declared.
    """
    flags: list[str] = []
    positionals: list[str] = []
    for name, prop in (schema.get("properties") or {}).items():
        if not isinstance(prop, dict):
            continue
        flag = prop.get("x-flag")
        if isinstance(flag, str) and flag:
            if flag not in flags:
                flags.append(flag)
        elif prop.get("x-positional") is True:
            positionals.append(name)
    commands = list(schema.get("x-commands") or []) if schema.get("x-command") else []
    contract: dict[str, Any] = {
        "usage": usage,
        "flags": flags,
        "positionals": positionals,
        "subcommands": [{"name": name, "aliases": [], "summary": ""}
                        for name in commands],
        "help": help_text,
        "inputSchema": schema,
    }
    if summary:
        contract["summary"] = summary
    return contract


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
