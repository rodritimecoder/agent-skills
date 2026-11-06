import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import decision_model


class TestBoxGate(unittest.TestCase):
    def answer(self, **overrides):
        base = {"found": True, "present": 0.885, "confidence": 0.651,
                "box": {"left": 0.1, "top": 0.1, "right": 0.9, "bottom": 0.9}}
        base.update(overrides)
        return base

    def test_accepts_a_present_and_tight_box(self):
        accepted, reason = decision_model.gate_box(self.answer())
        self.assertTrue(accepted)
        self.assertIsNone(reason)

    def test_found_without_a_target_is_rejected_on_presence(self):
        accepted, reason = decision_model.gate_box(self.answer(present=0.111, confidence=0.188))
        self.assertFalse(accepted)
        self.assertTrue(reason.startswith("present 0.111"), reason)

    def test_present_but_loose_is_rejected_on_confidence(self):
        accepted, reason = decision_model.gate_box(self.answer(present=0.899, confidence=0.144))
        self.assertFalse(accepted)
        self.assertTrue(reason.startswith("confidence 0.144"), reason)

    def test_no_box_at_all(self):
        accepted, reason = decision_model.gate_box(self.answer(found=False))
        self.assertFalse(accepted)
        self.assertEqual(reason, "no box located")

    def test_gates_are_configurable(self):
        self.assertTrue(decision_model.gate_box(self.answer(present=0.4), min_present=0.3)[0])
        self.assertFalse(decision_model.gate_box(self.answer(present=0.4), min_present=0.5)[0])

    def test_boundary_values_pass(self):
        accepted, _ = decision_model.gate_box(
            self.answer(present=0.5, confidence=0.30), min_present=0.5, min_confidence=0.30)
        self.assertTrue(accepted)


class TestCapabilities(unittest.TestCase):
    def test_the_shim_models_are_box_capable(self):
        for model in ("h2o-lightning-4b-Q4_K_M.gguf", "/models/H2O-Lightning-4b", "h2o-lightning"):
            self.assertTrue(decision_model.box_capable(model), model)

    def test_other_slot_candidates_are_not(self):
        for model in ("vllm-d3-nano-Q4_K_M.gguf", "pplx-decider-flash-v1.2", "imajev-4b"):
            self.assertFalse(decision_model.box_capable(model), model)

    def test_primitives_name_box_only_where_it_is_served(self):
        self.assertEqual(decision_model.primitives("h2o-lightning-4b"),
                         ["bool", "choice", "score", "box"])
        self.assertEqual(decision_model.primitives("vllm-d3-nano"),
                         ["bool", "choice", "score"])


if __name__ == "__main__":
    unittest.main()
