#!/usr/bin/env python3
"""Gate tests for design-pack verify (static) and check (runtime behaviour)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
DESIGN_PACK = ROOT / "scripts" / "design_pack.py"
LOOK = ROOT / "looks" / "glitch-console"
FAIL_CONTROL = ROOT / "tests" / "fail_control.html"


def run_check(files: list[str], *extra: str) -> subprocess.CompletedProcess:
    """Run the runtime check, skipping when this host has no browser runner.

    `check` exits 3 when playwright is not importable — a runner the checkout
    cannot install for itself. The static `verify` gates still run everywhere.
    """
    proc = subprocess.run(
        [sys.executable, str(DESIGN_PACK), "check", *files, *extra, "--json"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 3:
        raise unittest.SkipTest((proc.stderr or proc.stdout).strip()[:200])
    return proc


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
        proc = run_check([str(LOOK)])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data["pass"])

    def test_check_fails_on_control(self):
        proc = run_check([str(FAIL_CONTROL)], "--viewports", "375x812,1280x800")
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


class TestRunnerAbsence(unittest.TestCase):
    """A host without the browser runner skips the runtime gate, never fails it."""

    def test_missing_runner_skips_with_its_reason(self):
        with tempfile.TemporaryDirectory() as d:
            stub = Path(d) / "design_pack.py"
            stub.write_text(
                "import sys\n"
                "sys.stderr.write('check_runner: could not load playwright module\\n')\n"
                "sys.exit(3)\n",
                encoding="utf-8",
            )
            with mock.patch.object(sys.modules[__name__], "DESIGN_PACK", stub):
                with self.assertRaises(unittest.SkipTest) as ctx:
                    run_check([str(LOOK)])
        self.assertIn("could not load playwright", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
