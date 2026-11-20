"""Verify-level gate tests for the apiv-loop CLI.

Each case drives apiv_loop.py as a subprocess against an isolated .apiv/
directory so the verify gate behavior is locked in without mocking internals.

Run:
    cd orchestration/omnicli && python3 -m unittest tests.test_apiv_verify_gates -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "glitch-cat" / "apiv-loop" / "scripts" / "apiv_loop.py"


class ApivVerifyGatesTests(unittest.TestCase):
    def run_cli(self, cwd, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=60,
        )

    def dispatched_run(self, root):
        run_dir = root / ".apiv" / "r"
        run_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "name": "r",
            "realignments": 0,
            "realign_count": 0,
            "aligned": True,
            "planned": True,
            "dispatched": True,
            "phase": "DISPATCHED",
        }
        (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (run_dir / "brief_1.md").write_text("# Brief\n", encoding="utf-8")
        return run_dir

    def read_meta(self, run_dir):
        return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))

    def test_required_level_failure_routes_back_to_align(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self.dispatched_run(root)
            proc = self.run_cli(
                root, "verify", "r",
                "--lint", "fail",
                "--unit", "pass",
                "--integration", "pass",
            )
            self.assertNotEqual(proc.returncode, 0, proc.stderr)
            meta = self.read_meta(run_dir)
            self.assertEqual(meta["phase"], "ALIGNED")
            self.assertTrue(meta["needs_realign"])
            self.assertIs(meta["full_pass"], False)

    def test_skipped_required_level_is_not_full_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self.dispatched_run(root)
            proc = self.run_cli(
                root, "verify", "r",
                "--lint", "skip",
                "--unit", "pass",
                "--integration", "pass",
            )
            self.assertNotEqual(proc.returncode, 0, proc.stderr)
            meta = self.read_meta(run_dir)
            self.assertIs(meta["full_pass"], False)
            self.assertEqual(meta["verify_levels"]["lint"]["status"], "skip")

    def test_optional_levels_skipped_still_full_pass_and_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = self.dispatched_run(root)
            proc = self.run_cli(
                root, "verify", "r",
                "--lint", "pass",
                "--unit", "pass",
                "--integration", "pass",
                "--walkthrough", "skip",
                "--tours", "skip",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            meta = self.read_meta(run_dir)
            self.assertIs(meta["full_pass"], True)
            self.assertEqual(meta["phase"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
