"""Hermetic unit tests for the omnicli MCP face.

Run:
    python3 tests/test_mcp.py
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from catalog import mcp  # noqa: E402

OMNICLI = HERE.parent / "omnicli.py"


def _request(opener, url, method="GET", body=None, headers=None):
    """Return (status, body_bytes, headers_dict), treating HTTPError as data."""
    data = body.encode("utf-8") if isinstance(body, str) else body
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=5) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(), dict(exc.headers)
        finally:
            exc.close()


def _start_server(token="test-token", ctx=None, limiter=None):
    server = mcp.make_server("127.0.0.1", 0, token, ctx or {"allow_exec": False})
    if limiter is not None:
        server.mcp_rate = limiter
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, server.server_address[1], thread


def _stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


class _AuditIsolated(unittest.TestCase):
    """Keep every tools/call audit line in a temp dir, never the real home."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(
            mcp.builder, "db_path", return_value=Path(self._tmp.name) / "catalog.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)


class TestDefinitions(unittest.TestCase):
    def test_tools_list_returns_three_valid_tools(self):
        reply = mcp.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                             {"allow_exec": True})
        tools = reply["result"]["tools"]
        self.assertEqual([t["name"] for t in tools],
                         ["omni_search", "omni_invoke", "omni_exec"])
        self.assertEqual(mcp.TOOLS, tools)
        for tool in tools:
            self.assertTrue(tool.get("title"))
            self.assertTrue(tool.get("description"))
            schema = tool["inputSchema"]
            self.assertEqual(schema["type"], "object")
            self.assertIs(schema["additionalProperties"], False)
            self.assertIsInstance(schema["properties"], dict)

        by_name = {t["name"]: t for t in tools}
        search = by_name["omni_search"]["inputSchema"]
        self.assertEqual(search["required"], ["query"])
        self.assertEqual(search["properties"]["query"]["type"], "string")
        self.assertEqual((search["properties"]["limit"]["minimum"],
                          search["properties"]["limit"]["maximum"],
                          search["properties"]["limit"]["default"]), (1, 20, 5))
        self.assertEqual(search["properties"]["depth"]["enum"], ["brief", "contract", "chunks"])
        self.assertEqual(search["properties"]["depth"]["default"], "brief")
        self.assertEqual(search["properties"]["max_bytes"]["default"], 8000)

        invoke = by_name["omni_invoke"]["inputSchema"]
        self.assertEqual(invoke["required"], ["tool_id"])
        self.assertEqual(invoke["properties"]["args"]["items"]["type"], "string")
        self.assertEqual(invoke["properties"]["args"]["default"], [])
        self.assertEqual(invoke["properties"]["timeout"]["type"], "number")
        self.assertEqual(invoke["properties"]["timeout"]["default"], 300)

        ex = by_name["omni_exec"]["inputSchema"]
        self.assertEqual(ex["properties"]["sandbox"]["enum"], ["strict", "write", "none"])
        self.assertEqual(ex["properties"]["sandbox"]["default"], "strict")
        self.assertEqual(ex["properties"]["max_bytes"]["default"], 16000)

    def test_descriptions_document_contract_depth_and_enable_gate(self):
        by_name = {t["name"]: t for t in mcp.TOOLS}
        search_desc = by_name["omni_search"]["description"].lower()
        self.assertIn("contract", search_desc)
        self.assertIn("no separate describe", search_desc)
        self.assertIn("exposure", search_desc)
        self.assertIn("enable", by_name["omni_invoke"]["description"].lower())

    def test_exec_opt_in_controls_listing(self):
        hidden = mcp.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                              {"allow_exec": False})
        self.assertEqual([t["name"] for t in hidden["result"]["tools"]],
                         ["omni_search", "omni_invoke"])
        shown = mcp.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                             {"allow_exec": True})
        self.assertEqual(len(shown["result"]["tools"]), 3)


