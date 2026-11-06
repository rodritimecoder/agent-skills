#!/usr/bin/env python3
"""
Offline tests for markitdown_cli.py.

Runs against the skill-local .venv (the CLI re-execs itself, so plain python3
works). No network: the OCR tests use a stub OpenAI-compatible client and a
local stub HTTP server.
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

SKILL_DIR = Path(__file__).resolve().parent.parent

# Run inside the skill's venv, where markitdown is importable. (The CLI does
# this same re-exec automatically when invoked as a script.)
try:
    import markitdown  # noqa: F401
except ModuleNotFoundError:
    if os.environ.get("_MD_TEST_REEXEC") != "1":
        os.environ["_MD_TEST_REEXEC"] = "1"
        # Bundle copies are rsynced with `--exclude .venv`, so the in-tree symlink
        # is absent there; fall back to the machine-wide location it points at.
        venv_py = next(
            (c for c in (
                SKILL_DIR / ".venv" / "bin" / "python",
                Path.home() / ".venvs" / SKILL_DIR.name / "bin" / "python",
            ) if c.is_file()),
            None,
        )
        if venv_py is None:
            sys.exit("markitdown is not installed and no skill venv was found")
        if __name__ == "__main__":
            os.execv(str(venv_py), [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])
        # Imported by a runner (`python3 -m unittest test_markitdown_cli`): the
        # re-exec must re-enter that runner, not replay its arguments as a test
        # name -- which is how this used to fail with a confusing AttributeError.
        os.chdir(Path(__file__).resolve().parent)
        os.execv(str(venv_py), [str(venv_py), "-m", "unittest", Path(__file__).stem])
    sys.exit("markitdown is not installed in the skill venv")

CLI = [sys.executable, str(SKILL_DIR / "scripts" / "markitdown_cli.py")]

sys.path.insert(0, str(SKILL_DIR / "scripts"))
import markitdown_cli as m  # noqa: E402


def run(*args, stdin=None):
    return subprocess.run(CLI + list(args), capture_output=True, text=True, input=stdin)


class TestBasics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_reexec_uses_skill_venv(self):
        """Plain python3 must transparently run the skill's venv interpreter."""
        r = run("--doctor")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(
            str(SKILL_DIR / ".venv") in r.stdout or ".venvs/" in r.stdout,
            r.stdout,
        )

    def test_list_formats_runs(self):
        r = run("--list-formats")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("markitdown", r.stdout)
        self.assertIn("docx", r.stdout)

    def test_csv_to_stdout(self):
        p = Path(self.tmp.name)
        src = p / "t.csv"
        src.write_text("a,b\n1,2\n")
        r = run(str(src))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| a | b |", r.stdout)

    def test_single_file_output_path(self):
        src = Path(self.tmp.name) / "t.csv"
        src.write_text("a,b\n1,2\n")
        out = Path(self.tmp.name) / "sub" / "named.md"
        r = run(str(src), "-o", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out.exists(), "explicit -o file was not written")
        self.assertIn("| a | b |", out.read_text())

    def test_no_input_errors(self):
        self.assertNotEqual(run().returncode, 0)

    def test_multi_input_requires_directory_output(self):
        p = Path(self.tmp.name)
        (p / "a.csv").write_text("x\n1\n")
        (p / "b.csv").write_text("y\n2\n")
        r = run(str(p / "a.csv"), str(p / "b.csv"), "-o", str(p / "out.md"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("directory", r.stderr.lower())


class TestBatchBehaviour(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stem_collision_does_not_overwrite(self):
        (self.p / "doc.csv").write_text("from,csv\n")
        (self.p / "doc.html").write_text("<h1>from html</h1>")
        out = self.p / "out"
        r = run(str(self.p / "doc.csv"), str(self.p / "doc.html"), "-o", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("from", (out / "doc.md").read_text())
        self.assertIn("from html", (out / "doc-2.md").read_text())

    def test_recursive_preserves_structure_and_skips_junk(self):
        (self.p / "nested").mkdir()
        (self.p / "nested" / "deep.csv").write_text("d\n1\n")
        (self.p / "junk.py").write_text("print(1)\n")
        (self.p / "blob.bin").write_bytes(b"\x00\x01\x02")
        out = self.p / "out"
        r = run(str(self.p), "-r", "-o", str(out), "-v")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((out / "nested" / "deep.md").exists())
        self.assertFalse((out / "junk.md").exists())
        self.assertFalse((out / "blob.md").exists())
        self.assertIn("skipped", r.stderr + r.stdout)

    def test_legacy_binary_offices_are_not_claimed(self):
        (self.p / "old.doc").write_text("{\\rtf1 legacy}")
        (self.p / "old.ppt").write_text("{\\rtf1 legacy}")
        r = run(str(self.p), "-r", "-o", str(self.p / "out"), "-v")
        self.assertFalse((self.p / "out" / "old.md").exists(),
                         "legacy .doc/.ppt must be skipped, not emitted as raw RTF")

    def test_xlsx_is_included(self):
        from openpyxl import Workbook
        wb = Workbook()
        wb.active["A1"] = "Header"
        wb.save(self.p / "s.xlsx")
        out = self.p / "out"
        r = run(str(self.p), "-r", "-o", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Header", (out / "s.md").read_text())

    def test_stdin(self):
        r = run("-i", "-", stdin="<h1>piped</h1>")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("piped", r.stdout)

    def test_missing_file_reports_no_input(self):
        self.assertNotEqual(run(str(self.p / "nope.pdf")).returncode, 0)


class TestFrontmatter(unittest.TestCase):
    def test_yaml_quoting(self):
        self.assertEqual(m.yaml_quote('Report: Q1 "final"'), '"Report: Q1 \\"final\\""')

    def test_frontmatter_added_and_suppressible(self):
        body = m.with_frontmatter("content", "My: Title")
        self.assertTrue(body.startswith('---\ntitle: "My: Title"\n---\n'))
        self.assertIn("content", body)
        self.assertEqual(m.with_frontmatter("content", None), "content")


class TestOcrIsLocalAndOptional(unittest.TestCase):
    """The OCR path must be a local OpenAI-compatible endpoint, not tesseract."""

    def test_no_tesseract_dependency_anywhere(self):
        """OCR must not depend on system packages. The word may appear in prose,
        but no code path may import or invoke one."""
        import re
        src = (SKILL_DIR / "scripts" / "markitdown_cli.py").read_text()
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        code = re.sub(r'""".*?"""', "", code, flags=re.S)          # drop docstrings
        for banned in ("import pytesseract", "import tesseract", "enable_ocr",
                       "enable_audio", "--enable-ocr", "--enable-audio", "whisper"):
            self.assertNotIn(banned, code, f"{banned} must not appear in code")

    def test_ocr_defaults_point_at_local_server(self):
        self.assertIn("localhost", m.DEFAULT_OCR_BASE_URL)
        self.assertTrue(m.DEFAULT_OCR_MODEL)

    def test_ocr_prompt_is_a_transcription_prompt(self):
        self.assertIn("ranscribe", m.OCR_PROMPT)

    def test_ocr_builds_client_with_base_url(self):
        ns = mock.Mock(ocr=True, llm_client=None, llm_model=None, llm_api_key=None,
                       llm_base_url=None, ocr_client="openai",
                       ocr_base_url="http://127.0.0.1:9999/v1", ocr_model="qwen2.5vl",
                       llm_prompt=None)
        fake = mock.Mock()
        with mock.patch.object(m, "build_client", return_value=fake) as bc:
            engine = m.build_markitdown(ns)
        self.assertEqual(bc.call_args[0][0], "openai")
        self.assertEqual(bc.call_args[0][2], "http://127.0.0.1:9999/v1")
        self.assertIs(engine._llm_client, fake)

    def test_ocr_disabled_by_default(self):
        ns = mock.Mock(ocr=False, llm_client=None, llm_model=None)
        with mock.patch.object(m, "build_client") as bc:
            m.build_markitdown(ns)
        bc.assert_not_called()

    def test_llm_prompt_override_wins(self):
        ns = mock.Mock(ocr=True, llm_client=None, llm_model=None, llm_api_key=None,
                       llm_base_url=None, ocr_client="openai",
                       ocr_base_url=None, ocr_model="m", llm_prompt="CUSTOM")
        with mock.patch.object(m, "build_client", return_value=mock.Mock()):
            engine = m.build_markitdown(ns)
        self.assertIn("CUSTOM", engine.__dict__.values().__str__())


class TestEndpointProbe(unittest.TestCase):
    def setUp(self):
        seen = []          # closure: `self` inside a request handler is NOT the TestCase

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                body = json.dumps({"data": [{"id": "llava:latest"}, {"id": "qwen2.5vl"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.seen = seen
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()

    def test_probe_reports_reachable_and_models(self):
        out = m.probe_endpoint(f"http://127.0.0.1:{self.port}/v1", "llava")
        self.assertIn("reachable", out)
        self.assertIn("llava:latest", out)
        self.assertEqual(self.seen, ["/v1/models"])

    def test_unreachable_endpoint_is_reported_clearly(self):
        out = m.probe_endpoint("http://127.0.0.1:1/v1", "llava")
        self.assertIn("could not reach", out)

    def test_doctor_probes_when_ocr_requested(self):
        r = run("--doctor", "--ocr", "--ocr-base-url", f"http://127.0.0.1:{self.port}/v1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("reachable", r.stdout)
        self.assertIn("llava", r.stdout)


class TestOcrEndToEnd(unittest.TestCase):
    """End-to-end OCR against a stub OpenAI-compatible vision server.

    Exercises the real openai SDK path: image -> base64 data URI -> local
    /v1/chat/completions -> markdown output.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        received = []      # closure: `self` in a request handler is NOT the TestCase
        transcription = "INVOICE 4471\nTotal: 89.50"

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                received.append(body)
                out = {
                    "id": "x", "object": "chat.completion", "created": 0, "model": "stub",
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": transcription}}],
                }
                payload = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                payload = json.dumps({"data": [{"id": "stub-vision"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.received = received
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.tmp.cleanup()

    def _make_png(self) -> Path:
        from PIL import Image, ImageDraw
        p = Path(self.tmp.name) / "scan.png"
        img = Image.new("RGB", (240, 80), "white")
        ImageDraw.Draw(img).text((8, 30), "INVOICE 4471", fill="black")
        img.save(p)
        return p

    def test_png_ocr_uses_local_endpoint(self):
        src = self._make_png()
        out = Path(self.tmp.name) / "out.md"
        r = run(str(src), "--ocr",
                "--ocr-base-url", f"http://127.0.0.1:{self.port}/v1",
                "--ocr-model", "stub-vision", "-o", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.received), 1, "vision server was never called")
        body = self.received[0]
        self.assertEqual(body["model"], "stub-vision")
        url = body["messages"][0]["content"][1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"), url[:40])
        self.assertIn("INVOICE 4471", out.read_text())
        self.assertIn("89.50", out.read_text())

    def test_ocr_prompt_reaches_the_server(self):
        src = self._make_png()
        run(str(src), "--ocr",
            "--ocr-base-url", f"http://127.0.0.1:{self.port}/v1",
            "--ocr-model", "stub-vision", "-o", str(Path(self.tmp.name) / "o.md"))
        self.assertIn("Transcribe", self.received[0]["messages"][0]["content"][0]["text"])

    def test_custom_prompt_is_used(self):
        src = self._make_png()
        run(str(src), "--ocr", "--llm-prompt", "DESCRIBE IN SWEDISH",
            "--ocr-base-url", f"http://127.0.0.1:{self.port}/v1",
            "--ocr-model", "stub-vision", "-o", str(Path(self.tmp.name) / "o.md"))
        self.assertIn("DESCRIBE IN SWEDISH", self.received[0]["messages"][0]["content"][0]["text"])

    def test_ocr_off_by_default_makes_no_request(self):
        src = self._make_png()
        r = run(str(src), "-o", str(Path(self.tmp.name) / "o.md"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.received, [], "no vision call should happen without --ocr")

class TestTokenShieldingAndInspection(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_doc(self) -> Path:
        doc = self.p / "lecture.md"
        doc.write_text(
            "# Chapter 1: Introduction\n"
            "This is the opening overview of the course.\n\n"
            "## Section 1.1: CMOS Basics\n"
            "CMOS logic gates consist of PMOS and NMOS devices.\n\n"
            "## Section 1.2: Inverter Propagation Delay\n"
            "The propagation delay tpHL is measured from 50% input to 50% output.\n"
            "The NMOS discharge current determines the fall time.\n\n"
            "# Chapter 2: Dynamic Power\n"
            "Power dissipation has dynamic and static components.\n"
        )
        return doc

    def test_outline_table(self):
        src = self._make_doc()
        r = run(str(src), "--outline", "--table")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("### Outline: lecture.md", r.stdout)
        self.assertIn("| Level | Heading", r.stdout)
        self.assertIn("Chapter 1: Introduction", r.stdout)
        self.assertIn("Inverter Propagation Delay", r.stdout)
        self.assertIn("Chapter 2: Dynamic Power", r.stdout)

    def test_outline_projection_and_limit(self):
        src = self._make_doc()
        r = run(str(src), "--outline", "-p", "heading,words", "-n", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| Heading", r.stdout)
        self.assertNotIn("| Level", r.stdout)
        # Only 2 rows + header + sep = 4 lines
        table_lines = [l for l in r.stdout.splitlines() if l.startswith("|")]
        self.assertEqual(len(table_lines), 4)

    def test_outline_json(self):
        src = self._make_doc()
        r = run(str(src), "--outline", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["total_headings"], 4)
        self.assertEqual(data["headings"][0]["heading"], "Chapter 1: Introduction")

    def test_section_extraction(self):
        src = self._make_doc()
        r = run(str(src), "--section", "Propagation Delay")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("propagation delay tpHL", r.stdout)
        self.assertNotIn("Chapter 2: Dynamic Power", r.stdout)
        self.assertNotIn("CMOS Basics", r.stdout)

    def test_grep_extraction(self):
        src = self._make_doc()
        r = run(str(src), "--grep", "tpHL")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("tpHL", r.stdout)
        self.assertIn(":", r.stdout)  # line numbered

    def test_receipt_table_on_disk_write(self):
        src = self._make_doc()
        out = self.p / "converted.md"
        r = run(str(src), "-o", str(out), "--table")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out.exists())
        self.assertIn("| Input", r.stdout)
        self.assertIn("converted", r.stdout)

    def test_receipt_json_on_disk_write(self):
        src = self._make_doc()
        out = self.p / "converted.md"
        r = run(str(src), "-o", str(out), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out.exists())
        data = json.loads(r.stdout)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(len(data["converted"]), 1)
        self.assertEqual(data["converted"][0]["input"], "lecture.md")


if __name__ == "__main__":
    unittest.main(verbosity=2)
