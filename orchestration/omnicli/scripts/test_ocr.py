#!/usr/bin/env python3
"""Offline tests for navidc-ocr. Uses a stub llama-server; no real model."""
import base64
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

try:
    import pymupdf  # noqa: F401
except ModuleNotFoundError:
    if os.environ.get("_NAVIDC_TEST_REEXEC") != "1":
        os.environ["_NAVIDC_TEST_REEXEC"] = "1"
        py = str(SKILL_DIR / ".venv" / "bin" / "python")
        os.execv(py, [py, str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.exit("pymupdf missing from the skill venv")

sys.path.insert(0, str(SKILL_DIR / "scripts"))
import ocr  # noqa: E402

CLI = [sys.executable, str(SKILL_DIR / "scripts" / "ocr.py")]


def _clean_env(**overrides):
    """os.environ minus any NAVIDC_* override.

    Importing `ocr` above loads the real scripts/.env into this process, so
    those vars would otherwise be inherited by every subprocess and (correctly)
    take precedence over the .env a test writes. Strip them so each test
    actually controls the configuration it is asserting on.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("NAVIDC_") and not k.startswith("OCR_")}
    env.update(overrides)
    return env


def run(*args, env=None):
    return subprocess.run(CLI + list(args), capture_output=True, text=True,
                          env=env if env is not None else _clean_env())


class StubServer:
    """A stand-in llama-server exposing /health and /v1/chat/completions."""

    def __init__(self, fail_first=0, text="STUB OCR TEXT"):
        self.received = []
        self.fail_first = fail_first
        self.text = text
        received = self.received
        # `self` inside a BaseHTTPRequestHandler is the *request*, not this
        # object, so every value the handler needs must be captured here.
        fail_first, text = self.fail_first, self.text

        class H(http.server.BaseHTTPRequestHandler):
            def _json(self, obj, code=200):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                if self.path.startswith("/health"):
                    self._json({"status": "ok"})
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                received.append(body)
                if len(received) <= fail_first:
                    self._json({"error": "busy"}, 503)
                    return
                self._json({
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}]
                })

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.srv.shutdown()


def make_pdf(path: Path, pages: int = 3) -> Path:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100), f"Page {i + 1} content")
    doc.save(path)
    doc.close()
    return path


class TestDotEnv(unittest.TestCase):
    """The skill documents .env support, so it must actually work."""

    def _with_env(self, body):
        """Write scripts/.env, yield, then always restore it."""
        env_file = SKILL_DIR / "scripts" / ".env"
        backup = env_file.read_bytes() if env_file.exists() else None
        self.addCleanup(lambda: (env_file.write_bytes(backup) if backup is not None
                                 else env_file.unlink(missing_ok=True)))
        env_file.write_text(body, encoding="utf-8")
        return env_file

    def test_values_are_applied(self):
        self._with_env('NAVIDC_OCR_PORT=9123\nNAVIDC_OCR_HOST="127.0.0.1"\n')
        r = run("--server-cmd")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--port 9123", r.stdout)
        self.assertIn("--host 127.0.0.1", r.stdout)

    def test_real_environment_wins_over_file(self):
        self._with_env("NAVIDC_OCR_PORT=9123\n")
        r = run("--server-cmd", env=_clean_env(NAVIDC_OCR_PORT="7000"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--port 7000", r.stdout)
        self.assertNotIn("--port 9123", r.stdout)

    def test_export_quotes_comments_blank_lines(self):
        self._with_env(
            "# a comment\n"
            "\n"
            "export NAVIDC_OCR_PORT=9321\n"
            "NAVIDC_OCR_MODEL_DIR='/run/media/rodri/AI/models/nandraj/NaviDC-OCR-GGUF'\n"
        )
        r = run("--server-cmd")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--port 9321", r.stdout)
        self.assertIn("nandraj", r.stdout)
        self.assertNotIn("#", r.stdout.splitlines()[0])

    def test_doctor_reports_env_file(self):
        self._with_env("NAVIDC_OCR_PORT=9123\n")
        r = run("--doctor")
        self.assertIn("env file", r.stdout)
        self.assertIn("NAVIDC_OCR_PORT", r.stdout)

    def test_missing_env_file_is_harmless(self):
        env_file = SKILL_DIR / "scripts" / ".env"
        backup = env_file.read_bytes() if env_file.exists() else None
        self.addCleanup(lambda: env_file.write_bytes(backup) if backup is not None else None)
        env_file.unlink(missing_ok=True)
        self.assertEqual(run("--server-cmd").returncode, 0)


class TestPatchedServer(unittest.TestCase):
    """These GGUFs need the patched build; --doctor/--server-cmd must say so."""

    def test_server_cmd_points_at_a_real_binary(self):
        r = run("--server-cmd")
        self.assertEqual(r.returncode, 0, r.stderr)
        exe = ocr.find_server_bin()
        self.assertIsNotNone(exe, "no llama-server found for this skill")
        self.assertTrue(exe.exists(), f"{exe} does not exist")
        self.assertTrue(os.access(exe, os.X_OK), f"{exe} is not executable")
        self.assertIn(str(exe), r.stdout)

    def test_doctor_reports_the_patch(self):
        r = run("--doctor")
        self.assertIn("patch", r.stdout)
        # must not report the binary as missing on this machine
        self.assertNotIn("not installed on PATH", r.stdout)

    def test_server_cmd_uses_context_8192(self):
        self.assertIn("-c 8192", run("--server-cmd").stdout)


class TestServerCmd(unittest.TestCase):
    def test_server_cmd_is_printed_not_run(self):
        r = run("--server-cmd")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("llama-server", r.stdout)
        self.assertIn("--mmproj", r.stdout)
        self.assertIn(str(ocr.MODEL_DIR), r.stdout)

    def test_server_cmd_uses_real_weights_present_on_disk(self):
        weights, mmproj = ocr.find_model()
        self.assertIsNotNone(weights, "NaviDC weights not found")
        self.assertIsNotNone(mmproj, "mmproj not found")
        self.assertTrue(weights.exists() and mmproj.exists())
        self.assertNotIn("mmproj", weights.name.lower())

    def test_no_windows_paths_anywhere(self):
        src = (SKILL_DIR / "scripts" / "ocr.py").read_text()
        for bad in ("C:\\", "D:\\", "llama-server.exe", "Users\\rodri"):
            self.assertNotIn(bad, src, f"stale Windows path {bad!r}")

    def test_reexec_uses_skill_venv(self):
        """System python3 has no pymupdf, so the CLI must re-exec into .venv."""
        system_python = "/usr/bin/python3"
        probe = subprocess.run([system_python, "-c", "import pymupdf"],
                               capture_output=True, text=True)
        if probe.returncode == 0:
            self.skipTest(f"{system_python} can import pymupdf; nothing to re-exec")
        # Invoking the CLI with the system interpreter must still work.
        r = subprocess.run([system_python, str(SKILL_DIR / "scripts" / "ocr.py"),
                            "--server-cmd"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("llama-server", r.stdout)


class TestPageSelection(unittest.TestCase):
    def test_all_pages(self):
        self.assertEqual(ocr.parse_pages(None, 5), [0, 1, 2, 3, 4])

    def test_ranges_and_lists(self):
        self.assertEqual(ocr.parse_pages("1-3,7", 10), [0, 1, 2, 6])

    def test_out_of_range_exits(self):
        with self.assertRaises(SystemExit) as cm:
            ocr.parse_pages("9-11", 3)
        self.assertIn("out of range", str(cm.exception))

    def test_duplicates_collapse(self):
        self.assertEqual(ocr.parse_pages("2,2,1", 5), [0, 1])


class TestOcrAgainstStub(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        self.srv = StubServer()
        self.addCleanup(self.srv.stop)
        self.addCleanup(self.tmp.cleanup)

    def _ocr(self, *extra):
        return run(str(self.p / "doc.pdf"), "--endpoint",
                   f"{self.srv.base}/v1/chat/completions", *extra)

    def test_pdf_pages_marked_and_ordered(self):
        make_pdf(self.p / "doc.pdf", pages=3)
        r = self._ocr()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("<!-- Page 1 -->", r.stdout)
        self.assertIn("<!-- Page 3 -->", r.stdout)
        self.assertEqual(len(self.srv.received), 3)
        # page markers must appear in ascending order regardless of completion order
        idx = [r.stdout.index(f"<!-- Page {n} -->") for n in (1, 2, 3)]
        self.assertEqual(idx, sorted(idx))

    def test_request_shape(self):
        make_pdf(self.p / "doc.pdf", pages=1)
        self._ocr()
        body = self.srv.received[0]
        self.assertEqual(body["temperature"], 0.0)
        url = body["messages"][0]["content"][1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"), url[:40])
        self.assertIn("Extract all text", body["messages"][0]["content"][0]["text"])

    def test_page_subset_only_sends_those_pages(self):
        make_pdf(self.p / "doc.pdf", pages=5)
        r = self._ocr("--pages", "2-3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.srv.received), 2)
        self.assertIn("<!-- Page 2 -->", r.stdout)
        self.assertNotIn("<!-- Page 4 -->", r.stdout)

    def test_image_input(self):
        import pymupdf as pm
        img = pm.Pixmap(pymupdf.csRGB, pm.IRect(0, 0, 20, 20))
        img.set_rect(pm.IRect(0, 0, 20, 20), (255, 255, 255))
        img.save(self.p / "scan.png")
        r = run(str(self.p / "scan.png"), "--endpoint", f"{self.srv.base}/v1/chat/completions")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("STUB OCR TEXT", r.stdout)
        self.assertNotIn("<!-- Page", r.stdout)

    def test_output_file(self):
        make_pdf(self.p / "doc.pdf", pages=1)
        out = self.p / "out" / "doc.md"
        r = self._ocr("-o", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("STUB OCR TEXT", out.read_text())

    def test_retry_then_success(self):
        make_pdf(self.p / "doc.pdf", pages=1)
        # fail_first is bound when the stub is built, so build a fresh one
        flaky = StubServer(fail_first=1)
        self.addCleanup(flaky.stop)
        r = run(str(self.p / "doc.pdf"), "--endpoint",
                f"{flaky.base}/v1/chat/completions")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("STUB OCR TEXT", r.stdout)
        self.assertEqual(len(flaky.received), 2)

    def test_persistent_failure_marks_page_and_exits_zero(self):
        """A failed page is annotated in the output rather than losing the run."""
        make_pdf(self.p / "doc.pdf", pages=1)
        self.srv.stop()
        r = run(str(self.p / "doc.pdf"), "--endpoint", f"{self.srv.base}/v1/chat/completions")
        # server is gone, but the preflight health check should catch it
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not reachable", r.stderr)

    def test_unreachable_server_is_reported_with_start_command(self):
        make_pdf(self.p / "doc.pdf", pages=1)
        r = run(str(self.p / "doc.pdf"), "--endpoint", "http://127.0.0.1:1/v1/chat/completions")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("llama-server", r.stderr)

    def test_unsupported_extension(self):
        (self.p / "notes.xyz").write_text("x")
        r = run(str(self.p / "notes.xyz"), "--endpoint", f"{self.srv.base}/v1/chat/completions")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unsupported", r.stderr)

    def test_missing_file(self):
        r = run(str(self.p / "ghost.pdf"), "--endpoint", f"{self.srv.base}/v1/chat/completions")
        self.assertNotEqual(r.returncode, 0)

    def test_no_input(self):
        self.assertNotEqual(run().returncode, 0)


class TestDoctor(unittest.TestCase):
    def test_reports_unreachable_and_exits_nonzero(self):
        r = run("--doctor")
        self.assertEqual(r.returncode, 1)
        self.assertIn("reachable", r.stdout)
        self.assertIn("llama-server", r.stdout)

    def test_reports_reachable_when_up(self):
        srv = StubServer()
        self.addCleanup(srv.stop)
        import io
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["ocr.py", "--doctor", "--endpoint",
                                             f"{srv.base}/v1/chat/completions"]), \
             mock.patch.object(sys, "stdout", buf):
            code = ocr.main()
        self.assertEqual(code, 0)
        self.assertIn("reachable  yes", buf.getvalue())
        self.assertIn(srv.base, buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
