#!/usr/bin/env python3
"""End-to-end dispatcher tests for academic-pipeline-v2 (stdlib only).

Builds a throwaway workspace in a tempdir, then drives stages 3-5 through
``scripts/run_pipeline.py`` and checks the merged step evidence.  No network,
no services, no external tools.
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
RUNNER = SCRIPTS / "run_pipeline.py"
VALID_STATUSES = {"ok", "failed", "skipped"}
VALID_STEP_TYPES = {"D", "P", "H"}
STAGE_STEP_TYPES = {1: "P", 2: "P", 3: "D", 4: "D", 5: "P"}

sys.path.insert(0, str(SCRIPTS))
import gates  # noqa: E402  - stage 5 gate module under test

META = {
    "course": "MATH101",
    "weeks": [
        {
            "week": "Week_01",
            "topic": "Limits",
            "tutorial": "Limits solutions",
            "nodes": [
                {"id": "n1", "label": "Limits", "kind": "page"},
                {"id": "n2", "label": "Limits solutions", "kind": "assignment"},
            ],
        },
        {
            "week": "Week_02",
            "topic": "Derivatives",
            "tutorial": "",
            "nodes": [{"id": "n3", "label": "Derivatives", "kind": "page"}],
        },
    ],
}

NOTES = {
    "week_01_limits.md": (
        "---\n"
        "id: note-1\n"
        "title: Limits\n"
        "week: 1\n"
        "kind: topic\n"
        "---\n"
        "# Limits\n\n"
        "A limit describes the value a function approaches.\n\n"
        "## One-sided limits\n\n"
        "Approach from the left or the right.\n"
    ),
    "week_02_derivatives.md": (
        "---\n"
        "id: note-2\n"
        "title: Derivatives\n"
        "week: 2\n"
        "kind: topic\n"
        "---\n"
        "# Derivatives\n\n"
        "The derivative measures instantaneous rate of change.\n\n"
        "## Power rule\n\n"
        "d/dx x^n = n x^(n-1).\n"
    ),
}

SIFT_REPORT = {
    "items": [
        {
            "id": "note-1",
            "source": "canvas",
            "decisions": {"is_admin_fluff": False},
            "confidence": 0.9,
            "route": "keep",
        },
        {
            "id": "note-2",
            "source": "canvas",
            "decisions": {"is_admin_fluff": False},
            "confidence": 0.85,
            "route": "keep",
        },
    ]
}


def load_runner():
    """Import scripts/run_pipeline.py by path (module name keeps it isolated)."""
    spec = importlib.util.spec_from_file_location("run_pipeline_under_test", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_workspace(root):
    workspace = Path(root) / "workspace"
    ingest = workspace / "01_ingest"
    sift = workspace / "02_sift"
    cleaned = sift / "cleaned"
    (workspace / "05_verify").mkdir(parents=True)
    ingest.mkdir(parents=True)
    cleaned.mkdir(parents=True)

    (ingest / "meta.json").write_text(json.dumps(META, indent=2) + "\n", encoding="utf-8")
    for name, text in NOTES.items():
        (cleaned / name).write_text(text, encoding="utf-8")
    (sift / "sift_report.json").write_text(
        json.dumps(SIFT_REPORT, indent=2) + "\n", encoding="utf-8"
    )
    return workspace


def run_main(argv):
    module = load_runner()
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = module.main(argv)
    return code, out.getvalue(), err.getvalue()


def read_step(workspace, number):
    path = Path(workspace) / "05_verify" / f"step_{number:02d}.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


class PipelineE2ETests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = build_workspace(self._tmp.name)

    def _run(self, stage):
        return run_main([stage, "--workspace", str(self.workspace)])

    def test_dry_run_writes_nothing(self):
        code, _out, _err = run_main(
            ["stage4", "--workspace", str(self.workspace), "--dry-run"]
        )
        self.assertEqual(code, 0)
        self.assertFalse((Path(self.workspace) / "05_verify" / "step_04.json").exists())

    def test_a_raising_lane_fails_a_deterministic_stage(self):
        """Stage 4 delivers three pages; one renderer raising cannot be green."""
        module = load_runner()
        parts = [
            ("render_graph", {"status": "ok", "outputs": ["04_render/graph.html"]}),
            ("render_anki", {"status": "ok", "outputs": ["04_render/anki.html"]}),
            ("render_cornell", "render_cornell.run raised: name 're' is not defined"),
        ]
        payload = module._merge_results(
            4, "2026-01-01T00:00:00Z", parts, workspace=self.workspace
        )
        self.assertEqual(payload["status"], "failed", payload)
        self.assertTrue(any("render_cornell" in e for e in payload["errors"]), payload)

    def test_stages_three_four_five_write_evidence(self):
        for stage, number in (("stage3", 3), ("stage4", 4), ("stage5", 5)):
            code, _out, err = self._run(stage)
            path, payload = read_step(self.workspace, number)
            self.assertTrue(path.is_file(), f"missing {path}: {err}")
            self.assertIn("status", payload)
            self.assertIn(payload["status"], VALID_STATUSES, payload)
            self.assertIn(payload.get("step_type"), VALID_STEP_TYPES, payload)
            self.assertEqual(payload["step_type"], STAGE_STEP_TYPES[number], payload)
            if number == 3:
                context = Path(self.workspace) / "03_structure" / "CONTEXT.md"
                self.assertTrue(context.is_file(), f"missing {context}")
                self.assertIn("stage 3", context.read_text(encoding="utf-8").lower())
            if number == 5:
                context = Path(self.workspace) / "05_verify" / "CONTEXT.md"
                self.assertTrue(context.is_file(), f"missing {context}")
            if number in (3, 4):
                self.assertEqual(code, 0, f"{stage} failed: {err}")
                self.assertEqual(payload["status"], "ok", payload)
            else:
                # gate5 has no judge dependency, so stage 5 may be "skipped".
                self.assertIn(payload["status"], VALID_STATUSES, payload)

    def test_step_04_outputs_include_all_renderers(self):
        code, _out, err = self._run("stage3")
        self.assertEqual(code, 0, err)
        code, _out, err = self._run("stage4")
        self.assertEqual(code, 0, err)

        path, payload = read_step(self.workspace, 4)
        outputs = [str(item.get("path", "")) if isinstance(item, dict) else str(item)
                   for item in payload["outputs"]]
        joined = "\n".join(outputs)
        for name in ("graph.html", "anki.html", "cornell.html"):
            self.assertIn(name, joined, payload)
            self.assertTrue((Path(self.workspace) / "04_render" / name).is_file(), payload)

    def test_step_04_outputs_are_relative_existing_paths(self):
        self.assertEqual(self._run("stage3")[0], 0)
        code, _out, err = self._run("stage4")
        self.assertEqual(code, 0, err)

        _path, payload = read_step(self.workspace, 4)
        outputs = payload["outputs"]
        self.assertTrue(outputs, payload)
        for entry in outputs:
            self.assertIsInstance(entry, str, payload)
            self.assertFalse(Path(entry).is_absolute(), entry)
            self.assertTrue((Path(self.workspace) / entry).is_file(), entry)
        self.assertEqual(outputs, sorted(set(outputs)), outputs)

    def test_stage5_without_judge_is_skipped_with_reason(self):
        self.assertEqual(self._run("stage3")[0], 0)
        self.assertEqual(self._run("stage4")[0], 0)

        code, _out, _err = self._run("stage5")
        path, payload = read_step(self.workspace, 5)
        self.assertTrue(path.is_file())
        self.assertEqual(payload["status"], "skipped", payload)
        self.assertNotEqual(code, 0, "a skipped gate must not exit green")
        gate5 = [g for g in payload.get("gates", []) if g.get("gate") == "gate5_judge"]
        self.assertTrue(gate5, payload)
        self.assertEqual(gate5[0]["status"], "skipped", payload)
        why = "\n".join(payload.get("evidence", []) + payload.get("errors", []))
        self.assertIn("gate5_judge: skipped", why)
        self.assertIn("judge", why.lower())
        # The tag stays P (the judge is the intended worker); only status skips.
        self.assertEqual(payload.get("step_type"), "P", payload)
        self.assertIn("step_type P retained", why)

    def _prepare_gate_workspace(self):
        self.assertEqual(self._run("stage3")[0], 0)
        code, _out, err = self._run("stage4")
        self.assertEqual(code, 0, err)
        return Path(self.workspace)

    def test_gate5_skipped_when_no_judge_is_given(self):
        ws = self._prepare_gate_workspace()

        result = gates.run(ws, deps={})

        self.assertEqual(result["status"], "skipped", result)
        self.assertFalse(result["ok"], result)
        gate5 = [g for g in result["gates"] if g["gate"] == "gate5_judge"]
        self.assertEqual(gate5[0]["status"], "skipped", result)
        self.assertEqual(result["step_type"], "P", result)

    def test_gate5_passes_with_fake_judge_accepting(self):
        ws = self._prepare_gate_workspace()
        seen = []

        def judge(workspace):
            seen.append(Path(workspace))
            return True

        result = gates.run(ws, deps={"judge": judge})

        self.assertEqual(result["status"], "ok", result)
        self.assertTrue(result["ok"], result)
        self.assertEqual(seen, [ws], seen)
        gate5 = [g for g in result["gates"] if g["gate"] == "gate5_judge"]
        self.assertEqual(gate5[0]["status"], "ok", result)

    def test_gate5_fails_with_fake_judge_rejecting(self):
        ws = self._prepare_gate_workspace()

        result = gates.run(ws, deps={"judge": lambda _ws: False})

        self.assertEqual(result["status"], "failed", result)
        self.assertFalse(result["ok"], result)
        gate5 = [g for g in result["gates"] if g["gate"] == "gate5_judge"]
        self.assertEqual(gate5[0]["status"], "failed", result)
        self.assertIn(
            "gate5_judge: failed", "\n".join(result["evidence"]), result
        )

    def test_step_type_is_stamped_on_failure(self):
        # Malformed meta.json makes stage3 (a deterministic stage) fail fast.
        meta = Path(self.workspace) / "01_ingest" / "meta.json"
        meta.write_text("{ not json", encoding="utf-8")

        code, _out, err = self._run("stage3")
        path, payload = read_step(self.workspace, 3)

        self.assertTrue(path.is_file(), err)
        self.assertEqual(payload["status"], "failed", payload)
        self.assertNotEqual(code, 0, "a failed stage must not exit green")
        self.assertEqual(payload["step_type"], "D", payload)

    def test_judge_rubric_covers_every_render_artefact(self):
        ws = self._prepare_gate_workspace()

        rubric = gates.judge_rubric(ws)

        for name in ("graph.html", "anki.html", "cornell.html"):
            self.assertIn(name, rubric)
        self.assertIn("PASS", rubric)
        self.assertIn("FAIL", rubric)
        # The parser must read the verdict, not the echoed rubric.
        self.assertTrue(gates._parse_judge_verdict("Reasoning...\nPASS\nfaithful"))
        self.assertFalse(gates._parse_judge_verdict("Reasoning...\nFAIL\ninvented"))
        self.assertFalse(gates._parse_judge_verdict("no verdict here"))

    def test_cli_judge_is_opt_in_via_env_and_swappable(self):
        """PIPELINE_CLI_JUDGE wires gates.cli_judge; the fake stands in for it."""
        ws = self._prepare_gate_workspace()
        original = gates.cli_judge
        gates.cli_judge = lambda _ws: {"accepted": True, "reason": "stub judge"}
        previous = os.environ.get("PIPELINE_CLI_JUDGE")
        os.environ["PIPELINE_CLI_JUDGE"] = "1"
        try:
            code, _out, err = self._run("stage5")
        finally:
            gates.cli_judge = original
            if previous is None:
                os.environ.pop("PIPELINE_CLI_JUDGE", None)
            else:
                os.environ["PIPELINE_CLI_JUDGE"] = previous

        _path, payload = read_step(ws, 5)
        self.assertEqual(code, 0, err)
        self.assertEqual(payload["status"], "ok", payload)
        self.assertEqual(payload["step_type"], "P", payload)
        gate5 = [g for g in payload.get("gates", []) if g.get("gate") == "gate5_judge"]
        self.assertEqual(gate5[0]["status"], "ok", payload)

    def test_stage5_fails_when_a_render_file_is_deleted(self):
        self.assertEqual(self._run("stage3")[0], 0)
        self.assertEqual(self._run("stage4")[0], 0)

        victim = Path(self.workspace) / "04_render" / "cornell.html"
        victim.unlink()
        code, _out, err = self._run("stage5")
        path, payload = read_step(self.workspace, 5)
        self.assertTrue(path.is_file(), err)
        self.assertTrue(
            code != 0 or payload["status"] == "failed",
            f"stage5 should fail without cornell.html (code={code}, status={payload['status']})",
        )
        self.assertNotEqual(payload["status"], "ok")
        self.assertIn(payload["status"], VALID_STATUSES)

    def test_help_lists_all_stages(self):
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for stage in ("stage1", "stage2", "stage3", "stage4", "stage5", "all"):
            self.assertIn(stage, result.stdout)


if __name__ == "__main__":
    unittest.main()
