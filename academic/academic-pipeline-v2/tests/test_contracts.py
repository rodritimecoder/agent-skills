#!/usr/bin/env python3
"""Contract tests for academic-pipeline-v2 (stdlib only)."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
RUNNER = ROOT / "scripts" / "run_pipeline.py"


def validate(schema, instance):
    """Tiny JSON-Schema-subset validator for the fields these contracts need.

    Supports: type (object/array/integer/string/number), required,
    enum, minimum, maximum, and item/object property constraints.
    """

    def _check(instance, node, path):
        if "enum" in node:
            if instance not in node["enum"]:
                raise ValueError(f"{path}: {instance!r} not in {node['enum']}")
        node_type = node.get("type")
        if node_type == "object":
            if not isinstance(instance, dict):
                raise ValueError(f"{path}: expected object, got {type(instance).__name__}")
            for key in node.get("required", []):
                if key not in instance:
                    raise ValueError(f"{path}: missing required key {key!r}")
            props = node.get("properties", {})
            for key, value in instance.items():
                if key in props:
                    _check(value, props[key], f"{path}.{key}")
        elif node_type == "array":
            if not isinstance(instance, list):
                raise ValueError(f"{path}: expected array, got {type(instance).__name__}")
            items = node.get("items")
            if items is not None:
                for i, item in enumerate(instance):
                    _check(item, items, f"{path}[{i}]")
        elif node_type == "integer":
            if not isinstance(instance, int) or isinstance(instance, bool):
                raise ValueError(f"{path}: expected integer, got {type(instance).__name__}")
        elif node_type == "number":
            if not isinstance(instance, (int, float)) or isinstance(instance, bool):
                raise ValueError(f"{path}: expected number, got {type(instance).__name__}")
        elif node_type == "string":
            if not isinstance(instance, str):
                raise ValueError(f"{path}: expected string, got {type(instance).__name__}")
        if "minimum" in node and isinstance(instance, (int, float)):
            if instance < node["minimum"]:
                raise ValueError(f"{path}: {instance} < {node['minimum']}")
        if "maximum" in node and isinstance(instance, (int, float)):
            if instance > node["maximum"]:
                raise ValueError(f"{path}: {instance} > {node['maximum']}")

    _check(instance, schema, "$")
    return True


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.step_schema = json.loads((CONTRACTS / "step.schema.json").read_text())
        self.sift_schema = json.loads((CONTRACTS / "sift_report.schema.json").read_text())
        self.meta_schema = json.loads((CONTRACTS / "meta.schema.json").read_text())

    def test_step_valid(self):
        valid = {
            "stage": 1,
            "stage_name": "ingest",
            "step_type": "P",
            "status": "ok",
            "started_at": "2026-10-25T00:00:00Z",
            "finished_at": "2026-10-25T00:01:00Z",
            "inputs": {"workspace": "./workspace"},
            "outputs": [],
            "evidence": [],
            "errors": [],
        }
        self.assertTrue(validate(self.step_schema, valid))

    def test_step_requires_step_type(self):
        missing = {
            "stage": 3,
            "stage_name": "structure",
            "status": "ok",
            "started_at": "2026-10-25T00:00:00Z",
            "finished_at": "2026-10-25T00:01:00Z",
            "inputs": {},
            "outputs": [],
            "evidence": [],
            "errors": [],
        }
        with self.assertRaises(ValueError):
            validate(self.step_schema, missing)

    def test_step_accepts_each_step_type(self):
        for step_type in ("D", "P", "H"):
            valid = {
                "stage": 4,
                "stage_name": "render",
                "step_type": step_type,
                "status": "ok",
                "started_at": "2026-10-25T00:00:00Z",
                "finished_at": "2026-10-25T00:01:00Z",
                "inputs": {},
                "outputs": [],
                "evidence": [],
                "errors": [],
            }
            self.assertTrue(validate(self.step_schema, valid), step_type)

    def test_step_rejects_unknown_step_type(self):
        for bad in ("X", "deterministic", "", None):
            invalid = {
                "stage": 4,
                "stage_name": "render",
                "step_type": bad,
                "status": "ok",
                "started_at": "2026-10-25T00:00:00Z",
                "finished_at": "2026-10-25T00:01:00Z",
                "inputs": {},
                "outputs": [],
                "evidence": [],
                "errors": [],
            }
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate(self.step_schema, invalid)

    def test_step_invalid(self):
        invalid = {
            "stage": 9,
            "stage_name": "ingest",
            "status": "maybe",
            "started_at": "2026-10-25T00:00:00Z",
            "finished_at": "2026-10-25T00:01:00Z",
            "inputs": {},
            "outputs": [],
            "evidence": [],
            "errors": [],
        }
        with self.assertRaises(ValueError):
            validate(self.step_schema, invalid)

    def test_sift_valid(self):
        valid = {
            "items": [
                {
                    "id": "note-1",
                    "source": "canvas",
                    "decisions": {"is_admin_fluff": False},
                    "confidence": 0.9,
                    "route": "keep",
                }
            ]
        }
        self.assertTrue(validate(self.sift_schema, valid))

    def test_sift_invalid(self):
        invalid = {
            "items": [
                {
                    "id": "note-1",
                    "source": "canvas",
                    "decisions": {},
                    "confidence": 2.0,
                    "route": "keep",
                }
            ]
        }
        with self.assertRaises(ValueError):
            validate(self.sift_schema, invalid)

    def test_meta_valid(self):
        valid = {
            "course": "MATH101",
            "weeks": [
                {
                    "week": "Week_01",
                    "topic": "Limits",
                    "tutorial": "Limits solutions",
                    "nodes": [
                        {"id": "n1", "label": "Limits", "kind": "topic"}
                    ],
                }
            ],
        }
        self.assertTrue(validate(self.meta_schema, valid))

    def test_meta_invalid(self):
        invalid = {
            "course": "MATH101",
            "weeks": [
                {
                    "week": "Week_01",
                    "topic": "Limits",
                    "tutorial": "Limits solutions",
                    "nodes": [{"id": "n1", "label": "Limits"}],
                }
            ],
        }
        with self.assertRaises(ValueError):
            validate(self.meta_schema, invalid)

    def test_help_lists_all_five_stages(self):
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for stage in ("stage1", "stage2", "stage3", "stage4", "stage5"):
            self.assertIn(stage, result.stdout)


if __name__ == "__main__":
    unittest.main()
