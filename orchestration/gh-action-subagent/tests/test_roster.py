#!/usr/bin/env python3
"""Roster integrity tests. No network, no subscription required."""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))
import roster  # noqa: E402

SERVED_2026_10_25 = [
    "beam-free", "claude-haiku-5-5", "deepseek-v4-pro", "deepseek-v4.1-flash",
    "gemini-4-argon", "glm-5.2", "glm-5.3", "glm-5.3-flash", "gpt-5.6-luna",
    "gpt-6-luna", "grok-4.7", "hy3", "hy4-preview", "iceman-contributor-free",
    "kimi-k2.7-code", "kimi-k3", "kimi-k3.1-pro", "longcat-2.0",
    "mimo-v2.5", "mimo-v2.5-pro", "mimo-v2.6-flash", "mimo-v2.6-pro",
    "minimax-m3", "minimax-m3.1-flash", "muse-spark-1.2-contributor",
    "muse-spark-1.3-contributor", "qwen3.7-plus", "qwen3.8-flash",
    "qwen3.8-max", "step-5-preview",
]


class TestRoster(unittest.TestCase):
    def test_01_every_id_is_one_the_provider_served(self):
        curated = {m["id"] for m in roster.MODELS}
        self.assertEqual(curated, set(SERVED_2026_10_25))
        print("  ✓ every curated id was served by opencode-go on 2026-10-25")

    def test_02_no_id_carries_a_provider_prefix(self):
        for model in roster.MODELS:
            self.assertNotIn("/", model["id"], model["id"])
            self.assertNotIn(" ", model["id"], model["id"])
        print("  ✓ ids are bare, the provider prefix is added at call time")

    def test_03_tiers_roles_and_rungs_are_coherent(self):
        self.assertEqual({m["tier"] for m in roster.MODELS}, {1, 2, 3})
        for model in roster.MODELS:
            self.assertIn(model["role"], roster.ROLES, model["id"])
            self.assertIn(model["tier"], roster.TIERS, model["id"])
            self.assertIn(roster.rung(model), {"lure", "harpoon", "specialist", "free"}, model["id"])
            self.assertNotIn("rank", model, f"{model['id']} still carries a rank")
        print("  ✓ no ranks, and every tier, role and rung is legal")

    def test_03b_the_plan_page_documents_29_and_iceman_is_the_thirtieth(self):
        live_on_page = [m["id"] for m in roster.MODELS if roster.documented(m)]
        served_only = [m["id"] for m in roster.MODELS if not roster.documented(m)]
        self.assertEqual(len(live_on_page), 29)
        self.assertEqual(served_only, ["iceman-contributor-free"])
        print("  ✓ 29 documented models plus the undocumented free one")

    def test_04_limits_are_numbers_or_unlimited(self):
        for model in roster.MODELS:
            self.assertIsInstance(model["price_in"], (int, float), model["id"])
            self.assertIsInstance(model["price_out"], (int, float), model["id"])
            self.assertIsInstance(model["monthly"], (int, float, type(None)), model["id"])
            self.assertIsInstance(model["req_5h"], (int, type(None)), model["id"])
            if model["monthly"] is not None:
                self.assertGreater(model["monthly"], 0, model["id"])
        print("  ✓ every limit is a number, or explicitly unlimited")

    def test_05_free_models_cost_nothing_both_ways(self):
        for model in roster.MODELS:
            if model["price_in"] == 0:
                self.assertEqual(model["price_out"], 0, model["id"])
        print("  ✓ a free input price never hides a paid output price")

    def test_06_training_is_never_silently_unknown(self):
        for model in roster.MODELS:
            self.assertIn(model["trains"], (True, False, None), model["id"])
            if model["trains"] is not False:
                self.assertTrue(model["retention"], model["id"])
        print("  ✓ every model states whether it trains, and unknown is marked")

    def test_07_diff_catalog_reports_both_directions(self):
        live = list(SERVED_2026_10_25) + ["brand-new-model"]
        live.remove("claude-haiku-5-5")
        live.append("claude-haiku-5.5")
        missing, extra = roster.diff_catalog(live)
        self.assertEqual(missing, ["claude-haiku-5-5"])
        self.assertIn("brand-new-model", extra)
        self.assertIn("claude-haiku-5.5", extra)
        print("  ✓ drift is caught in both directions, including the dot/hyphen class")

    def test_08_table_shows_the_invocation_ready_id(self):
        table = roster.render_table([m for m in roster.MODELS if m["id"] == "claude-haiku-5-5"])
        self.assertIn("claude-haiku-5-5", table)
        self.assertIn("3,850", table)
        self.assertIn("$15", table)
        self.assertIn("harpoon", table)
        self.assertNotIn("Rank", table)
        print("  ✓ the table prints the bare id, the rung, the 5h estimate and the monthly cap")

    def test_08b_order_is_tier_then_price_not_a_quality_score(self):
        ordered = roster.ordered(roster.MODELS)
        self.assertEqual([m["tier"] for m in ordered], sorted(m["tier"] for m in ordered))
        for tier in (1, 2, 3):
            costs = [
                roster.cost_per_request(m)
                for m in ordered
                if m["tier"] == tier and roster.cost_per_request(m) is not None
            ]
            self.assertEqual(costs, sorted(costs), f"tier {tier} is not cheapest-first")
        lures = [m["id"] for m in ordered if m["tier"] == 2]
        self.assertEqual(lures[0], "mimo-v2.6-flash")
        self.assertEqual(roster.rung(next(m for m in ordered if m["id"] == "mimo-v2.6-flash")), "lure")
        self.assertEqual(roster.rung(next(m for m in ordered if m["id"] == "beam-free")), "free")
        print("  ✓ tiers group the ladder, price orders within a rung")

    def test_09_check_reports_a_missing_cli_without_crashing(self):
        original = roster.shutil.which
        roster.shutil.which = lambda name: None
        try:
            self.assertEqual(roster.cmd_check(), 1)
        finally:
            roster.shutil.which = original
        print("  ✓ --check degrades cleanly when the CLI is absent")

    def test_10_arithmetic_reproduces_the_published_estimates(self):
        computed = {
            m["id"]: roster.estimate_requests(m)
            for m in roster.MODELS
            if m["id"] in roster.PROFILES and m["req_5h"] is not None
        }
        close = [mid for mid, doc in ((m["id"], m["req_5h"]) for m in roster.MODELS if m["id"] in computed) if abs(computed[mid] - doc) / doc <= 0.02]
        self.assertGreaterEqual(len(close), 20, f"only {len(close)} models reconcile within 2%")
        print(f"  ✓ the token arithmetic reproduces {len(close)} of {len(computed)} published estimates within 2%")

    def test_11_the_calculator_never_overstates_capacity(self):
        for model in roster.MODELS:
            if model["req_5h"] is None or model["id"] not in roster.PROFILES:
                continue
            computed = roster.estimate_requests(model)
            self.assertLessEqual(
                computed,
                model["req_5h"] * 1.02,
                f"{model['id']}: calculator promises {computed} against a published {model['req_5h']}",
            )
        print("  ✓ sizing never promises more tasks than OpenCode publishes")

    def test_12_a_plan_splits_one_allowance_across_its_agents(self):
        rows = roster.plan_lanes([("deepseek-v4.1-flash", 1)], hours=5)
        alone = rows[0]["tasks_per_agent"]
        shared = roster.plan_lanes([("deepseek-v4.1-flash", 4)], hours=5)[0]
        self.assertEqual(shared["tasks_per_agent"], alone // 4)
        self.assertLessEqual(shared["tasks_total"], alone)
        self.assertLess(alone - shared["tasks_total"], 4)
        self.assertLessEqual(shared["spend"], shared["allowance"])
        print("  ✓ four agents share one allowance instead of quadrupling it")

    def test_13_a_longer_block_gets_a_bigger_share_up_to_the_monthly_cap(self):
        model = next(m for m in roster.MODELS if m["id"] == "glm-5.3-flash")
        self.assertAlmostEqual(roster.window_allowance(model, 5), 12.0)
        self.assertAlmostEqual(roster.window_allowance(model, 10), 24.0)
        self.assertAlmostEqual(roster.window_allowance(model, 500), model["monthly"])
        print("  ✓ the window grows with the block and stops at the monthly limit")

    def test_14_lane_specs_reject_duplicates_and_bad_counts(self):
        self.assertEqual(roster.parse_lanes("glm-5.3-flash:2,mimo-v2.6-flash"), [("glm-5.3-flash", 2), ("mimo-v2.6-flash", 1)])
        with self.assertRaises(ValueError):
            roster.parse_lanes("glm-5.3-flash:2,glm-5.3-flash:1")
        with self.assertRaises(ValueError):
            roster.parse_lanes("glm-5.3-flash:0")
        with self.assertRaises(KeyError):
            roster.plan_lanes([("not-a-model", 1)])
        print("  ✓ lane specs reject duplicates, zero agents and unknown models")

    def test_15_an_unknown_profile_is_reported_not_invented(self):
        rows = roster.plan_lanes([("gemini-4-argon", 1)], hours=5)
        self.assertIsNone(rows[0]["per_request"])
        self.assertIsNone(rows[0]["tasks_per_agent"])
        self.assertIn("unknown", roster.render_plan(rows, 5))
        print("  ✓ a model with no published token profile reports unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
