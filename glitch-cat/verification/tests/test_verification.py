#!/usr/bin/env python3
"""Tests for the verification gate.

Offline tests cover the parts that must never need a browser: pixel arithmetic,
viewport parsing, the five questions, and the partial-gate rule. Live tests
drive the fixture app over real CDP and are skipped — not failed — when no
browser answers on :9222, because a stopped daemon is not a broken gate.

    python3 tests/test_verification.py
"""

from __future__ import annotations

import json
import shutil
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import cdp_lite  # noqa: E402
import verify  # noqa: E402
from fixture_app import Handler  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def cdp_alive(port: int = 9222) -> bool:
    try:
        return bool(cdp_lite.list_targets(port=port))
    except cdp_lite.CDPError:
        return False


class FixtureServer:
    def __init__(self) -> None:
        self.port = free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "FixtureServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"


class TestPureParts(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-test-"))

    def _png(self, name: str, pixels: bytes, width: int = 4, height: int = 4) -> Path:
        path = self.tmp / name
        verify._write_png(path, width, height, pixels)
        return path

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for the pixel layer")
    def test_01_identical_pngs_pass(self):
        pixels = bytes([12, 34, 56] * 16)
        before = self._png("a.png", pixels)
        after = self._png("b.png", pixels)
        result = verify.compare_pixels(before, after)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["changed"], 0)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for the pixel layer")
    def test_02_changed_pixels_fail_with_box(self):
        before = self._png("a.png", bytes([0, 0, 0] * 16))
        after_pixels = bytearray(before.read_bytes() and bytes([0, 0, 0] * 16))
        after_pixels[3 * 5] = 255
        after = self._png("b.png", bytes(after_pixels))
        diff = self.tmp / "diff.png"
        result = verify.compare_pixels(before, after, diff_out=diff)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["changed"], 1)
        self.assertEqual(result["box"], {"x": 1, "y": 1, "w": 1, "h": 1})
        self.assertTrue(diff.exists())

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for the pixel layer")
    def test_03_tolerance_absorbs_antialiasing(self):
        before = self._png("a.png", bytes([100, 100, 100] * 16))
        after = self._png("b.png", bytes([106, 106, 106] * 16))
        self.assertEqual(verify.compare_pixels(before, after, tolerance=8)["status"], "pass")
        self.assertEqual(verify.compare_pixels(before, after, tolerance=2)["status"], "fail")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for the pixel layer")
    def test_04_size_change_is_a_failure_not_a_crash(self):
        before = self._png("a.png", bytes([0, 0, 0] * 16), width=4, height=4)
        after = self._png("b.png", bytes([0, 0, 0] * 9), width=3, height=3)
        result = verify.compare_pixels(before, after)
        self.assertEqual(result["status"], "fail")
        self.assertIn("size changed", result["detail"])

    def test_05_viewport_parsing(self):
        self.assertEqual(verify._parse_viewport("390x844"), (390, 844, 1.0, True))
        self.assertEqual(verify._parse_viewport("1440x900@2"), (1440, 900, 2.0, False))
        with self.assertRaises(verify.Dependency):
            verify._parse_viewport("big")

    def test_06_five_questions_and_skeleton(self):
        self.assertEqual(len(verify.QUESTIONS), 5)
        config = verify.init_config(self.tmp / ".verify")
        loaded = json.loads(config.read_text())
        for key in ("api", "journey", "expect", "pixels", "states", "errors"):
            self.assertIn(key, loaded)
        self.assertEqual(len(verify._unanswered(loaded)), 5)

    def test_07_unanswered_gate_is_partial(self):
        config = {
            "name": "smoke",
            "api": {"url": "http://127.0.0.1:9/never"},
            "journey": [{"wait": 1}],
        }
        gaps = verify._unanswered(config)
        self.assertEqual(len(gaps), 3)

    def test_08_doctor_needs_no_app(self):
        result = verify.doctor(port=9222)
        for layer in ("hands", "eyes", "pixels", "states", "errors"):
            self.assertIn(layer, result)
        self.assertIn("ready", result)


