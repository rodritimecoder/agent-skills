#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROUTER_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROUTER_DIR / "scripts"))
import router  # type: ignore

# 8100, deliberately outside the model slot range (8080-8088 in ports.json):
# this is a development router, not an inference slot. It sat on 8088, which
# is the DeskForge-Qwen3.5-4B GUI-grounding slot, so the two could not run
# together.
PORT = 8100

class EvalRouterHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/health", "/v1/health"):
            self._send_json(200, {"status": "pass", "service": "eval-router"})
        elif self.path in ("/v1/models", "/models"):
            self._send_json(200, {
                "object": "list",
                "data": [
                    {"id": "eval-router-auto", "object": "model", "owned_by": "glitchcatclub"},
                    {"id": "eval-router-easy", "object": "model", "owned_by": "glitchcatclub"},
                    {"id": "eval-router-moderate", "object": "model", "owned_by": "glitchcatclub"},
                    {"id": "eval-router-hard", "object": "model", "owned_by": "glitchcatclub"}
                ]
            })
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path in ("/v1/chat/completions", "/chat/completions"):
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8")
            try:
                body = json.loads(raw_body)
            except Exception:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            messages = body.get("messages", [])
            user_prompt = ""
            system_prompt = None
            for m in messages:
                if m.get("role") == "system":
                    system_prompt = m.get("content", "")
                elif m.get("role") == "user":
                    user_prompt = m.get("content", "")

            if not user_prompt:
                self._send_json(400, {"error": "No user message found"})
                return

            res = router.execute_request(user_prompt, mode="blocking", system_prompt=system_prompt)
            resp_payload = {
                "id": f"chatcmpl-evalrouter-{int(time.time()*1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": f"eval-router-{res['tier']}",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": res["content"]
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": max(1, len(user_prompt.split())),
                    "completion_tokens": max(1, len(res["content"].split())),
                    "total_tokens": max(1, len(user_prompt.split()) + len(res["content"].split()))
                },
                "eval_router_meta": {
                    "tier": res["tier"],
                    "model_used": res["model_used"],
                    "fallback_model": res["fallback_model"],
                    "latency_ms": res["latency_ms"],
                    "eval_passed": res["eval_passed"],
                    "cost_saved_usd": res["cost_saved_usd"]
                }
            }
            self._send_json(200, resp_payload)
        else:
            self._send_json(404, {"error": "Endpoint not found"})

def run_server(port: int = PORT, host: str = "127.0.0.1"):
    server = HTTPServer((host, port), EvalRouterHandler)
    print(f"[eval-router] Proxy running on http://{host}:{port} (OpenAI-compatible /v1/chat/completions)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[eval-router] Shutting down.")
        server.server_close()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=PORT, metavar="PORT")
    args = p.parse_args()
    run_server(args.port)
