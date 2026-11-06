#!/usr/bin/env python3
"""Minimal Chrome DevTools Protocol client over a hand-rolled WebSocket.

Stdlib only: no websockets / websocket-client / playwright-python. Chrome is
reached on the CDP HTTP endpoint, a page target is selected (created if none),
and frames are exchanged straight over the socket so protocol events survive
navigation.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import time
import urllib.error
import urllib.request


class CDPError(RuntimeError):
    pass


class CDPNotRunning(CDPError):
    pass


def _http_json(url: str, method: str = "GET", timeout: float = 5.0):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
    return json.loads(body) if body.strip() else {}


def list_targets(host: str = "127.0.0.1", port: int = 9222, timeout: float = 5.0):
    try:
        targets = _http_json(f"http://{host}:{port}/json/list", timeout=timeout)
    except (urllib.error.URLError, OSError) as exc:
        raise CDPNotRunning(
            f"no CDP endpoint on {host}:{port} ({exc}). "
            "Start one with `playwright-rs daemon start`."
        ) from exc
    return [t for t in targets if t.get("type") == "page"]


def new_target(host: str = "127.0.0.1", port: int = 9222, url: str = "about:blank"):
    return _http_json(f"http://{host}:{port}/json/new?{url}", method="PUT")


class CDP:
    def __init__(self, ws_url: str, timeout: float = 20.0):
        self.timeout = timeout
        self.events: list[dict] = []
        self._id = 0
        self._closed = False
        host, port, path = self._split(ws_url)
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._handshake(host, port, path)

    @staticmethod
    def _split(ws_url: str):
        if not ws_url.startswith("ws://"):
            raise CDPError(f"unsupported CDP url: {ws_url}")
        rest = ws_url[len("ws://"):]
        authority, _, path = rest.partition("/")
        host, _, port_s = authority.partition(":")
        return host, int(port_s or 80), "/" + path

    def _handshake(self, host: str, port: int, path: str) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(request.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise CDPError("CDP closed the socket during the WebSocket handshake")
            head += chunk
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if "101" not in status:
            raise CDPError(f"CDP refused the WebSocket upgrade: {status}")
        self._buf = head.split(b"\r\n\r\n", 1)[1]

    def _write_frame(self, payload: bytes, opcode: int = 0x1) -> None:
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + mask + masked)

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise CDPError("CDP closed the connection")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_frame(self) -> tuple[int, bytes]:
        while True:
            b1, b2 = self._read_exact(2)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length)
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise CDPError("CDP sent a close frame")
            if opcode == 0x9:
                self._write_frame(payload, opcode=0xA)
                continue
            if opcode == 0xA:
                continue
            return opcode, payload

    def _read_message(self) -> dict:
        opcode, payload = self._read_frame()
        while opcode == 0x0:
            _, more = self._read_frame()
            payload += more
        return json.loads(payload.decode("utf-8", "replace"))

    def send(self, method: str, params: dict | None = None, timeout: float | None = None):
        if self._closed:
            raise CDPError("CDP session is closed")
        self._id += 1
        msg_id = self._id
        self._sock.settimeout(timeout or self.timeout)
        self._write_frame(json.dumps({"id": msg_id, "method": method, "params": params or {}}).encode())
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            if time.monotonic() > deadline:
                raise CDPError(f"timed out waiting for {method}")
            message = self._read_message()
            if message.get("id") == msg_id:
                if "error" in message:
                    raise CDPError(f"{method}: {message['error'].get('message')}")
                return message.get("result", {})
            if "method" in message:
                self.events.append(message)

    def pump(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._sock.settimeout(remaining)
            try:
                message = self._read_message()
            except (socket.timeout, TimeoutError):
                return
            if "method" in message:
                self.events.append(message)

    def drain(self) -> list[dict]:
        out, self.events = self.events, []
        return out

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._write_frame(b"", opcode=0x8)
        except OSError:
            pass
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self) -> "CDP":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def connect(host: str = "127.0.0.1", port: int = 9222, prefer: str | None = None,
            timeout: float = 20.0) -> CDP:
    targets = list_targets(host, port)
    chosen = None
    if targets:
        if prefer:
            chosen = next((t for t in targets if t.get("url", "").startswith(prefer)), None)
        chosen = chosen or targets[-1]
    else:
        chosen = new_target(host, port)
    ws_url = chosen.get("webSocketDebuggerUrl")
    if not ws_url:
        raise CDPError(f"target has no webSocketDebuggerUrl: {chosen.get('url')}")
    return CDP(ws_url, timeout=timeout)
