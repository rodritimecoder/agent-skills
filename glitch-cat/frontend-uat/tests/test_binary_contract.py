#!/usr/bin/env python3
"""The binary must keep the command surface frontend-uat depends on."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BIN = ROOT / "multimodal" / "playwright" / "bin" / "playwright-rs"


class TestBinaryContract(unittest.TestCase):
    """frontend-uat calls uat --ref and expects candidates to exist.

    Both are new in this binary. Without this test a rebuild can drop them and
    the failure only shows up on a machine that happens to have a browser and a
    decision server running.
    """

    @classmethod
    def setUpClass(cls):
        if not BIN.is_file():
            raise unittest.SkipTest(f"no binary at {BIN}")

    def test_01_uat_accepts_a_ref(self):
        res = subprocess.run([str(BIN), "uat", "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("--ref", res.stdout)
        print("  ✓ uat still accepts --ref")

    def test_02_candidates_exposes_the_ref_space(self):
        res = subprocess.run([str(BIN), "candidates", "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("--json", res.stdout)
        print("  ✓ candidates still exists and can emit JSON")

    def test_03_click_can_be_asked_for_an_effect(self):
        res = subprocess.run([str(BIN), "click", "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("--expect-text", res.stdout)
        self.assertIn("--expect-url", res.stdout)
        print("  ✓ click still waits for a state and accepts an expected effect")

    def test_04_daemon_control_is_still_there(self):
        res = subprocess.run([str(BIN), "daemon", "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        for action in ("start", "status"):
            self.assertIn(action, res.stdout)
        print("  ✓ daemon start/status still exist")


if __name__ == "__main__":
    unittest.main(verbosity=2)
