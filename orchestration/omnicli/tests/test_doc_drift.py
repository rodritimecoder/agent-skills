#!/usr/bin/env python3
"""Control/mutant tests for the doc-drift gate's stale-search-routing leg."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CHECK = REPO / "orchestration" / "omnicli" / "tests" / "doc_drift_check.py"

# Mirrors search_routing_docs() in doc_drift_check.py: one file, three globs.
CURATED = (
    ("CONTEXT.md", None),
    ("orchestration/omnicli/hooks", "*.py"),
    ("orchestration/omnicli/plugin", "*.js"),
    ("orchestration/omnicli/references", "*.md"),
)
MUTANT_LINE = '- omnicli search "transcribe audio" — find catalogued tools by intent.\n'


class DocDriftTest(unittest.TestCase):
    def _copy_scanned_docs(self, root: Path) -> None:
        for rel, pattern in CURATED:
            src = REPO / rel
            if pattern is None:
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                continue
            for path in sorted(src.glob(pattern)):
                if path.name.startswith("plan-"):
                    continue
                dst = root / path.relative_to(REPO)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dst)

    def _run(self, root: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["OMNICLI_DOC_DRIFT_ROOT"] = str(root)
        return subprocess.run(
            [sys.executable, str(CHECK), "--json"],
            capture_output=True, text=True, env=env, cwd=str(REPO), timeout=120,
        )

    @staticmethod
    def _stale_check(payload: dict) -> dict:
        return next(c for c in payload["checks"] if c["name"] == "stale_search")

    def test_clean_scanned_docs_exit_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._copy_scanned_docs(root)
            proc = self._run(root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            stale = self._stale_check(payload)
            self.assertEqual(stale["status"], "PASS", stale["detail"])

    def test_mutant_stale_search_instruction_exits_one(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._copy_scanned_docs(root)
            target = root / "orchestration/omnicli/references/skill-stack-architecture.md"
            self.assertTrue(target.exists())
            with target.open("a", encoding="utf-8") as fh:
                fh.write("\n" + MUTANT_LINE)
            proc = self._run(root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertFalse(payload["ok"])
            stale = self._stale_check(payload)
            self.assertEqual(stale["status"], "FAIL", stale["detail"])
            self.assertIn("skill-stack-architecture.md", stale["detail"])


if __name__ == "__main__":
    unittest.main()
