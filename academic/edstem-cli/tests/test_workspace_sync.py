#!/usr/bin/env python3
"""Offline tests for the safe Ed workspace -> Git snapshot workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import workspace_sync  # noqa: E402


class SafePathTests(unittest.TestCase):
    def test_rejects_traversal_absolute_and_backslash(self):
        for raw in ("../escape", "a/../../b", "/etc/passwd", "C:/windows", "a\\b", "", "a/./b"):
            with self.assertRaises(workspace_sync.WorkspaceSyncError, msg=raw):
                workspace_sync.safe_relative_path(raw)

    def test_accepts_normal_paths_and_rejects_manifest_name(self):
        self.assertEqual(workspace_sync.safe_relative_path("tests/a.c"), "tests/a.c")
        with self.assertRaises(workspace_sync.WorkspaceSyncError):
            workspace_sync.safe_relative_path(workspace_sync.MANIFEST)


class SkipRuleTests(unittest.TestCase):
    def test_skips_backups_secrets_and_generated_dirs(self):
        cases = {
            "tests/sort_test.c.bak": "backup or secret file",
            ".env": "credential file",
            ".env.local": "credential file",
            "build/main.o": "generated directory",
            "notes.key": "backup or secret file",
        }
        for relative, expected in cases.items():
            self.assertEqual(workspace_sync.skip_reason(relative), expected, relative)
        self.assertIsNone(workspace_sync.skip_reason("main.c"))
        self.assertIsNone(workspace_sync.skip_reason("tests/compress_test.c"))


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.snapshot = self.root / "snapshot"
        self.repo = self.root / "repo"
        self.snapshot.mkdir()
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        (self.snapshot / "main.c").write_text("int main(void){return 0;}\n")
        (self.snapshot / "tests").mkdir()
        (self.snapshot / "tests" / "unit.c").write_text("int unit(void){return 1;}\n")
        (self.snapshot / "notes.bak").write_text("scratch\n")
        (self.snapshot / "build").mkdir()
        (self.snapshot / "build" / "main.o").write_bytes(b"\x00\x01")

    def test_compare_classifies_added_changed_unchanged_removed_and_skipped(self):
        (self.repo / "main.c").write_text("int main(void){return 0;}\n")
        (self.repo / workspace_sync.MANIFEST).write_text(
            json.dumps({"version": 1, "workspace_id": "ws1", "files": ["old.c", "main.c"]})
        )
        (self.repo / "old.c").write_text("stale\n")

        report = workspace_sync.compare_snapshot(self.snapshot, self.repo)

        self.assertEqual(report["added"], ["tests/unit.c"])
        self.assertEqual(report["changed"], [])
        self.assertEqual(report["unchanged"], ["main.c"])
        self.assertEqual(report["removed"], ["old.c"])
        self.assertEqual(
            [item["path"] for item in report["skipped"]],
            ["build/main.o", "notes.bak"],
        )

    def test_snapshot_rejects_symlink_and_oversized_file(self):
        os.symlink(self.snapshot / "main.c", self.snapshot / "link.c")
        with self.assertRaises(workspace_sync.WorkspaceSyncError):
            workspace_sync.snapshot_files(self.snapshot)
        os.unlink(self.snapshot / "link.c")

        with tempfile.TemporaryDirectory() as small:
            monkey = workspace_sync
            original = monkey.MAX_FILE_BYTES
            monkey.MAX_FILE_BYTES = 8
            try:
                with self.assertRaises(workspace_sync.WorkspaceSyncError):
                    workspace_sync.snapshot_files(self.snapshot)
            finally:
                monkey.MAX_FILE_BYTES = original

    def test_apply_writes_files_and_manifest_but_never_deletes(self):
        (self.repo / workspace_sync.MANIFEST).write_text(
            json.dumps({"version": 1, "workspace_id": "ws1", "files": ["old.c"]})
        )
        (self.repo / "old.c").write_text("stale\n")

        result = workspace_sync.apply_snapshot(self.snapshot, self.repo, "ws1")

        self.assertEqual(result["applied"], ["main.c", "tests/unit.c"])
        self.assertEqual(result["removed_not_deleted"], ["old.c"])
        self.assertTrue((self.repo / "old.c").is_file(), "removed file must not be deleted")
        self.assertEqual(
            (self.repo / "tests" / "unit.c").read_text(),
            (self.snapshot / "tests" / "unit.c").read_text(),
        )
        manifest = json.loads((self.repo / workspace_sync.MANIFEST).read_text())
        self.assertEqual(manifest["workspace_id"], "ws1")
        self.assertEqual(manifest["files"], ["main.c", "old.c", "tests/unit.c"])

    def test_apply_refuses_a_different_workspace_id(self):
        (self.repo / workspace_sync.MANIFEST).write_text(
            json.dumps({"version": 1, "workspace_id": "other", "files": []})
        )
        with self.assertRaises(workspace_sync.WorkspaceSyncError):
            workspace_sync.apply_snapshot(self.snapshot, self.repo, "ws1")

    def test_apply_refuses_symlink_in_destination(self):
        (self.repo / "tests").mkdir()
        os.symlink("/etc/hostname", self.repo / "tests" / "unit.c")
        with self.assertRaises(workspace_sync.WorkspaceSyncError):
            workspace_sync.apply_snapshot(self.snapshot, self.repo, "ws1")

    def test_git_clean_requirement(self):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        (self.repo / "local.txt").write_text("uncommitted\n")
        with self.assertRaises(workspace_sync.WorkspaceSyncError):
            workspace_sync.require_clean_git_repo(self.repo)
        (self.repo / "local.txt").unlink()
        workspace_sync.require_clean_git_repo(self.repo)

    def test_unified_diff_is_bounded_and_flags_binary(self):
        (self.repo / "main.c").write_text("int main(void){return 1;}\n")
        (self.repo / "bin.dat").write_bytes(b"\x00\x01")
        (self.snapshot / "bin.dat").write_bytes(b"\x00\x02")
        report = workspace_sync.compare_snapshot(self.snapshot, self.repo)

        text = workspace_sync.unified_diff(self.snapshot, self.repo, report, limit=200)

        self.assertIn("--- a/main.c", text)
        self.assertIn("Binary file differs: bin.dat", text)
        self.assertLessEqual(len(text), 400)


class HelperPathTests(unittest.TestCase):
    def test_helper_path_resolves_through_symlinked_cli(self):
        """Regression: a symlinked CLI looked for ed_ws.js beside the symlink."""
        from importlib.machinery import SourceFileLoader
        from importlib.util import module_from_spec, spec_from_loader

        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "edstem-cli"
            os.symlink(ROOT / "scripts" / "ed_cli.py", link)
            loader = SourceFileLoader("ed_cli_probe", str(link))
            module = module_from_spec(spec_from_loader("ed_cli_probe", loader))
            loader.exec_module(module)
            helper = module._workspace_helper_path()
            self.assertTrue(helper.is_file(), helper)
            self.assertEqual(helper.resolve(), (ROOT / "scripts" / "ed_ws.js").resolve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
