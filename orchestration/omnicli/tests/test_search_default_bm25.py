"""Regression tests for the dense-default demotion.

Default `omnicli search` is pure BM25: it must not start the dense slot and
must report `tier=bm25` / `dense.ran=false`. Dense retrieval is opt-in via
`--fusion always` (or `--fusion auto`).

Run:
    cd orchestration/omnicli && python3 -m unittest tests.test_search_default_bm25 -v
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
SKILL = HERE.parent
OMNICLI = SKILL / "omnicli.py"


def run_omnicli(*args, env=None, cwd=None):
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(OMNICLI), *args],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(cwd) if cwd else str(SKILL),
        env=merged,
    )


class TestDefaultBm25(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.shimdir = Path(self._tmp.name) / "bin"
        self.shimdir.mkdir()
        self.marker = Path(self._tmp.name) / "ensure_called.txt"
        shim = self.shimdir / "llama-rig"
        shim.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "ensure" ]; then echo touched > "' + str(self.marker) + '"; fi\n'
            "exit 1\n"
        )
        shim.chmod(0o755)
        self.env = {"PATH": str(self.shimdir) + os.pathsep + os.environ.get("PATH", "")}

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_search_is_pure_bm25(self):
        proc = run_omnicli("search", "turn a recorded podcast into readable text", "--no-rerank", "--json", env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data.get("tier"), "bm25", data)
        self.assertFalse(data.get("dense", {}).get("ran"), data)
        self.assertFalse(self.marker.exists(), "llama-rig ensure 8084 must not be invoked by default search")

    def test_fusion_always_runs_dense_when_available(self):
        proc = run_omnicli("search", "transcribe a zoom lecture recording", "--no-rerank", "--fusion", "always", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        if not data.get("dense", {}).get("ran"):
            self.skipTest("dense endpoint :8084 unavailable in this environment")
        self.assertTrue(data["dense"]["ran"])
        self.assertIn("dense", data["tier"])

    def test_cjk_regression_agent_reach_top(self):
        proc = run_omnicli("search", "调研一下这个话题在网上的讨论", "--no-rerank", "--json", env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data.get("results"), data)
        self.assertEqual(data["results"][0]["skill"], "agent-reach", data)


if __name__ == "__main__":
    unittest.main()