class TestDispatch(_AuditIsolated):
    def test_initialize_shape(self):
        reply = mcp.dispatch({"jsonrpc": "2.0", "id": "a", "method": "initialize", "params": {}}, {})
        self.assertEqual(reply["id"], "a")
        result = reply["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(result["serverInfo"], {"name": "omnicli-mcp", "version": "1.0.0"})

    def test_ping(self):
        reply = mcp.dispatch({"jsonrpc": "2.0", "id": 2, "method": "ping"}, {})
        self.assertEqual(reply, {"jsonrpc": "2.0", "id": 2, "result": {}})

    def test_unknown_method_is_minus_32601(self):
        reply = mcp.dispatch({"jsonrpc": "2.0", "id": 3, "method": "nope"}, {})
        self.assertEqual(reply["error"]["code"], -32601)

    def test_unknown_tool_is_minus_32602(self):
        reply = mcp.dispatch({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                              "params": {"name": "nope", "arguments": {}}}, {})
        self.assertEqual(reply["error"]["code"], -32602)

    def test_notifications_and_responses_return_none(self):
        self.assertIsNone(mcp.dispatch(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, {}))
        self.assertIsNone(mcp.dispatch(
            {"jsonrpc": "2.0", "method": "notifications/anything", "params": {}}, {}))
        self.assertIsNone(mcp.dispatch(
            {"jsonrpc": "2.0", "id": 5, "result": {}}, {}))

    def test_invalid_request_validation(self):
        bad_version = mcp.dispatch({"jsonrpc": "1.0", "id": 6, "method": "ping"}, {})
        self.assertEqual(bad_version["error"]["code"], -32600)
        no_id = mcp.dispatch({"jsonrpc": "2.0", "method": "ping"}, {})
        self.assertEqual(no_id["error"]["code"], -32600)


class TestMetaTools(_AuditIsolated):
    def _call(self, name, arguments, ctx=None):
        return mcp.dispatch(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
             "params": {"name": name, "arguments": arguments}}, ctx or {})

    def test_search_runs_one_cli_subprocess_without_rerank(self):
        seen = {}

        def fake(argv, timeout):
            seen.update(argv=argv, timeout=timeout)
            return {"exit_code": 0, "stdout": '{"results":[]}', "stderr": ""}

        with mock.patch.object(mcp, "_run_cli", fake):
            reply = self._call("omni_search", {"query": "transcribe audio", "limit": 3})
        self.assertEqual(seen["argv"],
                         ["search", "transcribe audio", "--json", "--depth", "brief",
                          "--limit", "3", "--no-rerank"])
        self.assertEqual(reply["result"]["content"][0]["text"], '{"results":[]}')
        self.assertFalse(reply["result"]["isError"])

    def test_depth_contract_and_section_doc_passed_through(self):
        seen = {}

        def fake(argv, timeout):
            seen["argv"] = argv
            return {"exit_code": 0, "stdout": "{}", "stderr": ""}

        with mock.patch.object(mcp, "_run_cli", fake):
            self._call("omni_search", {"query": "cornell notes", "depth": "contract",
                                       "section": "token shield", "doc": "SKILL.md"})
        self.assertEqual(seen["argv"], ["search", "cornell notes", "--json",
                                        "--depth", "contract", "--limit", "5",
                                        "--no-rerank", "--section", "token shield",
                                        "--doc", "SKILL.md"])

    def test_invoke_argv_projections_and_double_dash(self):
        seen = {}

        def fake(argv, timeout):
            seen.update(argv=argv, timeout=timeout)
            return {"exit_code": 0, "stdout": "{}", "stderr": ""}

        with mock.patch.object(mcp, "_run_cli", fake):
            self._call("omni_invoke", {
                "tool_id": "foo/bar", "args": ["--x", "1"], "fields": ["a", "b"],
                "jq": ".c", "grep": "ERR", "timeout": 5, "max_bytes": 123,
            })
        self.assertEqual(seen["argv"], ["invoke", "foo/bar", "--omni-json",
                                        "--omni-max-bytes", "123", "--omni-project", "a,b",
                                        "--omni-jq", ".c", "--omni-grep", "ERR",
                                        "--", "--x", "1"])
        self.assertEqual(seen["timeout"], 5.0)

    def test_exec_runs_js_plan_when_enabled(self):
        seen = {}

        def fake(argv, timeout):
            seen.update(argv=argv, timeout=timeout)
            return {"exit_code": 0, "stdout": '{"plan":"<inline>","exit_code":0}', "stderr": ""}

        with mock.patch.object(mcp, "_run_cli", fake):
            reply = self._call("omni_exec", {"code": "console.log(1)", "sandbox": "strict",
                                             "max_calls": 7, "timeout": 8, "mem_limit": 256},
                               {"allow_exec": True})
        self.assertEqual(seen["argv"][:9], ["exec", "-c", "console.log(1)", "--sandbox",
                                            "strict", "--max-calls", "7", "--timeout", "8.0"])
        self.assertIn("--quiet", seen["argv"])
        self.assertIn("--json", seen["argv"])
        self.assertIn("--mem-limit", seen["argv"])
        self.assertEqual(seen["timeout"], 18.0)
        self.assertFalse(reply["result"]["isError"])

    def test_exec_hidden_without_opt_in_returns_tool_error(self):
        reply = self._call("omni_exec", {"script": "console.log(1)"}, {"allow_exec": False})
        result = reply["result"]
        self.assertTrue(result["isError"])
        self.assertIn("OMNICLI_MCP_ALLOW_EXEC", result["content"][0]["text"])

    def test_oversize_result_is_refused_not_truncated(self):
        def fake(argv, timeout):
            return {"exit_code": 0, "stdout": "X" * 9000, "stderr": ""}

        with mock.patch.object(mcp, "_run_cli", fake):
            reply = self._call("omni_search", {"query": "x", "max_bytes": 64})
        result = reply["result"]
        self.assertTrue(result["isError"])
        text = result["content"][0]["text"]
        self.assertLessEqual(len(text.encode("utf-8")), 64)
        self.assertIn("error", json.loads(text))
        self.assertNotIn("X" * 20, text)

    def test_nonzero_exit_is_error_without_raw_args(self):
        secret = "SECRET_ARG_9f3a71"

        def fake(argv, timeout):
            return {"exit_code": 1, "stdout": "", "stderr": "omnicli: tool is disabled"}

        with mock.patch.object(mcp, "_run_cli", fake):
            reply = self._call("omni_invoke", {"tool_id": "foo/bar", "args": ["--password", secret]})
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("disabled", reply["result"]["content"][0]["text"])
        self.assertNotIn(secret, json.dumps(reply))

    def test_audit_line_has_fields_and_no_args(self):
        def fake(argv, timeout):
            return {"exit_code": 0, "stdout": "{}", "stderr": ""}

        with mock.patch.object(mcp, "_run_cli", fake):
            self._call("omni_invoke", {"tool_id": "foo/bar", "args": ["--token", "secret"]})
        lines = (Path(self._tmp.name) / "mcp-audit.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        entry = json.loads(lines[-1])
        for field in ("ts", "transport", "tool", "target", "ok", "bytes", "remote"):
            self.assertIn(field, entry)
        self.assertEqual(entry["tool"], "omni_invoke")
        self.assertEqual(entry["target"], "foo/bar")
        self.assertEqual(entry["transport"], "stdio")
        self.assertIsNone(entry["remote"])
        self.assertNotIn("args", entry)
        self.assertNotIn("secret", json.dumps(entry))


class TestHTTP(_AuditIsolated):
    AUTH = {"Authorization": "Bearer test-token"}

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"OMNICLI_MCP_ORIGINS": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server, self.port, self.thread = _start_server()
        self.addCleanup(_stop_server, self.server, self.thread)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _headers(self, **extra):
        headers = dict(self.AUTH)
        headers.update(extra)
        return headers

    def _req(self, method, path, body=None, headers=None):
        return _request(self.opener, f"http://127.0.0.1:{self.port}{path}",
                        method=method, body=body, headers=headers)

    def _post(self, obj, headers=None, path="/mcp"):
        return self._req("POST", path, body=json.dumps(obj), headers=headers)

    def test_no_token_401(self):
        status, _, _ = self._post({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                  headers={"Content-Type": "application/json"})
        self.assertEqual(status, 401)

    def test_wrong_token_401(self):
        status, _, _ = self._post({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                  headers={"Authorization": "Bearer wrong"})
        self.assertEqual(status, 401)

    def test_foreign_origin_403(self):
        status, _, _ = self._post({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                  headers=self._headers(Origin="http://evil.example"))
        self.assertEqual(status, 403)

    def test_bad_protocol_version_400(self):
        status, _, _ = self._post({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                  headers=self._headers(**{"MCP-Protocol-Version": "1999-01-01"}))
        self.assertEqual(status, 400)

    def test_new_protocol_version_2026_accepted(self):
        status, body, _ = self._post(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers=self._headers(**{"MCP-Protocol-Version": "2026-07-28"}), path="/")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"]["protocolVersion"], "2025-06-18")

    def test_get_405(self):
        status, _, _ = self._req("GET", "/omni", headers=self.AUTH)
        self.assertEqual(status, 405)

    def test_post_notification_202(self):
        status, body, _ = self._post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                                     headers=self.AUTH)
        self.assertEqual(status, 202)
        self.assertEqual(body, b"")

    def test_initialize_sets_session_header(self):
        status, _, headers = self._post(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers=self.AUTH)
        self.assertEqual(status, 200)
        lowered = {k.lower(): v for k, v in headers.items()}
        sid = lowered.get("mcp-session-id", "")
        self.assertEqual(len(sid), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in sid))

    def test_health_returns_json(self):
        status, body, _ = self._req("GET", "/health", headers=self.AUTH)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "omnicli-mcp")
        self.assertEqual(payload["tools"], ["omni_search", "omni_invoke"])

    def test_health_requires_token(self):
        status, _, _ = self._req("GET", "/health")
        self.assertEqual(status, 401)

    def test_delete_204(self):
        status, _, _ = self._req("DELETE", "/", headers=self.AUTH)
        self.assertEqual(status, 204)

    def test_rate_limit_returns_429(self):
        server, port, thread = _start_server(limiter=mcp._RateLimiter(max_calls=2, window=60.0))
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            statuses = []
            for _ in range(3):
                status, _, _ = _request(
                    opener, f"http://127.0.0.1:{port}/", method="POST",
                    body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": "nope", "arguments": {}}}),
                    headers=self.AUTH)
                statuses.append(status)
            self.assertEqual(statuses, [200, 200, 429])
        finally:
            _stop_server(server, thread)


class TestStdio(unittest.TestCase):
    @staticmethod
    def _spawn():
        return subprocess.Popen([sys.executable, str(OMNICLI), "mcp"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1)

    @staticmethod
    def _read_lines(proc, count):
        lines = []
        for _ in range(count):
            ready, _, _ = select.select([proc.stdout], [], [], 30)
            assert ready, "no reply from stdio face"
            line = proc.stdout.readline()
            assert line, "empty reply line"
            assert line.count("\n") == 1, "more than one JSON object on a line"
            lines.append(json.loads(line))
        return lines

    def test_handshake_one_json_object_per_line(self):
        proc = self._spawn()
        try:
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ]
            proc.stdin.write("\n".join(json.dumps(m) for m in messages) + "\n")
            proc.stdin.flush()
            by_id = {reply["id"]: reply for reply in self._read_lines(proc, 2)}
            self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
            self.assertEqual([t["name"] for t in by_id[2]["result"]["tools"]],
                             ["omni_search", "omni_invoke"])
        finally:
            self._shutdown(proc)

    def test_live_search_depth_contract_smoke(self):
        """One real narrow query through the stdio handshake; output stays bounded."""
        proc = self._spawn()
        try:
            req = {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                   "params": {"name": "omni_search", "arguments": {
                       "query": "cornell notes", "depth": "contract", "limit": 3,
                       "max_bytes": 12000}}}
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            reply = self._read_lines(proc, 1)[0]
            result = reply["result"]
            self.assertFalse(result.get("isError"), result["content"][0]["text"][:300])
            text = result["content"][0]["text"]
            self.assertLessEqual(len(text.encode("utf-8")), 12000)
            contract = json.loads(text)
            self.assertTrue(contract.get("contract"), contract)
            self.assertIn("cornell", json.dumps(contract).lower())
        finally:
            self._shutdown(proc)

    @staticmethod
    def _shutdown(proc):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
            proc.wait(timeout=5)
        finally:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()


if __name__ == "__main__":
    unittest.main()
