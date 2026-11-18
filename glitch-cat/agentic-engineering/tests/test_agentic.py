#!/usr/bin/env python3
"""
test_agentic.py — Grounded test suite for agentic-engineering
Tests Kem's 7-step loop in isolated temporary directories, including the parts
that must be able to fail: deterministic gates, the fresh-context judge, and
the rule that a card is not done until a human moves it.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
AGENTIC_PY = SKILL_DIR / "agentic.py"


def run_agentic(*args, cwd=None):
    return subprocess.run([sys.executable, str(AGENTIC_PY), *args], capture_output=True, text=True, cwd=cwd)


def card_path(target: Path, column: str, card_id: str) -> Path | None:
    matches = list((target / ".kanban" / column).glob(f"{card_id}*.md"))
    return matches[0] if matches else None


def write_judge(tmpdir: Path, name: str, output: str) -> str:
    script = Path(tmpdir) / name
    script.write_text(f"#!/bin/sh\ncat > /dev/null\nprintf '%s\\n' \"{output}\"\n", encoding="utf-8")
    script.chmod(0o755)
    return f"sh {script}"


def test_agentic_pipeline_end_to_end():
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "my_project"
        target.mkdir()

        res_init = run_agentic("init", str(target))
        assert res_init.returncode == 0, f"Init failed: {res_init.stderr}"
        assert (target / ".kanban" / "01_new" / "CARD-001_example.md").is_file(), "CARD-001_example.md missing"

        res_list = run_agentic("kanban", "list", str(target))
        assert res_list.returncode == 0, f"List failed: {res_list.stderr}"
        assert "CARD-001" in res_list.stdout

        res_add = run_agentic("kanban", "add", "Build Navigation Bar", "--target", str(target))
        assert res_add.returncode == 0, f"Add failed: {res_add.stderr}"
        assert list((target / ".kanban" / "01_new").glob("CARD-002*.md")), "CARD-002 was not created"

        res_listen = run_agentic("listen", str(target), "--once")
        assert res_listen.returncode == 0, f"Listen failed: {res_listen.stderr}"
        assert (target / ".kanban" / "02_picked_up" / "CARD-001_example.md").is_file(), "CARD-001 not picked up"

        res_split = run_agentic("split", "Billing Dashboard", "--json")
        assert res_split.returncode == 0, f"Split failed: {res_split.stderr}"
        plan = json.loads(res_split.stdout)
        assert plan["total_lanes"] == 3
        assert plan["lanes"][0]["sandbox"].startswith("lane-1"), plan["lanes"][0]
        assert plan["lanes"][0]["model"], plan["lanes"][0]

        res_run = run_agentic(
            "run", "CARD-001", str(target),
            "--test", "true",
            "--evidence", ".kanban/evidence/CARD-001.json",
            "--mock-judge", "PASS",
        )
        assert res_run.returncode == 1, f"Missing evidence must fail the gate:\n{res_run.stdout}{res_run.stderr}"
        assert card_path(target, "02_picked_up", "CARD-001"), "Failed gate must return the card to picked_up"

        evidence = target / ".kanban" / "evidence" / "CARD-001.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text('{"verdict": "pass"}', encoding="utf-8")

        res_run = run_agentic(
            "run", "CARD-001", str(target),
            "--test", "true",
            "--evidence", ".kanban/evidence/CARD-001.json",
            "--mock-judge", "PASS",
        )
        assert res_run.returncode == 0, f"Gated run failed:\n{res_run.stdout}{res_run.stderr}"
        assert "Kem's 7-Step Loop" in res_run.stdout
        assert "03_review" in res_run.stdout or "03_review" in res_run.stderr
        assert card_path(target, "03_review", "CARD-001"), "Approved work must stop in review for the human"
        assert not card_path(target, "04_done", "CARD-001"), "The pipeline must not declare the card done"

        res_done = run_agentic("kanban", "move", "CARD-001", "done", "--target", str(target))
        assert res_done.returncode == 0, f"Human move failed: {res_done.stderr}"
        assert card_path(target, "04_done", "CARD-001"), "The human move to done did not land"

        res_reject = run_agentic(
            "run", "CARD-002", str(target),
            "--test", "true",
            "--mock-judge", "FAIL",
        )
        assert res_reject.returncode == 1, "Expected rejection to halt with code 1"
        assert "Kem's Pink Arrow triggered" in res_reject.stdout

        res_ungated = run_agentic("kanban", "add", "Ungated Change", "--target", str(target))
        assert res_ungated.returncode == 0, f"Add failed: {res_ungated.stderr}"
        res_refuse = run_agentic("run", "CARD-003", str(target), "--mock-judge", "PASS")
        assert res_refuse.returncode == 2, "A run with no gate must refuse with usage exit 2"
        assert "Nothing could fail" in res_refuse.stdout

        rejecting_judge = write_judge(
            Path(tmpdir),
            "rejecting_judge.sh",
            "VERDICT: REJECTED\\nSCORE: 30\\nDELTA: missing integration test\\nFEEDBACK: diff has no test",
        )
        res_real = run_agentic(
            "run", "CARD-002", str(target),
            "--test", "true",
            "--judge-cmd", rejecting_judge,
        )
        assert res_real.returncode == 1, f"Fresh judge rejection must halt:\n{res_real.stdout}{res_real.stderr}"
        recorded = card_path(target, "02_picked_up", "CARD-002").read_text(encoding="utf-8")
        assert "missing integration test" in recorded, "The rejection delta was not written to the card"

        broken_judge = write_judge(Path(tmpdir), "broken_judge.sh", "Looks fine to me, ship it.")
        res_broken = run_agentic(
            "run", "CARD-002", str(target),
            "--test", "true",
            "--judge-cmd", broken_judge,
        )
        assert res_broken.returncode == 1, "An unparseable verdict must fail closed"
        assert "fail closed" in res_broken.stdout.lower() or "fail closed" in res_broken.stderr.lower(), res_broken.stdout + res_broken.stderr

        print("\n🎉 Deterministic gates, fresh-context judge, and human delivery verified.")


if __name__ == "__main__":
    test_agentic_pipeline_end_to_end()
