#!/usr/bin/env python3
"""Gates that cannot fail are not gates. Every test has a negative control.

Stdlib only: `python3 tests/test_gates.py`. No pytest, no venv, matching the
skill's compatibility claim.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "_tools"
sys.path.insert(0, str(TOOLS))

import dreamer  # noqa: E402
import links  # noqa: E402
import mem  # noqa: E402


def make_root() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="memory-test-"))
    for name in ("01_transcripts", "02_notes", "03_wiki", "04_context", "db"):
        (tmp / name).mkdir(parents=True, exist_ok=True)
    return tmp


def write_note(root: Path, *, title: str, body: str, **meta) -> Path:
    folder = root / "02_notes" / "proj"
    folder.mkdir(parents=True, exist_ok=True)
    data = {"id": mem.slug(title), "title": title,
            "type": meta.pop("type", "decision"), "project": "proj",
            "ts": "2026-11-10T00:00:00", "source": "manual",
            "entities": meta.pop("entities", []),
            "sources": meta.pop("sources", []), "confidence": 0.9,
            "verified": meta.pop("verified", False)}
    path = folder / f"{mem.slug(title)}.md"
    path.write_text(mem.dump_frontmatter(data) + f"\n# {title}\n\n{body}\n",
                    encoding="utf-8")
    return path


class MemoryGates(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_root()

    # ------------------------------------------------------------ roundtrip

    def test_save_then_search_finds_it(self) -> None:
        mem.main(["--root", str(self.root), "save", "--title", "Refresh race",
                  "--type", "decision", "--project", "api",
                  "--body", "Refresh must be single-flight."])
        con = mem.ensure_index(self.root)
        row = con.execute("SELECT * FROM docs WHERE title = 'Refresh race'").fetchone()
        con.close()
        self.assertIsNotNone(row)
        self.assertIn("single-flight", row["body"])

    def test_forget_removes_it_from_search(self) -> None:
        """Negative control for injection: forgotten means gone from recall."""
        mem.main(["--root", str(self.root), "save", "--title", "Secret plan",
                  "--project", "api", "--body", "Do not surface this again."])
        con = mem.ensure_index(self.root)
        target = con.execute("SELECT id FROM docs WHERE title = 'Secret plan'").fetchone()
        con.close()
        mem.main(["--root", str(self.root), "forget", target["id"]])
        con = mem.ensure_index(self.root)
        gone = con.execute(
            "SELECT count(*) FROM docs WHERE title = 'Secret plan'").fetchone()[0]
        con.close()
        self.assertEqual(gone, 0)
        self.assertTrue((self.root / "_archive").is_dir())

    # ------------------------------------------------------------ links gate

    def test_links_clean_on_empty_store(self) -> None:
        self.assertTrue(links.check(self.root)["ok"])

    def test_dangling_wikilink_fails(self) -> None:
        page = self.root / "03_wiki" / "entities" / "topic" / "alpha.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(mem.dump_frontmatter(
            {"id": "wiki-alpha", "title": "alpha", "type": "entity",
             "sources": ["02_notes/proj/x.md"], "verified": True})
            + "\n# alpha\n\nSee [[nowhere]].\n", encoding="utf-8")
        result = links.check(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(any(f["rule"] == "dangling-wikilink"
                            for f in result["findings"]))

    def test_unresolved_source_fails(self) -> None:
        write_note(self.root, title="Claims a ghost", body="evidence",
                   sources=["01_transcripts/ghost.jsonl"])
        result = links.check(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(any(f["rule"] == "unresolved-source"
                            for f in result["findings"]))

    def test_header_over_budget_fails(self) -> None:
        header = self.root / "04_context" / "MEMORY.md"
        header.write_text("\n".join(f"- fact {i} → `mem get x{i}`"
                                    for i in range(mem.MAX_HEADER_LINES + 5)) + "\n",
                          encoding="utf-8")
        result = links.check(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(any(f["rule"] == "header-over-lines"
                            for f in result["findings"]))

    def test_page_without_source_fails(self) -> None:
        page = self.root / "03_wiki" / "entities" / "topic" / "orphan.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(mem.dump_frontmatter(
            {"id": "wiki-orphan", "title": "orphan", "type": "entity"})
            + "\n# orphan\n\nNo provenance.\n", encoding="utf-8")
        result = links.check(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(any(f["rule"] == "page-without-source"
                            for f in result["findings"]))

    # ------------------------------------------------------------ dreamer

    def test_wiki_merges_two_notes_into_one_page(self) -> None:
        write_note(self.root, title="Uses auth", body="`auth.py` guards the route.",
                   entities=["auth.py"])
        write_note(self.root, title="Auth again", body="`auth.py` also refreshes.",
                   entities=["auth.py"])
        report = dreamer.build_wiki(self.root)
        self.assertEqual(report["pages"], 1)
        page = self.root / "03_wiki" / "entities" / "code" / "auth-py.md"
        self.assertTrue(page.is_file())
        self.assertIn("uses-auth", page.read_text(encoding="utf-8"))

    def test_header_stays_inside_budget(self) -> None:
        for i in range(300):
            write_note(self.root, title=f"Rule {i}", body=f"Rule number {i} holds.",
                       type="rule")
        report = dreamer.promote(self.root)
        self.assertFalse(report["over_budget"])
        self.assertLessEqual(report["lines"], mem.MAX_HEADER_LINES)

    def test_crossref_flags_unsupported_claim(self) -> None:
        (self.root / "01_transcripts" / "s1.jsonl").write_text(
            '{"action":"edit","path":"auth.py"}\n', encoding="utf-8")
        write_note(self.root, title="Invented claim",
                   body="We proved `quantum_cache.py` works.",
                   sources=["01_transcripts/s1.jsonl"])
        report = dreamer.crossref(self.root)
        self.assertEqual(report["verified"], 0)
        self.assertTrue(report["broken"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
