"""End-to-end gates for the apiv-loop align/plan steps.

Each case drives the real apiv_loop.py as a subprocess against an isolated
temporary directory, so gate behavior is verified without mocking internals.

Run:
    cd orchestration/omnicli && python3 -m unittest tests.test_apiv_align_gates -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "glitch-cat" / "apiv-loop" / "scripts" / "apiv_loop.py"


class ApivAlignGateTests(unittest.TestCase):
    def run_cli(self, cwd, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=60,
        )

    def read_meta(self, run_dir):
        return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))

    def test_align_scaffolds_plan_and_meta_with_aligned_phase(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proc = self.run_cli(root, "align", "r")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            run_dir = root / ".apiv" / "r"
            self.assertTrue((run_dir / "plan.md").is_file())
            meta_path = run_dir / "meta.json"
            self.assertTrue(meta_path.is_file())
            meta = self.read_meta(run_dir)
            self.assertEqual(meta["phase"], "ALIGNED")
            self.assertTrue(meta["aligned"])

    def test_plan_refuses_when_align_never_ran(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proc = self.run_cli(root, "plan", "r")
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")
            self.assertIn("align", proc.stderr)

    def test_second_align_increments_realignments_and_records_reason(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / ".apiv" / "r"
            proc = self.run_cli(root, "align", "r")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            before = self.read_meta(run_dir)["realignments"]
            proc = self.run_cli(root, "align", "r", "--reason", "scope changed")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            meta = self.read_meta(run_dir)
            self.assertEqual(meta["realignments"], before + 1)
            self.assertEqual(meta["realign_count"], before + 1)
            self.assertEqual(meta["realign_reason"], "scope changed")


if __name__ == "__main__":
    unittest.main()
