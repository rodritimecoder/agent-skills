#!/usr/bin/env python3
"""Tests for stage 5 gates (stdlib unittest, tempfile workspaces, fake deps)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gates  # noqa: E402

HTML = (
    "<!doctype html>\n<html><body><h1>{t}</h1>"
    "<p>Covering Week_01 of the course.</p></body></html>\n"
)

META = {
    "course": "48520",
    "weeks": [
        {
            "week": "Week_01",
            "topic": "Intro",
            "tutorial": "Tutorial 1",
            "nodes": [{"id": "n1", "label": "Intro", "kind": "topic"}],
        }
    ],
}


def build_workspace(root, missing=None):
    """Create a gate-passing workspace; `missing` names one artifact to omit."""
    root = Path(root)
    (root / "01_ingest").mkdir(parents=True)
    if missing != "meta.json":
        (root / "01_ingest" / "meta.json").write_text(json.dumps(META), encoding="utf-8")

    (root / "02_sift").mkdir()
    if missing != "notes.md":
        (root / "02_sift" / "notes.md").write_text(
            "# Week 1\n\n```python\nx = 1\n```\n\n$$a+b$$\n$$c$$\n", encoding="utf-8"
        )
    (root / "02_sift" / "sift_report.json").write_text(
        json.dumps({"items": [{"name": "notes.md", "confidence": 0.91}]}), encoding="utf-8"
    )

    course = root / "03_structure" / "48520"
    (course / "01_weeks" / "Week_01").mkdir(parents=True)
    (course / "01_weeks" / "Week_01" / "topic.md").write_text("# Intro\n", encoding="utf-8")
    (course / "02_index").mkdir()
    (course / "02_index" / "index.md").write_text(
        "- [Week_01](../01_weeks/Week_01/topic.md)\n", encoding="utf-8"
    )

    render = root / "04_render"
    render.mkdir()
    for name in gates.EXPECTED_HTML:
        if name == missing:
            continue
        (render / name).write_text(HTML.format(t=name), encoding="utf-8")
    return root


class GatesTest(unittest.TestCase):
    def test_passing_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = build_workspace(Path(tmp) / "ws")
            calls = []

            def judge(workspace):
                calls.append(workspace)
                return {"accepted": True, "reason": "sample is faithful"}

            result = gates.run(ws, deps={"judge": judge})

            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["ok"])
            self.assertEqual(result["stage"], 5)
            for key in (
                "stage",
                "stage_name",
                "status",
                "started_at",
                "finished_at",
                "inputs",
                "outputs",
                "evidence",
                "errors",
            ):
                self.assertIn(key, result)
            self.assertEqual(result["errors"], [])
            self.assertEqual(len(calls), 1)
            self.assertTrue(all("gate" in str(g) for g in result["evidence"]))

            step = ws / "05_verify" / "step_05.json"
            self.assertTrue(step.is_file())
            written = json.loads(step.read_text(encoding="utf-8"))
            self.assertEqual(written["status"], "ok")
            self.assertEqual(written["stage"], 5)
            self.assertEqual(len(written["gates"]), 5)
            self.assertTrue(all(g["status"] == "ok" for g in written["gates"]))

    def test_missing_render_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = build_workspace(Path(tmp) / "ws", missing="anki.html")

            result = gates.run(ws, deps={"judge": lambda _ws: True})

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any("anki.html" in line for line in result["evidence"]))
            written = json.loads(
                (ws / "05_verify" / "step_05.json").read_text(encoding="utf-8")
            )
            statuses = {g["gate"]: g["status"] for g in written["gates"]}
            self.assertEqual(statuses["gate4_render"], "failed")
            self.assertEqual(statuses["gate1_assets"], "ok")

    def test_gate4_fails_when_a_page_omits_a_declared_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = build_workspace(Path(tmp) / "ws")
            anki = Path(ws) / "04_render" / "anki.html"
            anki.write_text("<!doctype html>\n<html><body><h1>Anki Hub</h1></body></html>\n", encoding="utf-8")

            result = gates.run(ws, deps={"judge": lambda _ws: {"accepted": True}})

            self.assertFalse(result["ok"], result)
            gate4 = [g for g in result["gates"] if g["gate"] == "gate4_render"][0]
            self.assertEqual(gate4["status"], "failed")
            self.assertIn("Week_01", "\n".join(result["evidence"]))

    def test_missing_judge_is_skipped_not_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = build_workspace(Path(tmp) / "ws")

            result = gates.run(ws, deps={})

            self.assertEqual(result["status"], "skipped")
            self.assertFalse(result["ok"])
            self.assertTrue(any("gate5_judge: skipped" in line for line in result["evidence"]))

    def test_gate3_missing_week_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = build_workspace(Path(tmp) / "ws")
            index = ws / "03_structure" / "48520" / "02_index" / "index.md"
            index.write_text("- nothing here\n", encoding="utf-8")

            ok, evidence = gates.gate3_okf(ws, {})
            self.assertFalse(ok)
            self.assertTrue(any("Week_01" in line for line in evidence))

    def test_gate4_external_script_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = build_workspace(Path(tmp) / "ws")
            page = ws / "04_render" / "graph.html"
            page.write_text(
                '<html><body><script src="https://cdn.example.com/x.js"></script></body></html>',
                encoding="utf-8",
            )

            ok, evidence = gates.gate4_render(ws, {})
            self.assertFalse(ok)
            self.assertTrue(any("external script src" in line for line in evidence))

    def test_gate1_invalid_meta_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = build_workspace(Path(tmp) / "ws")
            (ws / "01_ingest" / "meta.json").write_text(
                json.dumps({"course": "48520"}), encoding="utf-8"
            )

            ok, evidence = gates.gate1_assets(ws, {})
            self.assertFalse(ok)
            self.assertTrue(any("weeks" in line for line in evidence))

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = build_workspace(Path(tmp) / "ws")
            result = gates.run(ws, dry_run=True, deps={"judge": lambda _ws: True})

            self.assertEqual(result["status"], "skipped")
            self.assertFalse((ws / "05_verify" / "step_05.json").exists())


if __name__ == "__main__":
    unittest.main()
