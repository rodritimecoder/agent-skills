#!/usr/bin/env python3
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))
from pipeline_core import EvalPipeline, PropagationRiskError


class TestEvalPipeline(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="test_pipeline_")
        self.ledger = Path(self.td) / "ledger"
        self.pipe = EvalPipeline(self.ledger)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_01_all_steps_pass(self):
        self.pipe.register_step("ingest", "D", lambda x: x + 1, lambda out: (out > 0, "must be positive"))
        self.pipe.register_step("model_call", "P", lambda x: x * 2, lambda out: (out % 2 == 0, "must be even"))
        self.pipe.register_step("format", "D", lambda x: f"result_{x}", lambda out: (out.startswith("result_"), "must start with prefix"))

        res = self.pipe.run(5)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["final_output"], "result_12")
        self.assertEqual(len(list(self.ledger.glob("step_*.json"))), 3)
        print("  ✓ pipeline flow · verified")

    def test_02_propagation_risk_halt(self):
        self.pipe.register_step("step1", "D", lambda x: {"items": []}, lambda out: (len(out["items"]) > 0, "items list empty"))
        self.pipe.register_step("step2_should_not_run", "P", lambda x: x, None)

        with self.assertRaises(PropagationRiskError) as cm:
            self.pipe.run({})

        err = cm.exception
        self.assertEqual(err.step_idx, 1)
        self.assertEqual(err.step_type, "D")
        self.assertIn("items list empty", err.failure_reason)

        # Ensure step 2 never created an artifact
        self.assertTrue((self.ledger / "step_01_step1.json").exists())
        self.assertFalse((self.ledger / "step_02_step2_should_not_run.json").exists())
        print("  ✓ propagation risk halt · verified")


class TestAuditGate(unittest.TestCase):
    """`audit` is a gate: it must be able to fail."""

    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="test_audit_")
        self.cli = Path(__file__).resolve().parent.parent / "eval_pipeline.py"

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _write(self, ledger, filename, payload):
        ledger.mkdir(parents=True, exist_ok=True)
        (ledger / filename).write_text(json.dumps(payload), encoding="utf-8")

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(self.cli), "audit", *args],
            capture_output=True, text=True, cwd=self.td,
        )

    def test_ok_and_skipped_exit_zero(self):
        ledger = Path(self.td) / "ledger"
        self._write(ledger, "step_01_ingest.json", {"stage": 1, "stage_name": "ingest", "step_type": "D", "status": "ok"})
        self._write(ledger, "step_05_verify.json", {"stage": 5, "stage_name": "verify", "step_type": "P", "status": "skipped"})
        proc = self._run("--ledger-dir", str(ledger))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ingest", proc.stdout)
        self.assertIn("SKIPPED", proc.stdout)
        print("  ✓ audit passes ok/skipped · verified")

    def test_failed_step_exits_non_zero(self):
        ledger = Path(self.td) / "ledger"
        self._write(ledger, "step_01_ingest.json", {"stage": 1, "stage_name": "ingest", "step_type": "D", "status": "ok"})
        self._write(ledger, "step_02_sift.json", {
            "stage": 2, "stage_name": "sift", "step_type": "P", "status": "failed",
            "errors": ["classifier confidence below floor"],
        })
        proc = self._run("--ledger-dir", str(ledger))
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("sift", proc.stdout)
        self.assertIn("FAILED", proc.stdout)
        self.assertIn("classifier confidence below floor", proc.stdout)
        print("  ✓ audit fails on failed step · verified")

    def test_missing_status_and_empty_ledger_fail(self):
        ledger = Path(self.td) / "ledger"
        self._write(ledger, "step_04_render.json", {"stage_name": "render", "step_type": "D"})
        self.assertNotEqual(self._run("--ledger-dir", str(ledger)).returncode, 0)

        empty = Path(self.td) / "empty"
        empty.mkdir()
        self.assertNotEqual(self._run("--ledger-dir", str(empty)).returncode, 0)
        print("  ✓ audit refuses unverifiable evidence · verified")

    def test_json_output_is_machine_readable(self):
        ledger = Path(self.td) / "ledger"
        self._write(ledger, "step_02_sift.json", {"stage": 2, "stage_name": "sift", "step_type": "P", "status": "failed"})
        proc = self._run("--ledger-dir", str(ledger), "--json")
        self.assertNotEqual(proc.returncode, 0)
        report = json.loads(proc.stdout)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failed_steps"], 1)
        self.assertEqual(report["steps"][0]["name"], "sift")
        print("  ✓ audit --json · verified")


if __name__ == "__main__":
    print("\n🧪 Running Eval Pipeline Test Suite:")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestEvalPipeline)
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAuditGate))
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
