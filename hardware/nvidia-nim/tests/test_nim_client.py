#!/usr/bin/env python3
"""
test_nim_client.py — Unit tests for nim_client.py
Tests environment resolution, CLI parsing, subagent tool schemas, and client initialization.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import nim_client
from nim_client import (
    DEFAULT_BASE_URL,
    DEFAULT_CHAT_MODEL,
    NimClient,
    SUBAGENT_TOOLS,
    chat,
    resolve_api_key,
    resolve_api_keys,
    resolve_base_url,
)


def _seed_manifest():
    """Offline fixture mirroring the corrected seed: 20 active, 13 candidates, 8 retired."""
    active = [f"active/model-{i:02d}" for i in range(20)]
    candidates = [f"candidate/model-{i:02d}" for i in range(13)]
    retired = [
        {"id": f"retired/model-{i:02d}", "role": "chat", "reason": "delisted"}
        for i in range(8)
    ]
    manifest = {
        "roles": {"chat": active[:11], "embed": active[11:], "decide": []},
        "candidates": candidates,
        "retired": retired,
        "models": {},
    }
    # Live catalog holds the 20 active ids plus the 13 candidate ids only;
    # retired entries are delisted history and are no longer live.
    live = [{"id": mid} for mid in (active + candidates)]
    return manifest, live


class TestNimClient(unittest.TestCase):
    def test_default_base_url(self):
        self.assertEqual(DEFAULT_BASE_URL, "https://integrate.api.nvidia.com/v1")
        self.assertEqual(resolve_base_url(), "https://integrate.api.nvidia.com/v1")

    @patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi-test-key-12345"})
    def test_resolve_api_key_from_env(self):
        self.assertEqual(resolve_api_key(), "nvapi-test-key-12345")

    @patch.dict(os.environ, {"NVIDIA_API_KEYS": "nvapi-key-1,nvapi-key-2"})
    def test_resolve_multiple_keys(self):
        keys = resolve_api_keys()
        self.assertIn("nvapi-key-1", keys)
        self.assertIn("nvapi-key-2", keys)

    @patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi-custom-key"})
    def test_client_init_with_env(self):
        client = NimClient()
        self.assertEqual(client.api_key, "nvapi-custom-key")
        self.assertTrue(client.is_configured())

    def test_subagent_tool_schema(self):
        self.assertEqual(len(SUBAGENT_TOOLS), 1)
        fn = SUBAGENT_TOOLS[0]["function"]
        self.assertEqual(fn["name"], "run_bash_batch")
        self.assertIn("commands", fn["parameters"]["properties"])

    def test_client_error_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("nim_client.resolve_api_keys", return_value=[]):
                client = NimClient(api_key=None)
                with self.assertRaises(ValueError) as ctx:
                    client.chat_completion([{"role": "user", "content": "hi"}])
                self.assertIn("No NVIDIA_API_KEY configured", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_successful_chat_mock(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__iter__.return_value = [
            b'data: {"choices":[{"delta":{"content":"9.8 is larger than 9.11."}}]}\n',
            b'data: [DONE]\n',
        ]
        mock_urlopen.return_value = mock_resp

        client = NimClient(api_key="nvapi-mock-123")
        res = client.chat_completion([{"role": "user", "content": "Which is larger, 9.11 or 9.8?"}])
        self.assertEqual(res["choices"][0]["message"]["content"], "9.8 is larger than 9.11.")


class TestCatalogSummary(unittest.TestCase):
    """Offline coverage for drift accounting; no credentials or network needed."""

    def _summary(self, manifest, live=None, fetch_error=None):
        fake_catalog = MagicMock()
        if fetch_error is not None:
            fake_catalog.fetch_catalog.side_effect = fetch_error
        else:
            fake_catalog.fetch_catalog.return_value = live
        with patch.object(nim_client, "load_catalog_manifest", return_value=manifest):
            with patch.object(nim_client, "nim_catalog", fake_catalog):
                return nim_client.catalog_summary()

    def test_candidates_and_retired_are_not_drift(self):
        manifest, live = _seed_manifest()
        result = self._summary(manifest, live)
        self.assertEqual(result["drift"], 0)
        self.assertEqual(result["retired_count"], 8)
        self.assertEqual(result["degraded_roles"], ["decide"])
        self.assertNotIn("note", result)

    def test_new_live_id_counts_as_drift(self):
        manifest, live = _seed_manifest()
        live = live + [{"id": "org/brand-new-model"}]
        result = self._summary(manifest, live)
        self.assertEqual(result["drift"], 1)
        self.assertEqual(result["retired_count"], 8)

    def test_unreachable_live_catalog_gives_no_drift(self):
        manifest, _ = _seed_manifest()
        result = self._summary(manifest, fetch_error=OSError("offline"))
        self.assertIsNone(result["drift"])
        self.assertIn("live catalog unreachable", result["note"])
        self.assertEqual(result["retired_count"], 8)

    def test_missing_manifest_gives_no_drift(self):
        with patch.object(nim_client, "load_catalog_manifest", return_value=None):
            result = nim_client.catalog_summary()
        self.assertIsNone(result["drift"])
        self.assertEqual(result["note"], "manifest unavailable")


if __name__ == "__main__":
    unittest.main()
