#!/usr/bin/env python3
import concurrent.futures
import json
import shutil
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts"))
from harness_core import (
    ProjectsHarness,
    EnvelopeHook,
    MemoryWriter,
    RouteChecker,
    ClashChecker,
    QueueLimiter,
    RuleClashError,
    ProjectsHarnessError,
)


class TestProjectsHarness(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="test_projects_")
        self.tmp_workspace = Path(self.td)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_01_handoff_envelope(self):
        cases = [
            ("Implement OAuth flow", "Please add Google OAuth to login button"),
            ("Run database migrations", "Create migration script for users table"),
            ("Fix responsive styling", "The navbar breaks on mobile screens"),
        ]
        for brief, msg in cases:
            env = EnvelopeHook.wrap(brief, msg)
            self.assertEqual(env["coordinator_label"], "AI-GENERATED")
            self.assertEqual(env["owner_label"], "FROM OWNER (VERBATIM)")
            self.assertIn(brief, env["formatted"])
            self.assertIn(msg, env["formatted"])

        with self.assertRaises(ProjectsHarnessError):
            EnvelopeHook.wrap("", "valid msg")
        with self.assertRaises(ProjectsHarnessError):
            EnvelopeHook.wrap("valid brief", "")
        print("  ✓ handoff · 3/3")

    def test_02_report_forced_by_hook(self):
        q = QueueLimiter(self.tmp_workspace)
        q.enqueue("task_01")
        with self.assertRaises(ProjectsHarnessError):
            q.complete("task_01", report=None)

        rep = {"summary": "Completed successfully", "exit_code": 0}
        promoted = q.complete("task_01", report=rep)
        self.assertIsNone(promoted)
        status = q.status()
        self.assertEqual(len(status["done"]), 1)
        self.assertEqual(status["done"][0]["report"], rep)
        print("  ✓ report · forced by a hook")

    def test_03_memory_one_line_history_kept(self):
        mem = MemoryWriter(self.tmp_workspace)
        mem.update("Launch date", "Oct 14")
        mem.update("Launch date", "Oct 21")
        line = mem.update("Launch date", "Oct 28")

        self.assertEqual(line, "Launch date: Oct 28 <- Oct 21 <- Oct 14")
        lines, _ = mem.load()
        self.assertEqual(len(lines), 1)
        facts = mem.read_facts()
        self.assertEqual(facts["Launch date"], "Oct 28")
        print("  ✓ memory · one line, history kept")

    def test_04_parallel_saves(self):
        mem = MemoryWriter(self.tmp_workspace)
        total_workers = 20

        def worker_save(idx: int):
            return mem.update(f"item_{idx:02d}", f"val_{idx}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_save, i) for i in range(total_workers)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        self.assertEqual(len(results), total_workers)
        lines, _ = mem.load(cap=100)
        self.assertEqual(len(lines), total_workers)
        print("  ✓ parallel saves · 20/20")

    def test_05_memory_cap_200_of_210_lines(self):
        mem = MemoryWriter(self.tmp_workspace)
        for i in range(210):
            mem.update(f"fact_{i:03d}", f"value_{i}")

        loaded_lines, was_capped = mem.load(cap=200)
        self.assertEqual(len(loaded_lines), 200)
        self.assertTrue(was_capped)
        print("  ✓ cap · 200 of 210 lines")

    def test_06_clash_raised_and_asked(self):
        instructions = {
            "file_naming": "snake_case",
            "api_format": "json",
        }
        err = ClashChecker.check(instructions, "file_naming", "snake_case")
        self.assertIsNone(err)

        err = ClashChecker.check(instructions, "file_naming", "camelCase")
        self.assertIsNotNone(err)
        self.assertIsInstance(err, RuleClashError)
        self.assertEqual(err.instruction_rule, "snake_case")
        self.assertEqual(err.proposed_value, "camelCase")
        print("  ✓ clash · raised and asked")

    def test_07_queue_max_2_concurrency_and_promotions(self):
        q = QueueLimiter(self.tmp_workspace, max_concurrency=2)
        total_tasks = 9

        statuses = [q.enqueue(f"task_{i:02d}") for i in range(total_tasks)]
        self.assertEqual(statuses[:2], ["working", "working"])
        self.assertEqual(statuses[2:], ["queued"] * 7)

        stat = q.status()
        self.assertEqual(len(stat["working"]), 2)
        self.assertEqual(len(stat["queued"]), 7)

        completed = 0
        while stat["working"]:
            current_id = stat["working"][0]["task_id"]
            q.complete(current_id, report={"status": "done"})
            completed += 1
            stat = q.status()

        self.assertEqual(completed, total_tasks)
        self.assertEqual(len(stat["done"]), total_tasks)
        self.assertEqual(len(stat["working"]), 0)
        self.assertEqual(len(stat["queued"]), 0)
        print("  ✓ queue · max 2, 9/9 queued starts")


if __name__ == "__main__":
    print("\n🧪 Running Kem's Claude Projects CLI 7-Stage Verification Suite:")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestProjectsHarness)
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
