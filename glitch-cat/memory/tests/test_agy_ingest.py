#!/usr/bin/env python3
"""Tests for Antigravity transcript ingestion (agy_ingest.py).

Stdlib only: python3 tests/test_agy_ingest.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "_tools"
sys.path.insert(0, str(TOOLS))

import agy_ingest  # noqa: E402


class AgyIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="agy-ingest-test-"))
        self.root = self.tmp / "memory"
        self.brain = self.tmp / "brain"
        self.root.mkdir()
        self.brain.mkdir()

    def make_transcript(self, session_id: str, steps: list[dict]) -> Path:
        session_dir = self.brain / session_id / ".system_generated" / "logs"
        session_dir.mkdir(parents=True, exist_ok=True)
        t_file = session_dir / "transcript.jsonl"
        with t_file.open("w", encoding="utf-8") as fh:
            for s in steps:
                fh.write(json.dumps(s) + "\n")
        return t_file

    def test_parses_tool_calls_and_actions(self) -> None:
        steps = [
            {
                "step_index": 0,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-10T12:00:00Z",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "args": {"CommandLine": "npm test", "Cwd": "/home/user/my-app"},
                    }
                ],
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "RUN_COMMAND",
                "status": "DONE",
                "content": "All tests passed",
            },
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-10T12:01:00Z",
                "tool_calls": [
                    {
                        "name": "replace_file_content",
                        "args": {"TargetFile": "/home/user/my-app/src/index.ts"},
                    }
                ],
            },
            {
                "step_index": 3,
                "source": "MODEL",
                "type": "REPLACE_FILE_CONTENT",
                "status": "DONE",
            },
        ]
        self.make_transcript("ses-01", steps)

        total, sessions = agy_ingest.ingest_all(self.root, [self.brain])
        self.assertEqual(total, 2)
        self.assertEqual(sessions, 1)

        out_file = self.root / "01_transcripts" / "my-app" / "ses-01.jsonl"
        self.assertTrue(out_file.is_file())

        lines = [json.loads(line) for line in out_file.read_text().splitlines() if line]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["action"], "bash")
        self.assertEqual(lines[0]["cmd"], "npm test")
        self.assertEqual(lines[0]["ok"], True)
        self.assertEqual(lines[1]["action"], "edit")
        self.assertEqual(lines[1]["path"], "/home/user/my-app/src/index.ts")

    def test_strips_secrets_and_private_tags(self) -> None:
        steps = [
            {
                "step_index": 0,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-10T12:00:00Z",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "args": {
                            "CommandLine": "curl -H 'Auth: <private>secret123</private>' https://api.com -H 'Key: sk-EXAMPLEabcdef1234567890abcdef'",
                            "Cwd": "/home/user/sec-app",
                        },
                    }
                ],
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "RUN_COMMAND",
                "status": "DONE",
            },
        ]
        self.make_transcript("ses-sec", steps)

        agy_ingest.ingest_all(self.root, [self.brain])
        out_file = self.root / "01_transcripts" / "sec-app" / "ses-sec.jsonl"
        content = out_file.read_text()
        self.assertNotIn("secret123", content)
        self.assertNotIn("sk-EXAMPLEabcdef1234567890abcdef", content)
        self.assertIn("[private]", content)
        self.assertIn("[redacted]", content)

    def test_deduplicates_reads_per_session(self) -> None:
        steps = [
            {
                "step_index": 0,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-10T12:00:00Z",
                "tool_calls": [
                    {"name": "view_file", "args": {"AbsolutePath": "/home/user/doc.md"}}
                ],
            },
            {"step_index": 1, "status": "DONE"},
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-10T12:05:00Z",
                "tool_calls": [
                    {"name": "view_file", "args": {"AbsolutePath": "/home/user/doc.md"}}
                ],
            },
            {"step_index": 3, "status": "DONE"},
        ]
        self.make_transcript("ses-dedup", steps)

        total, _ = agy_ingest.ingest_all(self.root, [self.brain])
        self.assertEqual(total, 1)  # second read dropped

    def test_incremental_and_idempotent(self) -> None:
        steps = [
            {
                "step_index": 0,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-10T12:00:00Z",
                "tool_calls": [
                    {"name": "run_command", "args": {"CommandLine": "ls", "Cwd": "/app"}}
                ],
            },
            {"step_index": 1, "status": "DONE"},
        ]
        self.make_transcript("ses-inc", steps)

        # Pass 1
        t1, s1 = agy_ingest.ingest_all(self.root, [self.brain])
        self.assertEqual(t1, 1)
        self.assertEqual(s1, 1)

        # Pass 2 without changes: nothing ingested
        t2, s2 = agy_ingest.ingest_all(self.root, [self.brain])
        self.assertEqual(t2, 0)
        self.assertEqual(s2, 0)


if __name__ == "__main__":
    unittest.main()
