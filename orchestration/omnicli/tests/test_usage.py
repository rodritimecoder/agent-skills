"""Usage telemetry: identity tagging and the aggregation behind `omnicli usage`.

The point of these tests is that the question "is omnicli used in OpenCode or
only agy?" has an answer read from a file, not from memory.

    python3 tests/test_usage.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from catalog import bindings, builder  # noqa: E402
from omnicli import _parse_since, cmd_usage  # noqa: E402


class Identity(unittest.TestCase):
    def _identity(self, env):
        with mock.patch.dict(os.environ, env, clear=True):
            return bindings.trace_identity()

    def test_t3_code_wins_over_opencode(self):
        harness, _ = self._identity({"T3CODE_CLI_PATH": "/x", "OPENCODE": "1"})
        self.assertEqual(harness, "t3-code")

    def test_opencode_marker(self):
        self.assertEqual(self._identity({"OPENCODE": "1"})[0], "opencode")

    def test_agy_marker_is_its_liveness_variable(self):
        self.assertEqual(self._identity({"ANTIGRAVITY_AGENT": "1"})[0], "agy")

    def test_agy_beats_markers_inherited_from_the_outer_harness(self):
        # A T3 Code shell that launches agy keeps T3CODE_CLI_PATH in the child.
        harness, session = self._identity({
            "T3CODE_CLI_PATH": "/x",
            "OPENCODE_SESSION_ID": "ses_outer",
            "ANTIGRAVITY_AGENT": "1",
            "ANTIGRAVITY_CONVERSATION_ID": "conv_inner",
        })
        self.assertEqual(harness, "agy")
        self.assertEqual(session, "conv_inner")

    def test_explicit_override_wins(self):
        self.assertEqual(self._identity({"OMNICLI_HARNESS": "boxxy", "T3CODE_CLI_PATH": "/x"})[0],
                         "boxxy")

    def test_unknown_harness_is_cli(self):
        self.assertEqual(self._identity({})[0], "cli")

    def test_session_prefers_opencode_id_then_pid(self):
        _, session = self._identity({"OPENCODE_SESSION_ID": "ses_123"})
        self.assertEqual(session, "ses_123")
        _, fallback = self._identity({})
        self.assertTrue(fallback.startswith("ppid:"))


class Since(unittest.TestCase):
    def test_relative_units(self):
        now = time.time()
        self.assertAlmostEqual(now - _parse_since("2h"), 7200, delta=5)
        self.assertAlmostEqual(now - _parse_since("7d"), 604800, delta=5)

    def test_bad_spec_exits(self):
        with self.assertRaises(SystemExit):
            _parse_since("soon")


class Aggregation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "trace.jsonl"
        self.now = time.time()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rows):
        self.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def _call(self, verb, tool, harness, session, age=10.0):
        return {"kind": "call", "call": verb, "tool": tool, "t": self.now - age,
                "harness": harness, "session": session, "via": "cli"}

    def _usage(self, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_usage(trace=str(self.path), as_json=True, **kwargs)
        return json.loads(buf.getvalue())

    def test_counts_and_conversion(self):
        self._write([
            self._call("search", "find a transcriber", "t3-code", "s1", age=20),
            self._call("invoke", "zoom-recorder", "t3-code", "s1", age=18),
            self._call("search", "make a deck", "agy", "s2", age=15),
            self._call("describe", "deck", "agy", "s2", age=14),
            self._call("search", "unanswered", "opencode", "s3", age=10),
        ])
        out = self._usage()
        self.assertEqual(out["calls"], 5)
        self.assertEqual(out["sessions"], 3)
        self.assertEqual(out["harness"], {"t3-code": 2, "agy": 2, "opencode": 1})
        self.assertEqual(out["search_sessions"], 3)
        self.assertEqual(out["search_acted"], 2)
        self.assertAlmostEqual(out["search_acted_rate"], 0.6667, places=3)
        self.assertIn("zoom-recorder", out["tools"])
        self.assertIn("find a transcriber", out["queries"])

    def test_rows_before_the_window_are_ignored(self):
        self._write([
            self._call("search", "old", "cli", "s0", age=9 * 86400),
            self._call("search", "new", "cli", "s1", age=5),
        ])
        out = self._usage(since="7d")
        self.assertEqual(out["calls"], 1)
        self.assertEqual(out["queries"], {"new": 1})

    def test_pre_change_rows_report_unknown_harness(self):
        self._write([{"kind": "call", "call": "search", "tool": "x", "t": self.now - 5}])
        self.assertEqual(self._usage()["harness"], {"unknown": 1})

    def test_done_rows_are_not_calls(self):
        self._write([
            self._call("search", "q", "cli", "s1"),
            {"kind": "done", "call": "search", "tool": "q", "ms": 3, "rc": 0,
             "harness": "cli", "session": "s1"},
        ])
        self.assertEqual(self._usage()["calls"], 1)

    def test_no_trace_exits(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(buf):
            cmd_usage(trace=str(self.path), as_json=True)


class JsBindings(unittest.TestCase):
    """The generated JS module has to answer what the Python CLI answers.

    Identity is the seam that drifts: it exists twice because the sandboxed
    module cannot import `catalog`. These tests run the generated file through
    `node` instead of trusting the two copies to stay in sync.
    """

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node not installed")
        cls.tmp = tempfile.TemporaryDirectory()
        con = builder.connect()
        try:
            cls.out = bindings.write(con, Path(cls.tmp.name))
        finally:
            con.close()
        cls.module = cls.out / "omnicli_tools.mjs"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _node_identity(self, env):
        probe = Path(self.tmp.name) / "identity_probe.mjs"
        probe.write_text(
            'import { traceIdentity } from "./omnicli_tools.mjs";\n'
            "process.stdout.write(JSON.stringify(traceIdentity()));\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [self.node, str(probe)], capture_output=True, text=True, timeout=60,
            cwd=self.tmp.name, env=dict(env),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_generated_module_is_valid_esm(self):
        proc = subprocess.run([self.node, "--check", str(self.module)],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.out / "omnicli_tools.d.ts").is_file())

    def test_generated_dts_declares_the_sleek_surface(self):
        text = (self.out / "omnicli_tools.d.ts").read_text(encoding="utf-8")
        for needle in ("export declare function result(", "export declare function $(",
                       "export declare const tools:", "export declare const TOOLS:"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_proxy_index_and_helpers_are_importable(self):
        probe = Path(self.tmp.name) / "surface_probe.mjs"
        probe.write_text(
            'import { tools, TOOLS, result, planResult, $, SPEC } from "./omnicli_tools.mjs";\n'
            "process.stdout.write(JSON.stringify({\n"
            "  callable: typeof tools, alias: TOOLS === tools,\n"
            "  known: typeof tools[SPEC[0].id], unknown: tools.__missing__ === undefined,\n"
            "  result: typeof result, alias2: planResult === result, shell: typeof $,\n"
            "}));\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [self.node, str(probe)], capture_output=True, text=True, timeout=60,
            cwd=self.tmp.name, env=dict(os.environ),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["callable"], "function")
        self.assertTrue(payload["alias"])
        self.assertEqual(payload["known"], "function")
        self.assertTrue(payload["unknown"])
        self.assertEqual(payload["result"], "function")
        self.assertTrue(payload["alias2"])
        self.assertEqual(payload["shell"], "function")

    def test_trace_identity_agrees_with_the_cli(self):
        cases = [
            {"T3CODE_CLI_PATH": "/x", "OPENCODE_SESSION_ID": "ses_t3"},
            {"ANTIGRAVITY_AGENT": "1", "ANTIGRAVITY_CONVERSATION_ID": "conv_1"},
            {"OPENCODE": "1", "OPENCODE_SESSION_ID": "ses_oc"},
            {"OMNICLI_HARNESS": "boxxy"},
            {"OMNICLI_HARNESS": "agy", "ANTIGRAVITY_AGENT": "1",
             "T3CODE_CLI_PATH": "/x", "OPENCODE_SESSION_ID": "ses_outer"},
            {},
        ]
        for env in cases:
            with self.subTest(env=env):
                with mock.patch.dict(os.environ, env, clear=True):
                    expected = bindings.trace_identity()
                actual = self._node_identity(env)
                self.assertEqual(actual[0], expected[0], env)
                # A ppid fallback names two different processes by design;
                # every explicit session must match exactly.
                if not expected[1].startswith("ppid:"):
                    self.assertEqual(actual[1], expected[1], env)


if __name__ == "__main__":
    unittest.main()
