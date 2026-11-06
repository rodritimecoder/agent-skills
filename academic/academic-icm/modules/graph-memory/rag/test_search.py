#!/usr/bin/env python3
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import search as rag_search

SCHEMA = """
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    file TEXT,
    section TEXT,
    start_line INTEGER,
    end_line INTEGER,
    text TEXT,
    kind TEXT
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content='chunks', content_rowid='id');
CREATE TABLE vectors (
    id INTEGER PRIMARY KEY,
    vec BLOB
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


class TestGraphMemorySearch(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_rag.db"
        self.db = sqlite3.connect(self.db_path)
        self.db.executescript(SCHEMA)

        # Seed test chunks
        cur = self.db.cursor()
        cur.execute(
            "INSERT INTO chunks VALUES (1, '48520_tut10.md', 'CMOS Inverters', 10, 25, 'The propagation delay of CMOS inverter depends on NMOS and PMOS transconductance.', 'chunk')"
        )
        cur.execute(
            "INSERT INTO chunks VALUES (2, 'notes_power.md', 'Dynamic Power', 5, 18, 'Dynamic power dissipation is proportional to load capacitance and switching frequency.', 'chunk')"
        )
        cur.execute(
            "INSERT INTO chunks_fts (rowid, text) VALUES (1, 'The propagation delay of CMOS inverter depends on NMOS and PMOS transconductance.')"
        )
        cur.execute(
            "INSERT INTO chunks_fts (rowid, text) VALUES (2, 'Dynamic power dissipation is proportional to load capacitance and switching frequency.')"
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_render_table(self):
        rows = [{"rank": 1, "file": "a.md", "snippet": "hello world"}]
        table = rag_search.render_table(rows, ["rank", "file", "snippet"])
        self.assertIn("Rank", table)
        self.assertIn("a.md", table)
        self.assertIn("hello world", table)

    def test_keyword_leg(self):
        matches = rag_search.keyword_leg(self.db, "propagation delay inverter")
        self.assertEqual(matches, [1])

        power_matches = rag_search.keyword_leg(self.db, "dynamic power capacitance")
        self.assertEqual(power_matches, [2])

    def test_fuse(self):
        legs = {
            "keyword": [1, 2],
            "meaning": [2, 1]
        }
        ranked, found_by = rag_search.fuse(legs)
        self.assertEqual(len(ranked), 2)
        self.assertIn("keyword", found_by[1])
        self.assertIn("meaning", found_by[1])

    def test_fetch_hit(self):
        hit = rag_search.fetch_hit(self.db, 1, 1, ["keyword", "meaning"])
        self.assertEqual(hit["rank"], 1)
        self.assertEqual(hit["file"], "48520_tut10.md")
        self.assertEqual(hit["section"], "CMOS Inverters")
        self.assertEqual(hit["lines"], "10-25")
        self.assertEqual(hit["legs"], "keyword+meaning")
        self.assertIn("propagation delay", hit["snippet"])

    def test_cli_search_table_and_projection(self):
        cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "search.py"),
            "propagation", "delay",
            "--table",
            "-p", "file,section,snippet"
        ]
        env = os.environ.copy()
        env["RAG_DB_PATH"] = str(self.db_path)
        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("48520_tut10.md", res.stdout)
        self.assertIn("CMOS Inverters", res.stdout)
        self.assertIn("| File", res.stdout)
        self.assertNotIn("| Lines |", res.stdout)  # Projected out

    def test_cli_json_and_limit(self):
        cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "search.py"),
            "power",
            "--json",
            "-n", "1"
        ]
        env = os.environ.copy()
        env["RAG_DB_PATH"] = str(self.db_path)
        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        hits = json.loads(res.stdout)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["file"], "notes_power.md")


if __name__ == "__main__":
    unittest.main()
