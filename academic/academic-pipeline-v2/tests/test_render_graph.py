#!/usr/bin/env python3
"""Stage 4a renderer tests (stdlib unittest)."""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_graph  # noqa: E402

SCHEMA = json.loads((ROOT / "contracts" / "step.schema.json").read_text(encoding="utf-8"))
REQUIRED = set(SCHEMA["required"])
NODE_IDS = ["w1-topic", "w1-solution", "w2-topic"]

META = {
    "course": "48430 - Fundamentals of C Programming",
    "weeks": [
        {
            "week": "Week 01",
            "topic": "Variables and types",
            "tutorial": "Tutorial 1",
            "nodes": [
                {"id": "w1-topic", "label": "Variables & types", "kind": "topic"},
                {"id": "w1-solution", "label": "Tutorial 1 worked answers", "kind": "solution"},
            ],
        },
        {
            "week": "Week 02",
            "topic": "Control flow",
            "tutorial": "",
            "nodes": [{"id": "w2-topic", "label": "Loops and branches", "kind": "topic"}],
        },
    ],
}


MATCH_SCRIPT = r'<script id="%s" type="application/json">(.*?)</script>'


def _embedded_json(page: str, element_id: str):
    match = re.search(MATCH_SCRIPT % re.escape(element_id), page, flags=re.S)
    if match is None:
        raise AssertionError("missing embedded JSON block %r" % element_id)
    return json.loads(match.group(1).replace("<\\/", "</"))


class RenderGraphTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        (self.ws / "01_ingest").mkdir(parents=True)
        (self.ws / "01_ingest" / "meta.json").write_text(json.dumps(META), encoding="utf-8")
        self.step = render_graph.run(self.ws)
        self.html_path = self.ws / "04_render" / "graph.html"
        self.html = self.html_path.read_text(encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_file_exists(self):
        self.assertTrue(self.html_path.is_file(), "graph.html was not emitted")
        self.assertEqual(self.step["evidence"][0]["path"], str(self.html_path))

    def test_has_canvas_or_svg(self):
        self.assertTrue("<canvas" in self.html or "<svg" in self.html)

    def test_contains_every_node_id(self):
        for node_id in NODE_IDS:
            self.assertIn(node_id, self.html, "missing node id %r" % node_id)

    def test_week_chip_per_week(self):
        weeks = [week["week"] for week in META["weeks"]]
        self.assertIn('data-week="*"', self.html, "missing all-weeks chip")
        for week in weeks:
            self.assertIn('data-week="%s"' % week, self.html, "missing chip for %r" % week)
        chips = re.findall(r'class="chip[^"]*"[^>]*data-week="[^"]+"', self.html)
        self.assertEqual(len(chips), len(weeks) + 1, "expected one chip per week plus all-weeks")

    def test_week_chips_filter_graph(self):
        # Every node and every edge carries the week key the chips filter on.
        node_weeks = re.findall(r'class="node"[^>]*data-week="([^"]+)"', self.html)
        self.assertEqual(sorted(node_weeks), sorted(["Week 01", "Week 01", "Week 02"]))
        self.assertIn('classList.toggle("off"', self.html)

    def test_edges_drawn_to_week_centre(self):
        self.assertIn("drawEdge(", self.html, "no edge-drawing call found")
        specs = _embedded_json(self.html, "edge-data")
        self.assertEqual(len(specs), len(NODE_IDS), "expected one spoke per node")
        for spec in specs:
            for key in ("week", "id", "x1", "y1", "x2", "y2"):
                self.assertIn(key, spec, "edge spec missing %r" % key)
        self.assertEqual({spec["week"] for spec in specs}, {"Week 01", "Week 02"})
        self.assertEqual({spec["id"] for spec in specs}, set(NODE_IDS))
        self.assertIn('id="edge-layer"', self.html)

    def test_click_shows_settings_panel(self):
        self.assertIn('el.addEventListener("click"', self.html)
        for field in ("p-id", "p-label", "p-kind", "p-week"):
            self.assertIn('id="%s"' % field, self.html)
        self.assertIn("panel.week.textContent", self.html)

    def test_escape_clears_selection(self):
        self.assertIn('ev.key === "Escape"', self.html)
        self.assertIn("clearSelection", self.html)
        self.assertIn("showPanel(PLACEHOLDER)", self.html)

    def test_no_remote_script_src(self):
        for tag in re.findall(r"<script\b[^>]*>", self.html, flags=re.I):
            self.assertNotRegex(tag, r"""(?i)src\s*=\s*["']?https?://""")
        self.assertNotRegex(self.html, r"""(?i)<script[^>]+src=""")
        self.assertNotRegex(self.html, r"""https?://[^"'\\s]+\.js""")

    def test_injects_meta_json(self):
        self.assertIn('id="meta-data"', self.html)
        self.assertIn("Week 01", self.html)
        self.assertIn("Week 02", self.html)

    def test_step_keys_exact(self):
        self.assertEqual(set(self.step) - {"html_path"}, REQUIRED)
        self.assertEqual(self.step["stage"], 4)
        self.assertEqual(self.step["stage_name"], "render")
        self.assertEqual(self.step["status"], "ok")
        self.assertIsInstance(self.step["inputs"], dict)
        self.assertIsInstance(self.step["outputs"], list)
        self.assertIsInstance(self.step["errors"], list)
        evidence = self.step["evidence"][0]
        self.assertIn("path", evidence)
        self.assertEqual(evidence["bytes"], self.html_path.stat().st_size)

    def test_week_edges_and_panel(self):
        self.assertIn('<g id="edge-layer">', self.html)
        for panel_id in ("p-id", "p-label", "p-kind", "p-week"):
            self.assertIn('id="%s"' % panel_id, self.html)
        self.assertIn("legend-item", self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
