#!/usr/bin/env python3
"""Unit tests for the per-session state bridge (Kem control-probe style).

A gate that cannot fail is not a gate: every positive assertion is paired with
a mutated negative control.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compactor  # noqa: E402


class SessionScopeTests(unittest.TestCase):
    def test_two_sessions_are_isolated(self):
        with tempfile.TemporaryDirectory() as root:
            a_json, a_md = compactor.session_state_paths("ses_alpha", root)
            b_json, _ = compactor.session_state_paths("ses_beta", root)
            self.assertNotEqual(a_json, b_json)
            self.assertEqual(a_md.name, "STATE.md")
            self.assertTrue(a_json.parent.is_dir())

    def test_invalid_session_id_is_refused(self):
        for bad in ("", "../escape", "a/b", "x" * 200):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                compactor.session_state_paths(bad)

    def test_env_precedence(self):
        os.environ["OPENCODE_SESSION_ID"] = "ses_from_opencode"
        os.environ.pop("STATE_SESSION_ID", None)
        self.assertEqual(compactor._effective_session_id(), "ses_from_opencode")
        os.environ["STATE_SESSION_ID"] = "ses_override"
        self.assertEqual(compactor._effective_session_id(), "ses_override")
        os.environ.pop("STATE_SESSION_ID", None)
        os.environ.pop("OPENCODE_SESSION_ID", None)


class HandoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.json_path, self.md_path = compactor.session_state_paths("ses_test", str(self.root))
        self.prev_session = os.environ.get("STATE_SESSION_ID")
        os.environ["STATE_SESSION_ID"] = "ses_test"

    def tearDown(self):
        if self.prev_session is None:
            os.environ.pop("STATE_SESSION_ID", None)
        else:
            os.environ["STATE_SESSION_ID"] = self.prev_session
        self.tmp.cleanup()

    def _state(self, **overrides):
        data = {
            "version": "1.1",
            "goal": "Build the bridge",
            "active_milestone": "Verify",
            "turn_count": 3,
            "facts": ["FACT_A: GPUs online"],
            "decisions": ["D: SQLite over Redis"],
            "forbidden": ["RULE: never kill -9"],
            "tasks_completed": ["scaffold"],
            "tasks_open": ["run integration test"],
        }
        data.update(overrides)
        self.json_path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def test_render_contract(self):
        self._state()
        text = compactor.bridge_summary(str(self.root))
        for needle in (
            "## Objective",
            "Build the bridge",
            "## Ground Truth Facts (verbatim, zero-loss)",
            "FACT_A: GPUs online",
            "D: SQLite over Redis",
            "RULE: never kill -9",
            "- [x] scaffold",
            "- [ ] run integration test",
            "## Next Move",
            "run integration test",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_negative_control_mutated_fact_changes_summary(self):
        self._state()
        before = compactor.bridge_summary(str(self.root))
        self._state(facts=["FACT_B: GPUs OFFLINE"])
        after = compactor.bridge_summary(str(self.root))
        self.assertNotEqual(before, after)
        self.assertIn("FACT_B", after)
        self.assertNotIn("FACT_A", after)

    def test_negative_control_plant_error_lands_in_forbidden(self):
        self._state()
        before = compactor.bridge_summary(str(self.root))
        self._state(forbidden=["RULE: failed step must never become a fact"])
        after = compactor.bridge_summary(str(self.root))
        self.assertNotEqual(before, after)
        self.assertIn("failed step must never become a fact", after)
        self.assertIn("Negative Constraints", after)

    def test_no_ledger_degrades_gracefully(self):
        text = compactor.bridge_summary(str(self.root))
        self.assertIn("No state ledger initialized", text)
        self.assertIn("## Next Move", text)


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print("usage: test_bridge.py [-v] [-q] [tests ...]")
        print('Exit codes: 0 success; 1 runtime/validation error; 2 invalid arguments (usage error); other non-zero values are script-specific.')
        sys.exit(0)
    unittest.main(verbosity=2)
