#!/usr/bin/env python3
"""Tests for scripts/write_context.py (stdlib unittest only)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import write_context  # noqa: E402

SCHEMA = ROOT / "contracts" / "step.schema.json"
TEMPLATE = ROOT / "_templates" / "stage-CONTEXT.md"

EXPECTED_FOLDERS = {
    1: "01_ingest",
    2: "02_sift",
    3: "03_structure",
    4: "04_render",
    5: "05_verify",
}


def validate(schema, instance):
    """Tiny JSON-Schema-subset validator (object/array/scalar + required)."""

    def _check(instance, node, path):
        if "enum" in node and instance not in node["enum"]:
            raise ValueError(f"{path}: {instance!r} not in {node['enum']}")
        node_type = node.get("type")
        if node_type == "object":
            if not isinstance(instance, dict):
                raise ValueError(f"{path}: expected object")
            for key in node.get("required", []):
                if key not in instance:
                    raise ValueError(f"{path}: missing required key {key!r}")
            props = node.get("properties", {})
            for key, value in instance.items():
                if key in props:
                    _check(value, props[key], f"{path}.{key}")
        elif node_type == "array":
            if not isinstance(instance, list):
                raise ValueError(f"{path}: expected array")
            items = node.get("items")
            if items is not None:
                for i, item in enumerate(instance):
                    _check(item, items, f"{path}[{i}]")
        elif node_type == "integer":
            if not isinstance(instance, int) or isinstance(instance, bool):
                raise ValueError(f"{path}: expected integer")
        elif node_type == "string":
            if not isinstance(instance, str):
                raise ValueError(f"{path}: expected string")
        if "minimum" in node and isinstance(instance, (int, float)):
            if instance < node["minimum"]:
                raise ValueError(f"{path}: below minimum")
        if "maximum" in node and isinstance(instance, (int, float)):
            if instance > node["maximum"]:
                raise ValueError(f"{path}: above maximum")

    _check(instance, schema, "$")
    return True


class WriteContextTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir(parents=True)
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_all_five_stage_folders_get_a_context(self):
        for stage, folder in EXPECTED_FOLDERS.items():
            path = write_context.write_stage_context(
                self.workspace,
                stage,
                reads=[f"{folder}/in.txt"],
                writes=[f"{folder}/out.txt"],
                checks=["looks right"],
            )
            self.assertEqual(path, self.workspace / folder / "CONTEXT.md")
            self.assertTrue(path.is_file(), f"{path} missing")

        for folder in EXPECTED_FOLDERS.values():
            target = self.workspace / folder / "CONTEXT.md"
            self.assertTrue(target.is_file(), f"{folder}/CONTEXT.md not written")

    def test_contract_fields_and_no_workspace_map(self):
        path = write_context.write_stage_context(
            self.workspace,
            2,
            reads=["01_ingest/**/*.md"],
            writes=["02_sift/cleaned/**/*.md"],
            checks=["fences are balanced"],
        )
        body = path.read_text(encoding="utf-8")
        for field in ("**Actor:**", "**Step type:**", "**Proof:**"):
            self.assertIn(field, body)
        self.assertIn("05_verify/step_02.json", body)
        for section in ("## Inputs", "## Process", "## Outputs", "## Human check"):
            self.assertIn(section, body)
        # The per-stage contract must not carry a copy of the workspace map.
        self.assertNotIn("Stage execution map", body)
        self.assertNotIn("## Stages", body)

    def test_body_names_stage_reads_and_writes(self):
        path = write_context.write_stage_context(
            self.workspace,
            3,
            reads=["01_ingest/meta.json", "02_sift/sift_report.json"],
            writes=["03_structure/acme/02_index/index.md"],
            checks=["each week has slides"],
            human="Researcher approves outline.",
        )
        body = path.read_text(encoding="utf-8")
        self.assertIn("3", body)
        self.assertIn("03_structure", body)
        self.assertIn("01_ingest/meta.json", body)
        self.assertIn("02_sift/sift_report.json", body)
        self.assertIn("03_structure/acme/02_index/index.md", body)
        self.assertIn("each week has slides", body)
        self.assertIn("Researcher approves outline.", body)
        # No placeholder survives rendering.
        for token in ("{{STAGE}}", "{{TITLE}}", "{{READS}}", "{{WRITES}}",
                      "{{CHECKS}}", "{{HUMAN}}"):
            self.assertNotIn(token, body)
        # Template really was found (not the inline fallback) when it ships.
        if TEMPLATE.is_file():
            self.assertNotIn("{{COURSE}}", body)

    def test_second_call_does_not_overwrite(self):
        write_context.write_stage_context(
            self.workspace, 2, reads=["a"], writes=["b"], checks=["c"]
        )
        target = self.workspace / "02_sift" / "CONTEXT.md"
        before = target.read_text(encoding="utf-8")

        with self.assertRaises(FileExistsError):
            write_context.write_stage_context(
                self.workspace, 2, reads=["NEW"], writes=["NEW"], checks=["NEW"]
            )
        self.assertEqual(before, target.read_text(encoding="utf-8"))

        write_context.write_stage_context(
            self.workspace, 2, reads=["NEW"], writes=["NEW"], checks=["NEW"],
            overwrite=True,
        )
        self.assertIn("NEW", target.read_text(encoding="utf-8"))

    def test_run_returns_contract_payload(self):
        payload = write_context.run(self.workspace)
        validate(self.schema, payload)
        expected = {
            "stage", "stage_name", "step_type", "status", "started_at", "finished_at",
            "inputs", "outputs", "evidence", "errors",
        }
        self.assertEqual(len(payload), 10)  # step.schema.json requires ten keys
        self.assertEqual(set(payload), expected)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["errors"], [])
        for folder in EXPECTED_FOLDERS.values():
            self.assertTrue((self.workspace / folder / "CONTEXT.md").is_file())
        # Idempotent: a second run keeps existing contexts and stays ok.
        again = write_context.run(self.workspace)
        validate(self.schema, again)
        self.assertEqual(again["status"], "ok")

    def test_run_dry_run_writes_nothing(self):
        payload = write_context.run(self.workspace, dry_run=True)
        validate(self.schema, payload)
        self.assertTrue(payload["inputs"]["dry_run"])
        for folder in EXPECTED_FOLDERS.values():
            self.assertFalse((self.workspace / folder / "CONTEXT.md").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
