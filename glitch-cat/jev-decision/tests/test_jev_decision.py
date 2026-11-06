#!/usr/bin/env python3
"""Tests for the JEV decision primitives and CLI.

The engine tests answer against the live decision server; the CLI tests pin the
contract other skills rely on (`--json` before the subcommand, `--context-file`,
`--require-server`, the batch schema).
"""
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CLI = SKILL_DIR / "jev_decision.py"

sys.path.append(str(SKILL_DIR / "scripts"))
from jev_engine import JevEngine  # noqa: E402


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestJevDecision(unittest.TestCase):
    def setUp(self):
        self.engine = JevEngine()

    def test_01_bool_primitive(self):
        ctx = "Architecture note: Postgres 14 was deprecated and replaced with SQLite 3."
        q = "Does SQLite supersede Postgres?"
        res = self.engine.decide_bool(ctx, q)
        self.assertIn("decision", res)
        self.assertIn("confidence", res)
        self.assertTrue(res["source"], "every answer names where it came from")
        print("  ✓ bool · verified")

    def test_02_choice_primitive(self):
        ctx = "The user specified that integration tests must run in parallel across CPU cores."
        q = "Which execution mode should be chosen?"
        options = ["sequential_lane", "parallel_worker_lane", "skip_tests"]
        res = self.engine.decide_choice(ctx, q, options)
        self.assertIn(res["selection"], options)
        self.assertGreater(res["confidence"], 0.1)
        print("  ✓ choice · verified")

    def test_03_score_primitive(self):
        ctx = "Complete unit test coverage for authentication module with 0 failing assertions."
        criteria = "unit test coverage and zero failure assertions"
        res = self.engine.decide_score(ctx, criteria)
        self.assertGreater(res["score"], 0.0)
        self.assertLessEqual(res["score"], 1.0)
        print("  ✓ score · verified")

    def test_04_composite_primitive(self):
        ctx = "Pull request contains 40 new passing tests, clean formatting, and valid documentation."
        q = "Is this pull request safe and high quality?"
        options = ["merge_now", "request_changes", "block"]
        res = self.engine.decide_composite(ctx, q, options)
        self.assertIn("gate", res)
        self.assertIn("action", res)
        self.assertIn("quality_score", res)
        self.assertIn(res["action"], options)
        print(f"  ✓ composite (gate={res['gate']}, action='{res['action']}', score={res['quality_score']}) · verified")

    def test_05_context_cleaning_pairwise(self):
        claims = [
            {"timestamp": "2026-01-01", "text": "Deploy target is AWS ECS cluster."},
            {"timestamp": "2026-06-01", "text": "AWS ECS cluster is obsolete, migrated to local Podman."},
        ]
        res = self.engine.clean_context_claims(claims)
        self.assertEqual(res["total_input_claims"], 2)
        self.assertGreaterEqual(res["active_claims_retained"], 1)
        print("  ✓ context clean · verified")

    def test_06_batch_is_one_request(self):
        """Three typed answers, one round trip."""
        if not self.engine.is_online():
            print("  ⚠️ decision server offline, skipping batch")
            return
        res = self.engine.decide_batch(
            "Order review page with buttons: Back to catalog, Complete purchase.",
            {
                "ship": {"type": "bool", "instructions": "Is the cart non-empty?"},
                "target": {"type": "choice", "instructions": "Which button finishes the purchase?",
                           "options": ["Back to catalog", "Complete purchase"]},
                "risk": {"type": "score", "instructions": "How risky is this purchase?",
                         "levels": ["none", "low", "medium", "high"]},
            },
        )
        self.assertEqual(set(res), {"ship", "target", "risk"})
        self.assertEqual(res["ship"]["primitive"], "bool")
        self.assertEqual(res["target"]["selection"], "Complete purchase")
        self.assertEqual(res["risk"]["primitive"], "score")
        self.assertIn("risk", res)
        self.assertEqual(set(res["risk"]["probabilities"]), {"none", "low", "medium", "high"})
        print(f"  ✓ batch (target='{res['target']['selection']}', risk={res['risk']['score']}) · verified")

    def test_07_named_score_levels_map_to_a_scalar(self):
        """`levels: [none, low, medium, high]` must not collapse to 0.0."""
        if not self.engine.is_online():
            print("  ⚠️ decision server offline, skipping named levels")
            return
        res = self.engine.decide_batch("The change is a one-line docstring fix.", {
            "risk": {"type": "score", "instructions": "How risky is this change?",
                     "levels": ["none", "low", "medium", "high"]},
        })
        risk = res["risk"]
        self.assertGreater(risk["score"], 0.0)
        self.assertLess(risk["score"], 0.6)
        self.assertEqual(set(risk["probabilities"]), {"none", "low", "medium", "high"})
        print(f"  ✓ named levels -> {risk['score']} · verified")

    def test_08_vision_decision(self):
        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        ctx = "Visual screen inspection of an empty canvas."
        q = "Is visual canvas element present?"
        res = self.engine.decide_bool(ctx, q, image=png_b64)
        self.assertIn("decision", res)
        self.assertIn("confidence", res)
        print(f"  ✓ vision decision ({res['source']}) · verified")

    def test_18_backend_accepts_any_decision_server_unless_pinned(self):
        class Response:
            def __init__(self, model_id):
                self.body = json.dumps({"data": [{"id": model_id}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return self.body

        engine = JevEngine()
        with patch("jev_engine.urllib.request.urlopen", return_value=Response("/models/h2o-lightning-4b-Q4_K_M.gguf")):
            self.assertEqual(engine.backend(), "systemone")
        with patch("jev_engine.urllib.request.urlopen", return_value=Response("/models/vllm-d3-nano-Q4_K_M.gguf")):
            self.assertEqual(engine.backend(), "systemone")
        with patch.dict("os.environ", {"JEV_REQUIRE_H2O": "1"}), \
             patch("jev_engine.urllib.request.urlopen", return_value=Response("/models/vllm-d3-nano-Q4_K_M.gguf")):
            self.assertEqual(JevEngine().backend(), "none")

    def test_19_h2o_native_payload_and_answer(self):
        engine = JevEngine()
        engine.model_name = "h2o-lightning-4b"
        request_payload = {}

        def post(payload):
            request_payload.update(payload)
            return {"answer": {"type": "noul", "noul": 0.93}}

        with patch.object(engine, "backend", return_value="systemone"), \
             patch.object(engine, "is_online", return_value=True), \
             patch.object(engine, "_post", side_effect=post):
            result = engine._call_systemone(
                "browser state", "Is the confirmation visible?", None, "noul"
            )

        self.assertEqual(request_payload["state"], {"context": "browser state"})
        self.assertEqual(request_payload["questions"]["answer"], {
            "type": "noul", "instructions": "Is the confirmation visible?"
        })
        self.assertTrue(result["decision"])
        self.assertEqual(result["probabilities"]["true"], 0.93)
        self.assertEqual(result["source"], "h2o-lightning-4b")

    def test_20_post_refuses_unverified_model(self):
        engine = JevEngine()
        with patch.object(engine, "backend", return_value="none"), \
             patch.object(engine, "is_online") as online:
            self.assertIsNone(engine._post({"questions": {}}))
            online.assert_not_called()


class TestCliContract(unittest.TestCase):
    """What other skills call, pinned."""

    def test_10_json_before_subcommand(self):
        """academic-icm invokes `jev_decision.py --json bool --context …`."""
        proc = subprocess.run(
            [sys.executable, str(CLI), "--json", "bool",
             "--context", "The deployment was cancelled and replaced by v2.",
             "--question", "Is the v1 config superseded?"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        res = json.loads(proc.stdout)
        self.assertEqual(res["primitive"], "bool")
        self.assertIn("decision", res)

    def test_11_context_file_keeps_facts_on_disk(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("The deployment was cancelled and replaced by v2.")
            path = fh.name
        try:
            proc = subprocess.run(
                [sys.executable, str(CLI), "bool", "--context-file", path,
                 "--question", "Is the v1 config superseded?", "--json"],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["primitive"], "bool")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_12_require_server_fails_instead_of_heuristics(self):
        """An unreachable server is an error, not a silent keyword guess."""
        proc = subprocess.run(
            [sys.executable, str(CLI), "bool", "--context", "anything at all",
             "--question", "Is this decided?", "--port", str(_closed_port()),
             "--require-server"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertIn("did not answer", proc.stderr)

    def test_13_heuristic_fallback_warns_but_answers(self):
        proc = subprocess.run(
            [sys.executable, str(CLI), "bool", "--context", "anything at all",
             "--question", "Is this decided?", "--port", str(_closed_port())],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("heuristic", proc.stderr)

    def test_14_batch_rejects_an_unusable_question(self):
        """A choice with no options must fail with guidance, before any request."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"state": "x", "questions": {"pick": {"type": "choice",
                                                           "instructions": "Which?"}}}, fh)
            path = fh.name
        try:
            proc = subprocess.run([sys.executable, str(CLI), "batch", path],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("non-empty 'options'", proc.stderr)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_15_out_writes_json_and_prints_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "res.json"
            proc = subprocess.run(
                [sys.executable, str(CLI), "bool", "--context", "The build passed all tests.",
                 "--question", "Did the build succeed?", "--out", str(out)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(len(proc.stdout.strip().splitlines()), 1, proc.stdout)
            self.assertIn(str(out), proc.stdout)
            self.assertEqual(json.loads(out.read_text())["primitive"], "bool")


    def test_16_comma_separated_options_are_split(self):
        """`--options a,b,c` means three options, not one option with commas."""
        proc = subprocess.run(
            [sys.executable, str(CLI), "--json", "choice",
             "--context", "The certificate expired at 03:00 and payments stopped.",
             "--question", "Which team owns this?",
             "--options", "infra,payments,docs"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        res = json.loads(proc.stdout)
        self.assertIn(res["selection"], ["infra", "payments", "docs"])
        self.assertEqual(sorted(res["probabilities"]), ["docs", "infra", "payments"])

    def test_17_source_names_the_served_model(self):
        engine = JevEngine()
        if not engine.is_online():
            self.skipTest("no decision server online")
        res = engine.decide_bool("The build passed every test.", "Did the build succeed?")
        self.assertNotEqual(res["source"], "heuristic_fallback")
        if engine.model_name:
            self.assertEqual(res["source"], engine.model_name)


if __name__ == "__main__":
    print("\n🧪 Running the decision test suite:")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestJevDecision)
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestCliContract))
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
