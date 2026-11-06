#!/usr/bin/env python3
"""Tests for reply-meter. Stdlib unittest, no network, no model."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import meter  # noqa: E402

CLEAN = (
    "Open the config file and set the port to 8080. Restart the service after "
    "the edit lands. The health endpoint returns one line of JSON. Confirm the "
    "new value before you run the migration. Log every failure to the shared ledger."
)

SLOP = (
    "We should leverage a robust, seamless pipeline that must unlock value "
    "across the entire landscape. It's crucial that we delve into the tapestry "
    "of options; the team can't ignore this. Building on that, we might "
    "streamline the holistic workflow to elevate every stakeholder. In summary, "
    "we verify the cache, check the routes, and confirm the queue before we "
    "ship \u2014 which is absolutely vital."
)

KEYS = {"words", "sentences", "longest_sentence", "faults_per_100w", "faults"}


class TestShape(unittest.TestCase):
    def test_returns_exactly_the_documented_keys(self):
        self.assertEqual(set(meter.score(CLEAN)), KEYS)

    def test_empty_text_does_not_divide_by_zero(self):
        result = meter.score("")
        self.assertEqual(result["words"], 0)
        self.assertEqual(result["faults"], [])
        self.assertEqual(result["faults_per_100w"], 0.0)

    def test_counts(self):
        result = meter.score("One two three. One two three four five.")
        self.assertEqual(result["words"], 8)
        self.assertEqual(result["sentences"], 2)
        self.assertEqual(result["longest_sentence"], 5)


class TestCleanReply(unittest.TestCase):
    def test_clean_paragraph_scores_zero_faults(self):
        result = meter.score(CLEAN)
        self.assertEqual(result["faults"], [])
        self.assertEqual(result["faults_per_100w"], 0.0)
        self.assertGreater(result["words"], 30)
        self.assertGreaterEqual(result["sentences"], 4)
        self.assertLessEqual(result["longest_sentence"], 25)

    def test_numbered_list_is_not_a_fault(self):
        reply = (
            "## Fix\n\n"
            "The failure comes from a stale socket.\n\n"
            "1. Stop the worker.\n"
            "2. Remove the socket file.\n"
            "3. Start the worker again.\n"
        )
        self.assertEqual(meter.score(reply)["faults"], [])


class TestSlopReply(unittest.TestCase):
    def setUp(self):
        self.result = meter.score(SLOP)
        self.rules = {fault["rule"] for fault in self.result["faults"]}

    def test_trips_at_least_four_named_rules(self):
        self.assertGreaterEqual(len(self.rules), 4)

    def test_trips_the_expected_rules(self):
        expected = {
            "banned_modal", "contraction", "semicolon", "slop_word",
            "ing_clause_start", "synonym_rotation", "em_dash",
            "summary_boilerplate",
        }
        self.assertEqual(expected - self.rules, set())

    def test_slop_words_fire_one_fault_each(self):
        slop = [f for f in self.result["faults"] if f["rule"] == "slop_word"]
        self.assertGreaterEqual(len(slop), 5)

    def test_faults_are_located(self):
        for fault in self.result["faults"]:
            self.assertEqual(set(fault), {"rule", "line", "excerpt"})
            self.assertGreaterEqual(fault["line"], 1)
            self.assertTrue(fault["excerpt"].strip())

    def test_faults_are_sorted_by_line(self):
        lines = [f["line"] for f in self.result["faults"]]
        self.assertEqual(lines, sorted(lines))

    def test_line_numbers_follow_the_document(self):
        reply = "Ship it.\n\nWe should stop.\n\nThe queue drains.\n"
        faults = meter.score(reply)["faults"]
        self.assertEqual(len(faults), 1)
        self.assertEqual(faults[0]["rule"], "banned_modal")
        self.assertEqual(faults[0]["line"], 3)

    def test_latin_abbrev_does_not_split_the_sentence(self):
        reply = "See e.g. the runbook before you touch the queue.\n"
        result = meter.score(reply)
        self.assertEqual(result["sentences"], 1)
        self.assertIn("latin_abbrev", {f["rule"] for f in result["faults"]})


class TestRate(unittest.TestCase):
    def test_faults_per_100w_matches_the_formula(self):
        result = meter.score(SLOP)
        expected = round(len(result["faults"]) * 100.0 / result["words"], 1)
        self.assertEqual(result["faults_per_100w"], expected)
        self.assertGreater(result["faults_per_100w"], 0.0)

    def test_rate_is_normalised_by_length(self):
        one = meter.score(SLOP)
        two = meter.score(SLOP + "\n\n" + SLOP)
        self.assertGreater(two["words"], one["words"])
        self.assertGreater(len(two["faults"]), len(one["faults"]))
        self.assertEqual(one["faults_per_100w"], two["faults_per_100w"])


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "reply.md"
        self.path.write_text(SLOP, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "meter.py"), "--file", str(self.path), *args],
            capture_output=True, text=True, check=True,
        )

    def test_json_matches_score(self):
        data = json.loads(self.run_cli("--json").stdout)
        self.assertEqual(data, meter.score(SLOP))
        self.assertEqual(set(data), KEYS)

    def test_human_output_reports_the_rate(self):
        out = self.run_cli().stdout
        self.assertIn("faults/100w", out)
        self.assertIn("banned_modal", out)

    def test_missing_file_exits_2(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "meter.py"), "--file",
             str(Path(self.tmp.name) / "nope.md")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
