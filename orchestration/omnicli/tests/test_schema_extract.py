"""Unit tests for catalog.schema_extract.

Run:
    python3 tests/test_schema_extract.py
"""

from __future__ import annotations

import argparse
import json
import os
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

# A real ESM `node:util` parser. `--format` and `--name` are declared as
# strings on purpose: the help text is what refines them.
ESM_TOOL = r'''#!/usr/bin/env node
/**
 * Reference ESM CLI used by the unit tests.
 */
import { parseArgs } from "node:util";

const { values } = parseArgs({
  allowPositionals: true,
  options: {
    help: { type: "boolean", short: "h", description: "show usage" },
    json: { type: "boolean", short: "j", description: "machine output" },
    limit: { type: "string", default: "10", description: "row count" },
    tag: { type: "string", multiple: true, description: "repeatable tag" },
    verbose: { type: "boolean", multiple: true },
    format: { type: "string" },
    name: { type: "string" },
  },
});

if (values.help) {
  console.log("usage: tool.mjs [--json] [--limit N] [--tag TAG] [--format {md,txt}] query");
  console.log("");
  console.log("options:");
  console.log("  --json                machine output");
  console.log("  --limit N             row count");
  console.log("  --tag TAG             repeatable tag");
  console.log("  --verbose             noisy");
  console.log("  --format {md,txt}     output format");
  console.log("  --name TEXT           display name");
  console.log("");
  console.log("positional arguments:");
  console.log("  query                 search terms");
  process.exit(0);
}
'''

# The CommonJS half of the same hook: `require("node:util")` must see the patch
# too, which is what `syncBuiltinESMExports` alone does not guarantee.
CJS_TOOL = r'''#!/usr/bin/env node
/**
 * Reference CommonJS CLI used by the unit tests.
 */
const { parseArgs } = require("node:util");

const { values } = parseArgs({
  options: {
    help: { type: "boolean", short: "h" },
    "dry-run": { type: "boolean", description: "plan only" },
    output: { type: "string", default: "out.json" },
  },
});

if (values.help) {
  console.log("usage: cjs.js [--dry-run] [--output FILE]");
  process.exit(0);
}
'''

# A runtime with no readable help and a hand-written schema: the `--omni-schema`
# branch has to build the whole contract from the schema.
OMNI_MJS_TOOL = r'''#!/usr/bin/env node
/**
 * Emits a hand-written omni schema.
 */
const schema = {
  type: "object",
  properties: {
    json: { type: "boolean", "x-flag": "--json" },
    limit: { type: "integer", "x-flag": "--limit", default: 5 },
  },
  required: [],
  additionalProperties: false,
  "x-command": false,
  "x-commands": [],
};

if (process.argv.includes("--omni-schema")) {
  console.log(JSON.stringify(schema));
  process.exit(0);
}
if (process.argv.includes("--help")) {
  console.log("usage: omni.mjs [--json] [--limit N]");
  process.exit(0);
}
'''

OMNI_SHELL_TOOL = '''#!/bin/sh
case "$1" in
  --omni-schema)
    printf '%s\\n' '{"type":"object","properties":{"resume":{"type":"boolean","x-flag":"--resume"},"target":{"type":"string","x-positional":true}},"required":["target"],"x-command":false,"x-commands":[]}'
    exit 0
    ;;
  --help)
    echo "omni.sh: emit records"
    exit 0
    ;;
esac
echo "omni.sh: emit records"
'''

# Reachable only through a `--omni-sc*` glob, so the literal flag is absent
# from the source: a probe here would be a bug, and the marker proves it ran.
SAFE_SHELL_TOOL = '''#!/bin/sh
if [ "$1" = "--help" ]; then
  echo "usage: safe.sh [--limit N]"
  exit 0
fi
case "$1" in
  --omni-sc*) touch "$OMNICLI_TEST_MARKER" ;;
esac
echo "usage: safe.sh [--limit N]"
'''

