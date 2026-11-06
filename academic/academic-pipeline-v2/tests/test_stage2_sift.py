"""Tests for Stage 2 (sift): fingerprinting, dedupe, routing, report schema."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CONTRACTS = ROOT / "contracts"

sys.path.insert(0, str(SCRIPTS))
import stage2_sift  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "pipeline_test_contracts", Path(__file__).resolve().parent / "test_contracts.py"
)
_tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tc)
validate = _tc.validate


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class Stage2SiftTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)
        self.ingest = self.ws / "01_ingest"
        self.step_schema = json.loads((CONTRACTS / "step.schema.json").read_text())
        self.sift_schema = json.loads((CONTRACTS / "sift_report.schema.json").read_text())

    def tearDown(self):
        self._tmp.cleanup()

    def test_pipeline_scaffolding_is_not_sifted_as_course_material(self):
        """01_ingest/CONTEXT.md is written by the dispatcher, not by the course.

        Regression: it used to be copied into 02_sift/cleaned and rendered as a
        note, so every study sheet opened with "Stage 1: Ingest Folder".
        """
        _write(self.ingest / "CONTEXT.md", "# Stage 1: Ingest\n\nFolder: 01_ingest\n")
        _write(self.ingest / "markdown" / "week1.md", "Limits notes\n")

        result = stage2_sift.run(self.ws)
        self.assertEqual(result["status"], "ok", result["errors"])
        report = json.loads((self.ws / "02_sift" / "sift_report.json").read_text())
        sources = [i["source"] for i in report["items"]]
        self.assertNotIn("CONTEXT.md", sources)
        self.assertIn("markdown/week1.md", sources)
        self.assertFalse((self.ws / "02_sift" / "cleaned" / "CONTEXT.md").exists())

    def test_frontmatter_id_is_the_report_id(self):
        """Stage 3 matches notes by their own frontmatter id, so the report must too."""
        _write(
            self.ingest / "markdown" / "week1.md",
            "---\nid: canvas-42\ntitle: Limits\nweek: 1\nkind: topic\n---\n\n# Limits\n\nA limit.\n",
        )
        result = stage2_sift.run(self.ws)
        self.assertEqual(result["status"], "ok", result["errors"])
        report = json.loads((self.ws / "02_sift" / "sift_report.json").read_text())
        self.assertEqual([i["id"] for i in report["items"]], ["canvas-42"])

    def test_fingerprint_ignores_whitespace_and_case(self):
        a = stage2_sift.fingerprint("Hello   World\n")
        b = stage2_sift.fingerprint("hello world")
        self.assertEqual(a, b)
        self.assertNotEqual(a, stage2_sift.fingerprint("hello worlds"))

    def test_missing_ingest_dir_is_skipped(self):
        result = stage2_sift.run(self.ws)
        validate(self.step_schema, result)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["stage"], 2)
        self.assertEqual(result["stage_name"], "sift")
        self.assertEqual(result["errors"], [])
        self.assertFalse((self.ws / "02_sift" / "sift_report.json").exists())

    def test_dedupe_without_classifier(self):
        _write(self.ingest / "markdown" / "week1.md", "Limits notes\n")
        _write(self.ingest / "markdown" / "week1_copy.md", " limits   notes ")
        _write(self.ingest / "transcripts" / "week2.md", "Derivatives\n")

        result = stage2_sift.run(self.ws)
        validate(self.step_schema, result)
        self.assertEqual(result["status"], "ok")

        report = json.loads((self.ws / "02_sift" / "sift_report.json").read_text())
        validate(self.sift_schema, report)
        items = report["items"]
        self.assertEqual(len(items), 3)
        routes = {i["source"]: i["route"] for i in items}
        self.assertEqual(routes["markdown/week1.md"], "keep")
        self.assertEqual(routes["markdown/week1_copy.md"], "drop")
        self.assertEqual(routes["transcripts/week2.md"], "keep")
        self.assertTrue(all(i["confidence"] == 0.0 for i in items))
        dup = [i for i in items if i["source"] == "markdown/week1_copy.md"][0]
        self.assertTrue(dup["decisions"]["is_duplicate"])

        cleaned = self.ws / "02_sift" / "cleaned"
        self.assertTrue((cleaned / "markdown" / "week1.md").is_file())
        self.assertTrue((cleaned / "transcripts" / "week2.md").is_file())
        self.assertFalse((cleaned / "markdown" / "week1_copy.md").exists())
        self.assertIn(str(self.ws / "02_sift" / "sift_report.json"), result["outputs"])
        self.assertTrue(
            any(e.get("status") == "unavailable" for e in result["evidence"]),
            result["evidence"],
        )

    def test_classifier_routes_keep_review_drop(self):
        _write(self.ingest / "keep.md", "Lecture content about integrals.")
        _write(self.ingest / "review.md", "Ambiguous tutorial chatter.")
        _write(self.ingest / "drop.md", "Room change announcement.")

        def classify(item):
            self.assertIsInstance(item, dict)
            self.assertIn("id", item)
            self.assertIn("text", item)
            if "Lecture" in item["text"]:
                return {"admin_fluff": False, "confidence": 0.95}
            if "Ambiguous" in item["text"]:
                return {"admin_fluff": False, "confidence": 0.4}
            return {"admin_fluff": True, "confidence": 0.9}

        result = stage2_sift.run(self.ws, deps={"classify": classify})
        validate(self.step_schema, result)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["errors"], [])

        report = json.loads((self.ws / "02_sift" / "sift_report.json").read_text())
        validate(self.sift_schema, report)
        by_source = {i["source"]: i for i in report["items"]}
        self.assertEqual(by_source["keep.md"]["route"], "keep")
        self.assertEqual(by_source["review.md"]["route"], "review")
        self.assertEqual(by_source["drop.md"]["route"], "drop")
        self.assertAlmostEqual(by_source["keep.md"]["confidence"], 0.95)
        self.assertEqual(by_source["drop.md"]["decisions"]["is_admin_fluff"], True)

        cleaned = self.ws / "02_sift" / "cleaned"
        self.assertTrue((cleaned / "keep.md").is_file())
        self.assertFalse((cleaned / "review.md").exists())
        self.assertFalse((cleaned / "drop.md").exists())

    def test_raising_classifier_does_not_raise(self):
        _write(self.ingest / "note.md", "Some note")

        def classify(item):
            raise RuntimeError("model offline")

        result = stage2_sift.run(self.ws, deps={"classify": classify})
        validate(self.step_schema, result)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["evidence"][-1]["counts"]["keep"], 1)
        report = json.loads((self.ws / "02_sift" / "sift_report.json").read_text())
        self.assertEqual(report["items"][0]["route"], "keep")
        self.assertEqual(report["items"][0]["confidence"], 0.0)

    def test_dry_run_writes_nothing(self):
        _write(self.ingest / "note.md", "Some note")
        result = stage2_sift.run(self.ws, dry_run=True, deps={})
        validate(self.step_schema, result)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["outputs"], [])
        self.assertFalse((self.ws / "02_sift").exists())


if __name__ == "__main__":
    unittest.main()
