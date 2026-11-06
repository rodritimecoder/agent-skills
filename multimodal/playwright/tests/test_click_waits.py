#!/usr/bin/env python3
"""click must wait for a clickable element, and prove the effect it was asked for.

These are browser-backed. They skip when no Chromium can be started, which is
what happens on a machine where the daemon cannot come up.
"""

import json
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BIN = ROOT / "multimodal" / "playwright" / "bin" / "playwright-rs"

SLOW = """<!doctype html><html><body>
<h1>Slow app</h1><div id="root"></div><div id="status">booting</div>
<script>
  setTimeout(() => {
    document.getElementById('root').innerHTML = '<button id="go">Finish order</button>';
    document.getElementById('status').textContent = 'ready';
    document.getElementById('go').addEventListener('click', () => {
      setTimeout(() => { document.getElementById('status').textContent = 'order placed'; }, 200);
    });
  }, 700);
</script></body></html>"""

COVERED = """<!doctype html><html><body>
<button id="buy">Buy now</button>
<div style="position:fixed;inset:0;background:rgba(0,0,0,.4)"></div>
</body></html>"""

DISABLED = """<!doctype html><html><body>
<button id="pay" disabled>Pay</button>
</body></html>"""

WORKFLOW = """<!doctype html><html><body>
<h1>Order review</h1>
<button id="complete">Complete order</button>
<div id="status">waiting</div>
<script>document.getElementById('complete').addEventListener('click', () => {
  document.getElementById('status').textContent = 'order confirmed';
});</script>
</body></html>"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestClickWaits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BIN.is_file():
            raise unittest.SkipTest(f"no binary at {BIN}")
        try:
            probe = subprocess.run([str(BIN), "open", "about:blank"], capture_output=True, text=True, timeout=5)
            if probe.returncode != 0:
                raise unittest.SkipTest(f"playwright driver unavailable on this runner: {probe.stderr[:200]}")
        except (subprocess.TimeoutExpired, OSError) as e:
            raise unittest.SkipTest(f"playwright driver unavailable or timed out: {e}")
        start = subprocess.run([str(BIN), "daemon", "start"], capture_output=True, text=True, timeout=60)
        status = subprocess.run([str(BIN), "daemon", "status"], capture_output=True, text=True, timeout=30)
        if start.returncode != 0 or "running" not in status.stdout:
            raise unittest.SkipTest(f"could not start a browser daemon: {start.stderr[:200]}")

        cls.site = tempfile.TemporaryDirectory()
        root = Path(cls.site.name)
        (root / "slow.html").write_text(SLOW, encoding="utf-8")
        (root / "covered.html").write_text(COVERED, encoding="utf-8")
        (root / "disabled.html").write_text(DISABLED, encoding="utf-8")
        (root / "workflow.html").write_text(WORKFLOW, encoding="utf-8")

        cls.port = free_port()
        handler = partial(SimpleHTTPRequestHandler, directory=str(root))
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "httpd"):
            cls.httpd.shutdown()
            cls.httpd.server_close()
        if hasattr(cls, "site"):
            cls.site.cleanup()

    def open_page(self, name: str):
        res = subprocess.run(
            [str(BIN), "open", f"http://127.0.0.1:{self.port}/{name}", "--json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_01_waits_for_a_button_that_arrives_late(self):
        self.open_page("slow.html")
        res = subprocess.run(
            [str(BIN), "click", "#go", "--expect-text", "order placed", "--json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertTrue(data["ok"])
        self.assertGreaterEqual(data["waited_ms"], 500, "it should have waited for hydration")
        self.assertIn("text:order placed", data["effects"])
        print(f"  ✓ waited {data['waited_ms']}ms for hydration, then verified the effect")

    def test_02_refuses_a_button_under_an_overlay(self):
        self.open_page("covered.html")
        res = subprocess.run(
            [str(BIN), "click", "#buy", "--timeout", "1200"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("covered", (res.stderr or res.stdout).lower())
        print("  ✓ an overlay is reported as covered, not clicked through")

    def test_03_refuses_a_disabled_button(self):
        self.open_page("disabled.html")
        res = subprocess.run(
            [str(BIN), "click", "#pay", "--timeout", "800"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("disabled", (res.stderr or res.stdout).lower())
        print("  ✓ a disabled control is named, not silently clicked")

    def test_04_fails_when_the_promised_effect_never_happens(self):
        self.open_page("slow.html")
        res = subprocess.run(
            [str(BIN), "click", "#go", "--expect-text", "no such outcome", "--timeout", "900"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("never appeared", (res.stderr or res.stdout))
        print("  ✓ a click that changes nothing is not reported as success")

    def test_05_ai_snapshot_refs_drive_playwright_locators(self):
        self.open_page("workflow.html")
        snapshot = subprocess.run(
            [str(BIN), "snapshot", "--json"], capture_output=True, text=True, timeout=60
        )
        self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
        elements = json.loads(snapshot.stdout)["elements"]
        target = next(element for element in elements if "Complete order" in element["description"])
        self.assertRegex(target["ref"], r"^e\d+$")

        click = subprocess.run(
            [str(BIN), "click", target["ref"], "--expect-text", "order confirmed", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(click.returncode, 0, click.stderr)
        self.assertIn("text:order confirmed", json.loads(click.stdout)["effects"])
        print("  ✓ an AI-mode ARIA ref resolves through Playwright get_by_ref")

    def test_06_frontend_uat_ref_contract_runs_on_playwright(self):
        url = f"http://127.0.0.1:{self.port}/workflow.html"
        candidates = subprocess.run(
            [str(BIN), "candidates", url, "--json"], capture_output=True, text=True, timeout=60
        )
        self.assertEqual(candidates.returncode, 0, candidates.stderr)
        target = next(item for item in json.loads(candidates.stdout) if "Complete order" in item["description"])
        self.assertEqual(target["ref"], "uat-1")

        result = subprocess.run(
            [str(BIN), "uat", url, "--goal", "place the order", "--ref", target["ref"],
             "--expect-text", "order confirmed", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["actions"][0]["ref_id"], "uat-1")
        print("  ✓ frontend-uat's externally judged uat-N ref still executes and verifies")


if __name__ == "__main__":
    unittest.main(verbosity=2)
