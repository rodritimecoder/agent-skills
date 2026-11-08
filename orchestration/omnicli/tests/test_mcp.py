"""Conformance test for the omnicli MCP server (Face B).

Drives the server over real stdio with newline-delimited JSON-RPC, the way
an MCP client would. No mocking: if the transport or the framing is wrong,
this fails.

Usage:
    python3 tests/test_mcp.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent / "scripts" / "mcp_server.py"
SKILL_CLI = HERE.parent / "omnicli.py"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def search_available() -> bool:
    """Is the optional embedding re-ranker reachable?

    The rerank assertions only mean something when the endpoint answers; a
    skipped check is honest, a passing one against a dead port is not.
    """
    sys.path.insert(0, str(HERE.parent))
    from catalog import search

    return search.embedding_available()


class Client:
    """Minimal MCP client over stdio."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._id = 0

    def call(self, method: str, params: dict | None = None, expect_reply: bool = True):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if not expect_reply:
            return None
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed the stream")
        return json.loads(line)

    def notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    if not SERVER.is_file():
        print(f"❌ server not found at {SERVER}")
        return 1

    c = Client()
    results: list[bool] = []
    try:
        # 1. initialize
        r = c.call("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        })
        res = r.get("result", {})
        results.append(check("initialize returns protocolVersion",
                             res.get("protocolVersion") == "2025-06-18"))
        results.append(check("initialize advertises tools capability",
                             "tools" in res.get("capabilities", {})))
        results.append(check("initialize returns serverInfo",
                             res.get("serverInfo", {}).get("name") == "omnicli"))
        c.notify("notifications/initialized")

        # 2. tools/list — exactly four meta-tools
        r = c.call("tools/list")
        tools = r.get("result", {}).get("tools", [])
        names = sorted(t["name"] for t in tools)
        expected = sorted(["omni_discover", "omni_describe", "omni_invoke", "omni_status"])
        results.append(check("tools/list exposes exactly 4 meta-tools",
                             names == expected, ", ".join(names)))
        results.append(check("every tool has an inputSchema",
                             all("inputSchema" in t for t in tools)))
        total_desc = sum(len(t.get("description", "")) for t in tools)
        results.append(check("meta-tool descriptions are compact (< 1200 chars)",
                             total_desc < 1200, f"{total_desc} chars total"))

        # 3. omni_discover
        r = c.call("tools/call", {
            "name": "omni_discover",
            "arguments": {"intent": "transcribe a zoom lecture recording", "limit": 3},
        })
        payload = json.loads(r["result"]["content"][0]["text"])
        res_list = payload.get("results", [])
        top = res_list[0].get("skill") if res_list else None
        results.append(check("omni_discover routes to zoom-recorder or video-miner",
                             top in ("zoom-recorder", "video-miner"), f"got {top!r}"))
        results.append(check("omni_discover returns tool ids",
                             bool(res_list and res_list[0].get("tools"))))

        # 3b. the default reply is a routing view, not the chunk archive
        r = c.call("tools/call", {
            "name": "omni_discover",
            "arguments": {"intent": "transcribe a zoom lecture recording"},
        })
        size = len(r["result"]["content"][0]["text"].encode())
        results.append(check("omni_discover default reply is compact (< 4000 bytes)",
                             size < 4000, f"{size} bytes"))

        # 3c. rerank is honoured (it used to be swallowed by `not no_rerank`)
        if search_available():
            never = json.loads(c.call("tools/call", {
                "name": "omni_discover",
                "arguments": {"intent": "transcribe a zoom lecture", "rerank": "never"},
            })["result"]["content"][0]["text"])
            always = json.loads(c.call("tools/call", {
                "name": "omni_discover",
                "arguments": {"intent": "transcribe a zoom lecture", "rerank": "always"},
            })["result"]["content"][0]["text"])
            results.append(check("omni_discover rerank=never stays lexical",
                                 never.get("tier", "").startswith("bm25")
                                 and "rerank" not in never.get("tier", ""),
                                 never.get("tier", "")))
            results.append(check("omni_discover rerank=always reaches the re-ranker",
                                 "rerank" in always.get("tier", ""),
                                 always.get("tier", "")))

        # 4. omni_describe — one contract, no schemas for everything
        r = c.call("tools/call", {
            "name": "omni_discover",
            "arguments": {"intent": "read text out of a screenshot", "limit": 1},
        })
        payload = json.loads(r["result"]["content"][0]["text"])
        tool_id = payload["results"][0]["tools"][0]
        r = c.call("tools/call", {"name": "omni_describe", "arguments": {"tool_id": tool_id}})
        desc = json.loads(r["result"]["content"][0]["text"])
        results.append(check("omni_describe returns a contract for exactly one tool",
                             desc.get("id") == tool_id))
        results.append(check("omni_describe includes the invocation contract",
                             "contract" in desc and "argv" in desc))
        results.append(check("omni_describe reports the enable state",
                             isinstance(desc.get("enabled"), bool)))

        # 4b. stub mode: many signatures, still one bounded reply
        r = c.call("tools/call", {
            "name": "omni_describe",
            "arguments": {"tool_id": "*", "stub": True, "grep": "zoom", "max_bytes": 6000},
        })
        stubs = json.loads(r["result"]["content"][0]["text"])
        matched_stubs = stubs.get("matched", 0) >= 1 and "zoom(url: str" in stubs.get("signatures", "")
        results.append(check("omni_describe stub mode returns annotated signatures",
                             matched_stubs,
                             f"{stubs.get('matched', 0)} matched"))
        results.append(check("omni_describe stub mode stays bounded",
                             len(r["result"]["content"][0]["text"].encode()) <= 6000))

        # 5. omni_invoke — bounded output
        r = c.call("tools/call", {
            "name": "omni_invoke",
            "arguments": {"tool_id": "local/decide", "args": ["--help"], "max_bytes": 2000},
        })
        out = json.loads(r["result"]["content"][0]["text"])
        results.append(check("omni_invoke executes and returns output",
                             bool(out.get("output")) and out.get("exit_code") == 0))
        results.append(check("omni_invoke respects max_bytes",
                             len(r["result"]["content"][0]["text"].encode()) <= 2000,
                             f"{len(r['result']['content'][0]['text'].encode())} bytes"))

        # 5b. small caps are a budget to fill, not a banner
        for cap in (250, 400, 8000):
            r = c.call("tools/call", {
                "name": "omni_invoke",
                "arguments": {"tool_id": "local/decide", "args": ["--help"],
                              "max_bytes": cap},
            })
            text = r["result"]["content"][0]["text"]
            body = json.loads(text)
            size = len(text.encode())
            results.append(check(f"omni_invoke cap {cap} is exact and non-empty",
                                 size <= cap and len(body.get("output", "")) > 20,
                                 f"{size} bytes, output {len(body.get('output', ''))}"))

        # 5c. an unappliable projection says so instead of silently ignoring it
        r = c.call("tools/call", {
            "name": "omni_invoke",
            "arguments": {"tool_id": "local/decide", "args": ["--help"],
                          "projection": ["contract.flags"]},
        })
        body = json.loads(r["result"]["content"][0]["text"])
        results.append(check("omni_invoke warns when projection cannot apply",
                             body.get("projection_applied") is False
                             and "projection_warning" in body))

        # 5d. discovery does not imply exposure
        disable = subprocess.run([sys.executable, str(SKILL_CLI), "disable", "local/decide"],
                                 capture_output=True, text=True)
        try:
            r = c.call("tools/call", {"name": "omni_invoke",
                                      "arguments": {"tool_id": "local/decide",
                                                    "args": ["--help"]}})
            body = json.loads(r["result"]["content"][0]["text"])
            results.append(check("omni_invoke refuses a disabled tool",
                                 body.get("error") == "tool is disabled",
                                 str(body.get("error"))))
        finally:
            subprocess.run([sys.executable, str(SKILL_CLI), "enable", "local/decide"],
                           capture_output=True, text=True)

        # 6. omni_status
        r = c.call("tools/call", {"name": "omni_status", "arguments": {}})
        st = json.loads(r["result"]["content"][0]["text"])
        results.append(check("omni_status reports the retrieval tier",
                             st.get("retrieval_tier", "").startswith("bm25"),
                             st.get("retrieval_tier", "")))
        results.append(check("omni_status reports catalog freshness",
                             st.get("catalog", {}).get("skills", 0) > 0))
        results.append(check("omni_status reports the enable gate",
                             st.get("catalog", {}).get("tools_enabled", 0) > 0,
                             f"{st.get('catalog', {}).get('tools_enabled')} enabled"))
        services = st.get("services", [])
        ports = {s.get("port") for s in services}
        results.append(check("omni_status uses the shared health probe "
                             "(all services, with a tri-state)",
                             {8084, 8086, 9222}.issubset(ports)
                             and all(s.get("status") in ("ONLINE", "DEGRADED", "OFFLINE")
                                     for s in services),
                             f"{len(services)} services"))

        # 7. error handling
        r = c.call("tools/call", {"name": "omni_invoke",
                                  "arguments": {"tool_id": "does/not/exist"}})
        results.append(check("unknown tool id returns a tool error (not a crash)",
                             r.get("result", {}).get("isError") is True))
        r = c.call("nonexistent/method")
        results.append(check("unknown method returns a JSON-RPC error",
                             "error" in r))

        # 8. ping
        r = c.call("ping")
        results.append(check("ping is answered", "result" in r))

    finally:
        c.close()

    passed = sum(1 for x in results if x)
    print(f"\n  {passed}/{len(results)} MCP conformance checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
