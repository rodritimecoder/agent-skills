#!/usr/bin/env python3
"""Tests for stage 4c Cornell sheet renderer (stdlib unittest only)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_cornell  # noqa: E402

TWO_NOTES = """# Photosynthesis

Plants convert light energy into chemical energy.

# Calvin Cycle

The Calvin Cycle fixes carbon dioxide into glucose.
"""


class FakeNotes:
    """In-memory stand-in for the filesystem-backed deps."""

    def __init__(self, files):
        self.files = dict(files)
        self.written = {}

    def list_notes(self, cleaned_dir):
        return [Path(name) for name in sorted(self.files)]

    def read_note(self, path):
        return self.files[Path(path).name]

    def write_html(self, path, text):
        self.written[str(path)] = text
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")


class RenderCornellTests(unittest.TestCase):
    def test_one_pair_per_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            fake = FakeNotes({"Week_01.md": TWO_NOTES})
            result = render_cornell.run(
                workspace,
                deps={
                    "list_notes": fake.list_notes,
                    "read_note": fake.read_note,
                    "write_html": fake.write_html,
                },
            )
            self.assertEqual("ok", result["status"])
            self.assertEqual([], result["errors"])

            pairs = render_cornell.parse_pairs(TWO_NOTES)
            self.assertEqual(["Photosynthesis", "Calvin Cycle"], [p["cue"] for p in pairs])

            page = fake.written[str(workspace / "04_render" / "cornell.html")]
            self.assertEqual(2, page.count('class="pair"'))
            self.assertIn("Plants convert light energy", page)
            self.assertIn("Calvin Cycle fixes carbon dioxide", page)

            # Payload reports the pair count and the emitted size.
            evidence = {e["check"]: e for e in result["evidence"]}
            self.assertEqual(2, evidence["cornell_pairs"]["pair_count"])
            self.assertGreater(evidence["size_bytes"]["bytes"], 0)
            self.assertEqual(
                str(workspace / "04_render" / "cornell.html"), result["outputs"][0]["path"]
            )

    def test_renders_a_summary_section_from_the_notes_themselves(self):
        """The Cornell rubric requires cues, notes AND a summary."""
        page = render_cornell.render_html(render_cornell.parse_pairs(TWO_NOTES))
        self.assertIn('class="summary"', page)
        self.assertIn("Summary", page)
        # The summary quotes its own note; it must not invent content.
        self.assertIn("summary &mdash;", page.lower())

    def test_empty_note_bodies_are_not_rendered_as_pairs(self):
        text = "# Week 1 overview\n\n# Limits\n\nA limit is the value a function approaches.\n"
        page = render_cornell.render_html(render_cornell.parse_pairs(text))
        self.assertEqual(page.count('class="pair"'), 1, page)

    def test_print_stylesheet_present(self):
        page = render_cornell.render_html(render_cornell.parse_pairs(TWO_NOTES))
        self.assertIn("@media print", page)
        self.assertIn("@page", page)
        self.assertTrue(page.lstrip().startswith("<!DOCTYPE html>"))

    def test_no_external_script_src(self):
        page = render_cornell.render_html(render_cornell.parse_pairs(TWO_NOTES))
        self.assertNotIn("src=", page)
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)
        self.assertNotIn("<link", page)
        self.assertIn("quizToggle", page)
        self.assertIn("quiz-on", page)

    def test_missing_dep_skips_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = render_cornell.run(Path(tmp), deps={})
            self.assertEqual("skipped", result["status"])
            self.assertEqual([], result["errors"])
            self.assertTrue(result["evidence"])

    def test_payload_matches_step_schema_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "02_sift" / "cleaned").mkdir(parents=True)
            (workspace / "02_sift" / "cleaned" / "w1.md").write_text(TWO_NOTES, encoding="utf-8")
            result = render_cornell.run(workspace)

            schema = json.loads((ROOT / "contracts" / "step.schema.json").read_text(encoding="utf-8"))
            for key in schema["required"]:
                self.assertIn(key, result)
            self.assertIn(result["status"], schema["properties"]["status"]["enum"])
            self.assertIsInstance(result["stage"], int)
            self.assertIsInstance(result["inputs"], dict)
            self.assertIsInstance(result["outputs"], list)
            self.assertIsInstance(result["evidence"], list)
            self.assertIsInstance(result["errors"], list)
            self.assertEqual("ok", result["status"])
            self.assertTrue((workspace / "04_render" / "cornell.html").is_file())

    def test_empty_cleaned_dir_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "02_sift" / "cleaned").mkdir(parents=True)
            result = render_cornell.run(workspace)
            self.assertEqual("skipped", result["status"])
            self.assertEqual([], result["errors"])


if __name__ == "__main__":
    unittest.main()
