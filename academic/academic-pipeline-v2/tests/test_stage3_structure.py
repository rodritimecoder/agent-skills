#!/usr/bin/env python3
"""Tests for Stage 3 structure assembly (stdlib only, no network)."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "stage3_structure.py"
CONTRACTS = ROOT / "contracts"

SPEC = importlib.util.spec_from_file_location("stage3_structure", MODULE_PATH)
stage3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage3)

STEP_KEYS = {
    "stage",
    "stage_name",
    "step_type",
    "status",
    "started_at",
    "finished_at",
    "inputs",
    "outputs",
    "evidence",
    "errors",
}

META = {
    "course": "MATH101",
    "weeks": [
        {
            "week": "Week_01",
            "topic": "Limits",
            "tutorial": "Limits solutions",
            "nodes": [
                {"id": "n1", "label": "Limits", "kind": "topic"},
                {"id": "n2", "label": "Limits solutions", "kind": "tutorial"},
            ],
        },
        {
            "week": "Week_02",
            "topic": "Derivatives",
            "tutorial": "Derivatives solutions",
            "nodes": [
                {"id": "n3", "label": "Derivatives", "kind": "topic"},
                {"id": "n4", "label": "Derivatives solutions", "kind": "tutorial"},
            ],
        },
    ],
}

NOTE_TOPIC = """---
id: n1
week: 1
kind: topic
title: Limits
---
# Limits

A limit is the value a function approaches.
"""

NOTE_TUTORIAL = """---
id: n2
week: 1
kind: tutorial
title: Limits solutions
---
# Limits solutions

Worked problems on limits.
"""

SIFT_REPORT = {
    "items": [
        {
            "id": "n1",
            "source": "canvas",
            "decisions": {"is_admin_fluff": False},
            "confidence": 0.9,
            "route": "keep",
        },
        {
            "id": "n2",
            "source": "canvas",
            "decisions": {"is_admin_fluff": False},
            "confidence": 0.8,
            "route": "keep",
        },
    ]
}


class Stage3StructureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "workspace"
        (self.ws / "01_ingest").mkdir(parents=True)
        (self.ws / "02_sift").mkdir(parents=True)
        (self.ws / "01_ingest" / "meta.json").write_text(
            json.dumps(META), encoding="utf-8"
        )
        (self.ws / "02_sift" / "sift_report.json").write_text(
            json.dumps(SIFT_REPORT), encoding="utf-8"
        )
        (self.ws / "02_sift" / "limits-topic.md").write_text(
            NOTE_TOPIC, encoding="utf-8"
        )
        (self.ws / "02_sift" / "limits-tutorial.md").write_text(
            NOTE_TUTORIAL, encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_week_dirs(self):
        result = stage3.run(self.ws)
        self.assertEqual(result["status"], "ok", result["errors"])
        course = self.ws / "03_structure" / "math101"
        week1 = course / "01_weeks" / "Week_01"
        week2 = course / "01_weeks" / "Week_02"
        self.assertTrue(week1.is_dir())
        self.assertTrue(week2.is_dir())
        self.assertTrue((week1 / "topic.md").is_file())
        self.assertTrue((week1 / "tutorial.md").is_file())
        self.assertTrue((week2 / "topic.md").is_file())
        self.assertTrue((week2 / "tutorial.md").is_file())

        topic = (week1 / "topic.md").read_text(encoding="utf-8")
        for field in ("week: 1", "kind: topic", "sources:"):
            self.assertIn(field, topic)
        self.assertIn("limits-topic.md", topic)
        self.assertIn("A limit is the value", topic)

        tutorial = (week1 / "tutorial.md").read_text(encoding="utf-8")
        self.assertIn("kind: tutorial", tutorial)
        self.assertIn("limits-tutorial.md", tutorial)

    def test_index_lists_weeks_and_nodes(self):
        stage3.run(self.ws)
        index = (
            self.ws / "03_structure" / "math101" / "02_index" / "index.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Week_01", index)
        self.assertIn("Week_02", index)
        self.assertIn("math101/01_weeks/Week_01/topic.md", index)
        self.assertIn("math101/01_weeks/Week_01/tutorial.md", index)
        self.assertIn("math101/01_weeks/Week_02/topic.md", index)
        self.assertIn("math101/01_weeks/Week_02/tutorial.md", index)
        # deterministic: rerun yields identical bytes
        stage3.run(self.ws)
        again = (
            self.ws / "03_structure" / "math101" / "02_index" / "index.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(index, again)

    def test_state_files(self):
        stage3.run(self.ws)
        state_dir = self.ws / "03_structure" / "math101" / "03_state"
        state = json.loads((state_dir / ".agent_state.json").read_text())
        self.assertEqual(state["stage"], 3)
        self.assertIn("superseded_by", json.dumps(state))
        lines = (state_dir / "STATE.md").read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        self.assertIn("superseded-by", lines[0])
        self.assertTrue(any(line.startswith("stage: 3") for line in lines))

    def test_step_keys_and_contract(self):
        result = stage3.run(self.ws)
        self.assertEqual(set(result), STEP_KEYS)
        self.assertEqual(result["stage"], 3)
        self.assertEqual(result["stage_name"], "structure")
        self.assertIsInstance(result["inputs"], dict)
        self.assertIsInstance(result["outputs"], list)
        self.assertIsInstance(result["evidence"], list)
        self.assertIsInstance(result["errors"], list)

        schema = json.loads((CONTRACTS / "step.schema.json").read_text())
        for key in schema["required"]:
            self.assertIn(key, result)
        self.assertIn(result["status"], schema["properties"]["status"]["enum"])
        self.assertLessEqual(schema["properties"]["stage"]["minimum"], result["stage"])
        self.assertGreaterEqual(schema["properties"]["stage"]["maximum"], result["stage"])

    def test_missing_meta_skipped(self):
        (self.ws / "01_ingest" / "meta.json").unlink()
        result = stage3.run(self.ws)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(set(result), STEP_KEYS)
        self.assertTrue(result["evidence"])
        self.assertIn("meta.json", " ".join(result["evidence"]))
        self.assertFalse((self.ws / "03_structure").exists())

    def test_dry_run_writes_nothing(self):
        result = stage3.run(self.ws, dry_run=True)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["outputs"])
        self.assertFalse((self.ws / "03_structure").exists())

    def test_no_writes_outside_workspace(self):
        stage3.run(self.ws)
        for path in self.ws.rglob("*"):
            self.assertTrue(path.resolve().is_relative_to(self.ws.resolve()))


if __name__ == "__main__":
    unittest.main()
