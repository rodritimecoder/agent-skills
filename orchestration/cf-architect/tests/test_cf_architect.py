#!/usr/bin/env python3
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cf_architect as cf


def fake_runner(table):
    def runner(cmd):
        key = " ".join(cmd)
        if key in table:
            return table[key]
        return 0, "[]"

    return runner


WHOAMI = (
    0,
    json.dumps(
        {
            "authenticated": True,
            "email": "someone@example.com",
            "accounts": [{"id": "abc", "name": "acct"}],
        }
    ),
)


class ClassifyTests(unittest.TestCase):
    def test_r2_gate_is_detected_not_reported_as_permission(self):
        out = "┌ APIError\n│ [10042] Please enable R2 through the Cloudflare Dashboard.\n└"
        result = cf.classify("r2", 1, out)
        self.assertEqual(result["state"], "gated")
        self.assertIn("dashboard", result["detail"])

    def test_empty_list_is_empty(self):
        self.assertEqual(cf.classify("d1", 0, "[]")["state"], "empty")

    def test_populated_list_counts_resources(self):
        payload = json.dumps([{"name": "a"}, {"name": "b"}])
        result = cf.classify("workers", 0, payload)
        self.assertEqual(result["state"], "active")
        self.assertIn("2", result["detail"])

    def test_unrecognised_failure_is_error(self):
        result = cf.classify("kv", 3, "boom\nsecond line")
        self.assertEqual(result["state"], "error")
        self.assertEqual(result["detail"], "boom")


class ProbeTests(unittest.TestCase):
    def test_free_plan_gates_containers_without_calling_it(self):
        calls = []

        def runner(cmd):
            calls.append(" ".join(cmd))
            key = " ".join(cmd)
            table = {
                "cf --version": (0, "cf v0.15.0"),
                "cf auth whoami": WHOAMI,
                "cf accounts subscriptions get": (0, "[]"),
            }
            return table.get(key, (0, "[]"))

        report = cf.probe(runner)
        self.assertEqual(report["plan"], "free")
        self.assertFalse(report["containers_available"])
        self.assertEqual(report["services"]["containers"]["state"], "gated")
        self.assertIn("Workers Paid", report["services"]["containers"]["detail"])

    def test_paid_plan_reports_containers_from_the_api(self):
        table = {
            "cf --version": (0, "cf v0.15.0"),
            "cf auth whoami": WHOAMI,
            "cf accounts subscriptions get": (0, '[{"id":"s1"}]'),
            "cf containers applications list": (0, '[{"name":"app"}]'),
        }
        report = cf.probe(fake_runner(table))
        self.assertEqual(report["plan"], "paid")
        self.assertEqual(report["services"]["containers"]["state"], "active")

    def test_identity_is_read_from_the_account(self):
        table = {
            "cf --version": (0, "cf v0.15.0"),
            "cf auth whoami": WHOAMI,
            "cf accounts subscriptions get": (0, "[]"),
        }
        report = cf.probe(fake_runner(table))
        self.assertTrue(report["authenticated"])
        self.assertEqual(report["email"], "someone@example.com")
        self.assertEqual(report["cf_version"], "0.15.0")

    def test_unauthenticated_probe_is_reported(self):
        table = {
            "cf --version": (0, "cf v0.15.0"),
            "cf auth whoami": (1, '{"authenticated": false}'),
            "cf accounts subscriptions get": (1, "unauthorized"),
        }
        report = cf.probe(fake_runner(table))
        self.assertFalse(report["authenticated"])
        self.assertIsNone(report["plan"])
        self.assertIsNone(report["containers_available"])


class BudgetTests(unittest.TestCase):
    def run_budget(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cf.main(["budget", *argv])
        return code, buf.getvalue()

    def test_small_vault_fits_every_dimension(self):
        code, out = self.run_budget("--r2-gb", "1.5", "--requests-per-day", "5000")
        self.assertEqual(code, 0)
        self.assertIn("fits the free tier", out)

    def test_oversized_vault_fails_loudly(self):
        code, out = self.run_budget("--r2-gb", "25")
        self.assertEqual(code, 1)
        self.assertIn("exceed", out)

    def test_audio_hours_are_converted_to_neurons(self):
        limit_hours = cf.LIMITS["workers_ai_neurons_per_day"] / cf.LIMITS[
            "whisper_neurons_per_audio_hour"
        ]
        code, _ = self.run_budget("--audio-hours-per-day", f"{limit_hours + 1}")
        self.assertEqual(code, 1)


class ScriptsFixTests(unittest.TestCase):
    def capture(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cf.main(["scripts-fix", *argv])
        return buf.getvalue()

    def test_global_context_uses_the_flag(self):
        out = self.capture("--context", "global")
        self.assertIn("--allow-scripts=workerd", out)

    def test_project_context_uses_the_manifest_command(self):
        out = self.capture("--context", "project")
        self.assertIn("npm install-scripts approve workerd", out)
        self.assertIn("allowScripts", out)

    def test_project_context_warns_about_the_hard_error(self):
        out = self.capture("--context", "project")
        self.assertIn("EALLOWSCRIPTS", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
