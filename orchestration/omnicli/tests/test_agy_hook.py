#!/usr/bin/env python3
"""
Unit tests for Antigravity omnicli lifecycle hook (agy_omnicli_hook.py).
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add hook directory to path
HOOK_DIR = Path(__file__).resolve().parent.parent / "hooks"
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

    def test_pre_invocation_injects_protojson_routing_once_per_session(self):
        res = hook.handle_pre_invocation({"conversationId": "ses-inject-1", "invocationNum": 1})
        self.assertIn("injectSteps", res)
        self.assertEqual(len(res["injectSteps"]), 1)
        sys_msg = res["injectSteps"][0]["systemMessage"]
        self.assertIsInstance(sys_msg, dict)
        self.assertIn("[omnicli route]", sys_msg["systemMessage"])

        # Second invocation in same session should not spam duplicate systemMessage
        res2 = hook.handle_pre_invocation({"conversationId": "ses-inject-1", "invocationNum": 2})
        self.assertNotIn("injectSteps", res2)
        self.assertEqual(res2.get("terminationBehavior"), "")

    def test_unrelated_file_read_allowed(self):
        payload = {
            "conversationId": "ses-1",
            "cwd": "/home/rodri/my-app",
            "toolCall": {
                "id": "toolu_01",
                "name": "view_file",
                "args": {"AbsolutePath": "/home/rodri/my-app/index.js"},
            },
        }
        res = hook.handle_pre_tool_use(payload)
        self.assertEqual(res["decision"], "allow")

    def test_skill_dir_view_file_denied_when_unprimed_camel_case(self):
        target = os.path.join(self.skills_dir, "zoom-recorder", "SKILL.md")
        payload = {
            "conversationId": "ses-2",
            "cwd": "/home/rodri/my-app",
            "toolCall": {
                "id": "toolu_02",
                "name": "view_file",
                "args": {"AbsolutePath": target},
            },
        }
        res = hook.handle_pre_tool_use(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Denied by agy-omnicli-route", res["reason"])

    def test_skill_dir_find_by_name_denied_when_unprimed(self):
        payload = {
            "conversationId": "ses-find",
            "cwd": "/home/rodri/my-app",
            "toolCall": {
                "id": "toolu_03",
                "name": "find_by_name",
                "args": {"SearchDirectory": self.skills_dir, "Pattern": "*"},
            },
        }
        res = hook.handle_pre_tool_use(payload)
        self.assertEqual(res["decision"], "deny")

    def test_skill_dir_read_file_capital_path_denied_when_unprimed(self):
        target = os.path.join(self.skills_dir, "ocr", "SKILL.md")
        payload = {
            "conversationId": "ses-read-file-path",
            "cwd": "/home/rodri/my-app",
            "toolCall": {
                "id": "toolu_03b",
                "name": "read_file",
                "args": {"Path": target},
            },
        }
        res = hook.handle_pre_tool_use(payload)
        self.assertEqual(res["decision"], "deny")

    def test_skill_dir_shell_read_denied_when_unprimed(self):
        cmd = f"cat {self.skills_dir}/zoom-recorder/SKILL.md"
        payload = {
            "conversationId": "ses-3",
            "cwd": "/home/rodri/my-app",
            "toolCall": {
                "id": "toolu_04",
                "name": "run_command",
                "args": {"CommandLine": cmd},
            },
        }
        res = hook.handle_pre_tool_use(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Denied by agy-omnicli-route", res["reason"])

    def test_omnicli_search_and_exec_prime_session_and_allow(self):
        for idx, cmd in enumerate([
            "omnicli search 'transcribe audio'",
            "omnicli exec -c 'print(1)'",
        ]):
            session_id = f"ses-prime-{idx}"
            prime_payload = {
                "conversationId": session_id,
                "cwd": "/home/rodri/my-app",
                "toolCall": {
                    "id": f"toolu_p_{idx}",
                    "name": "run_command",
                    "args": {"CommandLine": cmd},
                },
            }
            res = hook.handle_pre_tool_use(prime_payload)
            self.assertEqual(res["decision"], "allow")
            self.assertTrue(hook._is_session_primed(session_id))

            target = os.path.join(self.skills_dir, "audiocpp-asr", "SKILL.md")
            read_payload = {
                "conversationId": session_id,
                "cwd": "/home/rodri/my-app",
                "toolCall": {
                    "id": f"toolu_r_{idx}",
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
            "toolCall": {
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
            "toolCall": {
                "name": "view_file",
                "args": {"AbsolutePath": target},
            },
        }
        res = hook.handle_pre_tool_use(payload)
        self.assertEqual(res["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
