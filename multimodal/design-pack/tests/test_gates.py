#!/usr/bin/env python3
"""Gate tests for design-pack verify (static) and check (runtime behaviour)."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGN_PACK = ROOT / "scripts" / "design_pack.py"
LOOK = ROOT / "looks" / "glitch-console"
FAIL_CONTROL = ROOT / "tests" / "fail_control.html"


class TestDesignPackGates(unittest.TestCase):
    def test_verify_passes_glitch_console(self):
        proc = subprocess.run(
            [sys.executable, str(DESIGN_PACK), "verify", str(LOOK), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data["pass"])
        self.assertEqual(data["fail_count"], 0)
        self.assertEqual(data["warn_count"], 0)

    def test_verify_fails_on_control(self):
        proc = subprocess.run(
            [sys.executable, str(DESIGN_PACK), "verify", str(FAIL_CONTROL), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertFalse(data["pass"])
        self.assertGreaterEqual(data["fail_count"], 4)

    def test_check_passes_glitch_console(self):
        proc = subprocess.run(
            [sys.executable, str(DESIGN_PACK), "check", str(LOOK), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data["pass"])

    def test_check_fails_on_control(self):
        proc = subprocess.run(
            [
                sys.executable,
                str(DESIGN_PACK),
                "check",
                str(FAIL_CONTROL),
                "--viewports",
                "375x812,1280x800",
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertFalse(data["pass"])
        checks_hit = {iss["check"] for iss in data["targets"][0]["issues"]}
        self.assertTrue(
            {"viewport", "overlap", "primitive", "type-floor", "contrast", "latency"}.issubset(
                checks_hit
            ),
            f"Expected all defect checks to trigger, got {checks_hit}",
        )


if __name__ == "__main__":
    unittest.main()
