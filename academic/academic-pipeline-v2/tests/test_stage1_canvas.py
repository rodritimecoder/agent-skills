#!/usr/bin/env python3
"""Tests for stage1_canvas.run() — stdlib unittest, fake deps only."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import stage1_canvas  # noqa: E402

STEP_SCHEMA = json.loads((ROOT / "contracts" / "step.schema.json").read_text())
META_SCHEMA = json.loads((ROOT / "contracts" / "meta.schema.json").read_text())


def validate(schema, instance):
    """Minimal JSON-Schema-subset validator (type/required/enum/min/max/items)."""

    def _check(value, node, path):
        if "enum" in node and value not in node["enum"]:
            raise ValueError(f"{path}: {value!r} not in {node['enum']}")
        node_type = node.get("type")
        if node_type == "object":
            if not isinstance(value, dict):
                raise ValueError(f"{path}: expected object")
            for key in node.get("required", []):
                if key not in value:
                    raise ValueError(f"{path}: missing {key!r}")
            props = node.get("properties", {})
            for key, sub in value.items():
                if key in props:
                    _check(sub, props[key], f"{path}.{key}")
        elif node_type == "array":
            if not isinstance(value, list):
                raise ValueError(f"{path}: expected array")
            if node.get("items") is not None:
                for i, sub in enumerate(value):
                    _check(sub, node["items"], f"{path}[{i}]")
        elif node_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{path}: expected integer")
        elif node_type == "string":
            if not isinstance(value, str):
                raise ValueError(f"{path}: expected string")
        if "minimum" in node and isinstance(value, (int, float)):
            if value < node["minimum"]:
                raise ValueError(f"{path}: below minimum")
        if "maximum" in node and isinstance(value, (int, float)):
            if value > node["maximum"]:
                raise ValueError(f"{path}: above maximum")

    _check(instance, schema, "$")
    return True


class FakeCanvas:
    """Records calls and returns per-week items."""

    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        week = args["week"]
        return [
            {"id": f"w{week}-page", "title": f"Week {week} Limits", "type": "page", "url": f"https://x/{week}"},
            {"id": f"w{week}-admin", "title": f"Week {week} Welcome", "type": "page", "url": ""},
            {"id": f"w{week}-tut", "title": f"Week {week} Tutorial Solutions", "type": "file", "url": ""},
        ]


def fake_classify(item):
    return "admin" in item.get("title", "").lower() or "welcome" in item.get("title", "").lower()


class Stage1CanvasTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_payload_matches_step_schema(self):
        canvas = FakeCanvas()
        result = stage1_canvas.run(
            self.workspace, deps={"canvas": canvas, "classify": fake_classify}
        )
        self.assertTrue(validate(STEP_SCHEMA, result))
        self.assertEqual(result["stage"], 1)
        self.assertEqual(result["stage_name"], "ingest")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(canvas.calls), 12)
        self.assertEqual([c["week"] for c in canvas.calls], list(range(1, 13)))

    def test_writes_markdown_per_week(self):
        result = stage1_canvas.run(
            self.workspace, deps={"canvas": FakeCanvas(), "classify": fake_classify}
        )
        week1 = self.workspace / "01_ingest" / "markdown" / "Week_01"
        self.assertTrue(week1.is_dir())
        self.assertTrue((week1 / "week-1-limits.md").is_file())
        self.assertTrue((week1 / "week-1-tutorial-solutions.md").is_file())
        self.assertFalse((week1 / "week-1-welcome.md").exists())
        self.assertIn("01_ingest/markdown/Week_12/week-12-limits.md", result["outputs"])
        self.assertIn("01_ingest/meta.json", result["outputs"])
        for rel in result["outputs"]:
            self.assertFalse(Path(rel).is_absolute())
            self.assertTrue((self.workspace / rel).is_file(), rel)

    def test_skips_classified_items(self):
        result = stage1_canvas.run(
            self.workspace, deps={"canvas": FakeCanvas(), "classify": fake_classify}
        )
        self.assertTrue(any("skipped by classifier" in line for line in result["evidence"]))
        text = " ".join(result["evidence"])
        self.assertIn("listed: 36", text)
        self.assertIn("kept: 24", text)

    def test_meta_created_and_valid(self):
        stage1_canvas.run(
            self.workspace, deps={"canvas": FakeCanvas(), "classify": fake_classify}
        )
        meta = json.loads((self.workspace / "01_ingest" / "meta.json").read_text())
        self.assertTrue(validate(META_SCHEMA, meta))
        self.assertEqual(len(meta["weeks"]), 12)
        week1 = next(w for w in meta["weeks"] if w["week"] == "Week_01")
        ids = [n["id"] for n in week1["nodes"]]
        self.assertIn("w1-page", ids)
        self.assertNotIn("w1-admin", ids)

    def test_meta_merges_by_node_id(self):
        meta_path = self.workspace / "01_ingest" / "meta.json"
        meta_path.parent.mkdir(parents=True)
        meta_path.write_text(
            json.dumps(
                {
                    "course": "MATH101",
                    "weeks": [
                        {
                            "week": "Week_01",
                            "topic": "Limits",
                            "tutorial": "",
                            "nodes": [{"id": "w1-page", "label": "Old", "kind": "page"}],
                        }
                    ],
                }
            )
        )
        stage1_canvas.run(
            self.workspace, deps={"canvas": FakeCanvas(), "classify": fake_classify}
        )
        meta = json.loads(meta_path.read_text())
        self.assertTrue(validate(META_SCHEMA, meta))
        self.assertEqual(meta["course"], "MATH101")
        week1 = next(w for w in meta["weeks"] if w["week"] == "Week_01")
        matches = [n for n in week1["nodes"] if n["id"] == "w1-page"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["label"], "Week 1 Limits")

    def test_missing_canvas_is_skipped(self):
        result = stage1_canvas.run(self.workspace)
        self.assertTrue(validate(STEP_SCHEMA, result))
        self.assertEqual(result["status"], "skipped")
        self.assertIn("canvas-cli unavailable", result["evidence"])
        self.assertEqual(result["outputs"], [])
        self.assertFalse((self.workspace / "01_ingest").exists())

    def test_canvas_error_does_not_raise(self):
        def boom(args):
            raise RuntimeError("canvas exploded")

        result = stage1_canvas.run(
            self.workspace, deps={"canvas": boom, "classify": fake_classify}
        )
        self.assertTrue(validate(STEP_SCHEMA, result))
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("canvas exploded" in e for e in result["errors"]))

    def test_dry_run_writes_nothing(self):
        result = stage1_canvas.run(
            self.workspace,
            dry_run=True,
            deps={"canvas": FakeCanvas(), "classify": fake_classify},
        )
        self.assertTrue(validate(STEP_SCHEMA, result))
        self.assertEqual(result["outputs"], [])
        self.assertFalse((self.workspace / "01_ingest").exists())
        self.assertTrue(any("dry-run" in line for line in result["evidence"]))


if __name__ == "__main__":
    unittest.main()
