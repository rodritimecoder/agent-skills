#!/usr/bin/env python3
"""Tests for the frontend-uat loop.

Offline tests cover the parts that must never depend on a live service: plan
validation, ref validation, the report shape, and the byte cap on stdout.

Live tests cover the two model turns and the CDP action against a real page
served from a temporary directory. They are skipped — not failed — when the CDP
browser on :9222 or the decision server on :8083 is down, because a stopped
daemon is not a broken loop.

    python3 tests/test_frontend_uat.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPT = SKILL_DIR / "scripts" / "frontend_uat.py"
sys.path.insert(0, str(SCRIPT.parent))

import frontend_uat as fu  # noqa: E402

PAGE = """<!doctype html><html><body>
<h1>Order review</h1>
<button id="b1">Back to catalog</button>
<button id="b2">Apply coupon</button>
<button id="b3" onclick="location.href='/cart.html'">Complete purchase</button>
<button id="b4">Save for later</button>
<a href="/cart.html">View cart</a>
</body></html>"""

CART = """<!doctype html><html><body>
<h1>Order confirmed</h1><p>Your payment was accepted.</p>
</body></html>"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestPureParts(unittest.TestCase):
    """No network, no services."""

    @classmethod
    def setUpClass(cls):
        if fu.find_fast_cdp() is None:
            raise unittest.SkipTest(
                "fast-cdp is not installed; the CLI refuses to parse arguments without it"
            )

    def test_01_decode_double_encoded(self):
        """fast-cdp eval returns the value JSON-encoded inside JSON."""
        self.assertEqual(fu._decode('[{"ref": "uat-1"}]'), [{"ref": "uat-1"}])
        self.assertEqual(fu._decode('"plain"'), "plain")
        with self.assertRaises(fu.DependencyError):
            fu._decode("not json at all")

    def test_02_format_report_is_one_line(self):
        rep = {"result": "pass", "intent": "click checkout", "duration_ms": 120,
               "selected": {"ref": "uat-3", "p_selected": 0.99},
               "verification": {"detail": "verified_by_assertions"}, "errors": []}
        line = fu.format_report(rep)
        self.assertEqual(line.count("\n"), 0)
        self.assertIn("[PASS]", line)
        self.assertIn("uat-3", line)
        self.assertLess(len(line), 200, "the default report must stay small")

    def test_03_format_report_surfaces_errors(self):
        rep = {"result": "fail", "intent": "x", "duration_ms": 5,
               "selected": {"ref": "uat-1", "p_selected": 0.1},
               "verification": {"detail": "failed"}, "errors": ["boom"]}
        self.assertIn("boom", fu.format_report(rep))

    def test_04_ref_must_belong_to_candidate_set(self):
        """A plan whose ref is not in its own candidate set must not click."""
        fast_cdp, jev = fu._require_halves()
        plan = {
            "url": "http://127.0.0.1:1/",
            "intent": "anything",
            "candidates": [{"ref": "uat-1", "description": "button 'A'"}],
            "decision": {"ref": "uat-9", "selection": "uat-9: button 'A'", "p_selected": 0.9},
            "steps": [],
        }
        rep = fu.run(fast_cdp, jev, plan["url"], plan["intent"], plan_in=plan)
        self.assertEqual(rep["result"], "fail")
        self.assertTrue(any("not in its candidate set" in e for e in rep["errors"]))
        self.assertIsNone(rep["action"], "nothing may be executed")

    def test_05_min_p_refuses_to_click(self):
        """A low-probability pick is refused before any action."""
        fast_cdp, jev = fu._require_halves()
        plan = {
            "url": "http://127.0.0.1:1/",
            "intent": "anything",
            "candidates": [{"ref": "uat-1", "description": "button 'A'"}],
            "decision": {"ref": "uat-1", "selection": "uat-1: button 'A'", "p_selected": 0.10,
                         "below_min_p": True},
            "steps": [],
        }
        rep = fu.run(fast_cdp, jev, plan["url"], plan["intent"], plan_in=plan, min_p=0.5)
        self.assertEqual(rep["result"], "fail")
        self.assertTrue(any("refusing to click" in e for e in rep["errors"]))
        self.assertIsNone(rep["action"])

    def test_06_plan_mismatch_exits_2(self):
        """A plan made for another url/intent is a usage error, not a click."""
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps({"url": "http://elsewhere/", "intent": "other"}))
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "run", "--url", "http://127.0.0.1:1/",
                 "--intent", "different", "--plan", str(plan_path)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("plan was made for", proc.stderr)

    def test_07_doctor_shape(self):
        out = fu.doctor()
        for key in ("fast_cdp", "jev_cli", "cdp_browser", "decision_server", "ready"):
            self.assertIn(key, out)

    def test_08_extractor_matches_upstream_contract(self):
        """The ref space is shared with `fast-cdp uat --ref`, so the JS must
        tag elements with data-uat-ref and number them in DOM order."""
        js = fu.EXTRACT_JS
        self.assertIn("data-uat-ref", js)
        self.assertIn("uat-${idx}", js)
        self.assertIn("[role=\"button\"]", js)


