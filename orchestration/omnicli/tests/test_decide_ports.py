#!/usr/bin/env python3
"""Route guard for decide.py: decision traffic only reaches :8083 or :8089.

:8085 (LightOnOCR) and :8090 (MiniCPM-OCR-Jev) are OCR slots. A decision client
that launches a server there, or POSTs /v1/systemone to it, hijacks a port the OCR
skills own. These tests pin the ports the module actually posts to.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import pathlib
import unittest
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "decide.py"


def load_decide():
    spec = importlib.util.spec_from_file_location("decide_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Resp:
    status = 200

    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DecisionSlotRoutingTests(unittest.TestCase):
    def test_primary_backend_posts_systemone_to_8083_only(self) -> None:
        mod = load_decide()
        seen: list[str] = []

        def fake_urlopen(req, timeout=None):
            seen.append(req.full_url)
            return _Resp({"answers": {"answer": {
                "type": "choice", "choice": "a",
                "probabilities": {"0": 0.9, "1": 0.1}, "confidence": 0.8}}})

        with mock.patch.object(mod.urllib.request, "urlopen", fake_urlopen):
            mod.ask_vllm("state", "question", ["a", "b"], "choice")

        self.assertEqual(seen, ["http://127.0.0.1:8083/v1/systemone"])

    def test_auxiliary_backend_posts_to_8089_only(self) -> None:
        mod = load_decide()
        seen: list[str] = []

        def fake_urlopen(req, timeout=None):
            seen.append(req.full_url)
            return _Resp({"completion_probabilities": [{"top_logprobs": [
                {"token": " A", "logprob": 0.0},
                {"token": " B", "logprob": -1.0},
            ]}]})

        with mock.patch.object(mod.urllib.request, "urlopen", fake_urlopen):
            mod.ask_imajev("state", "question", ["a", "b"], "choice")

        self.assertEqual(seen, ["http://127.0.0.1:8089/completion"])

    def test_only_decision_slot_ports_exist(self) -> None:
        mod = load_decide()
        self.assertEqual(mod.VLLM_PORT, 8083)
        self.assertEqual(mod.PPLX_PORT, 8083)
        self.assertEqual(mod.IMAJEV_PORT, 8089)
        for gone in ("JEVSTYLE_PORT", "JPT_ENGINE_PORT", "DEFAULT_PORT", "ENGINE_PORT"):
            self.assertFalse(hasattr(mod, gone), f"{gone} is a stale decision port")

    def test_backend_default_ports_are_decision_slots(self) -> None:
        mod = load_decide()
        for backend in (mod.ask_vllm, mod.ask_imajev):
            default = inspect.signature(backend).parameters["port"].default
            self.assertIn(default, (8083, 8089),
                          f"{backend.__name__} defaults to :{default}, not a decision slot")


if __name__ == "__main__":
    unittest.main()
