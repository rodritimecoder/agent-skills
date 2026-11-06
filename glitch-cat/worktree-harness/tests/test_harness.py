#!/usr/bin/env python3
"""
test_harness.py — Grounded tests for worktree-harness
Proves two things the skill claims: a worker branch is only integrated after
GATE_PASSED, and --verify is a real second gate beside --test.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent / "scripts" / "harness.py"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def harness(cwd, *args):
    return subprocess.run([sys.executable, str(HARNESS), *args], cwd=cwd, capture_output=True, text=True)


class TestWorktreeHarness(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="test_harness_"))
        self.repo = self.td / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "init")

        res = harness(self.repo, "start", "--goal", "verify gates", "--workers", "w1", "w2", "--run-name", "run_t")
        self.assertEqual(res.returncode, 0, res.stderr)

        for worker in ("w1", "w2"):
            tree = self.repo / ".harness" / "runs" / "run_t" / "worktrees" / worker
            (tree / f"{worker}.txt").write_text(f"{worker}\n", encoding="utf-8")
            git(tree, "add", ".")
            git(tree, "commit", "-m", f"{worker} change")

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_gate_and_integrate(self):
        fail = harness(self.repo, "gate", "--run-id", "run_t", "--worker", "w1", "--test", "true", "--verify", "test -f missing.txt")
        self.assertEqual(fail.returncode, 0, fail.stderr)
        manifest = json.loads((self.repo / ".harness" / "runs" / "run_t" / "manifest.json").read_text())
        self.assertEqual(manifest["workers"]["w1"]["gate"]["status"], "GATE_FAILED")
        self.assertEqual([c["label"] for c in manifest["workers"]["w1"]["gate"]["checks"]], ["test", "verify"])

        refused = harness(self.repo, "integrate", "--run-id", "run_t")
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn("no passing gate", refused.stdout.lower())

        pass_w1 = harness(self.repo, "gate", "--run-id", "run_t", "--worker", "w1", "--test", "true", "--verify", "test -f w1.txt")
        self.assertEqual(pass_w1.returncode, 0, pass_w1.stderr)
        pass_w2 = harness(self.repo, "gate", "--run-id", "run_t", "--worker", "w2", "--test", "true")
        self.assertEqual(pass_w2.returncode, 0, pass_w2.stderr)

        integrated = harness(self.repo, "integrate", "--run-id", "run_t", "--test", "true", "--verify", "test -f w1.txt -o -f w2.txt")
        self.assertEqual(integrated.returncode, 0, integrated.stdout + integrated.stderr)
        merged = git(self.repo, "show", "harness/run_t/integration:w1.txt")
        self.assertEqual(merged.stdout.strip(), "w1", integrated.stdout + integrated.stderr)
        merged2 = git(self.repo, "show", "harness/run_t/integration:w2.txt")
        self.assertEqual(merged2.stdout.strip(), "w2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
