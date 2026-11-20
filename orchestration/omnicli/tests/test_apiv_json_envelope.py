"""End-to-end tests for the apiv-loop --json machine-readable envelope.

Each case drives the real apiv_loop.py as a subprocess against an isolated
temporary directory, so envelope behavior is locked in without mocking internals.

Run:
    cd orchestration/omnicli && python3 -m unittest tests.test_apiv_json_envelope -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "glitch-cat" / "apiv-loop" / "scripts" / "apiv_loop.py"


class ApivJsonEnvelopeTests(unittest.TestCase):
    def run_cli(self, cwd, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=60,
        )

    def envelope(self, proc):
        return json.loads(proc.stdout)

    def ok(self, data, proc):
        if "ok" in data:
            return bool(data["ok"])
        return data.get("exit") == 0 and proc.returncode == 0

    def phase(self, data):
        if "phase" in data:
            return data["phase"]
        return " ".join(data.get("output", []))

    def error(self, data, proc):
        if "error" in data:
            return data["error"]
        if "message" in data:
            return data["message"]
        return " ".join(data.get("output", [])) or proc.stderr.strip()

    def test_align_json_returns_ok_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            proc = self.run_cli(Path(td), "--json", "align", "r")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = self.envelope(proc)
            self.assertIsInstance(data, dict)
            self.assertTrue(self.ok(data, proc))
            self.assertIn("ALIGNED", self.phase(data))
            self.assertEqual(data.get("command"), "align")

    def test_verify_json_without_dispatch_returns_error_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            proc = self.run_cli(Path(td), "--json", "verify", "r")
            self.assertNotEqual(proc.returncode, 0)
            data = self.envelope(proc)
            self.assertIsInstance(data, dict)
            self.assertFalse(self.ok(data, proc))
            self.assertTrue(self.error(data, proc))
            self.assertEqual(data.get("command"), "verify")

    def test_plan_json_after_align_returns_ok_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            aligned = self.run_cli(root, "--json", "align", "r")
            self.assertEqual(aligned.returncode, 0, aligned.stderr)
            self.assertTrue(self.ok(self.envelope(aligned), aligned))
            proc = self.run_cli(root, "--json", "plan", "r")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = self.envelope(proc)
            self.assertTrue(self.ok(data, proc))
            self.assertEqual(data.get("command"), "plan")
            self.assertIn("PLANNED", self.phase(data))


if __name__ == "__main__":
    unittest.main()
