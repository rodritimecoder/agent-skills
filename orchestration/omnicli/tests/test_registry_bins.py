"""Tests for metadata.bins: a skill whose command is not its own name.

Run:
    python3 tests/test_registry_bins.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from catalog import registry  # noqa: E402


def doc(frontmatter: str) -> str:
    return f"---\n{frontmatter}\n---\n\n# body\n"


class TestParseBins(unittest.TestCase):
    def test_inline_list(self):
        text = doc('name: x\ndescription: y\nmetadata:\n  bins: [vram-rig-ctl, other]')
        self.assertEqual(registry.parse_bins(text), ["vram-rig-ctl", "other"])

    def test_scalar_comma_separated(self):
        text = doc('name: x\ndescription: y\nmetadata:\n  bins: "verify-app, agentic"')
        self.assertEqual(registry.parse_bins(text), ["verify-app", "agentic"])

    def test_scalar_space_separated(self):
        text = doc("name: x\ndescription: y\nmetadata:\n  bins: a b")
        self.assertEqual(registry.parse_bins(text), ["a", "b"])

    def test_block_list(self):
        text = doc("name: x\ndescription: y\nmetadata:\n  bins:\n    - one\n    - two")
        self.assertEqual(registry.parse_bins(text), ["one", "two"])

    def test_absent(self):
        self.assertEqual(registry.parse_bins(doc("name: x\ndescription: y")), [])

    def test_bins_outside_metadata_is_ignored(self):
        text = doc("name: x\ndescription: y\nbins: [nope]")
        self.assertEqual(registry.parse_bins(text), [])

    def test_duplicates_collapse(self):
        text = doc("name: x\ndescription: y\nmetadata:\n  bins: a, a")
        self.assertEqual(registry.parse_bins(text), ["a"])


class TestResolveShim(unittest.TestCase):
    def setUp(self):
        self.bindir = Path(tempfile.mkdtemp())

    def _shim(self, name: str, executable: bool = True) -> None:
        path = self.bindir / name
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755 if executable else 0o644)

    def test_alias_resolves_after_skill_and_dir_names(self):
        self._shim("vram-rig-ctl")
        found = registry._resolve_shim("model-layer", "model-layer", "vram-rig-ctl", bindir=self.bindir)
        self.assertTrue(found.endswith("vram-rig-ctl"))

    def test_skill_name_wins_over_alias(self):
        self._shim("model-layer")
        self._shim("vram-rig-ctl")
        found = registry._resolve_shim("model-layer", "model-layer", "vram-rig-ctl", bindir=self.bindir)
        self.assertTrue(found.endswith("/model-layer"))

    def test_non_executable_is_not_a_shim(self):
        self._shim("alias-only", executable=False)
        self.assertIsNone(registry._resolve_shim("x", "x", "alias-only", bindir=self.bindir))

    def test_nothing_found(self):
        self.assertIsNone(registry._resolve_shim("x", "x", "", bindir=self.bindir))


class TestLiveSkills(unittest.TestCase):
    """The three skills this change exists for, when their shims are installed."""

    CASES = {"model-layer": "vram-rig-ctl", "verification": "verify-app",
             "agentic-engineering": "agentic"}

    def test_declared_bins_match_installed_shims(self):
        skills = registry.load_all_skills()
        tested = 0
        for skill, command in self.CASES.items():
            if skill not in skills:
                continue
            if not (Path.home() / ".local" / "bin" / command).exists():
                continue
            tested += 1
            self.assertTrue(skills[skill]["cli"].endswith(command),
                            f"{skill} resolved to {skills[skill]['cli']}, expected {command}")
        if tested == 0:
            self.skipTest("no shims installed")

    def test_skill_without_bins_finds_nothing(self):
        skills = registry.load_all_skills()
        if "academic-pipeline-v2" not in skills:
            self.skipTest("skill not present")
        self.assertIsNone(skills["academic-pipeline-v2"]["cli"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
