#!/usr/bin/env python3
"""
test_nim_client.py — Unit tests for nim_client.py
Tests environment resolution, CLI parsing, subagent tool schemas, and client initialization.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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


if __name__ == "__main__":
    unittest.main()
