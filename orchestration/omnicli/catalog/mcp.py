"""Single-tool MCP face for the omnicli catalog.

One core, two transports: newline-delimited JSON-RPC on stdio for local
harnesses, and Streamable HTTP (2025-06-18) on loopback for remote clients.
Both speak the same JSON-RPC dispatcher and run the *same* CLI in a subprocess
for every tool call — no second implementation of discovery or invocation.

The surface mirrors omnicli's native one-tool shape: ``omni_exec`` is the only
tool a JSON-RPC client sees, and it is listed by default. The retired search
and invoke tools are gone from this face; their work happens as inner calls
inside a plan, where the CLI still enforces the ``omnicli enable`` gate.
Listing is not authorization: actually running ``omni_exec`` still needs
``OMNICLI_MCP_ALLOW_EXEC=1`` (``--no-exec`` is an extra kill switch).

Stdlib only. No MCP SDK is installed, and the subset needed here is small.
"""

from __future__ import annotations

import collections
import hmac
import http.server
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
OMNICLI_PATH = SKILL_DIR / "omnicli.py"
sys.path.insert(0, str(SKILL_DIR))

from catalog import builder, invoke  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "omnicli-mcp"
SERVER_VERSION = "1.0.0"
DEFAULT_PORT = 8790
DEFAULT_HOST = "127.0.0.1"

# Clients new and old send these; the server still negotiates 2025-06-18.
ACCEPTED_PROTOCOL_VERSIONS = frozenset({
    "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28",
})
MAX_BODY_BYTES = 1024 * 1024
RATE_MAX_CALLS = 60
RATE_WINDOW_SECONDS = 60.0
STDIO_WORKERS = 4
DEFAULT_SUBPROCESS_TIMEOUT = 60.0
AUDIT_FILENAME = "mcp-audit.jsonl"


# --------------------------------------------------------------------------
# tool definitions
# --------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "omni_exec",
        "title": "Run one JavaScript plan (Code Mode)",
        "description": (
            "Run one JavaScript plan that can search, spec, describe, invoke "
            "and emit one bounded result — intermediate payloads stay out of "
            "context. Sandbox defaults to `strict`. Listed by default; calling "
            "it still needs OMNICLI_MCP_ALLOW_EXEC=1 (--no-exec is a kill switch)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "Inline JavaScript plan (alias: code)."},
                "code": {"type": "string", "description": "Alias for script."},
                "sandbox": {"type": "string", "enum": ["strict", "write", "none"],
                            "default": "strict"},
                "max_calls": {"type": "integer", "default": 100},
                "mem_limit": {"type": "integer", "description": "JS heap cap in MiB."},
                "timeout": {"type": "number", "default": 300},
                "max_bytes": {"type": "integer", "minimum": 64, "maximum": 10000000,
                              "default": 16000},
            },
            "additionalProperties": False,
        },
    },
]

