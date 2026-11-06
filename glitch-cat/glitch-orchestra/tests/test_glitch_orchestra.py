#!/usr/bin/env python3
import concurrent.futures
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))
from orchestra_conductor import OrchestraConductor


class TestGlitchOrchestra(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="test_orchestra_")
        self.conductor = OrchestraConductor(Path(self.td))
        self.cli = Path(__file__).resolve().parent.parent / "glitch_orchestra.py"

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def approve_plan(self):
        return self.conductor.draft_plan(
            audience="independent developers",
            great="clear, reliable behavior",
            made="small deterministic changes",
            moves="fit existing CLI conventions",
            feel="calm and understandable",
            references=["sample.png", "existing-cli"],
            readiness_cue="Human can explain the intended result",
        )

    def register_worker(self, session_id="worker_01"):
        return self.conductor.register_child_session(
            session_id,
            "Refactor models",
            "implementation specialist",
            "Only model registry code and its tests",
            "tty_01",
        )

    def test_plan_validation_and_human_dispatch_gate(self):
        with self.assertRaisesRegex(ValueError, "human approves"):
            self.register_worker()
        with self.assertRaisesRegex(ValueError, "references"):
            self.conductor.draft_plan("audience", "great", "made", "moves", "feel")

        plan = self.approve_plan()
        self.assertEqual(plan["audience"], "independent developers")
        self.assertEqual(plan["readiness_cue"], "Human can explain the intended result")
        self.assertEqual(self.conductor.status()["plan"]["references"], ["sample.png", "existing-cli"])
        with self.assertRaisesRegex(ValueError, "human approves"):
            self.register_worker()

        approval = self.conductor.approve_plan("project owner")
        self.assertEqual(approval["approver"], "project owner")
        worker = self.register_worker()
        self.assertEqual(worker["status"], "running")
        self.assertEqual(worker["role"], "implementation specialist")
        self.assertEqual(worker["scope"], "Only model registry code and its tests")
        self.assertTrue(self.conductor.status()["dispatch_approved"])

        with self.assertRaisesRegex(ValueError, "already approved"):
            self.conductor.approve_plan("another person")
        with self.assertRaisesRegex(ValueError, "cannot be changed"):
            self.approve_plan()

    def test_reference_reason_and_specialist_fields_are_validated(self):
        with self.assertRaisesRegex(ValueError, "but not both"):
            self.conductor.draft_plan(
                "audience", "great", "made", "moves", "feel",
                references=["reference"], references_unnecessary="because",
            )
        plan = self.conductor.draft_plan(
            "audience", "great", "made", "moves", "feel", references_unnecessary="No useful reference exists"
        )
        self.assertEqual(plan["references"], [])
        self.assertEqual(plan["references_unnecessary"], "No useful reference exists")
        self.conductor.approve_plan("owner")
        with self.assertRaisesRegex(ValueError, "role"):
            self.conductor.register_child_session("w", "task", " ", "scope")

    def test_worker_signals_and_qualitative_comparisons_persist_in_status(self):
        self.approve_plan()
        self.conductor.approve_plan("project owner")
        self.register_worker()
        signal = self.conductor.record_worker_signal("worker_01", "Ready for review", "ready")
        comparison = self.conductor.record_worker_comparison(
            "worker_01",
            "Write a short welcome message",
            "Before result",
            "After result",
            "After is warmer and clearer without losing the key details",
        )

        persisted = OrchestraConductor(Path(self.td)).status()
        self.assertEqual(persisted["active_sessions"][0]["worker_status"], "ready")
        self.assertEqual(signal["to"], "conductor")
        self.assertEqual(comparison["prompt"], "Write a short welcome message")
        self.assertEqual(comparison["before"], "Before result")
        self.assertEqual(comparison["after"], "After result")
        self.assertEqual(comparison["assessment"], "After is warmer and clearer without losing the key details")
        self.assertEqual([event["sequence"] for event in persisted["events"]], list(range(1, 6)))
        self.assertEqual(persisted["events"][-2]["type"], "worker_signal")
        self.assertEqual(persisted["events"][-1]["type"], "worker_comparison")

        with self.assertRaisesRegex(ValueError, "not found in active"):
            self.conductor.record_worker_signal("missing", "hello")
        with self.assertRaisesRegex(ValueError, "needs --message"):
            self.conductor.record_worker_signal("worker_01")

    def test_concurrent_cli_signals_are_retained_with_increasing_sequences(self):
        self.approve_plan()
        self.conductor.approve_plan("project owner")
        self.register_worker()
        messages = [f"parallel signal {index}" for index in range(24)]
        commands = [
            [
                sys.executable,
                str(self.cli),
                "--dir",
                self.td,
                "signal",
                "--id",
                "worker_01",
                "--message",
                message,
            ]
            for message in messages
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(commands)) as processes:
            results = list(
                processes.map(
                    lambda command: subprocess.run(command, capture_output=True, text=True, check=False, timeout=30),
                    commands,
                )
            )

        self.assertTrue(all(result.returncode == 0 for result in results), [result.stderr for result in results])
        events = OrchestraConductor(Path(self.td)).status()["events"]
        sequences = [event["sequence"] for event in events]
        self.assertEqual(sequences, list(range(1, len(events) + 1)))
        recorded_messages = [event["message"] for event in events if event["type"] == "worker_signal"]
        self.assertCountEqual(recorded_messages, messages)

    def test_02_completion_alert(self):
        res = self.conductor.trigger_completion_alert("Run complete")
        self.assertEqual(res["alert_message"], "Run complete")
        self.assertTrue(res["bell_emitted"])
        print("  ✓ completion alert · bell emitted")

    def test_evidence_gate_and_lifecycle_regressions(self):
        self.approve_plan()
        self.conductor.approve_plan("project owner")
        self.register_worker("verified_worker")
        self.register_worker("unverified_worker")
        missing = Path(self.td) / "missing.json"
        with self.assertRaises(FileNotFoundError):
            self.conductor.mark_session_complete("verified_worker", "Claim", evidence=str(missing))
        self.assertEqual(self.conductor.status()["active_count"], 2)

        evidence = Path(self.td) / "verify.json"
        evidence.write_text('{"verdict": "pass"}', encoding="utf-8")
        c = self.conductor.mark_session_complete("verified_worker", "Checkout shipped", evidence=str(evidence))
        self.assertEqual(c["status"], "completed")
        self.assertTrue(c["verified"])
        self.assertEqual(c["evidence"], str(evidence.resolve()))
        self.assertEqual(self.conductor.status()["verified_count"], 1)

        u = self.conductor.mark_session_complete("unverified_worker", "Trust me")
        self.assertFalse(u["verified"])
        status = self.conductor.status()
        self.assertEqual(status["active_count"], 0)
        self.assertEqual(status["completed_count"], 2)
        self.assertEqual(status["verified_count"], 1)
        self.assertEqual(status["events"][-1]["type"], "worker_completed")
        readable_status = subprocess.run(
            [sys.executable, str(self.cli), "--dir", self.td, "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertIn(str(evidence), readable_status.stdout)
        self.assertIn("UNVERIFIED", readable_status.stdout)
        print("  ✓ evidence gate · missing artifact refused, unverified completion labelled")

    def test_cli_requires_approval_and_exposes_status_events(self):
        def run(*arguments):
            return subprocess.run(
                [sys.executable, str(self.cli), "--dir", self.td, *arguments],
                capture_output=True,
                text=True,
                check=False,
            )

        plan_args = [
            "plan",
            "--audience", "new users",
            "--great", "useful output",
            "--made", "with small steps",
            "--moves", "across a workflow",
            "--feel", "clear",
            "--reference", "example.png",
            "--readiness-cue", "Owner says the draft matches intent",
        ]
        self.assertNotEqual(run("plan").returncode, 0)
        self.assertEqual(run(*plan_args).returncode, 0)
        self.assertNotEqual(
            run("register", "--id", "worker", "--task", "test", "--role", "tester", "--scope", "tests").returncode,
            0,
        )
        self.assertEqual(run("approve", "--by", "owner").returncode, 0)
        self.assertEqual(
            run("register", "--id", "worker", "--task", "test", "--role", "tester", "--scope", "tests").returncode,
            0,
        )
        human_status = run("status")
        self.assertIn("tester", human_status.stdout)
        self.assertIn("running", human_status.stdout)
        self.assertEqual(run("signal", "--id", "worker", "--status", "ready", "--message", "Baseline captured").returncode, 0)
        self.assertEqual(
            run(
                "compare", "--id", "worker", "--prompt", "same prompt",
                "--before", "before output", "--after", "after output",
                "--assessment", "The after output is more helpful",
            ).returncode,
            0,
        )
        status = run("status", "--json")
        self.assertEqual(status.returncode, 0, status.stderr)
        state = json.loads(status.stdout)
        self.assertTrue(state["dispatch_approved"])
        self.assertEqual(state["plan"]["readiness_cue"], "Owner says the draft matches intent")
        self.assertEqual(state["active_sessions"][0]["role"], "tester")
        self.assertEqual(state["events"][-2]["worker_status"], "ready")
        self.assertEqual(state["events"][-1]["assessment"], "The after output is more helpful")


if __name__ == "__main__":
    print("\n🧪 Running Glitch Orchestra Test Suite:")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestGlitchOrchestra)
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
