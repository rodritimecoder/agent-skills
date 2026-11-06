#!/usr/bin/env python3
"""Tests for stage1_zoom.run (stdlib only, fake deps, no network)."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "stage1_zoom.py"
STEP_SCHEMA = json.loads((ROOT / "contracts" / "step.schema.json").read_text(encoding="utf-8"))
META_SCHEMA = json.loads((ROOT / "contracts" / "meta.schema.json").read_text(encoding="utf-8"))


def load_module():
    spec = importlib.util.spec_from_file_location("stage1_zoom", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["stage1_zoom"] = module
    spec.loader.exec_module(module)
    return module


def validate(schema, instance):
    """Minimal JSON-Schema-subset validator (type/required/enum/items)."""

    def check(value, node, path):
        if "enum" in node and value not in node["enum"]:
            raise ValueError(f"{path}: {value!r} not in enum")
        node_type = node.get("type")
        if node_type == "object":
            if not isinstance(value, dict):
                raise ValueError(f"{path}: expected object")
            for key in node.get("required", []):
                if key not in value:
                    raise ValueError(f"{path}: missing {key!r}")
            for key, sub in value.items():
                if key in node.get("properties", {}):
                    check(sub, node["properties"][key], f"{path}.{key}")
        elif node_type == "array":
            if not isinstance(value, list):
                raise ValueError(f"{path}: expected array")
            if "items" in node:
                for i, item in enumerate(value):
                    check(item, node["items"], f"{path}[{i}]")
        elif node_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{path}: expected integer")
        elif node_type == "string":
            if not isinstance(value, str):
                raise ValueError(f"{path}: expected string")
        if "minimum" in node and isinstance(value, (int, float)) and value < node["minimum"]:
            raise ValueError(f"{path}: below minimum")
        if "maximum" in node and isinstance(value, (int, float)) and value > node["maximum"]:
            raise ValueError(f"{path}: above maximum")

    check(instance, schema, "$")
    return True


RECORDINGS = [
    {"id": "rec-abc123", "week": "1", "title": "Limits lecture"},
    {"id": "rec-def456", "week": "Week_02", "title": "Derivatives lecture"},
]


class Stage1ZoomTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name)

    def fake_deps(self, recordings=None):
        recordings = RECORDINGS if recordings is None else recordings
        calls = []

        def fetch(recording_id):
            calls.append(recording_id)
            return {
                "transcript_vtt": f"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n{recording_id}\n",
                "keyframes": [f"/slides/{recording_id}_001.png", f"/slides/{recording_id}_002.png"],
            }

        return {
            "list_recordings": lambda: list(recordings),
            "fetch": fetch,
            "course": "MATH101",
        }, calls

    def test_missing_deps_skips_without_raising(self):
        result = self.module.run(self.workspace)
        self.assertTrue(validate(STEP_SCHEMA, result))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["stage"], 1)
        self.assertEqual(result["stage_name"], "ingest")
        self.assertEqual(result["outputs"], [])
        joined = " ".join(result["evidence"])
        self.assertIn("list_recordings", joined)
        self.assertIn("fetch", joined)
        self.assertIn("requests", joined)
        self.assertFalse((self.workspace / "01_ingest").exists())

    def test_partial_deps_skip_and_name_the_missing_callable(self):
        result = self.module.run(self.workspace, deps={"list_recordings": lambda: []})
        self.assertTrue(validate(STEP_SCHEMA, result))
        self.assertEqual(result["status"], "skipped")
        self.assertTrue(any("fetch" in line for line in result["evidence"]))
        self.assertFalse(any("list_recordings (" in line for line in result["evidence"]))

    def test_ok_writes_transcripts_and_meta(self):
        deps, calls = self.fake_deps()
        result = self.module.run(self.workspace, deps=deps)
        self.assertTrue(validate(STEP_SCHEMA, result), result)
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(result["errors"], [])

        vtt = self.workspace / "01_ingest" / "transcripts" / "Week_01" / "rec-abc123.vtt"
        self.assertTrue(vtt.is_file())
        self.assertIn("rec-abc123", vtt.read_text(encoding="utf-8"))
        self.assertTrue(
            (self.workspace / "01_ingest" / "transcripts" / "Week_02" / "rec-def456.vtt").is_file()
        )

        # fetch is only ever asked for the recording id (never a video download).
        self.assertEqual(calls, ["rec-abc123", "rec-def456"])

        meta = json.loads((self.workspace / "01_ingest" / "meta.json").read_text(encoding="utf-8"))
        self.assertTrue(validate(META_SCHEMA, meta), meta)
        self.assertEqual(meta["course"], "MATH101")
        self.assertEqual([w["week"] for w in meta["weeks"]], ["Week_01", "Week_02"])
        nodes = meta["weeks"][0]["nodes"]
        transcript_nodes = [n for n in nodes if n["kind"] == "transcript"]
        self.assertEqual(len(transcript_nodes), 1)
        self.assertEqual(
            transcript_nodes[0]["keyframes"],
            ["/slides/rec-abc123_001.png", "/slides/rec-abc123_002.png"],
        )

        # All outputs are workspace-relative paths that exist on disk.
        for rel in result["outputs"]:
            self.assertFalse(Path(rel).is_absolute(), rel)
            self.assertTrue((self.workspace / rel).exists(), rel)
        self.assertIn("01_ingest/meta.json", result["outputs"])
        self.assertEqual(result["inputs"]["counts"]["recordings"], 2)
        self.assertEqual(result["inputs"]["counts"]["transcripts"], 2)
        self.assertEqual(result["inputs"]["counts"]["keyframes"], 4)

    def test_zoom_lane_preserves_canvas_nodes_already_in_meta(self):
        """A second lane must merge into meta.json, never replace it.

        Regression: stage1_zoom used to write meta.json outright, so running it
        after stage1_canvas deleted every Canvas node (0 weeks left).
        """
        ingest = self.workspace / "01_ingest"
        ingest.mkdir(parents=True, exist_ok=True)
        prior = {
            "course": "ELEC101",
            "weeks": [
                {
                    "week": "Week_01",
                    "topic": "Basic Laws",
                    "tutorial": "Tutorial Week 1",
                    "nodes": [{"id": "canvas-1", "label": "Week 1 notes", "kind": "page"}],
                }
            ],
        }
        (ingest / "meta.json").write_text(json.dumps(prior, indent=2) + "\n", encoding="utf-8")

        deps, _calls = self.fake_deps()
        result = self.module.run(self.workspace, deps=deps)
        self.assertEqual(result["status"], "ok", result["errors"])

        meta = json.loads((ingest / "meta.json").read_text(encoding="utf-8"))
        self.assertTrue(validate(META_SCHEMA, meta), meta)
        self.assertEqual(meta["course"], "ELEC101")
        week1 = next(w for w in meta["weeks"] if w["week"] == "Week_01")
        ids = [n["id"] for n in week1["nodes"]]
        self.assertIn("canvas-1", ids, "the Canvas node was deleted by the Zoom lane")
        self.assertIn("rec-abc123", ids)
        self.assertEqual(week1["topic"], "Basic Laws")
        self.assertEqual(week1["tutorial"], "Tutorial Week 1")
        self.assertIn("Week_02", [w["week"] for w in meta["weeks"]])

    def test_no_recordings_keeps_existing_meta_untouched(self):
        """Zero recordings must not rewrite a meta.json that already has nodes."""
        ingest = self.workspace / "01_ingest"
        ingest.mkdir(parents=True, exist_ok=True)
        prior = {"course": "ELEC101", "weeks": [{"week": "Week_01", "topic": "x", "tutorial": "", "nodes": []}]}
        path = ingest / "meta.json"
        path.write_text(json.dumps(prior, indent=2) + "\n", encoding="utf-8")
        before = path.read_text(encoding="utf-8")

        deps = {"list_recordings": lambda: [], "fetch": lambda _id: {}, "course": "ELEC101"}
        result = self.module.run(self.workspace, deps=deps)
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertTrue(any("kept existing" in line for line in result["evidence"]), result["evidence"])

    def test_no_video_files_written(self):
        deps, _ = self.fake_deps()
        self.module.run(self.workspace, deps=deps)
        suffixes = {p.suffix for p in self.workspace.rglob("*") if p.is_file()}
        self.assertFalse(suffixes & {".mp4", ".m4a", ".webm", ".mov"})

    def test_dry_run_writes_nothing_and_does_not_fetch(self):
        deps, calls = self.fake_deps()
        result = self.module.run(self.workspace, dry_run=True, deps=deps)
        self.assertTrue(validate(STEP_SCHEMA, result))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls, [])
        self.assertEqual(result["outputs"], [])
        self.assertEqual(list(self.workspace.rglob("*")), [])

    def test_fetch_failure_is_reported_not_raised(self):
        def boom(recording_id):
            raise RuntimeError(f"no passcode for {recording_id}")

        deps = {"list_recordings": lambda: list(RECORDINGS), "fetch": boom}
        result = self.module.run(self.workspace, deps=deps)
        self.assertTrue(validate(STEP_SCHEMA, result))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["errors"]), 2)
        self.assertIn("rec-abc123", result["errors"][0])
        # meta.json is still written so downstream stages see a consistent tree.
        self.assertTrue((self.workspace / "01_ingest" / "meta.json").is_file())

    def test_list_recordings_failure_is_reported_not_raised(self):
        def boom():
            raise RuntimeError("zoom api down")

        result = self.module.run(self.workspace, deps={"list_recordings": boom, "fetch": lambda _: {}})
        self.assertTrue(validate(STEP_SCHEMA, result))
        self.assertEqual(result["status"], "failed")
        self.assertIn("zoom api down", result["errors"][0])

    def test_unsafe_ids_stay_inside_workspace(self):
        deps, _ = self.fake_deps([{"id": "../../etc/passwd", "week": "../2", "title": "evil"}])
        result = self.module.run(self.workspace, deps=deps)
        self.assertEqual(result["status"], "ok", result["errors"])
        for rel in result["outputs"]:
            self.assertFalse(rel.startswith(".."), rel)
            self.assertTrue((self.workspace / rel).resolve().is_relative_to(self.workspace.resolve()))


if __name__ == "__main__":
    unittest.main()
