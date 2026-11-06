"""Unit tests for omnicli harness adapters and verification.

Run:
    python3 tests/test_harness.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(SKILL_DIR))

from catalog import harness  # noqa: E402


class TestHarnessRegistry(unittest.TestCase):
    def test_all_five_harnesses_present(self):
        expected = {"t3-code", "agy", "opencode", "pi", "boxxy"}
        self.assertEqual(set(harness.HARNESS_SPECS.keys()), expected)

    def test_alias_resolution(self):
        self.assertEqual(harness.resolve_harness_id("t3"), "t3-code")
        self.assertEqual(harness.resolve_harness_id("t3code"), "t3-code")
        self.assertEqual(harness.resolve_harness_id("agy"), "agy")
        self.assertEqual(harness.resolve_harness_id("antigravity"), "agy")
        self.assertEqual(harness.resolve_harness_id("opencode"), "opencode")
        self.assertEqual(harness.resolve_harness_id("oc"), "opencode")
        self.assertEqual(harness.resolve_harness_id("pi"), "pi")
        self.assertEqual(harness.resolve_harness_id("pi-agent"), "pi")
        self.assertEqual(harness.resolve_harness_id("boxxy"), "boxxy")
        self.assertEqual(harness.resolve_harness_id("boxxyclaw"), "boxxy")
        self.assertIsNone(harness.resolve_harness_id("nonexistent"))

    def test_doc_files_exist_and_non_empty(self):
        for h_id, spec in harness.HARNESS_SPECS.items():
            doc = harness.get_doc(h_id)
            self.assertIsNotNone(doc, f"Missing doc for {h_id}")
            self.assertGreater(len(doc), 100, f"Doc for {h_id} is too short")
            self.assertTrue(doc.startswith("# "), f"Doc for {h_id} must start with markdown heading")

    def test_config_snippets(self):
        for h_id in harness.HARNESS_SPECS:
            snippet = harness.get_config(h_id)
            self.assertIsNotNone(snippet, f"Missing config snippet for {h_id}")
            self.assertGreater(len(snippet), 10)


class TestHarnessDetection(unittest.TestCase):
    def test_detection_runs_cleanly(self):
        detected = harness.detect_active_harnesses()
        self.assertIsInstance(detected, list)
        for d in detected:
            self.assertIn("id", d)
            self.assertIn("name", d)
            self.assertIn("matched_indicators", d)
            self.assertTrue(len(d["matched_indicators"]) > 0)


class TestHarnessVerification(unittest.TestCase):
    def test_verify_each_harness(self):
        for h_id in harness.HARNESS_SPECS:
            res = harness.verify_harness(h_id)
            self.assertEqual(res["id"], h_id)
            self.assertIn(res["status"], ("PASS", "FAIL"))
            self.assertIsInstance(res["checks"], list)
            self.assertEqual(res["total"], len(res["checks"]))
            for c in res["checks"]:
                self.assertIn("check", c)
                self.assertIsInstance(c["passed"], bool)
                self.assertIn("detail", c)

    def test_verify_all(self):
        res = harness.verify_all()
        self.assertIn(res["status"], ("PASS", "FAIL"))
        self.assertEqual(len(res["harnesses"]), 5)


class TestHarnessCLI(unittest.TestCase):
    def test_cli_harness_list_json(self):
        proc = subprocess.run(
            [sys.executable, str(SKILL_DIR / "omnicli.py"), "harness", "list", "--json"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(len(data), 5)

    def test_cli_harness_verify_json(self):
        proc = subprocess.run(
            [sys.executable, str(SKILL_DIR / "omnicli.py"), "harness", "verify", "--json"],
            capture_output=True, text=True,
        )
        self.assertIn(proc.returncode, (0, 1))
        data = json.loads(proc.stdout)
        self.assertIn(data["status"], ("PASS", "FAIL"))

    def test_cli_harness_info(self):
        proc = subprocess.run(
            [sys.executable, str(SKILL_DIR / "omnicli.py"), "harness", "info", "t3-code"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("T3 Code", proc.stdout)


if __name__ == "__main__":
    unittest.main()
