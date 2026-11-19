"""Tests for the JS plan executor: generated bindings and `omnicli exec`."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from catalog import bindings, builder  # noqa: E402

OMNICLI = str(ROOT / "omnicli.py")
NODE = shutil.which("node")
BWRAP = shutil.which("bwrap")

needs_js_runtime = unittest.skipUnless(NODE, "node not installed")
needs_sandbox = unittest.skipUnless(BWRAP and NODE, "bubblewrap or node not installed")


def _node_probe(work: Path, source: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    probe = work / "probe.mjs"
    probe.write_text(source, encoding="utf-8")
    env = os.environ.copy()
    env.update({"OMNICLI_BIN": "/bin/false", "OMNICLI_MAX_CALLS": "1"})
    env.update(env_extra or {})
    return subprocess.run([NODE, str(probe)], cwd=str(work), env=env,
                          capture_output=True, text=True, timeout=120)


class TestBindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        con = builder.connect()
        builder.ensure_built(con, with_contracts=True, progress=False)
        con.close()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)
        con = builder.connect()
        bindings.write(con, self.out)
        con.close()

    @needs_js_runtime
    def test_write_emits_a_checkable_module_and_types(self):
        module = self.out / "omnicli_tools.mjs"
        types = self.out / "omnicli_tools.d.ts"
        self.assertTrue(module.is_file())
        self.assertTrue(types.is_file())
        check = subprocess.run([NODE, "--check", str(module)],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(check.returncode, 0, check.stderr)

    @needs_js_runtime
    def test_ensure_rewrites_the_same_package(self):
        con = builder.connect()
        fingerprint = builder.meta_get(con, "fingerprint", "")
        target = bindings.ensure(con, fingerprint, self.out)
        con.close()
        self.assertEqual(Path(target), self.out)
        self.assertTrue((Path(target) / "omnicli_tools.mjs").is_file())

    @needs_js_runtime
    def test_signatures_are_typescript(self):
        line = self._probe("""
import { SIGNATURES } from "./omnicli_tools.mjs";
console.log(SIGNATURES["academic-icm/scripts/academic_icm:zoom"]);
""").stdout
        self.assertIn("url: string", line)
        self.assertIn('"md" | "vtt" | "txt" | "all"', line)
        self.assertIn("video?: boolean", line)
        self.assertIn("Promise<InvokeEnvelope>", line)

    @needs_js_runtime
    def test_spec_filters_inside_node(self):
        payload = json.loads(self._probe("""
import { spec } from "./omnicli_tools.mjs";
console.log(JSON.stringify({
  grep: spec("zoom"),
  skill: spec({ skill: "zoom-recorder" }),
  limit: spec({ limit: 3 }),
}));
""").stdout)
        self.assertTrue(payload["grep"])
        for row in payload["grep"]:
            self.assertTrue("zoom" in row["id"].lower() or "zoom" in row["summary"].lower(), row)
        self.assertEqual(payload["skill"][0]["skill"], "zoom-recorder")
        self.assertEqual(len(payload["limit"]), 3)

    @needs_js_runtime
    def test_schema_validation_precedes_dispatch(self):
        payload = json.loads(self._probe("""
