"""Exit codes are the gate: findings must fail the run.

These tests drive the real CLI through subprocess so a discarded return value
or a missing `sys.exit` cannot pass. The slop fixture is built from the hub's
own UNSLOP_PATTERNS table, so changing a pattern breaks the fixture loudly
instead of leaving the tests green against stale text.

    python3 -m unittest discover -s engineering/review-hub/tests
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HUB = Path(__file__).resolve().parents[1] / "review_hub.py"

_spec = importlib.util.spec_from_file_location("review_hub_under_test", HUB)
hub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hub)

# One phrase per UNSLOP_PATTERNS row, checked against its own row below.
SLOP_SAMPLES = [
    "This is a crucial step.",
    "It is not just fast, but reliable.",
    "It serves as the base.",
    "In order to ship.",
    "Due to the fact that it works.",
    "It is important to note that this is fine.",
    "I hope this helps.",
    "One thing \u2014 another thing.",
    "It grows, highlighting the cost.",
    "Experts believe this.",
    "It might be suggested that this holds.",
    "We utilize it.",
]
SLOP_TEXT = "\n".join(SLOP_SAMPLES) + "\n"
CLEAN_TEXT = "The quick brown fox jumps over the lazy dog.\n"


class ExitCodes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="review-hub-exit-")
        cls.dir = Path(cls._tmp.name)
        cls.slop = cls.dir / "slop.md"
        cls.slop.write_text(SLOP_TEXT, encoding="utf-8")
        cls.clean = cls.dir / "clean.md"
        cls.clean.write_text(CLEAN_TEXT, encoding="utf-8")
        cls.monolith = cls.dir / "monolith.py"
        cls.monolith.write_text("value = 1\n" * 1001, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_hub(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HUB), *args],
            cwd=self.dir,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def assertNoTraceback(self, proc: subprocess.CompletedProcess):
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)

    def test_fixture_trips_every_unslop_pattern(self):
        self.assertEqual(len(SLOP_SAMPLES), len(hub.UNSLOP_PATTERNS))
        for (pattern, _label), sample in zip(hub.UNSLOP_PATTERNS, SLOP_SAMPLES):
            self.assertIsNotNone(re.search(pattern, sample, re.IGNORECASE), sample)
        self.assertGreaterEqual(len(hub.scan_unslop(SLOP_TEXT)), len(hub.UNSLOP_PATTERNS))

    def test_clean_text_is_actually_clean(self):
        self.assertEqual(hub.scan_unslop(CLEAN_TEXT), [])

    def test_slop_file_exits_one(self):
        proc = self.run_hub("review", "unslop", str(self.slop))
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("WARNING", proc.stdout)
        self.assertNoTraceback(proc)

    def test_clean_file_exits_zero(self):
        proc = self.run_hub("review", "unslop", str(self.clean))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)

    def test_fail_on_none_restores_zero(self):
        proc = self.run_hub("review", "unslop", str(self.slop), "--fail-on", "none")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("WARNING", proc.stdout)

    def test_unknown_suite_exits_two_plain(self):
        proc = self.run_hub("review", "doesnotexist")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("Unknown review suite", proc.stderr)
        self.assertNoTraceback(proc)

    def test_unknown_suite_exits_two_json(self):
        proc = self.run_hub("review", "doesnotexist", "--json")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("Unknown review suite", proc.stderr)
        self.assertNoTraceback(proc)

    def test_review_all_propagates_the_exit_code(self):
        proc = self.run_hub("review", "all", str(self.slop))
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("WARNING", proc.stdout)
        self.assertNoTraceback(proc)

    def test_thermonuclear_audit_fails_an_oversized_file(self):
        proc = self.run_hub("audit", "thermonuclear", str(self.monolith))
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("VIOLATION", proc.stdout)

    def test_out_writes_the_report_and_keeps_the_exit_code(self):
        out = self.dir / "report.json"
        proc = self.run_hub("review", "unslop", str(self.slop), "--out", str(out))
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertTrue(out.is_file())
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["status"], "WARNING")


if __name__ == "__main__":
    unittest.main()
