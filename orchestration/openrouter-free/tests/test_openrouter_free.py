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


if __name__ == "__main__":
    unittest.main()