import * as tools from "./omnicli_tools.mjs";
const cases = {
  unknown: () => tools.zoom({ url: "https://example.test/a.mp4", bogus: 1 }),
  missing: () => tools.zoom({}),
  enum: () => tools.zoom({ url: "https://example.test/a.mp4", format: "bad" }),
  type: () => tools.zoom({ url: 5 }),
};
const seen = {};
for (const [name, call] of Object.entries(cases)) {
  try { await call(); seen[name] = "no-error"; }
  catch (err) { seen[name] = err.constructor.name; }
}
console.log(JSON.stringify(seen));
""").stdout)
        for name in ("unknown", "missing", "enum", "type"):
            self.assertEqual(payload[name], "TypeError", f"{name}: {payload[name]}")

    def test_filtered_spec_stubs_match_bindings_disambiguation(self):
        # Filtering by --grep must not erase earlier-alphabetical collisions
        # like `design-pack/...:check`, or `spec --stubs` prints `check(...)`
        # while the module exports `guard_hooks_check(...)`.
        proc = subprocess.run(
            [sys.executable, OMNICLI, "spec", "--grep", "guard-hooks/scripts/guard:check", "--stubs"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("declare function guard_hooks_check(", proc.stdout)
        self.assertNotIn("declare function check(", proc.stdout)

    def _probe(self, source: str) -> subprocess.CompletedProcess:
        proc = _node_probe(self.out, source)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc


class TestExec(unittest.TestCase):
    def _exec(self, *argv: str, stdin: str | None = None,
              cwd: str | None = None) -> tuple[dict, subprocess.CompletedProcess]:
        proc = subprocess.run(
            [sys.executable, OMNICLI, "exec", *argv, "--json"],
            input=stdin, capture_output=True, text=True, timeout=300, cwd=cwd,
        )
        try:
            report = json.loads(proc.stdout)
        except ValueError:
            self.fail(f"exec did not print a JSON report (rc={proc.returncode}):\n{proc.stderr}")
        return report, proc

    def _code(self, work: Path, code: str, *extra: str):
        return self._exec("-c", code, "--workspace", str(work), *extra)

    @needs_sandbox
    def test_inline_plan_uses_globals_without_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, proc = self._code(Path(tmp), """
const rows = await search("audio transcription", 2);
console.log(rows.map((row) => row.skill).join(","));
""")
            self.assertEqual(proc.returncode, 0, report["stderr"])
            self.assertEqual(report["plan"], "<inline>")
            self.assertTrue(report["sandboxed"])
            self.assertEqual(report["tool_calls"], 1)
            self.assertTrue(report["stdout"].strip())

    @needs_sandbox
    def test_esm_plan_emits_its_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.mjs"
            plan.write_text(
                'import { search, emitResult } from "omnicli_tools";\n'
                'const rows = await search("ocr", 1);\n'
                "emitResult({ count: rows.length, first: rows[0] && rows[0].skill });\n",
                encoding="utf-8",
            )
            report, proc = self._exec(str(plan))
            self.assertEqual(proc.returncode, 0, report["stderr"])
            self.assertEqual(report["plan"], str(plan))
            self.assertGreaterEqual(report["tool_calls"], 1)
            self.assertEqual(report["result"]["count"], 1)
            self.assertTrue(report["result"]["first"])

    @needs_sandbox
    def test_stdin_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, proc = self._exec("-", "--workspace", tmp,
                                      stdin='console.log("stdin-success");\n')
            self.assertEqual(proc.returncode, 0, report["stderr"])
            self.assertEqual(report["plan"], "<stdin>")
            self.assertIn("stdin-success", report["stdout"])

    @needs_sandbox
    def test_parallel_fan_out_trips_the_call_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, proc = self._code(Path(tmp), """
const calls = Array.from({ length: 6 }, () => () => search("ocr", 1));
const rows = await parallel(calls, 6);
console.log("calls", rows.length);
""", "--max-calls", "2")
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("max-calls", report["stderr"])
            self.assertIn("parallel", report["stderr"])

    @needs_sandbox
    def test_parallel_fan_out_succeeds_in_write_sandbox_empty_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, proc = self._code(Path(tmp), """