@unittest.skipUnless(cdp_alive(), "no CDP browser on :9222 — start `playwright-rs daemon start`")
class TestLiveGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = FixtureServer().__enter__()
        cls.tmp = Path(tempfile.mkdtemp(prefix="verify-live-"))

    @classmethod
    def tearDownClass(cls):
        cls.fixture.__exit__(None, None, None)

    def test_10_cut_off_button_is_caught(self):
        report = verify.probe(
            self.fixture.url("/buggy"), viewport="390x844",
            journey=[{"click": "#pay"}], expect={"no_failed_requests": True},
        )
        self.assertEqual(report["status"], "fail")
        kinds = {problem["kind"] for problem in report["problems"]}
        self.assertIn("viewport", kinds)
        self.assertTrue(any("cut off" in problem["text"] for problem in report["problems"]))

    def test_11_fixed_page_passes(self):
        report = verify.probe(
            self.fixture.url("/fixed"), viewport="390x844",
            journey=[{"click": "#pay"}],
            expect={"text": "Order confirmed",
                    "requests": [{"contains": "/api/checkout", "status": 200}]},
        )
        self.assertEqual(report["status"], "pass", report["problems"])
        self.assertTrue(report["text"]["found"])

    def test_12_failed_request_is_named(self):
        report = verify.probe(
            self.fixture.url("/buggy"), viewport="390x844",
            journey=[{"click": "#pay"}, {"wait": 300}],
            expect={"no_failed_requests": True},
        )
        self.assertEqual(report["status"], "fail")

    def test_15_text_transform_is_matched_case_insensitively(self):
        report = verify.probe(
            self.fixture.url("/fixed"), viewport="390x844",
            journey=[{"click": "#pay"}], expect={"text": "Order confirmed"},
        )
        self.assertEqual(report["status"], "pass", report["problems"])
        strict = verify.probe(
            self.fixture.url("/fixed"), viewport="390x844",
            journey=[{"click": "#pay"}],
            expect={"text": "Order confirmed", "case_sensitive": True},
        )
        self.assertEqual(strict["status"], "fail")

    def test_16_shrink_to_fit_is_named(self):
        report = verify.probe(self.fixture.url("/wide"), viewport="390x844")
        self.assertTrue(report["layout"]["shrink_to_fit"])
        self.assertEqual(report["status"], "fail")
        kinds = [problem["kind"] for problem in report["problems"]]
        self.assertIn("layout", kinds)

    def test_17_eval_expectations(self):
        report = verify.probe(
            self.fixture.url("/fixed"), viewport="390x844",
            expect={"eval": [
                {"expression": "document.querySelector('#pay') !== null", "label": "button exists"},
                {"expression": "1 + 1 === 3", "label": "deliberately false"},
            ]},
        )
        self.assertEqual(report["status"], "fail")
        checks = {check["label"]: check["ok"] for check in report["evals"]}
        self.assertTrue(checks["button exists"])
        self.assertFalse(checks["deliberately false"])

    def test_18_covered_button_is_named(self):
        report = verify.probe(
            self.fixture.url("/occluded"), viewport="390x844",
            journey=[{"click": "#pay"}], expect={"no_failed_requests": True},
        )
        self.assertEqual(report["status"], "fail")
        occluded = [p for p in report["problems"] if p["kind"] == "occluded"]
        self.assertEqual(len(occluded), 1)
        self.assertIn("#overlay", occluded[0]["text"])

    def test_13_storybook_walker_isolates_the_broken_story(self):
        result = verify.storybook_states(self.fixture.url("/"), limit=10)
        self.assertEqual(result["status"], "fail")
        broken = [s for s in result["stories"] if s["status"] != "pass"]
        self.assertEqual([s["id"] for s in broken], ["cart-item--broken"])

    def test_14_full_gate_pass_and_fail(self):
        baseline = self.tmp / "baseline.png"
        verify.probe(self.fixture.url("/fixed"), viewport="390x844",
                     journey=[{"click": "#pay"}], screenshot=baseline)
        good = {
            "name": "cart", "api": {"url": self.fixture.url("/fixed"), "viewport": "390x844"},
            "journey": [{"click": "#pay"}],
            "expect": {"text": "Order confirmed",
                       "requests": [{"contains": "/api/checkout", "status": 200}]},
            "pixels": {"baseline": str(baseline), "max_changed": 0.0},
            "states": {"storybook": self.fixture.url("/"), "filter": "Default"},
            "errors": {"sentry": {"org": "acme", "project": "web"}},
        }
        passed = verify.run_pass(good, out_dir=self.tmp / "art-pass")
        self.assertEqual(passed["verdict"], "pass", passed)
        self.assertEqual(passed["exit"], verify.EXIT_PASS)
        self.assertEqual(passed["gate"], "full")
        bad = json.loads(json.dumps(good))
        bad["api"]["url"] = self.fixture.url("/buggy")
        failed = verify.run_pass(bad, out_dir=self.tmp / "art-fail")
        self.assertEqual(failed["verdict"], "fail")
        self.assertIn("eyes", failed["failed"])
        self.assertIn("pixels", failed["failed"])
        self.assertTrue((self.tmp / "art-fail" / "verify.json").exists())


