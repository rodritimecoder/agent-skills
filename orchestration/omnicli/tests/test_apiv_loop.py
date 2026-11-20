"""End-to-end tests for the apiv-loop CLI gates.

Each case drives the real apiv_loop.py as a subprocess against an isolated
.apiv/ directory, so gate behavior is locked in without mocking internals.

Run:
    cd orchestration/omnicli && python3 -m unittest tests.test_apiv_loop -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "glitch-cat" / "apiv-loop" / "scripts" / "apiv_loop.py"

LEVELS = ("lint", "unit", "integration", "walkthrough", "tours")


class ApivLoopCase(unittest.TestCase):
    def run_cli(self, cwd, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=60,
        )

    def write_meta(self, root, **fields):
        run_dir = root / ".apiv" / "r"
        run_dir.mkdir(parents=True, exist_ok=True)
        meta = {"name": "r", "realignments": 0, "realign_count": 0}
        meta.update(fields)
        (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return run_dir

    def read_meta(self, run_dir):
        return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))

    def dispatched_run(self, root):
        run_dir = self.write_meta(
            root,
            aligned=True,
            planned=True,
            dispatched=True,
            phase="DISPATCHED",
        )
        (run_dir / "brief_1.md").write_text("# Brief\n", encoding="utf-8")
        return run_dir


class ApivLoopTests(ApivLoopCase):
    def test_verify_refuses_without_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_meta(root, dispatched=False)
            proc = self.run_cli(root, "verify", "r")
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")
            self.assertIn("no dispatch recorded", proc.stderr)

    def test_verify_required_level_failure_routes_back_to_align(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self.dispatched_run(root)
            before = self.read_meta(run_dir)["realignments"]
            proc = self.run_cli(root, "verify", "r", "--lint", "fail")
            self.assertNotEqual(proc.returncode, 0)
            meta = self.read_meta(run_dir)
            self.assertEqual(meta["phase"], "ALIGNED")
            self.assertTrue(meta["needs_realign"])
            self.assertTrue(meta["verify_failed"])
            self.assertEqual(meta["realignments"], before + 1)

    def test_realign_cap_refuses_third(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self.write_meta(
                root, aligned=True, realignments=2, realign_count=2
            )
            proc = self.run_cli(root, "align", "r")
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("re-alignment cap", proc.stderr)
            proc = self.run_cli(root, "align", "r", "--force", "--reason", "test")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(self.read_meta(run_dir)["realignments"], 3)

    def test_bare_verify_records_full_pass_false(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self.dispatched_run(root)
            proc = self.run_cli(root, "verify", "r")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            meta = self.read_meta(run_dir)
            self.assertTrue(meta["verified"])
            self.assertIs(meta["full_pass"], False)
            for level in LEVELS:
                self.assertEqual(meta["verify_levels"][level]["status"], "skip")

    def test_full_pass_levels(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self.dispatched_run(root)
            proc = self.run_cli(
                root,
                "verify", "r",
                "--lint", "pass",
                "--unit", "pass",
                "--integration", "pass",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            meta = self.read_meta(run_dir)
            self.assertIs(meta["full_pass"], True)
            self.assertEqual(meta["phase"], "VERIFIED")

    def test_dispatch_return_vs_file_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self.write_meta(
                root, aligned=True, planned=True, dispatched=False, phase="PLANNED"
            )
            (run_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
            proc = self.run_cli(
                root, "dispatch", "r", "--files", "target.txt", "--command", "true"
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("no changed files", proc.stderr)
            proc = self.run_cli(
                root,
                "dispatch", "r",
                "--files", "target.txt",
                "--command", "printf x > target.txt",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            meta = self.read_meta(run_dir)
            self.assertEqual(meta["return_vs_file"]["changed"], ["target.txt"])


if __name__ == "__main__":
    unittest.main()
