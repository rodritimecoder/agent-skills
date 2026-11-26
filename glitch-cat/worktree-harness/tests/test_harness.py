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
import textwrap
import unittest
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent / "scripts" / "harness.py"

SCORE = '''\
def score(n):
    if n > 10:
        return "high"
    if n and n < 5:
        return "low"
    return "mid"
'''

WEAK_TEST = '''
import unittest
from pkg.score import score

class T(unittest.TestCase):
    def test_high(self):
        self.assertEqual(score(11), "high")
'''

THOROUGH_TEST = '''
import unittest
from pkg.score import score

class T(unittest.TestCase):
    def test_all(self):
        self.assertEqual(score(11), "high")
        self.assertEqual(score(10), "mid")
        self.assertEqual(score(4), "low")
        self.assertEqual(score(5), "mid")
        self.assertEqual(score(0), "mid")
'''

MUTATION_TEST_CMD = f"test -f ROOT_MARKER && {sys.executable} -m unittest test_score"


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

    def _gate(self, worker):
        manifest = json.loads((self.repo / ".harness" / "runs" / "run_t" / "manifest.json").read_text())
        return manifest["workers"][worker]["gate"]

    def _write_mutation_fixture(self, test_src=WEAK_TEST, worker="w2"):
        tree = self.repo / ".harness" / "runs" / "run_t" / "worktrees" / worker
        (tree / "pkg").mkdir(exist_ok=True)
        (tree / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (tree / "pkg" / "score.py").write_text(SCORE, encoding="utf-8")
        (tree / "test_score.py").write_text(textwrap.dedent(test_src), encoding="utf-8")
        (tree / "ROOT_MARKER").write_text("root\n", encoding="utf-8")
        return tree

    def test_gate_fails_on_surviving_mutant(self):
        self._write_mutation_fixture()
        res = harness(self.repo, "gate", "--run-id", "run_t", "--worker", "w2",
                      "--test", MUTATION_TEST_CMD, "--mutate", "pkg/score.py")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

        gate = self._gate("w2")
        self.assertEqual(gate["status"], "GATE_FAILED")
        self.assertIn("mutation", [c["label"] for c in gate["checks"]])
        self.assertTrue(gate["baseline_passed"])
        self.assertEqual(gate["mutate"], "pkg/score.py")
        self.assertEqual(gate["mutants_run"], 8)
        self.assertGreaterEqual(len(gate["survivors"]), 1)

    def test_gate_passes_when_baseline_green_and_all_mutants_killed(self):
        self._write_mutation_fixture(test_src=THOROUGH_TEST)
        res = harness(self.repo, "gate", "--run-id", "run_t", "--worker", "w2",
                      "--test", MUTATION_TEST_CMD, "--mutate", "pkg/score.py")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

        gate = self._gate("w2")
        self.assertEqual(gate["status"], "GATE_PASSED")
        self.assertTrue(gate["baseline_passed"])
        self.assertEqual(gate["mutants_run"], 8)
        self.assertEqual(gate["survivors"], [])

    def test_gate_fails_on_broken_baseline_even_when_every_mutant_dies(self):
        self._write_mutation_fixture()
        res = harness(self.repo, "gate", "--run-id", "run_t", "--worker", "w2",
                      "--test", "exit 1", "--mutate", "pkg/score.py")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

        gate = self._gate("w2")
        self.assertEqual(gate["status"], "GATE_FAILED")
        self.assertFalse(gate["baseline_passed"])
        self.assertEqual(gate["mutants_run"], 0)
        self.assertEqual(gate["survivors"], [])
        mutation = next(c for c in gate["checks"] if c["label"] == "mutation")
        self.assertFalse(mutation["passed"])

    def test_gate_refuses_mutate_without_test(self):
        self._write_mutation_fixture()
        res = harness(self.repo, "gate", "--run-id", "run_t", "--worker", "w2",
                      "--mutate", "pkg/score.py")
        self.assertNotEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("--mutate needs --test", res.stderr)

    def test_gate_refuses_mutate_path_outside_worktree(self):
        self._write_mutation_fixture()
        absolute = harness(self.repo, "gate", "--run-id", "run_t", "--worker", "w2",
                           "--test", "true", "--mutate", str(self.repo / "README.md"))
        self.assertNotEqual(absolute.returncode, 0, absolute.stdout + absolute.stderr)
        self.assertIn("absolute", absolute.stderr)

        escaping = harness(self.repo, "gate", "--run-id", "run_t", "--worker", "w2",
                           "--test", "true", "--mutate", "../manifest.json")
        self.assertNotEqual(escaping.returncode, 0, escaping.stdout + escaping.stderr)
        self.assertIn("escapes", escaping.stderr)

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