const calls = Array.from({ length: 10 }, () => () => search("ocr", 1));
const rows = await parallel(calls, 8);
emitResult({ count: rows.length, nonEmpty: rows.every((r) => Array.isArray(r) && r.length > 0) });
""", "--sandbox", "write")
            self.assertEqual(proc.returncode, 0, report["stderr"])
            self.assertNotIn("database is locked", report["stderr"])
            self.assertEqual(report["tool_calls"], 10)
            self.assertEqual(report["result"], {"count": 10, "nonEmpty": True})
            self.assertFalse((Path(tmp) / ".local").exists())

    @needs_sandbox
    def test_sandbox_blocks_writes_outside_the_workspace(self):
        outside = "/home/omnicli-sandbox-probe.txt"
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "probe.mjs"
            plan.write_text(
                'const fs = require("node:fs");\n'
                f"try {{ fs.writeFileSync({outside!r}, 'x'); console.log('wrote'); }}\n"
                "catch (err) { console.log('blocked'); }\n",
                encoding="utf-8",
            )
            report, proc = self._exec(str(plan))
            self.assertEqual(proc.returncode, 0, report["stderr"])
            self.assertEqual(report["stdout"].strip(), "blocked")
            self.assertFalse(os.path.exists(outside))

    @needs_sandbox
    def test_exec_from_cwd_tmp_uses_private_guest_workspace(self):
        # Regression: with cwd=/tmp and no --workspace, the workspace resolved
        # to /tmp itself and the old `--bind /tmp /tmp` hid the staged
        # /tmp/omnicli/node runtime, so sandboxed exec died before the plan ran.
        # The fix binds the workspace at the private guest path /tmp/omnicli/work.
        def roundtrip_plan(marker: str) -> str:
            return (
                'const fs = require("node:fs");\n'
                f"const name = '.omnicli-tmpcwd-{marker}.txt';\n"
                f"fs.writeFileSync(name, {marker!r});\n"
                f"console.log('roundtrip', fs.readFileSync(name, 'utf8') === {marker!r});\n"
            )

        cwd_files = []
        try:
            for sandbox in ("write", "strict"):
                marker = uuid.uuid4().hex
                target = Path("/tmp") / f".omnicli-tmpcwd-{marker}.txt"
                cwd_files.append(target)
                report, proc = self._exec("-c", roundtrip_plan(marker),
                                          "--sandbox", sandbox, cwd="/tmp")
                self.assertEqual(proc.returncode, 0, report["stderr"])
                self.assertEqual(report["sandbox"], sandbox)
                self.assertTrue(report["sandboxed"])
                self.assertIn("roundtrip true", report["stdout"])
                self.assertTrue(target.is_file())
                self.assertEqual(target.read_text(encoding="utf-8"), marker)
        finally:
            for target in cwd_files:
                target.unlink(missing_ok=True)

        # Positive control: an explicit --workspace uses the same mechanism.
        with tempfile.TemporaryDirectory() as tmp:
            marker = uuid.uuid4().hex
            report, proc = self._exec("-c", roundtrip_plan(marker), "--workspace", tmp)
            self.assertEqual(proc.returncode, 0, report["stderr"])
            self.assertIn("roundtrip true", report["stdout"])
            target = Path(tmp) / f".omnicli-tmpcwd-{marker}.txt"
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_text(encoding="utf-8"), marker)

    @needs_sandbox
    def test_strict_mode_masks_home_routes_through_the_bridge_and_denies_exec(self):
        sentinel = Path.home() / f".omnicli-probe-{os.getpid()}"
        sentinel.write_text("secret", encoding="utf-8")
        probe = """
import fs from "node:fs";
import net from "node:net";
import { execFileSync } from "node:child_process";
import { search } from "omnicli_tools";

try { fs.readFileSync(SENTINEL, "utf8"); console.log("home: readable"); }
catch (err) { console.log("home: masked"); }

const outcome = await new Promise((resolve) => {
  const sock = net.connect({ port: PORT, host: "127.0.0.1" });
  sock.setTimeout(1500);
  sock.once("connect", () => { sock.destroy(); resolve("network: open"); });
  sock.once("error", () => { sock.destroy(); resolve("network: blocked"); });
  sock.once("timeout", () => { sock.destroy(); resolve("network: blocked"); });
});
console.log(outcome);

console.log("search:", (await search("ocr", 1)).length);

let rc = 0;
try { execFileSync(process.env.OMNICLI_BIN, ["exec", "--help"], { stdio: "pipe" }); }
catch (err) { rc = err.status === undefined ? err.code : err.status; }
console.log("rc", rc);
"""
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "strict.mjs"
            plan.write_text(probe.replace("SENTINEL", repr(str(sentinel))).replace("PORT", str(port)),
                            encoding="utf-8")
            try:
                readable, _ = self._exec(str(plan), "--sandbox", "write")
                report, proc = self._exec(str(plan), "--sandbox", "strict")
            finally:
                sentinel.unlink(missing_ok=True)
                listener.close()
            self.assertIn("home: readable", readable["stdout"])
            self.assertIn("search:", readable["stdout"])
            self.assertIn("home: masked", report["stdout"])
            self.assertIn("network: blocked", report["stdout"])
            self.assertIn("search: 1", report["stdout"])
            self.assertIn("rc 126", report["stdout"])
            self.assertEqual(report["sandbox"], "strict")
            self.assertGreaterEqual(report["bridge_calls"], 1)
            self.assertIn("exec", report["bridge_denied"])

    @needs_sandbox
    def test_strict_mode_blocks_the_network_write_mode_allows(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        code = """