class TestLiveLoop(unittest.TestCase):
    """The real loop: one page, two model turns, one deterministic click."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.fast_cdp, cls.jev = fu._require_halves()
        except fu.DependencyError as exc:
            raise unittest.SkipTest(f"halves unavailable: {exc}")
        cls.out = fu.doctor()
        if not cls.out["ready"]:
            raise unittest.SkipTest(
                f"loop not ready — cdp={cls.out['cdp_browser']} decision={cls.out['decision_server']}")

        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "index.html").write_text(PAGE)
        (root / "cart.html").write_text(CART)
        cls.port = _free_port()
        handler = lambda *a, **kw: SimpleHTTPRequestHandler(*a, directory=str(root), **kw)  # noqa: E731
        cls.httpd = HTTPServer(("127.0.0.1", cls.port), handler)
        Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.port}/"

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "httpd"):
            cls.httpd.shutdown()
            cls.tmp.cleanup()

    def test_10_candidates_are_refs_in_dom_order(self):
        cands = fu.extract_candidates(self.fast_cdp, self.url)
        refs = [c["ref"] for c in cands]
        self.assertEqual(refs, [f"uat-{i}" for i in range(1, len(refs) + 1)], refs)
        self.assertGreaterEqual(len(cands), 4, cands)

    def test_11_keyword_matching_finds_nothing_but_the_model_does(self):
        """The reason this skill exists: an intent that shares no words with any
        label. `fast-cdp uat` reports no match; the decision model picks the
        purchase button anyway."""
        intent = "finish the payment and place the order"
        proc = subprocess.run([self.fast_cdp, "uat", self.url, "--goal", intent, "--json"],
                              capture_output=True, text=True, timeout=60)
        self.assertNotEqual(proc.returncode, 0, "keyword UAT unexpectedly matched")
        self.assertIn("No candidate matched", proc.stdout + proc.stderr)

        prepared = fu.plan(self.fast_cdp, self.jev, self.url, intent)
        chosen = next(c for c in prepared["candidates"] if c["ref"] == prepared["decision"]["ref"])
        self.assertIn("Complete purchase", chosen["description"], prepared["decision"])
        self.assertGreater(prepared["decision"]["p_selected"], 0.5, prepared["decision"])

    def test_12_full_loop_passes_with_an_assertion(self):
        rep = fu.run(self.fast_cdp, self.jev, self.url,
                     "finish the payment and place the order",
                     expect_text="Order confirmed")
        self.assertEqual(rep["result"], "pass", rep["errors"])
        self.assertEqual(rep["verification"]["method"], "assert")
        steps = {s["step"] for s in rep["steps"]}
        self.assertEqual(steps, {"extract_candidates", "choose_target", "execute_action"})

    def test_13_visual_gate_reads_the_screen_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            shot = Path(tmp) / "order.png"
            rep = fu.run(self.fast_cdp, self.jev, self.url,
                         "finish the payment and place the order",
                         assert_image="Does the page confirm that the order was placed successfully?",
                         screenshot=shot)
            self.assertEqual(rep["result"], "pass", rep["errors"])
            self.assertEqual(rep["verification"]["method"], "visual_gate")
            self.assertIn("visual_gate", {s["step"] for s in rep["steps"]})
            self.assertTrue(shot.is_file(), "the gate needs a screenshot")

    def test_14_ledger_serializes_every_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger"
            rep = fu.run(self.fast_cdp, self.jev, self.url,
                         "finish the payment and place the order",
                         expect_text="Order confirmed")
            fu.write_ledger(ledger, rep)
            for name in ("step_01_candidates.json", "step_02_decision.json",
                         "step_03_action.json", "step_04_verification.json"):
                self.assertTrue((ledger / name).is_file(), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
