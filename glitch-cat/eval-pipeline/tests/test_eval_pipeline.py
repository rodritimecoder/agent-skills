#!/usr/bin/env python3
import json
import shutil
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


if __name__ == "__main__":
    print("\n🧪 Running Eval Pipeline Test Suite:")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestEvalPipeline)
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
