"""Regression tests for the exec-only skill discovery manifest.

Covers three slices of the discovery plumbing:

* folded/literal YAML frontmatter is read to the end of the block, blank lines
  inside it included (the ``NOT for:`` / ``Routing:`` triggers live there);
* the generated skills window contains only active skills — archived and
  sidelined skills never leak into routing;
* ``lsSkills({brief:true})`` returns compact cards that are measurably smaller
  than the full listing and still fit one bounded result.

Run:
    cd orchestration/omnicli && python3 -m unittest tests.test_discovery_manifest -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))  # noqa: E402

from catalog import exec_runner, registry  # noqa: E402

NODE = shutil.which("node")


# ---------------------------------------------------------------------------
# 1. frontmatter block scalars
# ---------------------------------------------------------------------------

FOLDED_WITH_BLANKS = (
    "---\nname: demo\n"
    "description: >\n"
    "  First when-to-use sentence that carries the whole idea.\n"
    "  Second line continues this very same paragraph.\n"
    "\n"
    "  NOT for: writing reports, translation, or data analysis.\n"
    "\n"
    "  [Routing]: load references/web.md on demand.\n"
    "compatibility: \"SHOULD_NOT_LEAK\"\n"
    "---\nbody"
)


class TestFoldedFrontmatter(unittest.TestCase):
    def test_blank_lines_inside_folded_block_are_kept(self):
        name, desc = registry.parse_frontmatter(FOLDED_WITH_BLANKS)
        self.assertEqual(name, "demo")
        self.assertIn("First when-to-use sentence", desc)
        self.assertIn("Second line continues", desc)
        self.assertIn("NOT for: writing reports, translation, or data analysis.", desc)
        self.assertIn("[Routing]: load references/web.md on demand.", desc)
        self.assertGreater(len(desc), 180)
        # The next top-level key must not be swallowed into the description.
        self.assertNotIn("SHOULD_NOT_LEAK", desc)

    def test_negative_control_block_ends_at_next_key(self):
        # A blank line followed by an unindented key terminates the block. The
        # old regex also stopped there, but a greedy fix that simply dropped
        # its indent guard would pull the following key in — this pins it down.
        md = (
            "---\nname: demo\n"
            "description: >\n"
            "  only this line belongs to us\n"
            "\n"
            "compatibility: \"MUST_NOT_APPEAR\"\n"
            "---\nbody"
        )
        _, desc = registry.parse_frontmatter(md)
        self.assertIn("only this line belongs to us", desc)
        self.assertNotIn("MUST_NOT_APPEAR", desc)
        self.assertNotIn("compatibility", desc)

    def test_literal_block_keeps_newlines_and_blanks(self):
        md = (
            "---\nname: demo\n"
            "description: |\n"
            "  line one\n"
            "\n"
            "  line two\n"
            "---\nbody"
        )
        _, desc = registry.parse_frontmatter(md)
        self.assertIn("line one", desc)
        self.assertIn("line two", desc)
        self.assertIn("\n", desc)

    def test_real_agent_reach_description_not_truncated(self):
        path = registry.REPO_ROOT / "academic" / "agent-reach" / "SKILL.md"
        if not path.is_file():
            self.skipTest("agent-reach SKILL.md not present in this checkout")
        _, desc = registry.parse_frontmatter(path.read_text(encoding="utf-8"))
        self.assertIn("NOT for:", desc)
        self.assertIn("[Routing]", desc)
        self.assertGreater(len(desc), 900)


# ---------------------------------------------------------------------------
# 2. active-only generated manifest
# ---------------------------------------------------------------------------

ARCHIVED_NAMES = (
    "design-system",
    "eval-pipeline",
    "kem-dev-loop",
    "reply-meter",
    "semantic-cache",
    "swarm-contract",
    "glitch-orchestra",
)
ACTIVE_DOMAIN_SKILLS = (
    "apiv-loop",
    "graph-memory",
    "kem-thought",
    "guard-hooks",
    "state-compactor",
    "verification",
    "worktree-harness",
    "agentic-engineering",
)


class TestSkillsManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = exec_runner._canonical_skills_root()
        if cls.root is None:
            raise unittest.SkipTest("no canonical skills tree on this host")
        cls.tmp = tempfile.TemporaryDirectory(prefix="sdp-manifest-")
        cls.manifest = Path(cls.tmp.name) / "manifest.json"
        cls.count = exec_runner._write_skills_manifest(
            cls.manifest, cls.root, "/tmp/omnicli/skills")
        cls.data = json.loads(cls.manifest.read_text(encoding="utf-8"))
        cls.names = {e["name"] for e in cls.data["skills"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_archived_and_sidelined_are_absent(self):
        for name in ARCHIVED_NAMES:
            self.assertNotIn(name, self.names, f"archived skill leaked: {name}")

    def test_active_skills_in_all_domains_are_present(self):
        for name in ACTIVE_DOMAIN_SKILLS:
            self.assertIn(name, self.names, f"active skill missing: {name}")

    def test_manifest_shape_and_count(self):
        self.assertEqual(self.count, len(self.data["skills"]))
        self.assertEqual(self.data["root"], "/tmp/omnicli/skills")
        self.assertTrue(all({"name", "description", "dir"} <= set(e)
                            for e in self.data["skills"]))


# ---------------------------------------------------------------------------
# 3. brief lsSkills: compact, bounded, one-line triggers
# ---------------------------------------------------------------------------

NODE_SNIPPET = r"""
import fs from "node:fs";
import { pathToFileURL } from "node:url";
const { createSkillFs } = await import(pathToFileURL(process.env.SDP_SKILL_FS).href);
const manifest = JSON.parse(fs.readFileSync(process.env.SDP_MANIFEST, "utf8"));
const api = createSkillFs(manifest);
const full = api.lsSkills();
const brief = api.lsSkills({ brief: true });
const bytes = (v) => Buffer.byteLength(JSON.stringify(v), "utf8");
console.log(JSON.stringify({
  fullFields: Object.keys(full[0] || {}).sort(),
  briefFields: Object.keys(brief[0] || {}).sort(),
  fullCount: full.length,
  briefCount: brief.length,
  fullBytes: bytes(full),
  briefBytes: bytes(brief),
  maxTrigger: Math.max(0, ...brief.map((b) => b.trigger.length)),
}));
"""


class TestBriefSkillsWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not NODE:
            raise unittest.SkipTest("node not on PATH")
        cls.root = exec_runner._canonical_skills_root()
        if cls.root is None:
            raise unittest.SkipTest("no canonical skills tree on this host")
        cls.tmp = tempfile.TemporaryDirectory(prefix="sdp-brief-")
        cls.manifest = Path(cls.tmp.name) / "manifest.json"
        exec_runner._write_skills_manifest(cls.manifest, cls.root, "/tmp/omnicli/skills")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _run(self):
        env = dict(os.environ,
                   SDP_SKILL_FS=str((ROOT / "catalog" / "skill_fs.mjs").resolve()),
                   SDP_MANIFEST=str(self.manifest))
        proc = subprocess.run(
            [NODE, "--input-type=module", "-e", NODE_SNIPPET],
            capture_output=True, text=True, timeout=60, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-1000:])
        return json.loads(proc.stdout.strip())

    def test_full_shape_unchanged_brief_shape_and_trigger_cap(self):
        out = self._run()
        self.assertEqual(out["fullFields"], ["description", "name"])
        self.assertEqual(out["briefFields"], ["domain", "name", "trigger"])
        self.assertEqual(out["fullCount"], out["briefCount"])
        self.assertLessEqual(out["maxTrigger"], 120)

    def test_brief_is_smaller_and_fits_one_bounded_result(self):
        out = self._run()
        self.assertGreater(out["fullBytes"], 0)
        self.assertLess(out["briefBytes"], out["fullBytes"])
        # A single bounded result: comfortably within one exec stdout budget,
        # and at least half the size of the full listing.
        self.assertLess(out["briefBytes"], 10000)
        self.assertLess(out["briefBytes"] * 2, out["fullBytes"])


if __name__ == "__main__":
    unittest.main()
