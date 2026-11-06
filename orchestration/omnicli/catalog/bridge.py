"""Capability bridge for strict-mode plans.

A strict plan runs with no network and with the home directory masked. It can
still do real work because every tool call crosses one UNIX socket into the
parent process, which owns the credentials and holds the enable gate. The
sandbox never sees a token, and it cannot open a socket to anything except
this bridge.

The protocol is one newline-terminated JSON request per connection, answered
with one newline-terminated JSON reply. Keeping it line-oriented means a
partial read is a protocol error rather than a silently truncated payload.
"""

from __future__ import annotations

import json
import os
import socket
import socketserver
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

ALLOWED = {"search", "list", "tools", "describe", "invoke", "policy", "spec"}
MAX_REQUEST = 1 << 20
MAX_REPLY = 8 << 20
SHIM = '''#!/usr/bin/env python3
import json
import os
import socket
import sys

sock = os.environ.get("OMNICLI_BRIDGE")
if not sock:
    sys.stderr.write("omnicli: no bridge in this sandbox\\n")
    raise SystemExit(97)
request = json.dumps({"argv": sys.argv[1:]}).encode() + b"\\n"
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.settimeout(float(os.environ.get("OMNICLI_BRIDGE_TIMEOUT", "600")))
client.connect(sock)
client.sendall(request)
buffer = b""
while not buffer.endswith(b"\\n"):
    chunk = client.recv(1 << 16)
    if not chunk:
        break
    buffer += chunk
if not buffer.strip():
    sys.stderr.write("omnicli: empty bridge reply\\n")
    raise SystemExit(98)
reply = json.loads(buffer.decode())
sys.stdout.write(reply.get("stdout", ""))
sys.stderr.write(reply.get("stderr", ""))
raise SystemExit(int(reply.get("returncode", 1)))
'''


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(MAX_REQUEST)
        if not raw.strip():
            return
        try:
            payload = json.loads(raw.decode())
            argv = [str(a) for a in payload.get("argv") or []]
        except (ValueError, AttributeError):
            return
        reply = self.server.dispatch(argv)  # type: ignore[attr-defined]
        body = json.dumps(reply, ensure_ascii=False).encode()[:MAX_REPLY]
        self.wfile.write(body + b"\n")


class Bridge(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, path: str, cli: Path, timeout: float):
        super().__init__(path, _Handler)
        self.cli = cli
        self.timeout_seconds = timeout
        self.calls = 0
        self.denied: list[str] = []

    def dispatch(self, argv: list[str]) -> dict[str, Any]:
        verb = argv[0] if argv else ""
        if verb not in ALLOWED:
            self.denied.append(verb or "<empty>")
            return {"stdout": "", "stderr": f"omnicli: {verb or 'that'} is not reachable from a strict plan\n",
                    "returncode": 126}
        self.calls += 1
        try:
            proc = subprocess.run(
                [sys.executable, str(self.cli), *argv],
                capture_output=True, text=True, timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "omnicli: bridge call timed out\n", "returncode": 124}
        return {"stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}


def write_shim(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    shim = directory / "omnicli"
    shim.write_text(SHIM, encoding="utf-8")
    shim.chmod(0o755)
    return shim


class Serving:
    """Context manager: start the bridge on a socket and tear it down."""

    def __init__(self, path: Path, cli: Path, timeout: float):
        self.path = path
        self.cli = cli
        self.timeout = timeout
        self.server: Bridge | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> Bridge:
        if self.path.exists():
            self.path.unlink()
        self.server = Bridge(str(self.path), self.cli, self.timeout)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.server

    def __exit__(self, *exc: object) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.path.exists():
            os.unlink(self.path)


def reachable(sock_path: str) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(sock_path)
        return True
    except OSError:
        return False
    finally:
        probe.close()
