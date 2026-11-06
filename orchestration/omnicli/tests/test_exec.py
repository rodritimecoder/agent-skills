"""Tests for the plan executor: generated bindings and `omnicli exec`."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from catalog import bindings, builder  # noqa: E402

OMNICLI = str(ROOT / "omnicli.py")


class TestBindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        con = builder.connect()
        builder.ensure_built(con, rebuild=True, with_contracts=True, progress=False)
        con.close()

    def test_generated_module_exposes_the_plan_api(self):
        con = builder.connect()
        source = bindings.module_source(con)
        for symbol in ("def search(", "def describe(", "def invoke(", "def output(",
                       "def spec(", "TOOL_IDS", "SIGNATURES", "TOOLS = {"):
            self.assertIn(symbol, source)

    def test_typed_surface_recovers_required_args_and_choices(self):
        con = builder.connect()
        with tempfile.TemporaryDirectory() as tmp:
            module = self._load(con, Path(tmp))
            line = module.SIGNATURES.get("academic-icm/scripts/academic_icm:zoom", "")
            self.assertTrue(line.startswith("zoom(url: str"), line)
            self.assertIn("Literal['md', 'vtt', 'txt', 'all']", line)
            self.assertIn("video: bool = False", line)

    def test_typed_surface_does_not_shadow_the_plan_api(self):
        con = builder.connect()
        with tempfile.TemporaryDirectory() as tmp:
            module = self._load(con, Path(tmp))
            self.assertTrue(callable(module.search))
            self.assertNotIn("search", [row["fn"] for row in module.SPEC])

    def test_spec_filters_without_loading_the_catalog(self):
        con = builder.connect()
        with tempfile.TemporaryDirectory() as tmp:
            module = self._load(con, Path(tmp))
            rows = module.spec(grep="zoom")
            self.assertTrue(rows)
            self.assertTrue(all("zoom" in r["id"].lower() or "zoom" in r["summary"].lower()
                                for r in rows))
            self.assertEqual(module.spec(skill="zoom-recorder")[0]["skill"], "zoom-recorder")
            self.assertEqual(len(module.spec(limit=3)), 3)

    def _load(self, con, out: Path):
        import importlib.util

        bindings.write(con, out)
        spec = importlib.util.spec_from_file_location("omnicli_tools_probe", out / "omnicli_tools.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_write_emits_an_importable_module(self):
        con = builder.connect()
        with tempfile.TemporaryDirectory() as tmp:
            out = bindings.write(con, Path(tmp))
            module = out / "omnicli_tools.py"
            self.assertTrue(module.is_file())
            loaded = self._load(con, Path(tmp))
            self.assertGreater(len(loaded.TOOL_IDS), 0)
            self.assertEqual(len(loaded.TOOLS), len(loaded.TOOL_IDS))


class TestExec(unittest.TestCase):
    def _exec(self, plan: Path, *extra: str) -> dict:
        proc = subprocess.run(
            [sys.executable, OMNICLI, "exec", str(plan), "--json", *extra],
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not installed")
    def test_one_plan_runs_several_tool_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.py"
            plan.write_text(
                "from omnicli_tools import search\n"
                "print(','.join(r['skill'] for r in search('audio transcription', limit=2)))\n",
                encoding="utf-8",
            )
            report = self._exec(plan)
            self.assertTrue(report["sandboxed"])
            self.assertEqual(report["tool_calls"], 1)
            self.assertIn("audiocpp", report["stdout"])

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not installed")
    def test_sandbox_blocks_writes_outside_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "probe.py"
            plan.write_text(
                "import os\n"
                "outside = '/home/omnicli-sandbox-probe.txt'\n"
                "try:\n"
                "    open(outside, 'w').write('x')\n"
                "    print('wrote')\n"
                "except OSError:\n"
                "    print('blocked')\n",
                encoding="utf-8",
            )
            report = self._exec(plan)
            self.assertEqual(report["stdout"].strip(), "blocked")
            self.assertFalse(os.path.exists("/home/omnicli-sandbox-probe.txt"))

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not installed")
    def test_strict_mode_masks_home_and_reaches_tools_only_through_the_bridge(self):
        sentinel = Path.home() / f".omnicli-probe-{os.getpid()}"
        sentinel.write_text("secret", encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "probe.py"
            plan.write_text(
                "import os\n"
                "from omnicli_tools import search\n"
                f"path = {str(sentinel)!r}\n"
                "try:\n"
                "    open(path).read(1)\n"
                "    print('home: readable')\n"
                "except OSError:\n"
                "    print('home: masked')\n"
                "print('search:', len(search('ocr', limit=1)))\n",
                encoding="utf-8",
            )
            try:
                readable = self._exec(plan, "--sandbox", "write")
                report = self._exec(plan, "--sandbox", "strict")
            finally:
                sentinel.unlink(missing_ok=True)
            self.assertIn("home: readable", readable["stdout"])
            self.assertIn("home: masked", report["stdout"])
            self.assertIn("search: 1", report["stdout"])
            self.assertEqual(report["sandbox"], "strict")
            self.assertGreaterEqual(report["bridge_calls"], 1)

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not installed")
    def test_strict_mode_blocks_the_network_that_write_mode_allows(self):
        import socket

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "probe.py"
            plan.write_text(
                "import socket\n"
                f"port = {port}\n"
                "sock = socket.socket()\n"
                "sock.settimeout(1)\n"
                "try:\n"
                "    sock.connect(('127.0.0.1', port))\n"
                "    print('network: open')\n"
                "except OSError:\n"
                "    print('network: blocked')\n"
                "finally:\n"
                "    sock.close()\n",
                encoding="utf-8",
            )
            try:
                writable = self._exec(plan, "--sandbox", "write")
                strict = self._exec(plan, "--sandbox", "strict")
            finally:
                listener.close()
            self.assertIn("network: open", writable["stdout"])
            self.assertIn("network: blocked", strict["stdout"])

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not installed")
    def test_strict_mode_refuses_verbs_outside_the_capability_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "probe.py"
            plan.write_text(
                "import os, subprocess\n"
                "shim = os.environ['OMNICLI_BIN']\n"
                "proc = subprocess.run([shim, 'exec', '--help'], capture_output=True, text=True)\n"
                "print('rc', proc.returncode)\n",
                encoding="utf-8",
            )
            report = self._exec(plan, "--sandbox", "strict")
            self.assertIn("rc 126", report["stdout"])
            self.assertIn("exec", report["bridge_denied"])


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
