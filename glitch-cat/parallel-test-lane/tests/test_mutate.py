#!/usr/bin/env python3
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mutate

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


if __name__ == "__main__":
    unittest.main()