SAFE_MJS_TOOL = r'''#!/usr/bin/env node
/**
 * A CLI whose schema flag is never advertised.
 */
import fs from "node:fs";

if (process.argv.includes("--help")) {
  console.log("usage: safe.mjs [--limit N]");
  process.exit(0);
}
if (process.argv.some((arg) => arg.startsWith("--omni-s"))) {
  fs.writeFileSync(process.env.OMNICLI_TEST_MARKER, "ran");
  process.exit(0);
}
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
        self.assertEqual(registry.CONTRACT_PARSER_VERSION, 9)


class TestNodeSchema(unittest.TestCase):
    """`node:util` `parseArgs` declarations, probed from a live process."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_esm_parse_args_declarations_are_typed(self):
        script = write_script(self.dir, "tool.mjs", ESM_TOOL)
        schema, out = schema_extract.extract_node_schema(script)
        self.assertIsNotNone(schema, f"no schema; help was: {out[:400]}")
        props = schema["properties"]

        self.assertEqual(props["json"]["type"], "boolean")
        self.assertEqual(props["json"]["x-flag"], "--json")
        self.assertEqual(props["tag"]["type"], "array")
        self.assertEqual(props["tag"]["items"], {"type": "string"})
        self.assertEqual(props["verbose"]["type"], "array")
        self.assertEqual(props["verbose"]["items"], {"type": "boolean"})
        self.assertEqual(props["limit"]["type"], "string")
        self.assertEqual(props["limit"]["default"], "10")
        self.assertNotIn("help", props, "--help is not a parameter")
        self.assertIs(schema["x-command"], False)

    def test_esm_help_enriches_positionals_and_enums(self):
        script = write_script(self.dir, "tool.mjs", ESM_TOOL)
        contract = registry.extract_contract(script)
        props = contract["inputSchema"]["properties"]

        self.assertEqual(props["limit"]["type"], "integer",
                         "`--limit N` should refine the declared string")
        self.assertEqual(props["limit"]["default"], "10",
                         "a declared default must survive the refinement")
        self.assertEqual(props["format"]["enum"], ["md", "txt"])
        self.assertEqual(props["name"]["type"], "string")
        self.assertEqual(props["query"]["x-positional"], True)
        self.assertEqual(props["query"]["x-positional-index"], 0)
        self.assertIn("query", contract["inputSchema"]["required"])
        self.assertEqual(contract["summary"],
                         "Reference ESM CLI used by the unit tests.")

    def test_cjs_require_parse_args_is_hooked_too(self):
        script = write_script(self.dir, "tool.js", CJS_TOOL)
        contract = registry.extract_contract(script)
        props = contract["inputSchema"]["properties"]

        self.assertEqual(props["dry_run"]["type"], "boolean")
        self.assertEqual(props["dry_run"]["x-flag"], "--dry-run")
        self.assertEqual(props["output"]["type"], "string")
        self.assertEqual(props["output"]["default"], "out.json")
        self.assertNotIn("help", props)
        self.assertEqual(contract["summary"],
                         "Reference CommonJS CLI used by the unit tests.")

    def test_a_non_executable_module_without_help_is_not_run(self):
        marker = self.dir / "ran"
        script = self.dir / "helper.mjs"
        script.write_text(
            "import fs from 'node:fs';\n"
            "function parseArgs(argv) { return argv; }\n"
            f"fs.writeFileSync({str(marker)!r}, 'ran');\n"
            "parseArgs(process.argv);\n")
        contract = registry.extract_contract(script)
        self.assertFalse(marker.exists(), "an unprobeable module was executed")
        self.assertEqual(contract["usage"], "")
        self.assertNotIn("inputSchema", contract)
        self.assertEqual(contract["summary"], "")


class TestOmniSchema(unittest.TestCase):
    """The `--omni-schema` convention, for runtimes without a known parser."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_shell_script_contract_can_come_from_the_schema_alone(self):
        script = write_script(self.dir, "omni.sh", OMNI_SHELL_TOOL)
        contract = registry.extract_contract(script)
        schema = contract["inputSchema"]

        self.assertNotIn("usage:", contract["help"].lower(),
                         "this fixture deliberately has no usage line")
        self.assertEqual(contract["usage"], "omni.sh [options]")
        self.assertEqual(contract["flags"], ["--resume"])
        self.assertEqual(contract["positionals"], ["target"])
        self.assertEqual(schema["properties"]["resume"]["type"], "boolean")
        self.assertIs(schema["properties"]["target"]["x-positional"], True)
        self.assertEqual(schema["required"], ["target"])

    def test_mjs_schema_wins_over_the_help_fallback(self):
        script = write_script(self.dir, "omni.mjs", OMNI_MJS_TOOL)
        contract = registry.extract_contract(script)
        props = contract["inputSchema"]["properties"]

        self.assertIn("usage:", contract["usage"].lower())
        self.assertEqual(props["limit"]["type"], "integer")
        self.assertEqual(props["limit"]["default"], 5)
        self.assertEqual(props["json"]["type"], "boolean")
        self.assertEqual(contract["summary"],
                         "Emits a hand-written omni schema.")

    def test_schema_is_not_probed_when_nothing_advertises_it(self):
        marker = self.dir / "marker"
        os.environ["OMNICLI_TEST_MARKER"] = str(marker)
        try:
            shell = write_script(self.dir, "safe.sh", SAFE_SHELL_TOOL)
            mjs = write_script(self.dir, "safe.mjs", SAFE_MJS_TOOL)
            shell_contract = registry.extract_contract(shell)
            mjs_contract = registry.extract_contract(mjs)
        finally:
            os.environ.pop("OMNICLI_TEST_MARKER", None)

        self.assertFalse(marker.exists(), "--omni-schema was executed uninvited")
        self.assertIn("usage:", shell_contract["usage"].lower())
        self.assertIn("--limit", shell_contract["flags"])
        self.assertIn("usage:", mjs_contract["usage"].lower())
        self.assertIn("limit", mjs_contract["inputSchema"]["properties"],
                      "the help fallback should still supply a schema")


class TestNormalizeInputSchema(unittest.TestCase):
    def test_non_schema_shapes_are_rejected(self):
        self.assertIsNone(schema_extract.normalize_input_schema({}))
        self.assertIsNone(schema_extract.normalize_input_schema({"properties": []}))
        self.assertIsNone(schema_extract.normalize_input_schema({"type": "object"}))
        self.assertIsNone(schema_extract.normalize_input_schema(["nope"]))

    def test_contract_keys_are_filled_in(self):
        schema = schema_extract.normalize_input_schema(
            {"properties": {"json": {"type": "boolean"}}})
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["required"], [])
        self.assertIs(schema["additionalProperties"], False)
        self.assertIs(schema["x-command"], False)
        self.assertEqual(schema["x-commands"], [])

    def test_a_copy_is_returned(self):
        raw = {"properties": {"json": {"type": "boolean"}}}
        schema = schema_extract.normalize_input_schema(raw)
        schema["properties"]["json"]["type"] = "string"
        self.assertEqual(raw["properties"]["json"]["type"], "boolean")


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
