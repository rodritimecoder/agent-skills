#!/usr/bin/env python3
"""Tests for the design-system renderer (stdlib unittest, no fixtures on disk)."""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import render  # noqa: E402

BODY = """<h1>Coffee, measured</h1>
<p>Ratio first, then taste.</p>
<pre><code>1:16</code></pre>
<table>
<tr><th>Method</th><th>Time</th></tr>
<tr><td>V60</td><td>3:00</td></tr>
</table>
<blockquote>Grind finer before you change the water.</blockquote>"""

# One value unique to each look, used to prove only the chosen one is inlined.
ACCENT = {
    "house": "--accent: #0f766e;",
    "paper": "--accent: #8a3b12;",
    "terminal": "--accent: #38e07b;",
}


class RenderTests(unittest.TestCase):
    def test_output_contains_title(self):
        html = render.render("Coffee, measured", BODY)
        self.assertIn("<title>Coffee, measured</title>", html)

    def test_body_is_inserted_unchanged(self):
        html = render.render("t", BODY, look="paper")
        self.assertIn(BODY, html)

    def test_each_look_inlines_only_its_own_block(self):
        for look in render.LOOKS:
            with self.subTest(look=look):
                html = render.render("t", BODY, look=look)
                self.assertIn(f'<html lang="en" data-look="{look}">', html)
                self.assertIn(f'[data-look="{look}"]', html)
                self.assertIn(ACCENT[look], html)
                for other in render.LOOKS:
                    if other != look:
                        self.assertNotIn(ACCENT[other], html)
                        self.assertNotIn(f'[data-look="{other}"]', html)

    def test_look_defines_the_five_token_groups(self):
        html = render.render("t", BODY, look="terminal")
        for token in ("--ink:", "--font-body:", "--radius:", "--border:", "--shadow:"):
            self.assertIn(token, html)

    def test_base_styles_for_content_tags_are_present(self):
        css = render.page_css("house")
        for selector in ("h1 {", "h2 {", "p {", "pre {", "table {", "blockquote {"):
            self.assertIn(selector, css)

    def test_one_style_block_and_no_link(self):
        html = render.render("t", BODY, look="house")
        self.assertEqual(html.count("<style>"), 1)
        self.assertEqual(html.count("</style>"), 1)
        self.assertNotIn("<link", html)

    def test_no_external_requests(self):
        html = render.render("t", BODY, look="house")
        self.assertNotIn("<script", html)
        self.assertIsNone(re.search(r'\b(?:src|href)\s*=', html))
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("@import", html)

    def test_unknown_look_raises_and_lists_valid_looks(self):
        with self.assertRaises(ValueError) as caught:
            render.render("t", BODY, look="brutalist")
        message = str(caught.exception)
        self.assertIsInstance(caught.exception, render.RenderError)
        self.assertIn("unknown look 'brutalist'", message)
        for look in render.LOOKS:
            self.assertIn(look, message)

    def test_default_look_is_house(self):
        html = render.render("t", BODY)
        self.assertIn('data-look="house"', html)

    def test_title_is_escaped(self):
        html = render.render("A & B <script>", BODY)
        self.assertIn("<title>A &amp; B &lt;script&gt;</title>", html)
        self.assertNotIn("<script", html)


class WriteTests(unittest.TestCase):
    def test_write_matches_render_and_creates_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "nested" / "page.html"
            written = render.write(out, "t", BODY, look="paper")
            self.assertEqual(written, out)
            self.assertEqual(out.read_text(encoding="utf-8"), render.render("t", BODY, look="paper"))

    def test_cli_writes_a_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "body.html"
            body.write_text(BODY, encoding="utf-8")
            out = Path(tmp) / "page.html"
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "render.py"),
                 "--title", "CLI page", "--body", str(body),
                 "--look", "terminal", "--out", str(out)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            html = out.read_text(encoding="utf-8")
            self.assertIn("<title>CLI page</title>", html)
            self.assertIn(BODY, html)
            self.assertIn('data-look="terminal"', html)

    def test_cli_rejects_unknown_look(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "body.html"
            body.write_text(BODY, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "render.py"),
                 "--title", "T", "--body", str(body), "--look", "brutalist"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("unknown look 'brutalist'", proc.stderr)
            self.assertIn("house, paper, terminal", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
