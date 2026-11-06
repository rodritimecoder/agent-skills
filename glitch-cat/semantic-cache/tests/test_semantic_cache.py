#!/usr/bin/env python3
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.append(str(SCRIPTS))
from cache_engine import LocalEmbedder, SemanticCache, cosine_similarity


class TestSemanticCache(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="test_cache_")
        self.db_path = Path(self.td) / "cache.db"
        self.cache = SemanticCache(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _use_offline_embedder(self):
        """Force the deterministic 128d hash space so scores are reproducible."""
        self.cache.embedder = LocalEmbedder(endpoint="http://127.0.0.1:1/v1/embeddings")
        return self.cache.embedder

    def test_01_cache_hit_identical(self):
        q = "How do I configure git worktrees for parallel agents?"
        ans = "Use 'git worktree add <path> -b <branch>' and pre-claim file lines."
        self.cache.set(q, ans)

        res = self.cache.get(q, threshold=0.90)
        self.assertTrue(res["hit"])
        self.assertEqual(res["answer"], ans)
        self.assertGreaterEqual(res["similarity"], 0.95)
        print("  ✓ identical hit · verified")

    def test_02_cache_hit_paraphrase(self):
        q1 = "How do I configure git worktrees for parallel agents?"
        ans = "Use 'git worktree add <path> -b <branch>' and pre-claim file lines."
        self.cache.set(q1, ans)

        q2 = "How to configure git worktrees for parallel subagents?"
        res = self.cache.get(q2, threshold=0.75)
        if self.cache.embedder.last_source != "endpoint":
            self.skipTest(
                "paraphrase recall is a property of the embedding model on :8087; "
                f"the engine fell back to {self.cache.embedder.last_source} "
                f"and scored {res.get('best_similarity', 0):.3f} against a 0.75 threshold"
            )
        self.assertTrue(res["hit"])
        self.assertEqual(res["answer"], ans)
        print("  ✓ paraphrase hit · verified")

    def test_03_cache_miss_unrelated(self):
        q1 = "How do I configure git worktrees for parallel agents?"
        ans = "Use 'git worktree add <path> -b <branch>' and pre-claim file lines."
        self.cache.set(q1, ans)

        q2 = "What is the capital city of Australia?"
        res = self.cache.get(q2, threshold=0.75)
        self.assertFalse(res["hit"])
        print("  ✓ unrelated miss · verified")

    def test_04_stats_and_purge(self):
        self.cache.set("q1", "a1")
        self.cache.set("q2", "a2")
        self.cache.get("q1")
        st = self.cache.stats()
        self.assertEqual(st["total_entries"], 2)
        self.assertEqual(st["total_cache_hits"], 1)

        purged = self.cache.purge()
        self.assertEqual(purged, 2)
        st2 = self.cache.stats()
        self.assertEqual(st2["total_entries"], 0)
        print("  ✓ stats and purge · verified")

    def test_05_fallback_embedding_survives_a_restart(self):
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from cache_engine import LocalEmbedder\n"
            "e = LocalEmbedder(endpoint='http://127.0.0.1:1/v1/embeddings')\n"
            "v = e.embed('git worktrees for parallel agents')\n"
            "print(','.join(f'{x:.6f}' for x in v))\n"
        ) % str(SCRIPTS)
        outs = []
        for _ in range(2):
            proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            outs.append(proc.stdout.strip())
        self.assertEqual(outs[0], outs[1], "the fallback vector changed between processes")
        self.assertEqual(len(outs[0].split(",")), 128)
        print("  ✓ fallback embedding is identical across processes")

    # --- judge gate -------------------------------------------------------
    #
    # The collision the judge exists for: "Celsius to Fahrenheit" and
    # "Fahrenheit to Celsius" are the same bag of words, so cosine cannot tell
    # them apart. Similarity only nominates a candidate; the judge decides.

    def test_06_judge_rejects_opposite_unit_conversion(self):
        self._use_offline_embedder()
        cached_q = "Celsius to Fahrenheit"
        cached_a = "Multiply by 9/5 and add 32: 100 C = 212 F."
        self.cache.set(cached_q, cached_a)

        calls = []

        def judge(query, cached_query, answer):
            calls.append((query, cached_query, answer))
            return False

        res = self.cache.get("Fahrenheit to Celsius", threshold=0.90, judge=judge)

        # The candidate cleared the threshold on similarity alone...
        self.assertGreaterEqual(res["similarity"], 0.90)
        # ...and the judge still turned it into a miss, naming the id it refused.
        self.assertFalse(res["hit"])
        self.assertEqual(res["reason"], "judge_rejected")
        with sqlite3.connect(self.db_path) as conn:
            row_ids = [r[0] for r in conn.execute("SELECT id FROM semantic_cache")]
        self.assertIn(res["rejected_id"], row_ids)
        self.assertEqual(res["matched_query"], cached_q)
        self.assertNotIn("answer", res, "a rejected candidate must not be served")
        self.assertEqual(calls, [("Fahrenheit to Celsius", cached_q, cached_a)])
        # A refusal is not a hit: no counter moves, so a rejected row stays cold.
        self.assertEqual(self.cache.stats()["total_cache_hits"], 0)
        print("  ✓ judge rejected the C->F / F->C collision · verified")

    def test_07_judge_accepts_true_rewording(self):
        self._use_offline_embedder()
        cached_q = "Celsius to Fahrenheit"
        cached_a = "Multiply by 9/5 and add 32: 100 C = 212 F."
        self.cache.set(cached_q, cached_a)

        calls = []

        def judge(query, cached_query, answer):
            calls.append((query, cached_query, answer))
            return True

        q2 = "How do I convert Celsius to Fahrenheit?"
        res = self.cache.get(q2, threshold=0.50, judge=judge)

        self.assertTrue(res["hit"])
        self.assertEqual(res["answer"], cached_a)
        self.assertEqual(res["matched_query"], cached_q)
        self.assertEqual(res["hit_count"], 1)
        self.assertEqual(calls, [(q2, cached_q, cached_a)])
        self.assertEqual(self.cache.stats()["total_cache_hits"], 1)
        print("  ✓ judge accepted a genuine rewording · verified")

    def test_08_judge_not_called_without_a_candidate(self):
        self._use_offline_embedder()
        self.cache.set("Celsius to Fahrenheit", "Multiply by 9/5 and add 32.")

        calls = []

        def judge(query, cached_query, answer):
            calls.append((query, cached_query, answer))
            return True

        # No row clears the threshold at all.
        res = self.cache.get("What is the capital city of Australia?", threshold=0.90, judge=judge)
        self.assertFalse(res["hit"])
        self.assertNotIn("reason", res)
        self.assertNotIn("rejected_id", res)

        # A row exists and scores above zero, but still sits below the threshold.
        res_low = self.cache.get("Convert Kelvin to Rankine", threshold=0.95, judge=judge)
        self.assertFalse(res_low["hit"])
        self.assertGreater(res_low["best_similarity"], 0.0)
        self.assertLess(res_low["best_similarity"], 0.95)
        self.assertNotIn("reason", res_low)

        self.assertEqual(calls, [], "the judge must not run when nothing clears the threshold")
        print("  ✓ judge not called on clean miss · verified")

    def test_09_get_stays_backwards_compatible(self):
        self.cache.set("q", "a")
        # Legacy two-argument positional form, no judge.
        self.assertTrue(self.cache.get("q", 0.85)["hit"])
        # Judge is the optional third positional argument.
        self.assertTrue(self.cache.get("q", 0.85, lambda query, cached, answer: True)["hit"])
        self.assertFalse(self.cache.get("q", 0.85, lambda query, cached, answer: False)["hit"])
        print("  ✓ get() signature stays backwards compatible")


if __name__ == "__main__":
    print("\n🧪 Running Semantic Cache Test Suite:")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSemanticCache)
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
