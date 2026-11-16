"""Unit tests for catalog.schema_extract.

Run:
    python3 tests/test_schema_extract.py
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from catalog import registry, schema_extract  # noqa: E402

ARGPARSE_TOOL = '''#!/usr/bin/env python3
"""A tool with a real parser."""
import argparse

parser = argparse.ArgumentParser(prog="tool")
parser.add_argument("--mem-limit", type=int, metavar="MiB", default=2048,
                    help="heap ceiling in MiB")
parser.add_argument("--json", action="store_true", help="machine output")
parser.add_argument("--format", choices=["md", "vtt", "txt"], default="md")
parser.add_argument("--pages", nargs="+", type=int, metavar="PAGE")
subparsers = parser.add_subparsers(dest="command")
child = subparsers.add_parser("sub", help="run the subcommand")
child.add_argument("--job", required=True)
child.add_argument("--count", type=int, default=3)
parser.add_argument("query")

if __name__ == "__main__":
    parser.parse_args()
'''

HANDWRITTEN_TOOL = '''#!/usr/bin/env python3
"""No argparse here."""
import sys

if "--help" in sys.argv or "-h" in sys.argv:
    print("usage: tool.py [--limit N] [--json] target")
    sys.exit(0)
print("did the work")
'''

SHELL_TOOL = '''#!/bin/sh
usage() {
  echo "usage: tool.sh [--limit N] [--json] target"
}

case "$1" in
  --help) usage; exit 0 ;;
esac
usage
'''

FALLBACK_HELP = (
    "usage: tool.py [--limit N] [--format {md,txt}] query\n"
    "\n"
    "options:\n"
    "  -h, --help            show this help message and exit\n"
    "  --limit N             how many rows\n"
    "  --format {md,txt}     output format\n"
)


def write_script(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


class TestParserToSchema(unittest.TestCase):
    def test_declared_int_beats_a_metavar_of_mib(self):
        """`--mem-limit MiB` must stay an integer, not degrade to a string."""
        parser = argparse.ArgumentParser(prog="t")
        parser.add_argument("--mem-limit", type=int, metavar="MiB", default=2048,
                            help="heap ceiling")
        schema = schema_extract.parser_to_input_schema(parser)
        prop = schema["properties"]["mem_limit"]
        self.assertEqual(prop["type"], "integer")
        self.assertEqual(prop["x-flag"], "--mem-limit")
        self.assertEqual(prop["default"], 2048)
        self.assertEqual(prop["description"], "heap ceiling")

    def test_float_choices_store_true_and_array(self):
        parser = argparse.ArgumentParser(prog="t")
        parser.add_argument("--timeout", type=float, metavar="SECONDS")
        parser.add_argument("--format", choices=["md", "txt"])
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--pages", nargs="+", type=int, metavar="PAGE")
        schema = schema_extract.parser_to_input_schema(parser)
        props = schema["properties"]

        self.assertEqual(props["timeout"]["type"], "number")
        self.assertEqual(props["format"]["type"], "string")
        self.assertEqual(props["format"]["enum"], ["md", "txt"])
        self.assertEqual(props["json"]["type"], "boolean")
        self.assertIs(props["json"]["default"], False)
        self.assertEqual(props["pages"]["type"], "array")
        self.assertEqual(props["pages"]["items"], {"type": "integer"})

    def test_required_flags_are_listed(self):
        parser = argparse.ArgumentParser(prog="t")
        parser.add_argument("--url", required=True)
        parser.add_argument("--limit", type=int)
        schema = schema_extract.parser_to_input_schema(parser)
        self.assertEqual(schema["required"], ["url"])

    def test_positionals_carry_index_and_requiredness(self):
        parser = argparse.ArgumentParser(prog="t")
        parser.add_argument("query")
        parser.add_argument("limit", nargs="?", type=int)
        schema = schema_extract.parser_to_input_schema(parser)
        query = schema["properties"]["query"]
        limit = schema["properties"]["limit"]

        self.assertIs(query["x-positional"], True)
        self.assertEqual(query["x-positional-index"], 0)
        self.assertEqual(query["type"], "string")
        self.assertIs(limit["x-positional"], True)
        self.assertEqual(limit["x-positional-index"], 1)
        self.assertEqual(limit["type"], "integer")
        self.assertEqual(schema["required"], ["query"])

    def test_subparsers_are_commands_not_properties(self):
        parser = argparse.ArgumentParser(prog="t")
        parser.add_argument("--json", action="store_true")
        subparsers = parser.add_subparsers(dest="command")
        subparsers.add_parser("stats")
        subparsers.add_parser("add")
        schema = schema_extract.parser_to_input_schema(parser)
        self.assertIs(schema["x-command"], True)
        self.assertEqual(schema["x-commands"], ["add", "stats"])
        self.assertNotIn("command", schema["properties"])
        self.assertEqual(schema["properties"]["json"]["type"], "boolean")

    def test_a_plain_parser_is_not_a_command(self):
        parser = argparse.ArgumentParser(prog="t")
        parser.add_argument("--json", action="store_true")
        schema = schema_extract.parser_to_input_schema(parser)
        self.assertIs(schema["x-command"], False)
        self.assertEqual(schema["x-commands"], [])

    def test_help_and_version_are_not_parameters(self):
        parser = argparse.ArgumentParser(prog="t")
        parser.add_argument("--version", action="version", version="1")
        parser.add_argument("--limit", type=int)
        schema = schema_extract.parser_to_input_schema(parser)
        self.assertEqual(list(schema["properties"]), ["limit"])

    def test_longest_flag_wins_and_aliases_are_kept(self):
        parser = argparse.ArgumentParser(prog="t")
        parser.add_argument("-d", "--dir", "--directory")
        prop = schema_extract.parser_to_input_schema(parser)["properties"]["directory"]
        self.assertEqual(prop["x-flag"], "--directory")
        self.assertEqual(prop["x-aliases"], ["--dir"])

    def test_suppressed_defaults_are_dropped(self):
        parser = argparse.ArgumentParser(prog="t")
        parser.add_argument("--flag", default=argparse.SUPPRESS)
        prop = schema_extract.parser_to_input_schema(parser)["properties"]["flag"]
        self.assertNotIn("default", prop)

    def test_schema_is_json_serialisable(self):
        parser = argparse.ArgumentParser(prog="t")
        parser.add_argument("--limit", type=int, default=5)
        parser.add_argument("query")
        schema = schema_extract.parser_to_input_schema(parser)
        self.assertEqual(json.loads(json.dumps(schema)), schema)
        self.assertIs(schema["additionalProperties"], False)


class TestRuntimeExtraction(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_argparse_schema_is_read_from_the_live_parser(self):
        script = write_script(self.dir, "tool.py", ARGPARSE_TOOL)
        schema, out = schema_extract.extract_argparse_schema(script)
        self.assertIsNotNone(schema, f"no schema; help was: {out[:400]}")
        props = schema["properties"]
        self.assertEqual(props["mem_limit"]["type"], "integer")
        self.assertIs(schema["x-command"], True)
        self.assertEqual(schema["x-commands"], ["sub"])
        self.assertEqual(schema["required"], ["query"])

    def test_subcommand_schema_comes_from_the_subparser(self):
        script = write_script(self.dir, "tool.py", ARGPARSE_TOOL)
        schema, out = schema_extract.extract_argparse_schema(script, args=["sub"])
        self.assertIsNotNone(schema, f"no schema; help was: {out[:400]}")
        props = schema["properties"]
        self.assertIn("job", props)
        self.assertEqual(schema["required"], ["job"])
        self.assertEqual(props["count"]["type"], "integer")
        self.assertIs(schema["x-command"], False)
        self.assertNotIn("mem_limit", props,
                         "a subcommand's own --help does not declare the parent's flags")

    def test_contract_keeps_help_keys_and_gains_a_schema(self):
        script = write_script(self.dir, "tool.py", ARGPARSE_TOOL)
        contract = registry.extract_contract(script)
        for key in ("usage", "flags", "positionals", "subcommands", "help"):
            self.assertIn(key, contract)
        self.assertIn("usage:", contract["help"].lower())
        self.assertIn("inputSchema", contract)
        self.assertEqual(
            contract["inputSchema"]["properties"]["mem_limit"]["type"], "integer")

    def test_non_argparse_script_falls_back_to_the_contract(self):
        script = write_script(self.dir, "tool.py", HANDWRITTEN_TOOL)
        contract = registry.extract_contract(script)
        self.assertIn("usage:", contract["usage"].lower())
        schema = contract["inputSchema"]
        self.assertEqual(schema["properties"]["limit"]["x-flag"], "--limit")
        self.assertIs(schema["x-command"], False)

    def test_shell_script_gets_a_schema(self):
        script = write_script(self.dir, "tool.sh", SHELL_TOOL)
        contract = registry.extract_contract(script)
        self.assertIn("usage:", contract["usage"].lower())
        schema = contract["inputSchema"]
        self.assertEqual(schema["properties"]["json"]["x-flag"], "--json")
        self.assertIs(schema["properties"]["target"]["x-positional"], True)

    def test_parser_version_is_bumped(self):
        self.assertEqual(registry.CONTRACT_PARSER_VERSION, 8)


class TestContractFallback(unittest.TestCase):
    def test_typed_flags_survive_a_handwritten_help(self):
        contract = registry.parse_help_contract(FALLBACK_HELP)
        self.assertNotIn("inputSchema", contract)
        schema = schema_extract.contract_to_input_schema(contract)

        props = schema["properties"]
        self.assertEqual(props["limit"]["type"], "integer")
        self.assertEqual(props["limit"]["x-flag"], "--limit")
        self.assertEqual(props["format"]["enum"], ["md", "txt"])
        self.assertEqual(props["query"]["x-positional"], True)
        self.assertEqual(props["query"]["x-positional-index"], 0)
        self.assertEqual(schema["required"], ["query"])

    def test_subcommands_become_x_commands(self):
        help_text = "usage: tool.py [-h] {search,stats}\n"
        contract = registry.parse_help_contract(help_text)
        schema = schema_extract.contract_to_input_schema(contract)
        self.assertIs(schema["x-command"], True)
        self.assertEqual(schema["x-commands"], ["search", "stats"])
        self.assertNotIn("search", schema["properties"])

    def test_empty_contract_is_a_valid_empty_schema(self):
        schema = schema_extract.contract_to_input_schema(registry.parse_help_contract(""))
        self.assertEqual(schema["properties"], {})
        self.assertEqual(schema["required"], [])
        self.assertIs(schema["additionalProperties"], False)


class TestMergeParentSchema(unittest.TestCase):
    PARENT = {
        "type": "object",
        "properties": {
            "json": {"type": "boolean", "x-flag": "--json", "default": False},
            "db": {"type": "string", "x-flag": "--db"},
            "limit": {"type": "integer", "x-flag": "--limit"},
            "query": {"type": "string", "x-positional": True},
        },
        "required": ["query"],
        "additionalProperties": False,
        "x-command": True,
        "x-commands": ["sub"],
    }

    def child(self):
        return {
            "type": "object",
            "properties": {
                "job": {"type": "string", "x-flag": "--job"},
                "limit": {"type": "integer", "x-flag": "--limit", "default": 7},
            },
            "required": ["job"],
            "additionalProperties": False,
            "x-command": False,
            "x-commands": [],
        }

    def test_parent_options_are_added(self):
        merged = schema_extract.merge_parent_schema(self.child(), self.PARENT)
        self.assertEqual(merged["properties"]["json"]["type"], "boolean")
        self.assertEqual(merged["properties"]["db"]["x-flag"], "--db")
        self.assertEqual(merged["required"], ["job"])

    def test_child_properties_win(self):
        merged = schema_extract.merge_parent_schema(self.child(), self.PARENT)
        self.assertEqual(merged["properties"]["limit"]["default"], 7)
        self.assertIs(merged["x-command"], False)

    def test_positionals_are_not_inherited(self):
        merged = schema_extract.merge_parent_schema(self.child(), self.PARENT)
        self.assertNotIn("query", merged["properties"])

    def test_merge_does_not_alias_the_inputs(self):
        child = self.child()
        merged = schema_extract.merge_parent_schema(child, self.PARENT)
        merged["properties"]["job"]["type"] = "integer"
        merged["properties"]["json"]["type"] = "string"
        self.assertEqual(child["properties"]["job"]["type"], "string")
        self.assertEqual(self.PARENT["properties"]["json"]["type"], "boolean")

    def test_empty_child(self):
        merged = schema_extract.merge_parent_schema(
            {"type": "object", "properties": {}, "required": []}, self.PARENT)
        self.assertIn("json", merged["properties"])
        self.assertNotIn("query", merged["properties"])


class TestSubcommandFallbackSchema(unittest.TestCase):
    """A subcommand whose own help cannot be read still inherits the globals."""

    PARENT = {
        "usage": "tool.py [--json] [--db DB] query",
        "flags": ["--json", "--db"],
        "positionals": ["query"],
        "subcommands": [{"name": "stats"}],
        "help": "usage: tool.py [--json] [--db DB] query {stats}",
        "inputSchema": {
            "type": "object",
            "properties": {
                "json": {"type": "boolean", "x-flag": "--json"},
                "db": {"type": "string", "x-flag": "--db"},
                "query": {"type": "string", "x-positional": True,
                          "x-positional-index": 0},
            },
            "required": ["query"],
            "additionalProperties": False,
            "x-command": True,
            "x-commands": ["stats"],
        },
    }

    def test_fallback_keeps_parent_options_but_not_parent_positionals(self):
        from catalog import builder

        tool = {"id": "x/tool", "argv": ["python", "tool.py"], "path": None}
        out = builder._subcommand_contract(
            None, tool, "stats", self.PARENT, None, {})
        props = out["inputSchema"]["properties"]
        self.assertEqual(props["json"]["type"], "boolean")
        self.assertEqual(props["db"]["x-flag"], "--db")
        self.assertNotIn("query", props)
        self.assertIs(out["inputSchema"]["x-command"], False)
        self.assertEqual(out["flags"], ["--json", "--db"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
