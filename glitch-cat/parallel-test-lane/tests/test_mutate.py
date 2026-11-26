#!/usr/bin/env python3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mutate

MUTATE = Path(__file__).resolve().parents[1] / "scripts" / "mutate.py"

MODULE = '''\
def score(n):
    if n > 10:
        return "high"
    if n and n < 5:
        return "low"
    return "mid"
'''

WEAK = '''
import unittest
from score import score

class T(unittest.TestCase):
    def test_high(self):
        self.assertEqual(score(11), "high")
'''

THOROUGH = '''
import unittest
from score import score

class T(unittest.TestCase):
    def test_all(self):
        self.assertEqual(score(11), "high")
        self.assertEqual(score(10), "mid")
        self.assertEqual(score(4), "low")
        self.assertEqual(score(5), "mid")
        self.assertEqual(score(0), "mid")
'''

CMD = f"{sys.executable} -m unittest test_score"


def case(root, test_src):
    root = Path(root)
    (root / "score.py").write_text(MODULE)
    (root / "test_score.py").write_text(textwrap.dedent(test_src))
    return root


def cli(cwd, *args):
    return subprocess.run([sys.executable, str(MUTATE), *args], cwd=cwd, capture_output=True, text=True)


class MutateTest(unittest.TestCase):
    def test_plan_covers_all_four_mutations(self):
        with tempfile.TemporaryDirectory() as d:
            entries = mutate.plan(case(d, WEAK) / "score.py")
            texts = [t for _, t in entries]
            self.assertEqual(len(entries), 8)
            self.assertTrue(any("<=" in t for t in texts))       # comparison flip
            self.assertTrue(any(">= 5" in t for t in texts))     # comparison flip
            self.assertTrue(any("11" in t for t in texts))       # integer bump
            self.assertTrue(any("6" in t for t in texts))        # integer bump
            self.assertTrue(any(" or " in t for t in texts))     # and -> or
            self.assertEqual(sum(t == "" for t in texts), 3)     # deletes
            self.assertTrue(all(t != MODULE.splitlines(keepends=True)[ln - 1] for ln, t in entries))

    def test_weak_test_leaves_at_least_one_survivor(self):
        with tempfile.TemporaryDirectory() as d:
            root = case(d, WEAK)
            results = mutate.check(root / "score.py", CMD, limit=8)
            self.assertEqual(len(results), 8)
            self.assertTrue(any(not r["killed"] for r in results), msg=results)
            self.assertEqual((root / "score.py").read_text(), MODULE)

    def test_thorough_test_kills_every_mutant(self):
        with tempfile.TemporaryDirectory() as d:
            root = case(d, THOROUGH)
            results = mutate.check(root / "score.py", CMD, limit=8)
            survivors = [r for r in results if not r["killed"]]
            self.assertEqual(survivors, [], msg=f"survivors: {survivors}")
            self.assertEqual((root / "score.py").read_text(), MODULE)

    def test_cli_exits_1_on_survivor(self):
        with tempfile.TemporaryDirectory() as d:
            root = case(d, WEAK)
            res = cli(root, "score.py", "--test", CMD, "--limit", "8")
            self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
            self.assertIn("survived", res.stderr)

    def test_cli_exits_0_when_all_mutants_die(self):
        with tempfile.TemporaryDirectory() as d:
            root = case(d, THOROUGH)
            res = cli(root, "score.py", "--test", CMD, "--limit", "8")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("0 survived", res.stdout)

    def test_cli_allow_survivors_restores_reporting_behaviour(self):
        with tempfile.TemporaryDirectory() as d:
            root = case(d, WEAK)
            res = cli(root, "score.py", "--test", CMD, "--limit", "8", "--allow-survivors")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("survived", res.stdout)

    def test_cli_refuses_empty_mutation_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "clean.py").write_text("# no mutations here\n", encoding="utf-8")
            res = cli(root, "clean.py", "--test", "true")
            self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
            self.assertIn("no mutations", res.stderr)

    def test_cli_rejects_limit_below_one(self):
        with tempfile.TemporaryDirectory() as d:
            root = case(d, THOROUGH)
            res = cli(root, "score.py", "--test", CMD, "--limit", "0")
            self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
            self.assertEqual((root / "score.py").read_text(), MODULE)

    def test_plan_is_language_agnostic(self):
        source = (
            "// x == 1 is a comment\n"
            "const a = x && y;\n"
            "/* || block */\n"
            "* mul line\n"
            "let n = 1;\n"
            'throw new Error("no");\n'
            "<!-- html == comment -->\n"
            "-- sql || comment\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "app.js"
            path.write_text(source, encoding="utf-8")
            entries = mutate.plan(path)
            texts = [t for _, t in entries]
            self.assertEqual(sorted({ln for ln, _ in entries}), [2, 5, 6])
            self.assertTrue(any("||" in t for t in texts))
            self.assertTrue(any("2" in t for t in texts))
            self.assertEqual(texts.count(""), 1)  # only the throw line is deleted

    def test_check_runs_the_test_command_in_the_given_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "pkg").mkdir()
            (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (root / "pkg" / "score.py").write_text(MODULE, encoding="utf-8")
            weak = WEAK.replace("from score import score", "from pkg.score import score")
            (root / "test_score.py").write_text(textwrap.dedent(weak), encoding="utf-8")
            (root / "MARKER").write_text("root\n", encoding="utf-8")
            cmd = f"test -f MARKER && {CMD}"

            from_root = mutate.check(root / "pkg" / "score.py", cmd, limit=8, cwd=root)
            self.assertTrue(any(not r["killed"] for r in from_root), msg=from_root)

            from_file_dir = mutate.check(root / "pkg" / "score.py", cmd, limit=8)
            self.assertTrue(all(r["killed"] for r in from_file_dir), msg=from_file_dir)


if __name__ == "__main__":
    unittest.main()
