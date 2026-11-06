#!/usr/bin/env python3
"""Tests for stage 4b render_anki.py (stdlib unittest only)."""

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "render_anki.py"
SCHEMA_PATH = ROOT / "contracts" / "step.schema.json"


def load_module():
    spec = importlib.util.spec_from_file_location("render_anki", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NOTE_ONE = """# Week 1 - Foundations

Reliability means the system keeps working under failure.

## Redundancy

Duplicated components remove single points of failure.

- replicated state
- health checks

## Failure modes

Crash-stop and byzantine are the two broad families.
"""

NOTE_TWO = """# Week 2 - Consensus

Agreement among replicas is the core problem.

## Quorum

Any two majorities intersect in at least one node.

## Leader election

Raft elects a leader with randomized timeouts.
"""


class RenderAnkiTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.cleaned = self.workspace / "02_sift" / "cleaned"
        self.cleaned.mkdir(parents=True)
        (self.cleaned / "note_one.md").write_text(NOTE_ONE, encoding="utf-8")
        (self.cleaned / "note_two.md").write_text(NOTE_TWO, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _html(self, workspace=None):
        self.module.run(workspace or self.workspace)
        return (Path(workspace or self.workspace) / "04_render" / "anki.html").read_text(
            encoding="utf-8"
        )

    def _data(self, html):
        match = re.search(r"var DATA = (.+?);\s*\nvar state", html, re.S)
        self.assertIsNotNone(match, "embedded DATA payload not found")
        return json.loads(match.group(1))

    # -- extraction ------------------------------------------------------
    def test_one_card_per_heading(self):
        cards = self.module.extract_cards(NOTE_ONE)
        self.assertEqual(
            [c["q"] for c in cards],
            ["Week 1 - Foundations", "Redundancy", "Failure modes"],
        )
        self.assertEqual(
            cards[0]["a"],
            "Reliability means the system keeps working under failure.",
        )
        # first paragraph only, list items after a blank line are excluded
        self.assertEqual(
            cards[1]["a"],
            "Duplicated components remove single points of failure.",
        )
        self.assertEqual(
            cards[2]["a"],
            "Crash-stop and byzantine are the two broad families.",
        )

    def test_note_without_headings_yields_no_cards(self):
        self.assertEqual(self.module.extract_cards("just a paragraph\n"), [])

    def test_run_collects_cards_from_two_notes(self):
        result = self.module.run(self.workspace)
        html = (self.workspace / "04_render" / "anki.html").read_text(encoding="utf-8")
        self.assertIn("Week 1 - Foundations", html)
        self.assertIn("Week 2 - Consensus", html)
        self.assertIn("Quorum", html)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(
            any(ev == "cards: 6" for ev in result["evidence"]),
            result["evidence"],
        )
        self.assertTrue(
            any(ev.startswith("bytes: ") for ev in result["evidence"]),
            result["evidence"],
        )

    # -- html contract ---------------------------------------------------
    def test_one_deck_per_week_directory(self):
        weekly = self.workspace / "weekly"
        cleaned = weekly / "02_sift" / "cleaned"
        (cleaned / "week_01_foundations").mkdir(parents=True)
        (cleaned / "w2").mkdir()
        (cleaned / "week_01_foundations" / "note.md").write_text(NOTE_ONE, encoding="utf-8")
        (cleaned / "w2" / "note.md").write_text(NOTE_TWO, encoding="utf-8")

        decks = self.module.collect(cleaned)
        self.assertEqual([d["title"] for d in decks], ["Week 1 - Foundations", "Week 2"])
        self.assertEqual([len(d["cards"]) for d in decks], [3, 3])
        self.assertEqual(len({d["name"] for d in decks}), 2)

        html = self._html(weekly)
        data = self._data(html)
        self.assertEqual([d["title"] for d in data], ["Week 1 - Foundations", "Week 2"])
        self.assertEqual([len(d["cards"]) for d in data], [3, 3])

    def test_week_label_normalisation(self):
        for raw, label in (
            ("week_01_foundations", "Week 1 - Foundations"),
            ("w2", "Week 2"),
            ("module 3 - protocols", "Week 3 - Protocols"),
            ("week 12", "Week 12"),
        ):
            self.assertEqual(self.module.week_label(raw), label)

    def test_heading_with_no_text_is_not_a_card(self):
        """A bare title cannot be answered, so it must not enter a deck."""
        cards = self.module.extract_cards(
            "# Week 1 overview\n\n# Limits\n\nA limit is the value a function approaches.\n"
        )
        self.assertEqual([c["q"] for c in cards], ["Limits"])

    def test_pointer_and_prompt_answers_are_not_cards(self):
        text = "# Limits\n\nSee Lecture Notes.\n\n# Derivative\n\nExpress the result:\n"
        self.assertEqual(self.module.extract_cards(text), [])

    def test_page_ships_a_static_card_list_without_javascript(self):
        decks = [{"name": "week_01", "title": "Week 1", "cards": [{"q": "Q1", "a": "A1"}]}]
        page = self.module.render_html(decks)
        self.assertIn('class="static"', page)
        self.assertIn("All cards", page)
        self.assertIn("Q1", page)
        self.assertNotIn("__STATIC__", page)

    def test_deck_selector_present(self):
        html = self._html()
        self.assertIn('<select id="deck"', html)
        self.assertIn("function renderDeckOptions", html)
        self.assertIn("function allDecks", html)
        self.assertIn("All cards", html)
        self.assertIn('d.title + " (" + d.cards.length', html)

    def test_review_mode_flip_and_running_score(self):
        html = self._html()
        for token in (
            'id="flip"',
            'id="correct"',
            'id="incorrect"',
            'id="score"',
            "function flip",
            "function grade",
            "function renderScore",
            "state.scores",
        ):
            self.assertIn(token, html, token)
        self.assertRegex(html, r'id="score"[^>]*>Score 0/0 \(0%\)<')
        self.assertIn("s.right += 1", html)
        self.assertIn("s.wrong += 1", html)
        self.assertIn("s.streak", html)
        # grading unlocks only after the answer is revealed
        self.assertIn("!state.flipped", html)

    def test_tsv_handlers_present(self):
        html = self._html()
        self.assertIn("function exportTSV", html)
        self.assertIn("function importTSV", html)
        self.assertIn("function toTSV", html)
        self.assertIn("text/tab-separated-values", html)
        self.assertIn('id="importTSV"', html)
        self.assertIn("Export TSV", html)
        self.assertIn("a.download", html)

    def test_no_external_script_src(self):
        html = self._html()
        self.assertEqual(re.findall(r"<script[^>]*\bsrc\s*=", html, re.I), [])
        self.assertEqual(
            re.findall(r"""<script[^>]*src\s*=\s*['"]?https?://""", html, re.I), []
        )
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)

    def test_module_stays_under_550_lines(self):
        lines = MODULE_PATH.read_text(encoding="utf-8").splitlines()
        self.assertLess(len(lines), 550)

    def test_review_and_progress_hooks_present(self):
        self.module.run(self.workspace)
        html = (self.workspace / "04_render" / "anki.html").read_text(encoding="utf-8")
        for token in ('id="flip"', 'id="next"', 'id="prev"', 'id="progress"', "function flip"):
            self.assertIn(token, html)
        self.assertRegex(html, r'id="progress"[^>]*>0 / 0 reviewed<')

    def test_single_output_file(self):
        self.module.run(self.workspace)
        rendered = sorted(p.name for p in (self.workspace / "04_render").iterdir())
        self.assertEqual(rendered, ["anki.html"])

    def test_dry_run_writes_nothing(self):
        result = self.module.run(self.workspace, dry_run=True)
        self.assertFalse((self.workspace / "04_render" / "anki.html").exists())
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["outputs"], [])

    # -- step evidence contract ------------------------------------------
    def test_step_keys_exact_and_schema_valid(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        result = self.module.run(self.workspace)
        self.assertEqual(sorted(result), sorted(schema["required"]))
        self.assertEqual(result["stage"], 4)
        self.assertEqual(result["stage_name"], "render")
        self.assertIn(result["status"], schema["properties"]["status"]["enum"])
        self.assertIsInstance(result["inputs"], dict)
        self.assertIsInstance(result["outputs"], list)
        self.assertIsInstance(result["evidence"], list)
        self.assertIsInstance(result["errors"], list)
        self.assertTrue(1 <= result["stage"] <= 5)
        for key in schema["required"]:
            self.assertIn(key, result)


if __name__ == "__main__":
    unittest.main()
