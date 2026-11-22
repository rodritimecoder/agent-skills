#!/usr/bin/env python3
"""Tests for kem-notes transcript parsing with and without diarization."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# vault_mine.py lives in scripts/, one level up from tests/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import vault_mine as vmine  # noqa: E402

PLAIN_TRANSCRIPT = (
    "**[00:00]** Welcome to the Glitch Cat engineering breakdown.\n\n"
    "**[00:15]** My favorite question is how do you keep the context window honest?\n\n"
    "**[00:31]** We restate the question before we move to planning.\n"
)

DIARIZED_TRANSCRIPT = (
    "**[00:04] speaker_0:** My favorite question is how do you keep the context window honest?\n\n"
    "**[00:19] speaker_1:** We restate the question before we move to planning.\n"
)


class TestParseTranscriptBlocks(unittest.TestCase):
    def test_plain_blocks_are_real_rows_with_no_speaker(self):
        blocks = vmine.parse_transcript_blocks(PLAIN_TRANSCRIPT)
        self.assertEqual(len(blocks), 3)
        for ts, text, speaker in blocks:
            self.assertRegex(ts, r"^\d{1,2}:\d{2}")
            self.assertTrue(text)
            self.assertIsNone(speaker)

    def test_plain_transcript_has_no_placeholder(self):
        rows, synthesis = vmine.derive_kem_notes_content(PLAIN_TRANSCRIPT)
        joined = "\n".join(rows + synthesis)
        self.assertTrue(rows)
        self.assertNotIn("No timestamped blocks captured", joined)
        self.assertNotIn("Core Thesis", joined)
        self.assertNotIn("Synthesize key architectural patterns", joined)

    def test_diarized_blocks_carry_speaker_and_clean_quote(self):
        blocks = vmine.parse_transcript_blocks(DIARIZED_TRANSCRIPT)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0][2], "speaker_0")
        self.assertEqual(blocks[1][2], "speaker_1")
        self.assertEqual(
            blocks[0][1],
            "My favorite question is how do you keep the context window honest?",
        )
        self.assertNotIn("speaker_0", blocks[0][1])

    def test_diarized_transcript_surfaces_speaker_in_claim_label(self):
        rows, synthesis = vmine.derive_kem_notes_content(DIARIZED_TRANSCRIPT)
        joined = "\n".join(rows + synthesis)
        self.assertTrue(rows)
        self.assertNotIn("No timestamped blocks captured", joined)
        self.assertNotIn("Core Thesis", joined)
        self.assertNotIn("Synthesize key architectural patterns", joined)
        self.assertIn("speaker_0 / The question", joined)
        # The speaker label is stripped out of the verbatim quote column.
        self.assertNotIn("] speaker_0:**", joined)


class TestDiarizeCliDefaults(unittest.TestCase):
    def _effective_diarize(self, cmd, extra):
        """Run main() with fast_mine_video mocked so nothing is downloaded."""
        with tempfile.TemporaryDirectory() as d:
            argv = ["vault_mine", cmd, "https://example.invalid/v", "--vault-dir", d] + extra
            with patch.object(sys, "argv", argv), \
                 patch.object(vmine, "fast_mine_video", return_value=str(Path(d) / "out")) as mine:
                rc = vmine.main()
            self.assertEqual(rc, 0)
            return mine.call_args.kwargs["diarize"]

    def test_add_diarizes_by_default_and_opt_out_disables_it(self):
        self.assertTrue(self._effective_diarize("add", []))
        self.assertFalse(self._effective_diarize("add", ["--no-diarize"]))

    def test_kem_diarizes_by_default_and_opt_out_disables_it(self):
        self.assertTrue(self._effective_diarize("kem", []))
        self.assertFalse(self._effective_diarize("kem", ["--no-diarize"]))

    def test_speaker_names_still_implies_diarization(self):
        self.assertTrue(
            self._effective_diarize("add", ["--no-diarize", "--speaker-names", "A,B"])
        )


if __name__ == "__main__":
    unittest.main()
