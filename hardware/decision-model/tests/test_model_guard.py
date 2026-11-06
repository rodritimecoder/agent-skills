import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import decision_model


class Response:
    def __init__(self, model_id: str):
        self.body = json.dumps({"data": [{"id": model_id}]}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


class TestDecisionModelGuard(unittest.TestCase):
    def test_names_the_served_model(self):
        with patch.object(decision_model.urllib.request, "urlopen",
                          return_value=Response("/models/h2o-lightning-4b-Q4_K_M.gguf")):
            self.assertEqual(decision_model.served_model(8083), "/models/h2o-lightning-4b-Q4_K_M.gguf")

    def test_slot_rotation_is_accepted(self):
        with patch.object(decision_model.urllib.request, "urlopen",
                          return_value=Response("/models/vllm-d3-nano-Q4_K_M.gguf")):
            self.assertEqual(decision_model.served_model(8083), "/models/vllm-d3-nano-Q4_K_M.gguf")

    def test_h2o_pin_is_opt_in(self):
        with patch.dict(os.environ, {"DECISION_REQUIRE_H2O": "1"}), \
             patch.object(decision_model.urllib.request, "urlopen",
                          return_value=Response("/models/vllm-d3-nano-Q4_K_M.gguf")):
            with self.assertRaises(SystemExit) as error:
                decision_model.served_model(8083)
        self.assertIn("expected h2o-lightning-4b", str(error.exception))


if __name__ == "__main__":
    unittest.main()