class TestForge(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-forge-"))
        self.repo = self.tmp / "gulp-club"
        (self.repo / "app" / "order").mkdir(parents=True)
        (self.repo / "app" / "basket").mkdir(parents=True)
        (self.repo / "package.json").write_text(json.dumps({
            "name": "gulp-club",
            "dependencies": {"next": "15.0.0", "react": "19.0.0"},
            "scripts": {"dev": "next dev", "build": "next build"},
        }))
        (self.repo / "app" / "order" / "page.tsx").write_text("export default function Page() {}")
        (self.repo / "app" / "basket" / "page.tsx").write_text("export default function Page() {}")
        (self.repo / "playwright.config.ts").write_text("export default {}")
        (self.repo / ".claude").mkdir()

    def test_20_interview_reads_the_repo(self):
        found = verify.interview_repo(self.repo)
        self.assertEqual(found["app"], "gulp-club")
        self.assertEqual([row["surface"] for row in found["surfaces"]], ["web"])
        self.assertEqual(found["run"]["command"], "npm run dev")
        self.assertEqual(found["harness"], "claude")
        self.assertEqual(found["out_dir"], ".claude/skills/verify-gulp-club")
        titles = {feature["id"] for feature in found["features"]}
        self.assertEqual(titles, {"order", "basket"})
        self.assertTrue(any("Isolate" in question for question in found["open"]))
        self.assertEqual(verify.forge(self.repo)["verdict"], "open")

    def test_20b_defaults_to_the_portable_agents_directory(self):
        portable = self.tmp / "portable"
        (portable / "app").mkdir(parents=True)
        (portable / "package.json").write_text(json.dumps({
            "name": "portable", "dependencies": {"vite": "6.0.0"}, "scripts": {"dev": "vite"},
        }))
        (portable / "app" / "page.tsx").write_text("export default function P() {}")
        found = verify.interview_repo(portable)
        self.assertEqual(found["harness"], "agents")
        self.assertEqual(found["out_dir"], ".agents/skills/verify-portable")
        rendered = verify._render_skill(verify.forge(portable)["interview"], "2026-10-29")
        self.assertIn("@verify-portable", rendered)
        self.assertNotIn(".claude", rendered)

    def test_20c_static_html_pages_become_features(self):
        site = self.tmp / "static-site"
        site.mkdir()
        (site / "index.html").write_text("<h1>Home</h1>")
        (site / "order.html").write_text("<h1>Order</h1>")
        (site / "404.html").write_text("not found")
        (site / "package.json").write_text(json.dumps({
            "name": "static-site", "scripts": {"dev": "python3 -m http.server 8741"},
        }))
        found = verify.interview_repo(site)
        self.assertEqual([row["surface"] for row in found["surfaces"]], ["web"])
        self.assertEqual({feature["entry"] for feature in found["features"]}, {"/", "/order"})
        self.assertEqual(found["run"]["command"], "npm run dev")

    def test_21_apply_writes_a_six_heading_skill_and_a_feature_contract(self):
        result = verify.forge(self.repo, apply=True)
        out = self.repo / result["out_dir"]
        skill = (out / "SKILL.md").read_text()
        headings = [line[3:] for line in skill.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, ["Launch", "Doctor", "Drive", "Evidence", "Cleanup", "Helpers"])
        self.assertIn("verify-gulp-club skill and show its evidence", skill)
        self.assertIn("empty data directory", skill)
        self.assertIn("never by process name", skill)
        self.assertIn("dry-run", skill)
        self.assertNotIn("UNANSWERED", skill.split("## Launch")[1])
        index = (out / "features" / "README.md").read_text()
        self.assertIn("Feature entry contract", index)
        self.assertIn("`Gotchas` lists traps", index)
        self.assertIn("one convenient entry point is incomplete", index)
        page = (out / "features" / "order.md").read_text()
        page_headings = [line[3:] for line in page.splitlines() if line.startswith("## ")]
        self.assertEqual(page_headings, ["Sub-features", "How to get to it (user POV)",
                                         "Driving it with verify-gulp-club", "Gotchas"])
        self.assertIn("Seeded page, unproven feature", page)
        shim = out / "scripts" / "verify"
        self.assertTrue(shim.is_file())
        self.assertTrue(shim.stat().st_mode & 0o111)
        skeleton = json.loads((self.repo / ".verify" / "pass.json").read_text())
        self.assertEqual(skeleton["name"], "gulp-club")

    def test_22_empty_repo_names_every_open_question(self):
        empty = self.tmp / "blank"
        empty.mkdir()
        result = verify.forge(empty)
        self.assertEqual(result["exit"], verify.EXIT_UNCONFIGURED)
        self.assertEqual(result["verdict"], "open")
        self.assertGreaterEqual(len(result["interview"]["open"]), 4)
        self.assertEqual(result["interview"]["surfaces"][0]["surface"], "unknown")

    def test_23_apply_is_idempotent_for_an_existing_skill(self):
        verify.forge(self.repo, apply=True)
        skill = self.repo / ".claude" / "skills" / "verify-gulp-club" / "SKILL.md"
        skill.write_text("hand edited")
        verify.forge(self.repo, apply=True)
        self.assertEqual(skill.read_text(), "hand edited")

    def test_23b_adoption_line_lands_once_in_the_instruction_file(self):
        first = verify.forge(self.repo, apply=True, adopt_to=Path("AGENTS.md"))
        path = self.repo / "AGENTS.md"
        self.assertTrue(first["adopted"]["changed"])
        self.assertTrue(path.read_text().startswith("## Verification"))
        self.assertIn("verify-gulp-club skill and show its evidence", path.read_text())
        second = verify.forge(self.repo, apply=True, adopt_to=Path("AGENTS.md"))
        self.assertFalse(second["adopted"]["changed"])
        self.assertEqual(path.read_text().count("check it with the verify-gulp-club"), 1)

    def test_23c_adoption_extends_an_existing_verification_section(self):
        path = self.repo / "AGENTS.md"
        path.write_text("# House rules\n\n## Verification\n\nKeep it honest.\n")
        verify.forge(self.repo, apply=True, adopt_to=Path("AGENTS.md"))
        text = path.read_text()
        self.assertEqual(text.count("## Verification"), 1)
        self.assertIn("check it with the verify-gulp-club skill", text)


class TestControl(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="verify-control-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.target = self.repo / "app.py"
        self.target.write_text('def pay():\n    return 200\n')

    def _runner(self, red_status="fail", green_status="pass"):
        def run():
            broken = "return 500" in self.target.read_text()
            if broken:
                return {"verdict": red_status, "exit": verify.EXIT_FAIL if red_status == "fail" else verify.EXIT_PASS,
                        "failed": ["eyes"]}
            return {"verdict": green_status, "exit": verify.EXIT_PASS if green_status == "pass" else verify.EXIT_FAIL,
                    "failed": []}
        return run

    def test_24_control_passes_when_red_is_seen_and_restore_is_exact(self):
        before = self.target.read_bytes()
        report = verify.control(self.repo, self.target, "return 200", "return 500",
                                runner=self._runner(), out_dir=self.tmp / "art")
        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["restored"])
        self.assertEqual(report["sha256_before"], report["sha256_after"])
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(report["red"]["verdict"], "fail")
        self.assertTrue((self.tmp / "art" / "control.json").exists())

    def test_25_control_fails_when_the_gate_stays_green(self):
        report = verify.control(self.repo, self.target, "return 200", "return 500",
                                runner=self._runner(red_status="pass"), out_dir=self.tmp / "art")
        self.assertEqual(report["verdict"], "fail")
        self.assertIn("stayed green", report["detail"])
        self.assertEqual(self.target.read_text(), 'def pay():\n    return 200\n')

    def test_26_control_fails_when_green_never_returns(self):
        report = verify.control(self.repo, self.target, "return 200", "return 500",
                                runner=self._runner(green_status="fail"), out_dir=self.tmp / "art")
        self.assertEqual(report["verdict"], "fail")
        self.assertIn("did not pass after the restore", report["detail"])

    def test_27_control_refuses_ambiguous_protected_and_outside_targets(self):
        self.target.write_text("return 200\nreturn 200\n")
        with self.assertRaises(verify.Dependency):
            verify.control(self.repo, self.target, "return 200", "return 500", runner=lambda: {})
        secret = self.repo / ".env"
        secret.write_text("KEY=1\n")
        with self.assertRaises(verify.Dependency):
            verify.control(self.repo, secret, "KEY=1", "KEY=2", runner=lambda: {})
        with self.assertRaises(verify.Dependency):
            verify.control(self.repo, Path("/etc/hostname"), "host", "other", runner=lambda: {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
