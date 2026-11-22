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
    def test_module_is_at_least_25_percent_smaller_than_baseline(self):
        baseline = 520_823
        size = (self.out / "omnicli_tools.mjs").stat().st_size
        ceiling = int(baseline * 0.75)
        self.assertLessEqual(size, ceiling,
                             f"module {size} B must be <= {ceiling} B (25% under {baseline} B)")

    def test_dts_declares_the_sleek_surface(self):
        text = (self.out / "omnicli_tools.d.ts").read_text(encoding="utf-8")
        for needle in (
            "export interface PlanResult",
            "export declare function result(",
            "export declare const planResult",
            "export declare function $(",
            "export interface ShellCommand",
            "export interface ToolMap",
            "export declare const TOOLS:",
            "export declare const tools:",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

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

    @needs_js_runtime
    def test_tools_proxy_is_callable_and_indexed(self):
        # Positive control: tools("skill") still lists tools through the CLI.
        fake = self.out / "fake_omnicli.sh"
        fake.write_text("#!/bin/sh\nprintf '{\"listed\":true}'\n", encoding="utf-8")
        fake.chmod(0o755)
        proc = _node_probe(self.out, """
import { tools, TOOLS } from "./omnicli_tools.mjs";
const known = "cornell-notes/cli";
console.log(JSON.stringify({
  listed: await tools("cornell-notes"),
  callable: typeof tools,
  alias: TOOLS === tools,
  known: typeof tools[known],
  unknown: tools["not-a-real-tool-id"] === undefined,
  hasKnown: known in tools,
}));
""", {"OMNICLI_BIN": str(fake)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["listed"], {"listed": True})
        self.assertEqual(payload["callable"], "function")
        self.assertTrue(payload["alias"])
        self.assertEqual(payload["known"], "function")
        self.assertTrue(payload["unknown"])  # negative control for unknown id
        self.assertTrue(payload["hasKnown"])

    @needs_js_runtime
    def test_shell_gate_strict_throws_before_spawn_none_succeeds(self):
        marker = self.out / "shell-gate-marker.txt"
        strict = _node_probe(self.out, f"""
import {{ $ }} from "./omnicli_tools.mjs";
try {{ $`printf leaked > {str(marker)!r}`; console.log("NO-THROW"); }}
catch (err) {{ console.log(err.message); }}
""", {"OMNICLI_SANDBOX": "strict"})
        self.assertEqual(strict.returncode, 0, strict.stderr)
        self.assertIn("shell commands are disabled in strict sandbox", strict.stdout)
        # A gate that cannot fail is not a gate: no child was spawned.
        self.assertFalse(marker.exists(), "strict $ must throw before spawning")

        none = _node_probe(self.out, """
import { $ } from "./omnicli_tools.mjs";
console.log(await $`printf shell-ok`.text());
""", {"OMNICLI_SANDBOX": "none"})
        self.assertEqual(none.returncode, 0, none.stderr)
        self.assertEqual(none.stdout.strip(), "shell-ok")

    @needs_js_runtime
    def test_result_helper_writes_the_envelope(self):
        target = self.out / "result-envelope.json"
        proc = _node_probe(self.out, """
import { result, planResult } from "./omnicli_tools.mjs";
console.log(typeof result, planResult === result);
try { result(5); console.log("NO-THROW"); }
catch (err) { console.log(err.constructor.name + ": " + err.message); }
result({ ok: true, tool: "probe", proof: "gate", data: { n: 1 } });
""", {"OMNICLI_RESULT": str(target)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(lines[0], "function true")
        self.assertIn("TypeError: result: expected a single options object", lines[1])
        self.assertEqual(
            json.loads(target.read_text(encoding="utf-8")),
            {"ok": True, "tool": "probe", "proof": "gate", "data": {"n": 1}},
        )

    def test_spec_plan_header_changes_output_only_with_the_flag(self):
        base = [sys.executable, OMNICLI, "spec", "--grep", "cornell-notes/cli", "--limit", "1"]
        off = subprocess.run(base, capture_output=True, text=True, timeout=60)
        on = subprocess.run(base + ["--plan-header"], capture_output=True, text=True, timeout=60)
        self.assertEqual(off.returncode, 0, off.stderr)
        self.assertEqual(on.returncode, 0, on.stderr)
        # Negative control: without the flag the output is byte-identical to legacy.
        self.assertFalse(off.stdout.startswith("/*"))
        # Positive control: only with the flag a block comment is prepended.
        self.assertTrue(on.stdout.startswith("/*"))
        self.assertIn("cornell-notes/cli", on.stdout)
        self.assertTrue(on.stdout.endswith(off.stdout))
        # --json stays parseable with the flag (header is plain-mode only).
        as_json = subprocess.run(base + ["--json", "--plan-header"],
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(as_json.returncode, 0, as_json.stderr)
        self.assertIsInstance(json.loads(as_json.stdout), list)

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

    def _exec_plain(self, *argv: str, cwd: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, OMNICLI, "exec", *argv],
            capture_output=True, text=True, timeout=300, cwd=cwd,
        )

    def _code(self, work: Path, code: str, *extra: str):
        return self._exec("-c", code, "--workspace", str(work), *extra)

    def _assert_strict_import_refused(self, code: str, module: str):
        """A strict plan that imports *module* dies at the VM boundary.

        Slice 1 refuses node:net / node:child_process / node:worker_threads for
        require(), static import and dynamic import alike. The plan body never
        runs: the process exits non-zero and stderr names the blocked module.
        """
        report, proc = self._exec("-c", code, "--sandbox", "strict")
        self.assertNotEqual(proc.returncode, 0, report["stderr"])
        self.assertEqual(report["sandbox"], "strict")
        self.assertNotEqual(report["exit_code"], 0)
        self.assertIn(f"omnicli: {module} is blocked in the strict sandbox",
                      report["stderr"])
        return report, proc

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
        # Only allowed imports here (node:fs and omnicli_tools), so the plan
        # still runs under strict: $HOME is masked and search crosses the bridge.
        probe = """
import fs from "node:fs";
import { search } from "omnicli_tools";

try { fs.readFileSync(SENTINEL, "utf8"); console.log("home: readable"); }
catch (err) { console.log("home: masked"); }

console.log("search:", (await search("ocr", 1)).length);
"""
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "strict.mjs"
            plan.write_text(probe.replace("SENTINEL", repr(str(sentinel))),
                            encoding="utf-8")
            try:
                readable, _ = self._exec(str(plan), "--sandbox", "write")
                report, proc = self._exec(str(plan), "--sandbox", "strict")
            finally:
                sentinel.unlink(missing_ok=True)

        # Equivalent non-strict (write) behaviour: the real $HOME is visible
        # and search still returns rows.
        self.assertIn("home: readable", readable["stdout"])
        self.assertIn("search:", readable["stdout"])

        # Strict behaviour: bwrap masks $HOME and the tool call is routed over
        # the bridge (which is why bridge_calls is non-zero).
        self.assertEqual(proc.returncode, 0, report["stderr"])
        self.assertEqual(report["sandbox"], "strict")
        self.assertIn("home: masked", report["stdout"])
        self.assertNotIn("home: readable", report["stdout"])
        self.assertIn("search: 1", report["stdout"])
        self.assertGreaterEqual(report["bridge_calls"], 1)

        # Slice 1 denies exec by refusing node:child_process at the import
        # boundary: the old execFileSync(OMNICLI_BIN, ...) probe can no longer
        # even load, so assert the refusal for require, static and dynamic
        # import. worker_threads is refused by the same boundary.
        self._assert_strict_import_refused(
            'const cp = require("node:child_process"); console.log(typeof cp);',
            "node:child_process")
        self._assert_strict_import_refused(
            'import { execFileSync } from "node:child_process";',
            "node:child_process")
        self._assert_strict_import_refused(
            'export const marker = 1; const cp = await import("node:child_process");',
            "node:child_process")
        self._assert_strict_import_refused(
            'const wt = require("node:worker_threads"); console.log(typeof wt);',
            "node:worker_threads")

        # Non-strict (write) behaviour: child_process stays available when the
        # import boundary is not strict.
        with tempfile.TemporaryDirectory() as tmp:
            write, w_proc = self._code(Path(tmp), """
const cp = require("node:child_process");
console.log("child_process ok", typeof cp.execFileSync);
""", "--sandbox", "write")
        self.assertEqual(w_proc.returncode, 0, write["stderr"])
        self.assertIn("child_process ok function", write["stdout"])

    @needs_sandbox
    def test_strict_mode_blocks_the_network_write_mode_allows(self):
        # Slice 1 refuses node:net at the strict VM import boundary, so an
        # OS-level connect probe only runs in write mode. Strict mode is
        # expected to die at import time with stderr naming node:net.
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
                writable, w_proc = self._code(Path(tmp), code, "--sandbox", "write")
                strict, s_proc = self._code(Path(tmp), code, "--sandbox", "strict")
        finally:
            listener.close()

        # Non-strict (write): node:net imports and reaches the local listener.
        self.assertEqual(w_proc.returncode, 0, writable["stderr"])
        self.assertEqual(writable["sandbox"], "write")
        self.assertIn("network: open", writable["stdout"])
        self.assertNotIn("network: blocked", writable["stdout"])

        # Strict: the import is refused, so no connect probe output appears.
        self.assertNotEqual(s_proc.returncode, 0)
        self.assertEqual(strict["sandbox"], "strict")
        self.assertNotEqual(strict["exit_code"], 0)
        self.assertNotIn("network:", strict["stdout"])
        self.assertIn("omnicli: node:net is blocked in the strict sandbox",
                      strict["stderr"])

        # Static and dynamic import forms are refused by the same boundary.
        self._assert_strict_import_refused(
            'import net from "node:net"; console.log(typeof net);', "node:net")
        self._assert_strict_import_refused(
            'export const marker = 1; const net = await import("node:net");',
            "node:net")

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

    def test_quiet_suppresses_status_and_prints_result_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            quiet = self._exec_plain(
                "-c", 'console.log("loud"); result({ok:true,tool:"q",proof:"p",data:{n:1}})',
                "--quiet", "--sandbox", "none", cwd=tmp,
            )
            self.assertEqual(quiet.returncode, 0, quiet.stderr)
            self.assertNotIn("⚡ [exec]", quiet.stderr)
            parsed = json.loads(quiet.stdout)
            self.assertEqual(parsed, {"ok": True, "tool": "q", "proof": "p", "data": {"n": 1}})
            self.assertNotIn("loud", quiet.stdout)

            # Negative control: without --quiet the status line is present.
            loud = self._exec_plain("-c", 'console.log("loud")',
                                    "--sandbox", "none", cwd=tmp)
            self.assertEqual(loud.returncode, 0, loud.stderr)
            self.assertIn("⚡ [exec]", loud.stderr)
            self.assertIn("loud", loud.stdout)

    def test_quiet_with_json_matches_json_report(self):
        code = 'result({ok:true,tool:"p",proof:"g",data:{n:2}})'
        with tempfile.TemporaryDirectory() as tmp:
            q_report, q_proc = self._code(Path(tmp), code, "--quiet", "--sandbox", "none")
            n_report, n_proc = self._code(Path(tmp), code, "--sandbox", "none")
        self.assertEqual(q_proc.returncode, 0, q_proc.stderr)
        self.assertEqual(n_proc.returncode, 0, n_proc.stderr)
        for report in (q_report, n_report):
            report.pop("seconds", None)
        self.assertEqual(q_report, n_report)

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
