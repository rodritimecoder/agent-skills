"""Offline tests for the hard-leg-only routing gate contract.

Only the four hard legs (exec_only_flow, skills_bridge_flow, doc_drift,
skill_standard) decide the verdict: four passing hard legs => GREEN; any hard
leg failing, missing or malformed => RED. ``overfit`` is not a gate leg (overfit_check.py stays a
standalone diagnostic). Every decide() case here uses an injected report, so
no test touches the real catalog, writes an artifact or spawns an eval. The one
real-subprocess case proves a hard leg can go red end-to-end through the
env-override path.

    cd orchestration/omnicli && python3 -m unittest tests.test_routing_gate -v
"""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from tests import routing_gate as rg

HARD_LEGS = ("exec_only_flow", "skills_bridge_flow", "doc_drift", "skill_standard")


def clean_leg(name: str) -> dict:
    return {"pass": True, "exit": 0, "detail": f"{name} ok"}


def failed_leg(name: str, exit_code: int = 1) -> dict:
    return {"pass": False, "exit": exit_code, "detail": f"{name} marker-red"}


def clean_report() -> dict:
    """Three passing hard legs — the only input decide() needs."""
    return {"legs": {name: clean_leg(name) for name in HARD_LEGS}}


class TestHardLegDecision(unittest.TestCase):
    """decide() greens only on four passing hard legs; any broken leg is red."""

    def assert_red(self, report: dict, needle: str) -> list[str]:
        failures = rg.decide(report)
        self.assertTrue(failures, f"expected gate to be RED for {needle!r}, got green")
        self.assertTrue(
            any(needle in f for f in failures),
            f"expected a failure naming {needle!r}, got {failures}",
        )
        return failures

    def assert_green(self, report: dict, label: str) -> None:
        failures = rg.decide(report)
        self.assertEqual(failures, [], f"{label}: expected GREEN, got {failures}")

    def test_four_hard_legs_pass_is_green(self):
        self.assert_green(clean_report(), "four passing hard legs")

    def test_each_hard_leg_failure_is_red(self):
        for name in HARD_LEGS:
            with self.subTest(hard_leg=name):
                report = clean_report()
                report["legs"][name] = failed_leg(
                    name, exit_code=2 if name == "skills_bridge_flow" else 1
                )
                self.assert_red(report, name)

    def test_missing_hard_leg_is_red(self):
        for name in HARD_LEGS:
            with self.subTest(missing=name):
                report = clean_report()
                del report["legs"][name]
                self.assert_red(report, name)

    def test_non_dict_hard_leg_is_red(self):
        for name in HARD_LEGS:
            with self.subTest(malformed=name):
                report = clean_report()
                report["legs"][name] = "not-a-result-dict"
                self.assert_red(report, name)

    def test_empty_legs_is_red_for_all_four(self):
        for report in ({"legs": {}}, {}):
            with self.subTest(report=report):
                failures = rg.decide(report)
                self.assertEqual(len(failures), len(HARD_LEGS), failures)
                for name in HARD_LEGS:
                    self.assertTrue(any(name in f for f in failures), failures)

    def test_all_four_hard_legs_fail_together(self):
        report = clean_report()
        for name in HARD_LEGS:
            report["legs"][name] = failed_leg(name)
        failures = rg.decide(report)
        self.assertEqual(len(failures), len(HARD_LEGS), failures)
        for name in HARD_LEGS:
            self.assertTrue(any(name in f for f in failures), failures)

    def test_unknown_extra_legs_are_ignored(self):
        report = clean_report()
        report["legs"]["unrelated_leg"] = failed_leg("unrelated_leg")
        self.assert_green(report, "unrelated extra leg")

    def test_overfit_is_not_a_hard_leg(self):
        self.assertNotIn("overfit", HARD_LEGS)
        self.assertNotIn("overfit", rg.HARD_LEGS)
        report = clean_report()
        report["legs"]["overfit"] = failed_leg("overfit")
        self.assert_green(report, "failing overfit is not a leg")

    def test_decide_does_not_mutate_its_input(self):
        report = clean_report()
        before = copy.deepcopy(report)
        rg.decide(report)
        self.assertEqual(report, before)


class TestGateIsHardLegsOnly(unittest.TestCase):
    """Static contract: no eval/advisory machinery remains in the gate."""

    def test_declared_hard_legs_are_exactly_the_four(self):
        self.assertEqual(rg.HARD_LEGS, HARD_LEGS)

    def test_gate_source_has_no_eval_or_advisory_references(self):
        text = Path(rg.__file__).read_text(encoding="utf-8")
        for token in (
            "advisory", "eval_runner", "golden", "fresh", "paraphrase",
            "derive_metrics", "run_eval", "bm25", "GOLDEN_TOP",
            "FRESH_ANSWERABLE", "PARAPHRASE", "FRAGILE_MARGIN",
            "margin_failures", "negative_failures", "top1_raw", "top3_raw",
            "overfit",
        ):
            self.assertNotIn(token, text, f"gate still references {token!r}")


class TestRealDiscoveryMutant(unittest.TestCase):
    """Prove a hard leg can go red through the real subprocess runner path."""

    def test_exec_only_hard_leg_goes_red_through_real_gate(self):
        from tests.discovery_mutant import run_discovery_mutant

        result = run_discovery_mutant()
        self.assertEqual(result["mutant_exit"], 1, result)
        self.assertEqual(result["mutant_names_leg"], True, result)
        self.assertEqual(result["clean_exit"], 0, result)


if __name__ == "__main__":
    unittest.main()
