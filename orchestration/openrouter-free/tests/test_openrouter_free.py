import json
import subprocess
import unittest
from pathlib import Path


class TestOpenRouterFree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = str(Path(__file__).resolve().parent.parent / "scripts" / "or_agent.py")
        probe = subprocess.run(["python3", cls.cli, "doctor", "--json"], capture_output=True, text=True)
        try:
            health = json.loads(probe.stdout)
        except json.JSONDecodeError:
            raise unittest.SkipTest("doctor did not return JSON; no provider credentials here")
        creds = health.get("credentials", {}).get("openrouter_api_key", {})
        if not (creds.get("configured") and creds.get("valid")):
            raise unittest.SkipTest("no valid OPENROUTER_API_KEY; this suite tests the live service")

    def test_01_doctor_json_contract(self):
        res = subprocess.run(
            ["python3", self.cli, "doctor", "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Doctor check failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertIn("status", data)
        self.assertIn("credentials", data)
        self.assertIn("free_tier_telemetry", data)
        self.assertIn("local_homelab_fallbacks", data)

        creds = data["credentials"]["openrouter_api_key"]
        self.assertTrue(creds["configured"])
        self.assertTrue(creds["valid"])

        telemetry = data["free_tier_telemetry"]
        self.assertIsNotNone(telemetry["daily_requests_remaining"])
        self.assertGreater(telemetry["daily_requests_limit"], 0)

    def test_02_decide_response_projection(self):
        res = subprocess.run(
            [
                "python3",
                self.cli,
                "decide",
                "--query",
                "Is 100 greater than 10?",
                "--options",
                "yes",
                "no",
                "--project",
                "verdict,confidence",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        self.assertEqual(data.get("verdict"), "yes")
        self.assertIn("confidence", data)
        self.assertNotIn("probabilities", data)
        self.assertNotIn("raw", data)

    def test_03_decide_jq_projection(self):
        res = subprocess.run(
            [
                "python3",
                self.cli,
                "decide",
                "--query",
                "Is ice cold?",
                "--options",
                "yes",
                "no",
                "--jq",
                ".verdict",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(res.stdout.strip().strip('"'), "yes")

    def test_04_invalid_mode_exit_code(self):
        res = subprocess.run(
            ["python3", self.cli, "nonexistent_mode"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)


class TestVerdictNormalization(unittest.TestCase):
    """Offline pin for the chat-fallback contract: a verdict, not a paragraph."""

    @classmethod
    def setUpClass(cls):
        import importlib.util

        path = Path(__file__).resolve().parent.parent / "scripts" / "or_agent.py"
        spec = importlib.util.spec_from_file_location("or_agent_under_test", path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def norm(self, text, options=("yes", "no")):
        return self.mod._normalize_verdict(text, list(options))

    def test_chatty_completion_reduces_to_the_option(self):
        self.assertEqual(self.norm("yes  \nConfidence: 1.0")[0], "yes")
        self.assertEqual(self.norm("**no**")[0], "no")
        self.assertEqual(self.norm("Confidence: 0.9\nVerdict: yes")[0], "yes")

    def test_confidence_is_parsed_not_dropped(self):
        self.assertEqual(self.norm("yes\nConfidence: 1.0")[1], 1.0)
        self.assertEqual(self.norm("no\nProbability: 0.12")[1], 0.12)
        self.assertIsNone(self.norm("yes")[1])

    def test_option_is_not_matched_inside_a_word(self):
        self.assertEqual(self.norm("not sure")[0], "not sure")

    def test_canonical_option_spelling_is_preserved(self):
        self.assertEqual(self.norm("Needs Review", ["needs review", "ok"])[0], "needs review")


class TestCatalogDrift(unittest.TestCase):
    """Offline pins for the doctor --json catalog.drift contract.

    A retired *history* entry (or a degraded role) is diagnostic state, not
    catalog drift. Only a fresh public catalog fetch diffed by build_plan may
    set drift=true. When the fetch is unavailable, drift must be null.
    """

    class _FakeCatalogSync:
        """Minimal catalog_sync stand-in: public GET + build_plan, no network."""

        def __init__(self, catalog=None, report=None, fetch_exc=None):
            self._catalog = [] if catalog is None else catalog
            self._report = report or {"drift": False, "added": [], "retired": [], "reactivated": []}
            self._fetch_exc = fetch_exc
            self.plan_args = None

        def fetch_catalog(self, *args, **kwargs):
            if self._fetch_exc is not None:
                raise self._fetch_exc
            return self._catalog

        def build_plan(self, manifest, catalog):
            self.plan_args = (manifest, catalog)
            return {"manifest": manifest, "report": dict(self._report)}

    @classmethod
    def setUpClass(cls):
        import importlib.util

        path = Path(__file__).resolve().parent.parent / "scripts" / "or_agent.py"
        spec = importlib.util.spec_from_file_location("or_agent_drift_under_test", path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    @staticmethod
    def _manifest_with_history(n=9):
        return {
            "source": "https://openrouter.ai/api/v1/models",
            "updated_at": "2026-11-23T00:00:00Z",
            "roles": {role: [] for role in ("chat", "decide", "embed", "rerank", "tts")},
            "models": {},
            "retired": [
                {"id": f"dead/model-{i}:free", "reason": "delisted"} for i in range(n)
            ],
        }

    def _doctor_catalog(self, fake_sync, manifest):
        """Run run_doctor(as_json=True) fully offline; return its catalog field."""
        import contextlib
        import io
        import os
        from unittest import mock

        originals = (
            self.mod._catalog_sync,
            self.mod.load_catalog_manifest,
            self.mod.check_tcp_port,
        )
        self.mod._catalog_sync = fake_sync
        self.mod.load_catalog_manifest = lambda: manifest
        self.mod.check_tcp_port = lambda host, port, timeout=0.5: False
        buf = io.StringIO()
        try:
            with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "", "GEMINI_API_KEY": ""}):
                with contextlib.redirect_stdout(buf):
                    self.mod.run_doctor(as_json=True)
        finally:
            (
                self.mod._catalog_sync,
                self.mod.load_catalog_manifest,
                self.mod.check_tcp_port,
            ) = originals
        return json.loads(buf.getvalue())["catalog"]

    def test_retired_history_alone_does_not_produce_drift_true(self):
        """Nine retired entries + degraded roles must not flip drift to true."""
        fake = self._FakeCatalogSync(report={"drift": False})
        manifest = self._manifest_with_history(9)
        catalog = self._doctor_catalog(fake, manifest)

        self.assertEqual(catalog["retired_count"], 9)
        self.assertTrue(catalog["degraded_roles"])
        self.assertIs(catalog["drift"], False)
        self.assertNotIn("drift_note", catalog)
        self.assertIsNotNone(fake.plan_args)  # drift came from build_plan, not history
        self.assertEqual(len(fake.plan_args[0]["retired"]), 9)

    def test_fabricated_drift_report_propagates_as_true(self):
        """A genuine build_plan drift report must surface as drift=true."""
        fake = self._FakeCatalogSync(report={"drift": True, "added": ["free/new:free"]})
        catalog = self._doctor_catalog(fake, self._manifest_with_history())
        self.assertIs(catalog["drift"], True)
        self.assertNotIn("drift_note", catalog)

    def test_offline_or_unavailable_yields_null_drift(self):
        """No catalog_sync, or a failed public fetch, yields drift=null + note."""
        missing = self._doctor_catalog(None, self._manifest_with_history())
        self.assertIsNone(missing["drift"])
        self.assertIsInstance(missing.get("drift_note"), str)
        self.assertTrue(missing["drift_note"])

        offline = self._FakeCatalogSync(fetch_exc=OSError("network unreachable"))
        failed = self._doctor_catalog(offline, self._manifest_with_history())
        self.assertIsNone(failed["drift"])
        self.assertIsInstance(failed.get("drift_note"), str)
        self.assertTrue(failed["drift_note"])


if __name__ == "__main__":
    unittest.main()
