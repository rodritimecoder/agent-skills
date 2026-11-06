#!/usr/bin/env python3
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))
import cite_check  # noqa: E402


TRANSCRIPT = (
    "# Audio Transcript\n\n"
    "**[00:00]** We called most of it bullshit because a graph is just a visualiser.\n\n"
    "**[00:17]** Then it shows the tools and waits for your approval.\n\n"
    "**[00:35]** A check you have never seen fail does not prove anything.\n"
)


class TestCiteCheck(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="test_cite_check_")
        self.root = Path(self.td)
        (self.root / "transcript.md").write_text(TRANSCRIPT, encoding="utf-8")
        (self.root / "source.md").write_text(
            "# Source\n\n"
            "The gate fails when the quote is not verbatim.\n\n"
            "Launch, Doctor, Drive, Evidence, Cleanup, Helpers.\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def answer(self, body: str) -> Path:
        path = self.root / "answer.md"
        path.write_text(body, encoding="utf-8")
        return path

    def report(self, body: str, **kwargs):
        return cite_check.check(self.answer(body), **kwargs)

    def test_01_verbatim_quote_passes(self):
        report = self.report(
            'A gate that runs: [source.md](source.md)\n\n'
            '> "Launch, Doctor, Drive, Evidence, Cleanup, Helpers."\n'
        )
        self.assertTrue(report["pass"], report)
        self.assertEqual(report["verified_quotes"], 1)
        print("  ✓ a verbatim quote verifies against the cited file")

    def test_02_paraphrase_fails(self):
        report = self.report(
            'The lifecycle: [source.md](source.md)\n\n'
            '> "Launch, Doctor, Drive, Evidence, Cleanup and Helpers."\n'
        )
        self.assertFalse(report["pass"])
        self.assertEqual(report["violations"][0]["kind"], "quote_not_found")
        print("  ✓ a paraphrased quote is a violation")

    def test_03_bracket_insertion_is_tolerated(self):
        report = self.report(
            'What it measured: [source.md:3](source.md)\n\n'
            '> "The gate fails when the [verification] quote is not verbatim."\n'
        )
        self.assertTrue(report["pass"], report)
        print("  ✓ an editorial bracket is a skip, not a mismatch")

    def test_04_ellipsis_is_tolerated(self):
        report = self.report(
            'Two ends: [source.md](source.md)\n\n'
            '> "The gate fails ... is not verbatim."\n'
        )
        self.assertTrue(report["pass"], report)
        print("  ✓ an ellipsis matches the fragments in order")

    def test_05_dead_citation_fails(self):
        report = self.report(
            'The appendix: [gone.md:4](gone.md)\n\n'
            "Plain prose with no quote at all, long enough to be a claim of some kind.\n"
        )
        self.assertFalse(report["pass"])
        self.assertEqual(report["violations"][0]["kind"], "missing_file")
        print("  ✓ a citation to a file that does not exist fails")

    def test_06_unresolved_reference_warns_only(self):
        report = self.report(
            "The upstream repo is `karpathy/llm-wiki.md`, which is not local to this folder.\n"
        )
        self.assertTrue(report["pass"], report)
        self.assertEqual(report["warnings"][0]["kind"], "unresolved_reference")
        print("  ✓ a bare reference warns without failing the gate")

    def test_07_timestamp_resolves_to_transcript(self):
        report = self.report(
            'The claim:\n\n'
            '> "A check you have never seen fail does not prove anything." — [00:35]\n'
        )
        self.assertTrue(report["pass"], report)
        self.assertEqual(report["citations"], 1)
        print("  ✓ a [MM:SS] citation verifies against transcript blocks")

    def test_08_timestamp_mismatch_fails(self):
        report = self.report(
            'The claim:\n\n'
            '> "A check you have never run twice does not prove anything." — [00:35]\n'
        )
        self.assertFalse(report["pass"])
        self.assertEqual(report["violations"][0]["kind"], "quote_not_found")
        print("  ✓ a quote that drifted from the transcript fails")

    def test_09_uncited_prose_warns(self):
        report = self.report(
            "This paragraph makes a confident claim about the pipeline and cites nothing at all.\n"
        )
        self.assertTrue(report["pass"])
        self.assertEqual(report["warnings"][0]["kind"], "uncited_claim")
        print("  ✓ uncited prose warns without failing")

    def test_10_list_items_are_isolated(self):
        report = self.report(
            "- **Source:** [source.md](source.md)\n"
            '- **Caption:** "a caption quote that is not in the source at all"\n'
        )
        self.assertTrue(report["pass"], report)
        self.assertEqual(report["quotes"], 0)
        print("  ✓ a caption on its own line is not checked against the link above it")

    def test_11_tables_are_not_prose(self):
        report = self.report(
            "| tool | note |\n| :-- | :-- |\n| one | a row that is long enough to look like a claim |\n"
        )
        self.assertTrue(report["pass"], report)
        self.assertEqual(report["warnings"], [])
        print("  ✓ table rows are data, not uncited claims")

    def test_12_strict_lines_catches_the_wrong_window(self):
        body = (
            'Out of range: [source.md:5](source.md:5)\n\n'
            '> "The gate fails when the quote is not verbatim."\n'
        )
        loose = self.report(body)
        strict = self.report(body, strict_lines=True)
        self.assertTrue(loose["pass"], loose)
        self.assertFalse(strict["pass"], strict)
        self.assertEqual(strict["violations"][0]["kind"], "quote_outside_lines")
        print("  ✓ --strict-lines requires the quote to sit in the cited lines")


if __name__ == "__main__":
    unittest.main(verbosity=0)
