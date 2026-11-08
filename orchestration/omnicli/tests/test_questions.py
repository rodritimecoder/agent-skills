"""Tests for the distilled-question gate and snapshot.

Run:
    python3 tests/test_questions.py

The semantic half of the gate is exercised with a fake embedder, so the suite
runs with the embedding server down and cannot drift with the model slot.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from catalog import question_build, questions  # noqa: E402


SOURCE = (
    "Download transcripts, slide keyframes, and metadata from Zoom cloud "
    "recordings without API admin credentials."
)
SKILL = "zoom-recorder"


class TestGate(unittest.TestCase):
    def test_accepts_a_grounded_question(self):
        ok, reason = questions.gate(
            "pull the transcript and slides out of a cloud recording",
            "Download transcripts, slide keyframes, and metadata",
            SOURCE, SKILL,
        )
        self.assertTrue(ok, reason)

    def test_rejects_a_quote_that_is_not_verbatim(self):
        ok, reason = questions.gate(
            "get the captions from a recording",
            "Download the transcript and the slide deck",
            SOURCE, SKILL,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "quote not verbatim in source")

    def test_rejects_a_question_that_names_the_skill(self):
        ok, reason = questions.gate(
            "what does zoom recorder do with a cloud link",
            "Download transcripts, slide keyframes, and metadata",
            SOURCE, SKILL,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "names the skill")

    def test_allows_an_ordinary_word_from_the_skill_name(self):
        # "memory" is domain vocabulary; only the phrase is the answer key.
        ok, _reason = questions.gate(
            "search my notes for a fact i wrote months ago",
            "walks the graph for facts stored months ago",
            "walks the graph for facts stored months ago", "graph-memory",
        )
        self.assertTrue(ok)

    def test_rejects_short_and_long(self):
        self.assertFalse(questions.gate("get it", "", SOURCE, SKILL)[0])
        self.assertFalse(questions.gate(" ".join(["word"] * 25), "", SOURCE, SKILL)[0])

    def test_rejects_no_lexical_anchor(self):
        ok, reason = questions.gate(
            "how do i book a flight to tokyo",
            "Download transcripts, slide keyframes, and metadata",
            SOURCE, SKILL,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "no lexical anchor in source")


class TestSemanticGate(unittest.TestCase):
    def _embed(self, texts):
        """Description -> [1,0]; on-topic -> near it; off-topic -> orthogonal."""
        out = []
        for text in texts:
            low = text.lower()
            if "transcript" in low or "recording" in low or "captions" in low:
                out.append([1.0, 0.05])
            elif "bonjour" in low or "tokyo" in low:
                out.append([0.0, 1.0])
            else:
                out.append([1.0, 0.0])
        return out

    def test_control_question_with_a_stolen_quote_is_rejected(self):
        # The quote IS verbatim and the question borrows a word from it, so the
        # lexical gate passes. Only the semantic gate can catch a question that
        # is about something else entirely.
        raw = {"questions": {SKILL: [{
            "question": "download a flight to tokyo",
            "quote": "Download transcripts, slide keyframes, and metadata",
        }]}}
        res = question_build.build(raw, {SKILL: SOURCE}, embed=self._embed)
        self.assertEqual(res["accepted"].get(SKILL, []), [])
        self.assertTrue(any(r["reason"].startswith("self-similarity")
                            for r in res["rejected"]))

    def test_on_topic_question_survives_both_gates(self):
        raw = {"questions": {SKILL: [{
            "question": "pull the transcript out of a cloud recording",
            "quote": "Download transcripts, slide keyframes, and metadata",
        }]}}
        res = question_build.build(raw, {SKILL: SOURCE}, embed=self._embed)
        self.assertEqual(len(res["accepted"][SKILL]), 1)

    def test_exact_duplicate_across_skills_is_rejected(self):
        question = {
            "question": "pull the transcript out of a cloud recording",
            "quote": "Download transcripts, slide keyframes, and metadata",
        }
        raw = {"questions": {SKILL: [question], "video-miner": [dict(question)]}}
        res = question_build.build(raw, {SKILL: SOURCE, "video-miner": SOURCE},
                                   embed=self._embed)
        self.assertEqual(len(res["accepted"][SKILL]), 1)
        self.assertEqual(res["accepted"].get("video-miner", []), [])
        self.assertTrue(any(r["reason"].startswith("duplicate")
                            for r in res["rejected"]))


class TestSnapshot(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "questions.json"
            entries = {SKILL: [{"question": "pull the transcript out of a cloud recording",
                                "quote": "Download transcripts"}]}
            questions.write_snapshot(entries, path=path)
            loaded = questions.load(path)
            self.assertEqual(loaded[SKILL][0]["question"],
                             entries[SKILL][0]["question"])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("note", payload)

    def test_enabled_is_opt_in(self):
        import os
        original = os.environ.pop("OMNICLI_QUESTIONS", None)
        try:
            self.assertFalse(questions.enabled())
            os.environ["OMNICLI_QUESTIONS"] = "1"
            self.assertTrue(questions.enabled())
            os.environ["OMNICLI_QUESTIONS"] = "0"
            self.assertFalse(questions.enabled())
        finally:
            os.environ.pop("OMNICLI_QUESTIONS", None)
            if original is not None:
                os.environ["OMNICLI_QUESTIONS"] = original

    def test_disabled_snapshot_produces_description_rows_only(self):
        import os
        from catalog import vectors
        original = os.environ.pop("OMNICLI_QUESTIONS", None)
        try:
            rows = vectors._wanted_rows(force=False)
            self.assertTrue(rows)
            self.assertEqual({r[1] for r in rows}, {"description"})
        finally:
            os.environ.pop("OMNICLI_QUESTIONS", None)
            if original is not None:
                os.environ["OMNICLI_QUESTIONS"] = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
