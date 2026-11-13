#!/usr/bin/env python3
"""
Unit tests for Antigravity omnicli lifecycle hook (agy_omnicli_hook.py).
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Add hook directory to path
HOOK_DIR = Path(__file__).resolve().parent.parent / "hooks"
import sys
sys.path.insert(0, str(HOOK_DIR))

import agy_omnicli_hook as hook


class TestAgyOmnicliHook(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.skills_dir = os.path.join(self.test_dir, "skills")
        os.makedirs(self.skills_dir, exist_ok=True)

        self.primed_dir = os.path.join(self.test_dir, "primed")
        self.route_log = Path(os.path.join(self.test_dir, "route.jsonl"))

        # Patch module paths
        self.orig_skills_root = hook.SKILLS_ROOT
        self.orig_exempt_marker = hook.EXEMPT_MARKER
        self.orig_primed_dir = hook.PRIMED_DIR
        self.orig_route_log = hook.ROUTE_LOG

        hook.SKILLS_ROOT = self.skills_dir
        hook.EXEMPT_MARKER = os.path.join(self.skills_dir, ".omnicli-route-exempt")
        hook.PRIMED_DIR = Path(self.primed_dir)
        hook.ROUTE_LOG = self.route_log

    def tearDown(self):
        hook.SKILLS_ROOT = self.orig_skills_root
        hook.EXEMPT_MARKER = self.orig_exempt_marker
        hook.PRIMED_DIR = self.orig_primed_dir
        hook.ROUTE_LOG = self.orig_route_log
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_pre_invocation_injects_routing(self):
        res = hook.handle_pre_invocation({})
        self.assertIn("inject_steps", res)
        self.assertTrue(len(res["inject_steps"]) > 0)
        self.assertIn("[omnicli route]", res["inject_steps"][0]["system_message"])

    def test_unrelated_file_read_allowed(self):
        payload = {
            "conversationId": "ses-1",
            "cwd": "/home/rodri/my-app",
            "tool_call": {
                "name": "view_file",
                "args": {"AbsolutePath": "/home/rodri/my-app/index.js"},
            },
        }
        res = hook.handle_pre_tool_use(payload)
        self.assertEqual(res["decision"], "allow")

    def test_skill_dir_view_file_denied_when_unprimed(self):
        target = os.path.join(self.skills_dir, "zoom-recorder", "SKILL.md")
        payload = {
            "conversationId": "ses-2",
            "cwd": "/home/rodri/my-app",
            "tool_call": {
                "name": "view_file",
                "args": {"AbsolutePath": target},
            },
        }
        res = hook.handle_pre_tool_use(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Denied by agy-omnicli-route", res["reason"])

    def test_skill_dir_shell_read_denied_when_unprimed(self):
        cmd = f"cat {self.skills_dir}/zoom-recorder/SKILL.md"
        payload = {
            "conversationId": "ses-3",
            "cwd": "/home/rodri/my-app",
            "tool_call": {
                "name": "run_command",
                "args": {"CommandLine": cmd},
            },
        }
        res = hook.handle_pre_tool_use(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Denied by agy-omnicli-route", res["reason"])

    def test_omnicli_search_primes_session_and_allows(self):
        session_id = "ses-prime-test"
        # 1. First run omnicli search
        prime_payload = {
            "conversationId": session_id,
            "cwd": "/home/rodri/my-app",
            "tool_call": {
                "name": "run_command",
                "args": {"CommandLine": "omnicli search 'transcribe audio'"},
            },
        }
        res = hook.handle_pre_tool_use(prime_payload)
        self.assertEqual(res["decision"], "allow")
        self.assertTrue(hook._is_session_primed(session_id))

        # 2. Subsequent direct read of skill is now permitted
        target = os.path.join(self.skills_dir, "audiocpp-asr", "SKILL.md")
        read_payload = {
            "conversationId": session_id,
            "cwd": "/home/rodri/my-app",
            "tool_call": {
                "name": "view_file",
                "args": {"AbsolutePath": target},
            },
        }
        res2 = hook.handle_pre_tool_use(read_payload)
        self.assertEqual(res2["decision"], "allow")

    def test_project_inside_skills_is_exempt(self):
        target = os.path.join(self.skills_dir, "omnicli", "SKILL.md")
        payload = {
            "conversationId": "ses-exempt-proj",
            "cwd": self.skills_dir,
            "workspacePaths": [self.skills_dir],
            "tool_call": {
                "name": "view_file",
                "args": {"AbsolutePath": target},
            },
        }
        res = hook.handle_pre_tool_use(payload)
        self.assertEqual(res["decision"], "allow")

    def test_exempt_marker_allows_read(self):
        Path(hook.EXEMPT_MARKER).touch()
        target = os.path.join(self.skills_dir, "zoom-recorder", "SKILL.md")
        payload = {
            "conversationId": "ses-marker-test",
            "cwd": "/home/rodri/my-app",
            "tool_call": {
                "name": "view_file",
                "args": {"AbsolutePath": target},
            },
        }
        res = hook.handle_pre_tool_use(payload)
        self.assertEqual(res["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
