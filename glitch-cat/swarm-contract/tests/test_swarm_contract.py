#!/usr/bin/env python3
import json
import shutil
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))
from swarm_engine import SwarmContract, SwarmBudgetExceededError, ScorecardValidationError


class TestSwarmContract(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="test_swarm_")
        self.swarm = SwarmContract(Path(self.td))

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_01_init_and_scorecard_valid(self):
        m = self.swarm.init_swarm("Audit 10 microservices", max_budget_usd=1.00, max_tokens=100000)
        self.assertEqual(m["status"], "active")

        scorecard = {
            "worker_id": "worker_auth_01",
            "target": "auth-service",
            "status": "pass",
            "findings": "Zero vulnerabilities detected in token parsing",
        }
        entry = self.swarm.record_scorecard(scorecard, tokens_used=5000, cost_usd=0.05)
        self.assertEqual(entry["tokens_used"], 5000)
        summ = self.swarm.summary()
        self.assertEqual(summ["budget"]["spent_usd"], 0.05)
        self.assertEqual(summ["total_scorecards"], 1)
        print("  ✓ valid scorecard · verified")

    def test_02_scorecard_schema_validation_error(self):
        self.swarm.init_swarm("Test schema enforcement")
        # Missing required 'findings' field
        broken_scorecard = {
            "worker_id": "worker_02",
            "target": "db-service",
            "status": "fail",
        }
        with self.assertRaises(ScorecardValidationError):
            self.swarm.record_scorecard(broken_scorecard)
        print("  ✓ schema validation error · verified")

    def test_03_hard_budget_enforcement(self):
        self.swarm.init_swarm("Capped spend test", max_budget_usd=0.10, max_tokens=10000)
        sc1 = {"worker_id": "w1", "target": "t1", "status": "pass", "findings": "ok"}
        self.swarm.record_scorecard(sc1, tokens_used=4000, cost_usd=0.04)

        # Pre-flight check before spawn
        self.assertTrue(self.swarm.check_budget_availability(estimated_tokens=5000, estimated_usd=0.05))
        self.assertFalse(self.swarm.check_budget_availability(estimated_tokens=10000, estimated_usd=0.10))

        # Exceeding budget triggers hard halt
        sc2 = {"worker_id": "w2", "target": "t2", "status": "pass", "findings": "ok"}
        with self.assertRaises(SwarmBudgetExceededError):
            self.swarm.record_scorecard(sc2, tokens_used=8000, cost_usd=0.08)

        summ = self.swarm.summary()
        self.assertEqual(summ["status"], "budget_exhausted")
        print("  ✓ hard budget ceiling · verified")


if __name__ == "__main__":
    print("\n🧪 Running Swarm Contract Test Suite:")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSwarmContract)
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
