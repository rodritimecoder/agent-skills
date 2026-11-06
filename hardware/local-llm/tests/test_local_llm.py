#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import unittest

CLIENT_PY = str(Path(__file__).resolve().parent.parent / "scripts" / "llm_client.py")


class TestLocalLLM(unittest.TestCase):
    def test_01_models_json(self):
        res = subprocess.run(["python3", CLIENT_PY, "models", "--json"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"models --json failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        first = data[0]
        self.assertIn("model", first)
        self.assertIn("status", first)
        self.assertIn("launcher", first)

    def test_02_doctor_json(self):
        res = subprocess.run(["python3", CLIENT_PY, "doctor", "--json"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"doctor --json failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("online", data)
        self.assertIn("endpoint", data)

    def test_03_models_filtered(self):
        res = subprocess.run(["python3", CLIENT_PY, "models", "--status", "candidate", "--json"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        for m in data:
            self.assertEqual(m["status"], "candidate")


if __name__ == "__main__":
    unittest.main()
