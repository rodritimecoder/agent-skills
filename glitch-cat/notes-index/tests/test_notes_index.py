#!/usr/bin/env python3
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))
import notes_index_core  # noqa: E402
from notes_index_core import NotesIndex, api_key_pool, apply_rule, mask_secrets, plan, rule_block  # noqa: E402


class TestNotesIndex(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="test_notes_index_")
        self.folder = Path(self.td)
        self.index = NotesIndex(self.folder)

    def tearDown(self):
        self.index.close()
        shutil.rmtree(self.td, ignore_errors=True)

    def write(self, name: str, body: str) -> Path:
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def test_01_update_indexes_notes(self):
        self.write("2026-01-01-alpha.md", "# Alpha\n\nThe retrieval pipeline uses bm25 ranking.\n")
        self.write("2026-02-02-beta.md", "# Beta\n\nSwarm contracts enforce a budget ceiling.\n")
        report = self.index.update(use_summarizer=False)
        self.assertEqual(report.files_total, 2)
        self.assertEqual(report.new_files, 2)
        self.assertEqual(self.index.status()["rows"], 2)
        print("  ✓ first pass indexes every note")

    def test_02_unchanged_files_are_skipped(self):
        self.write("note.md", "# Note\n\nstable content about orchestration\n")
        self.index.update(use_summarizer=False)
        second = self.index.update(use_summarizer=False)
        self.assertEqual(second.unchanged_files, 1)
        self.assertEqual(second.new_files, 0)
        print("  ✓ unchanged notes are skipped")

    def test_03_changed_file_is_reindexed(self):
        path = self.write("note.md", "# Note\n\nfirst version\n")
        self.index.update(use_summarizer=False)
        path.write_text("# Note\n\nsecond version with different words\n", encoding="utf-8")
        report = self.index.update(use_summarizer=False)
        self.assertEqual(report.changed_files, 1)
        hits = self.index.search("different words")
        self.assertTrue(any(hit.path == "note.md" for hit in hits))
        print("  ✓ changed notes are re-indexed")

    def test_04_removed_file_rows_are_deleted(self):
        path = self.write("gone.md", "# Gone\n\ntemporary content\n")
        self.index.update(use_summarizer=False)
        self.assertEqual(self.index.status()["rows"], 1)
        path.unlink()
        report = self.index.update(use_summarizer=False)
        self.assertEqual(report.removed_files, 1)
        self.assertEqual(self.index.status()["rows"], 0)
        print("  ✓ removed notes leave no rows behind")

    def test_05_search_returns_ranked_hits(self):
        self.write("2026-03-03-graph.md", "# Graph\n\nKnowledge graph traversal with sqlite k-hop walks.\n")
        self.write("2026-03-04-cache.md", "# Cache\n\nSemantic cache bypass with vector cosine similarity.\n")
        self.index.update(use_summarizer=False)
        hits = self.index.search("graph traversal")
        self.assertTrue(hits)
        self.assertIn("graph", hits[0].path)
        self.assertTrue(hits[0].full_path.endswith(".md"))
        print("  ✓ search ranks the right note first")

    def test_06_search_respects_after_filter(self):
        self.write("2020-01-01-old.md", "# Old\n\nhistorical decision about indexing\n")
        self.write("2026-05-05-new.md", "# New\n\nrecent decision about indexing\n")
        self.index.update(use_summarizer=False)
        hits = self.index.search("indexing", after="2025-01-01")
        self.assertTrue(hits)
        self.assertTrue(all(hit.path.startswith("2026") for hit in hits))
        print("  ✓ --after filters out old notes")

    def test_07_health_line_shape(self):
        self.write("note.md", "# Note\n\ncontent\n")
        self.index.update(use_summarizer=False)
        health = self.index.health_line()
        self.assertIn("rows |", health)
        self.assertIn("last refreshed", health)
        self.assertIn("last error: none", health)
        print("  ✓ health line carries rows, freshness and error")

    def test_08_long_file_is_chunked_into_raw_rows(self):
        self.write("long.md", "# Long\n\n" + ("x" * 9000))
        report = self.index.update(use_summarizer=False)
        kinds = self.index.status()["rows_by_kind"]
        self.assertEqual(kinds.get("raw"), 3)
        print("  ✓ long notes become 4000-char raw rows")

    def test_09_secrets_are_masked_before_storage(self):
        fake_key = "sk-" + "abcdefghijklmnop1234"
        fake_aws = "AKIA" + "IOSFODNN7EXAMPLE"
        self.write("secret.md", f"# Secret\n\napi_key = {fake_key} and {fake_aws}\n")
        self.index.update(use_summarizer=False)
        conn = sqlite3.connect(str(self.index.db_path))
        stored = " ".join(row[0] for row in conn.execute("SELECT text FROM rows"))
        conn.close()
        self.assertNotIn(fake_key, stored)
        self.assertNotIn(fake_aws, stored)
        self.assertIn("sk-***", stored)
        print("  ✓ secrets are masked before they hit the database")

    def test_10_stale_lock_does_not_block(self):
        lock = self.folder / ".notes-index.lock"
        lock.write_text("999999", encoding="utf-8")
        self.write("note.md", "# Note\n\ncontent\n")
        report = self.index.update(use_summarizer=False)
        self.assertEqual(report.files_total, 1)
        print("  ✓ a dead lock is ignored, not a blocker")

    def test_11_rule_block_is_idempotent(self):
        script = self.folder / "index.py"
        script.write_text("#\n", encoding="utf-8")
        apply_rule(self.folder, script, "full")
        apply_rule(self.folder, script, "lean")
        text = (self.folder / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("notes-index:start"), 1)
        self.assertIn("don't also grep", text)
        print("  ✓ the AGENTS.md rule is rewritten, never duplicated")

    def test_14_rule_target_agents_by_default(self):
        script = self.folder / "index.py"
        script.write_text("#\n", encoding="utf-8")
        path = apply_rule(self.folder, script, "full")
        self.assertEqual(path.name, "AGENTS.md")
        self.assertTrue(path.exists())
        self.assertFalse((self.folder / "CLAUDE.md").exists())
        print("  ✓ the rule lands in AGENTS.md by default")

    def test_15_rule_target_claude_on_request(self):
        script = self.folder / "index.py"
        script.write_text("#\n", encoding="utf-8")
        path = apply_rule(self.folder, script, "full", "claude")
        self.assertEqual(path.name, "CLAUDE.md")
        print("  ✓ CLAUDE.md is still available on request")

    def test_12_plan_counts_long_files(self):
        self.write("short.md", "short\n")
        self.write("long.md", "y" * 9000)
        result = plan(self.folder)
        self.assertEqual(result["files"], 2)
        self.assertEqual(result["long_files"], 1)
        print("  ✓ the first-pass plan counts notes and summaries")

    def test_16_failed_summary_is_retried_next_run(self):
        self.write("long.md", "# Long\n\n" + ("z" * 9000))

        def broken(path, text):
            raise RuntimeError("summarizer exploded")

        def working(path, text):
            return {
                "topics": [{"title": "Long", "question": "what is long?", "summary": "a long note"}],
                "facts": [{"text": "the note is long"}],
            }

        self.index.summarize = broken
        first = self.index.update(use_summarizer=True)
        self.assertEqual(first.summaries_made, 0)
        self.assertEqual(len(first.summary_errors), 1)
        self.index.summarize = working
        processed = self.index.status()["files"]
        self.assertEqual(processed, 0)
        second = self.index.update(use_summarizer=True)
        self.assertEqual(second.new_files, 1)
        self.assertEqual(second.summaries_made, 1)
        self.assertEqual(self.index.status()["files"], 1)
        print("  ✓ a failed summary is retried on the next run")

    def test_17_malformed_summary_json_is_repaired(self):
        broken = '{"topics": [{"title": "T", "question": "Q", "summary": "S"},], "facts": [{"text": "F",}]}'
        parsed = NotesIndex._parse_summary(broken)
        self.assertEqual(parsed["topics"][0]["title"], "T")
        self.assertEqual(parsed["facts"][0]["text"], "F")
        print("  ✓ trailing commas in summarizer JSON are repaired")

    def test_18_levers_are_independently_selectable(self):
        script = self.folder / "index.py"
        script.write_text("#\n", encoding="utf-8")
        block = rule_block(script, "full", "agents", ("check-newer",))
        self.assertIn("anything newer on the same topic", block)
        self.assertNotIn("don't also grep", block)
        self.assertIn("Open the file before you state a fact", block)
        print("  ✓ one lever can be applied on its own")

    def test_19_trust_snippet_lever_replaces_the_strict_line(self):
        script = self.folder / "index.py"
        script.write_text("#\n", encoding="utf-8")
        block = rule_block(script, "full", "agents", ("trust-snippet",))
        self.assertIn("only if the snippet doesn't hold the answer", block)
        self.assertNotIn("Open the file before you state a fact", block)
        print("  ✓ the trust-snippet lever swaps the strict line")

    def test_20_all_four_levers_together(self):
        script = self.folder / "index.py"
        script.write_text("#\n", encoding="utf-8")
        block = rule_block(script, "full", "agents", ("no-grep", "trust-snippet", "fewer-results", "check-newer"))
        for needle in ("don't also grep", "snippet doesn't hold", "5, not 10", "anything newer"):
            self.assertIn(needle, block)
        print("  ✓ all four levers compose in one rule")

    def test_13_mask_secrets_helper(self):
        masked = mask_secrets("token: ghp_abcdefghijklmnopqrstuvwxyz012345")
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz012345", masked)
        print("  ✓ secret masking covers the common key shapes")

    def test_21_key_pool_reads_exported_key_files(self):
        key_file = self.folder / "keys.env"
        key_file.write_text(
            "# comment\nexport NVIDIA_API_KEY=nvapi-one\nNVIDIA_API_KEYS=nvapi-two,nvapi-one\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(notes_index_core, "KEY_FILES", (key_file,)):
            self.assertEqual(api_key_pool(), ["nvapi-one", "nvapi-two"])
        print("  ✓ the key pool parses exported key files without duplicates")

    def test_22_a_dead_provider_falls_through_to_the_next(self):
        reply = '{"topics": [{"title": "T", "question": "Q", "summary": "S"}], "facts": [{"text": "F"}]}'

        def dead(prompt):
            raise OSError("connection refused")

        self.index._providers = lambda: [("dead", dead), ("alive", lambda prompt: reply)]
        summary = self.index.summarize(self.folder / "note.md", "body " * 2000)
        self.assertEqual(summary["topics"][0]["title"], "T")
        self.assertEqual(summary["facts"][0]["text"], "F")
        print("  ✓ a dead summarizer falls through to the next provider")

    def test_23_frontier_api_precedes_the_local_fallback(self):
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi-test"}, clear=True), mock.patch.object(
            notes_index_core, "KEY_FILES", ()
        ):
            labels = [label for label, _ in self.index._providers()]
        self.assertTrue(labels[0].startswith("z-ai/glm-5.3-flash"), labels)
        self.assertTrue(labels[-1].startswith("local "), labels)
        print("  ✓ the hosted model is chosen before the local box")

    def _with_pool(self):
        return mock.patch.dict(os.environ, {"NOTES_INDEX_API_KEY": "key-one,key-two"}, clear=False), mock.patch.object(
            notes_index_core, "KEY_FILES", ()
        )

    def test_24_a_transient_failure_moves_to_the_next_key(self):
        env, files = self._with_pool()
        with env, files, mock.patch.object(
            notes_index_core.NotesIndex,
            "_post_chat",
            side_effect=[(None, 503, "HTTP 503 Service Unavailable"), ('{"ok": 1}', 200, "")],
        ) as post:
            self.assertEqual(self.index._call_api_model("prompt"), '{"ok": 1}')
            self.assertEqual(post.call_count, 2)
        print("  ✓ a 503 tries the second key instead of giving up")

    def test_25_an_empty_reply_moves_to_the_next_key(self):
        env, files = self._with_pool()
        with env, files, mock.patch.object(
            notes_index_core.NotesIndex,
            "_post_chat",
            side_effect=[(None, 200, "empty content (finish_reason=length)"), ('{"ok": 2}', 200, "")],
        ) as post:
            self.assertEqual(self.index._call_api_model("prompt"), '{"ok": 2}')
            self.assertEqual(post.call_count, 2)
        print("  ✓ truncated empty content is retried, not accepted")

    def test_26_a_bad_request_does_not_burn_the_second_key(self):
        env, files = self._with_pool()
        with env, files, mock.patch.object(
            notes_index_core.NotesIndex,
            "_post_chat",
            side_effect=[(None, 400, "HTTP 400 Bad Request"), ('{"never": 1}', 200, "")],
        ) as post:
            self.assertIsNone(self.index._call_api_model("prompt"))
            self.assertEqual(post.call_count, 1)
        self.assertIn("HTTP 400", self.index._api_error)
        print("  ✓ a 400 fails fast instead of spending the second key")

    def test_27_the_failure_message_carries_the_reason(self):
        self.index._providers = lambda: [
            (f"{self.index._api_model()} @ somewhere", self.index._call_api_model)
        ]
        env, files = self._with_pool()
        with env, files, mock.patch.object(
            notes_index_core.NotesIndex,
            "_post_chat",
            return_value=(None, 502, "HTTP 502 Bad Gateway"),
        ):
            with self.assertRaises(notes_index_core.SummarizerUnavailable) as caught:
                self.index._call_summarizer("prompt")
        self.assertIn("HTTP 502", str(caught.exception))
        print("  ✓ the error names the status instead of saying 'no answer'")

    def test_28_the_budget_grows_with_a_long_note(self):
        self.assertEqual(self.index._api_max_tokens(1_000), notes_index_core.DEFAULT_API_MAX_TOKENS)
        self.assertGreaterEqual(self.index._api_max_tokens(20_000), 9_000)
        self.assertEqual(self.index._api_max_tokens(10_000_000), 16_000)
        print("  ✓ a long note gets a bigger answer budget, capped at 16k")


if __name__ == "__main__":
    unittest.main(verbosity=2)