HANDLERS: dict[str, Any] = {}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _text_result(text: str, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _error_result(message: str) -> dict[str, Any]:
    return _text_result(message, is_error=True)


def respond(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def respond_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _int_arg(args: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(args.get(key) if args.get(key) is not None else default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _number_arg(args: dict[str, Any], key: str, default: float, low: float, high: float) -> float:
    try:
        value = float(args.get(key) if args.get(key) is not None else default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _run_cli(argv: list[Any], timeout: float) -> dict[str, Any]:
    """The one subprocess path. The exec meta-tool goes through here."""
    cmd = [sys.executable, str(OMNICLI_PATH)] + [str(a) for a in argv]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"exit_code": proc.returncode, "stdout": proc.stdout or "",
                "stderr": proc.stderr or "", "timed_out": False}
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "stdout": "",
                "stderr": f"omnicli: tool timed out after {timeout:g}s", "timed_out": True}
    except OSError as exc:
        return {"exit_code": 127, "stdout": "",
                "stderr": f"omnicli: failed to execute: {exc}", "timed_out": False}


def _shape_output(out: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Bound the reply. Oversize stdout is refused, never truncated JSON."""
    if int(out.get("exit_code", 0) or 0) != 0:
        stderr = str(out.get("stderr") or "").strip()
        if not stderr:
            stderr = f"omnicli exited with status {out.get('exit_code')}"
        capped, _, _ = invoke.cap(stderr, max_bytes)
        return _error_result(capped)
    stdout = str(out.get("stdout") or "")
    size = len(stdout.encode("utf-8", errors="replace"))
    if size > max_bytes:
        return _error_result(invoke.refusal(size, max_bytes))
    return _text_result(stdout.rstrip("\n"))


def _call_and_shape(argv: list[Any], max_bytes: int,
                    timeout: float = DEFAULT_SUBPROCESS_TIMEOUT) -> dict[str, Any]:
    return _shape_output(_run_cli(argv, timeout), max_bytes)


def _result_size(result: dict[str, Any]) -> int:
    text = "".join(c.get("text", "") for c in result.get("content", [])
                   if c.get("type") == "text")
    return len(text.encode("utf-8", errors="replace"))


def _audit(ctx: dict[str, Any], tool: str | None, target: str | None,
           ok: bool, size: int) -> None:
    """One line per tools/call. Never log arguments or tokens."""
    try:
        try:
            directory = builder.db_path().parent
        except Exception:  # pragma: no cover - fallback to the documented home
            directory = Path.home() / ".local" / "share" / "omnicli"
        directory.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "transport": ctx.get("transport", "stdio"),
            "tool": tool,
            "target": target or None,
            "ok": bool(ok),
            "bytes": int(size),
            "remote": ctx.get("remote"),
        }
        with open(directory / AUDIT_FILENAME, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover - telemetry must never break a call
        pass


# --------------------------------------------------------------------------
# meta-tool implementations
# --------------------------------------------------------------------------

def tool_exec(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    if not ctx.get("allow_exec", False):
        return _error_result(
            'omni_exec is disabled. Set OMNICLI_MCP_ALLOW_EXEC=1 to enable '
            'Code Mode on this MCP face (--no-exec is an extra kill switch).')
    code = str(args.get("script") or args.get("code") or "").strip()
    if not code:
        return _error_result('{"error": "script is required"}')
    max_bytes = _int_arg(args, "max_bytes", 16000, 64, 10000000)
    timeout = _number_arg(args, "timeout", 300.0, 1.0, 3600.0)
    max_calls = _int_arg(args, "max_calls", 100, 0, 100000)
    sandbox = str(args.get("sandbox") or "strict")
    if sandbox not in ("strict", "write", "none"):
        sandbox = "strict"
    # Inline JS goes via -c/--code; --quiet --json gives one clean JSON object.
    # `exec` has no --omni-max-bytes, so the ceiling is enforced by _shape_output.
    argv: list[Any] = ["exec", "-c", code, "--sandbox", sandbox,
                       "--max-calls", str(max_calls), "--timeout", str(timeout),
                       "--quiet", "--json"]
    if args.get("mem_limit") is not None:
        argv += ["--mem-limit", str(_int_arg(args, "mem_limit", 0, 64, 1000000))]
    return _call_and_shape(argv, max_bytes, timeout=timeout + 10.0)


HANDLERS.update({
    "omni_exec": tool_exec,
})


# --------------------------------------------------------------------------
# JSON-RPC dispatcher
# --------------------------------------------------------------------------

def _visible_tools(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    # The one-tool surface is permanent: `omni_exec` is always listed.
    # allow_exec gates execution (tool_exec / dispatch), never visibility.
    return list(TOOLS)


def _call_target(name: Any, arguments: dict[str, Any]) -> str | None:
    # No tool on this face exposes a callable target; kept for the audit shape.
    return None


def dispatch(request: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC message. Return None when no reply is due."""
    method = request.get("method")
    msg_id = request.get("id")
    params = request.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    # Responses and notifications never get a reply.
    if method is None:
        return None
    if method.startswith("notifications/") or method == "initialized":
        return None

    if request.get("jsonrpc") != "2.0":
        return respond_error(msg_id, -32600, "Invalid Request: jsonrpc must be '2.0'")
    if msg_id is None:
        return respond_error(msg_id, -32600, "Invalid Request: non-null id required")

    if method == "initialize":
        return respond(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method == "ping":
        return respond(msg_id, {})
    if method == "tools/list":
        return respond(msg_id, {"tools": _visible_tools(ctx)})
    if method == "shutdown":
        return respond(msg_id, {})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        target = _call_target(name, arguments)
        if name == "omni_exec" and not ctx.get("allow_exec", False):
            result = tool_exec(arguments, ctx)
            _audit(ctx, name, target, False, _result_size(result))
            return respond(msg_id, result)
        handler = HANDLERS.get(name)
        if handler is None or not isinstance(name, str):
            _audit(ctx, name if isinstance(name, str) else None, target, False, 0)
            return respond_error(msg_id, -32602, f"Unknown tool: {name}")
        try:
            result = handler(arguments, ctx)
        except Exception:  # never leak raw args into an error payload
            result = _error_result("omnicli: internal error in meta-tool")
        _audit(ctx, name, target, not result.get("isError", False), _result_size(result))
        return respond(msg_id, result)

    return respond_error(msg_id, -32601, f"Method not found: {method}")


# --------------------------------------------------------------------------
# stdio transport
# --------------------------------------------------------------------------

def serve_stdio(ctx: dict[str, Any], max_workers: int = STDIO_WORKERS) -> None:
    """NDJSON in, NDJSON out. A bounded worker pool keeps a slow tool from
    stalling ping; stdout is serialised under one lock and never carries logs.
    """
    pending: collections.deque[dict[str, Any]] = collections.deque()
    cond = threading.Condition()
    stopped = False
    out_lock = threading.Lock()

    def emit(reply: dict[str, Any] | None) -> None:
        if reply is None:
            return
        data = json.dumps(reply, ensure_ascii=False) + "\n"
        with out_lock:
            sys.stdout.write(data)
            sys.stdout.flush()

    def worker() -> None:
        nonlocal stopped
        while True:
            with cond:
                while not pending and not stopped:
                    cond.wait()
                if stopped and not pending:
                    return
                req = pending.popleft()
            local_ctx = dict(ctx, transport="stdio", remote=None)
            try:
                emit(dispatch(req, local_ctx))
            except Exception:
                emit(respond_error(req.get("id"), -32603, "internal error"))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max_workers)]
    for thread in threads:
        thread.start()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                emit(respond_error(None, -32700, "Parse error"))
                continue
            if not isinstance(req, dict):
                emit(respond_error(None, -32600, "Invalid Request"))
                continue
            with cond:
                pending.append(req)
                cond.notify()
    finally:
        with cond:
            stopped = True
            cond.notify_all()
        for thread in threads:
            thread.join()


# --------------------------------------------------------------------------
# HTTP transport (Streamable HTTP, no SSE / resumability / session state)
# --------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self, max_calls: int = RATE_MAX_CALLS, window: float = RATE_WINDOW_SECONDS):
        self.max_calls = max_calls
        self.window = window
        self._hits: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._hits and self._hits[0] <= now - self.window:
                self._hits.popleft()
            if len(self._hits) >= self.max_calls:
                return False
            self._hits.append(now)
            return True


class _MCPHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # never write logs to stdout; keep the bridge quiet on stderr too

    # -- primitives ---------------------------------------------------
    def _send(self, status: int, body: bytes = b"", content_type: str | None = None,
              headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.close_connection = True
        if body:
            self.wfile.write(body)

    def _json(self, status: int, obj: Any, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json", headers)

    def _reject(self, status: int, message: str) -> bool:
        self._send(status, message.encode("utf-8"), "text/plain")
        return False

    # -- guards -------------------------------------------------------
    def _auth_ok(self) -> bool:
        given = self.headers.get("Authorization", "")
        expected = "Bearer " + self.server.mcp_token  # type: ignore[attr-defined]
        return hmac.compare_digest(given, expected)

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        origin_name = (urllib.parse.urlsplit(origin).hostname or "").lower()
        host_name = (urllib.parse.urlsplit("//" + self.headers.get("Host", "")).hostname or "").lower()
        if origin_name and origin_name == host_name:
            return True
        raw = os.environ.get("OMNICLI_MCP_ORIGINS", "")
        allowed = {entry.strip().lower() for entry in raw.split(",") if entry.strip()}
        allowed_names = {
            (urllib.parse.urlsplit(entry if "://" in entry else "//" + entry).hostname or "").lower()
            for entry in allowed
        }
        return bool(origin_name) and origin_name in allowed_names

    def _protocol_ok(self) -> bool:
        version = self.headers.get("MCP-Protocol-Version")
        return version is None or version in ACCEPTED_PROTOCOL_VERSIONS

    def _guard(self) -> bool:
        if not self._auth_ok():
            return self._reject(401, "Unauthorized")
        if not self._origin_ok():
            return self._reject(403, "Forbidden: disallowed Origin")
        if not self._protocol_ok():
            return self._reject(400, "Bad Request: unsupported MCP-Protocol-Version")
        if urllib.parse.urlsplit(self.path).path not in ("/", "/mcp", "/omni", "/health"):
            return self._reject(404, "Not Found")
        return True

    # -- methods ------------------------------------------------------
    def do_POST(self) -> None:
        if not self._guard():
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            self._send(413, b"Request body too large", "text/plain")
            return
        raw = self.rfile.read(length) if length else b""
        try:
            req = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._json(200, respond_error(None, -32700, "Parse error"))
            return
        if not isinstance(req, dict):
            self._json(200, respond_error(None, -32600, "Invalid Request"))
            return
        if req.get("method") == "tools/call" and not self.server.mcp_rate.allow():  # type: ignore[attr-defined]
            self._send(429, b"Too Many Requests", "text/plain")
            return
        ctx = dict(self.server.mcp_ctx, transport="http",  # type: ignore[attr-defined]
                   remote=self.headers.get("Host"))
        try:
            reply = dispatch(req, ctx)
        except Exception:
            reply = respond_error(req.get("id"), -32603, "internal error")
        if reply is None:
            self._send(202)
            return
        headers = {}
        if req.get("method") == "initialize":
            headers["Mcp-Session-Id"] = secrets.token_hex(16)  # uuid4-hex shape
        self._json(200, reply, headers)

    def do_GET(self) -> None:
        if not self._guard():
            return
        if urllib.parse.urlsplit(self.path).path == "/health":
            tools = [t["name"] for t in _visible_tools(self.server.mcp_ctx)]  # type: ignore[attr-defined]
            self._json(200, {"ok": True, "service": SERVER_NAME, "tools": tools})
            return
        self._send(405, b"Method Not Allowed", "text/plain")

    def do_DELETE(self) -> None:
        if self._guard():
            self._send(204)


class _MCPHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], token: str,
                 ctx: dict[str, Any], rate: _RateLimiter):
        self.mcp_token = token
        self.mcp_ctx = ctx
        self.mcp_rate = rate
        super().__init__(address, _MCPHandler)


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                token: str = "", ctx: dict[str, Any] | None = None) -> _MCPHTTPServer:
    """Build a server without starting it (tests use port 0)."""
    if not token:
        raise ValueError("OMNICLI_MCP_TOKEN must not be empty")
    return _MCPHTTPServer((host, port), token, dict(ctx or {}), _RateLimiter())


def serve_http(host: str, port: int, token: str, ctx: dict[str, Any]) -> None:
    server = make_server(host, port, token, ctx)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

class _Options:
    def __init__(self, http: bool = False, port: int = DEFAULT_PORT,
                 host: str = DEFAULT_HOST, no_exec: bool = False):
        self.http = http
        self.port = port
        self.host = host
        self.no_exec = no_exec


def _coerce_args(argv_or_args: Any) -> Any:
    if argv_or_args is None:
        return _Options()
    if isinstance(argv_or_args, (list, tuple)):
        opts = _Options()
        tokens = iter(str(a) for a in argv_or_args)
        for token in tokens:
            if token == "--http":
                opts.http = True
            elif token == "--no-exec":
                opts.no_exec = True
            elif token == "--port":
                opts.port = int(next(tokens))
            elif token.startswith("--port="):
                opts.port = int(token.split("=", 1)[1])
            elif token == "--host":
                opts.host = next(tokens)
            elif token.startswith("--host="):
                opts.host = token.split("=", 1)[1]
        return opts
    return argv_or_args  # argparse.Namespace from the CLI verb


def _env_exec_opt_in() -> bool:
    return os.environ.get("OMNICLI_MCP_ALLOW_EXEC", "").strip().lower() in ("1", "true", "yes")


def main(argv_or_args: Any = None) -> int:
    ns = _coerce_args(argv_or_args)
    ctx: dict[str, Any] = {
        "transport": "stdio",
        "allow_exec": _env_exec_opt_in() and not getattr(ns, "no_exec", False),
        "remote": None,
    }
    if getattr(ns, "http", False):
        token = os.environ.get("OMNICLI_MCP_TOKEN", "").strip()
        if not token:
            print("omnicli mcp: refusing HTTP transport — OMNICLI_MCP_TOKEN is "
                  "unset or empty. Set a secret before exposing the bridge.",
                  file=sys.stderr)
            raise SystemExit(2)  # deliberate negative-control gate
        serve_http(getattr(ns, "host", DEFAULT_HOST), int(getattr(ns, "port", DEFAULT_PORT)),
                   token, ctx)
    else:
        serve_stdio(ctx)
    return 0