const net = require("node:net");
const outcome = await new Promise((resolve) => {
  const sock = net.connect({ port: PORT, host: "127.0.0.1" });
  sock.setTimeout(1500);
  sock.once("connect", () => { sock.destroy(); resolve("network: open"); });
  sock.once("error", () => { sock.destroy(); resolve("network: blocked"); });
  sock.once("timeout", () => { sock.destroy(); resolve("network: blocked"); });
});
console.log(outcome);
""".replace("PORT", str(port))
        try:
            with tempfile.TemporaryDirectory() as tmp:
                writable, _ = self._code(Path(tmp), code, "--sandbox", "write")
                strict, _ = self._code(Path(tmp), code, "--sandbox", "strict")
        finally:
            listener.close()
        self.assertIn("network: open", writable["stdout"])
        self.assertIn("network: blocked", strict["stdout"])

    @needs_sandbox
    def test_mem_limit_trips_on_a_large_js_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, proc = self._code(Path(tmp), """
const big = [];
for (;;) big.push(new Array(1 << 20).fill(7));
""", "--mem-limit", "64")
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("--mem-limit 64 MiB", report["stderr"])

    def test_python_plan_file_is_retired_with_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.py"
            plan.write_text("print('legacy')\n", encoding="utf-8")
            proc = subprocess.run([sys.executable, OMNICLI, "exec", str(plan)],
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("Python plans are retired", proc.stderr)
        self.assertIn("plan.mjs", proc.stderr)
        self.assertIn("spec --stubs", proc.stderr)

    def test_lang_py_is_retired_with_exit_2(self):
        proc = subprocess.run(
            [sys.executable, OMNICLI, "exec", "-c", "console.log(1)", "--lang", "py"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("Python plans are retired", proc.stderr)

    def test_unknown_lang_is_rejected(self):
        proc = subprocess.run(
            [sys.executable, OMNICLI, "exec", "-c", "console.log(1)", "--lang", "cobol"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("unknown --lang", proc.stderr)

    def test_exec_arg_validation(self):
        # neither script nor -c
        proc = subprocess.run([sys.executable, OMNICLI, "exec"],
                              capture_output=True, text=True, timeout=60)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("requires a plan script", proc.stderr)

        # both script and -c
        proc = subprocess.run(
            [sys.executable, OMNICLI, "exec", "dummy.mjs", "-c", "console.log(1)"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("cannot pass both", proc.stderr)


class TestCatalogReadOnly(unittest.TestCase):
    def test_connect_read_only_on_immutable_db(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        db = root / "catalog.db"
        con = builder.connect(db)
        con.execute("INSERT INTO tools(id, skill, kind) VALUES('x:y','x','script')")
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()

        db.chmod(0o444)
        root.chmod(0o555)
        self.addCleanup(db.chmod, 0o644)
        self.addCleanup(root.chmod, 0o755)

        os.environ["OMNICLI_DB_RO"] = "1"
        self.addCleanup(os.environ.pop, "OMNICLI_DB_RO", None)

        ro = builder.connect(db)
        self.addCleanup(ro.close)
        self.assertEqual(ro.execute("SELECT count(*) FROM tools").fetchone()[0], 1)


class TestContractIsolation(unittest.TestCase):
    def test_help_probe_cannot_write_into_the_caller_directory(self):
        from catalog import registry

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "noisy.py"
            script.write_text(
                "import pathlib, sys\n"
                "if '--help' in sys.argv:\n"
                "    pathlib.Path(sys.argv[1]).mkdir(exist_ok=True)\n"
                "print('usage: noisy [-h]')\n",
                encoding="utf-8",
            )
            registry.extract_contract(script)
            self.assertFalse((Path(tmp) / "--help").exists())


if __name__ == "__main__":
    unittest.main()
