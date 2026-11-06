"""Service health for the workstation, shared by both faces.

The MCP face used to carry its own probe: a hardcoded tailnet address and a
bare TCP connect. That reported a service as online whenever a socket
accepted — including on ports where `tailscale serve` owns the listener, so
a dead backend behind a live proxy looked healthy. The CLI already had the
right rule ("HTTP on loopback is authoritative; TCP alone is never proof of
health"), and the two faces disagreed.

There is now one implementation, and it is this one.
"""

from __future__ import annotations

import concurrent.futures as futures
import json
import re
import socket
import subprocess
import urllib.error
import urllib.request

SERVICES = [
    {"port": 8000, "name": "llama-swap Controller", "role": "Model hot-swapper", "probe": "/v1/models"},
    {"port": 8080, "name": "Genesis 35B Primary LLM", "role": "Dual-GPU flagship coder", "probe": "/health"},
    {"port": 8081, "name": "audio.cpp ASR & TTS", "role": "Streaming speech-to-text / TTS", "probe": "/health"},
    {"port": 8083, "name": "Decision Gating", "role": "Premier calibrated decisions (protocol auto-detected)", "probe": "/health"},
    {"port": 8084, "name": "CrispEmbed Scene-Text OCR", "role": "Ultra-fast text detection", "probe": "/health"},
    {"port": 8085, "name": "LightOnOCR Flagship OCR", "role": "Document and slide OCR", "probe": "/health"},
    {"port": 8086, "name": "Jina Reranker", "role": "Cross-encoder reranking for RAG", "probe": "/health"},
    {"port": 8087, "name": "Embedding Server (BGE / EmbeddingGemma)", "role": "Optional re-ranker for catalog search", "probe": "/health"},
    {"port": 8089, "name": "Decision Fallback (Imajev-4B)", "role": "Second opinion / A-B against :8083", "probe": "/health"},
    {"port": 9222, "name": "Chromium CDP DevTools", "role": "Direct WebSocket/CDP browser control", "probe": "/json/version"},
]


def tailscale_address() -> str | None:
    try:
        proc = subprocess.run(["tailscale", "status", "--json"],
                              capture_output=True, text=True, timeout=6)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            ips = data.get("Self", {}).get("TailscaleIPs", [])
            if ips:
                return ips[0]
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def http_status(port: int, path: str, host: str = "127.0.0.1",
                timeout: float = 0.8) -> int | None:
    try:
        request = urllib.request.Request(f"http://{host}:{port}{path}", method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


def proxied_ports() -> set[int]:
    """Ports where `tailscale serve` owns the tailnet listener."""
    try:
        proc = subprocess.run(["tailscale", "serve", "status"],
                              capture_output=True, text=True, timeout=6)
        if proc.returncode != 0:
            return set()
        return {int(port) for port in
                re.findall(r"^https://\S+:(\d+) \(", proc.stdout, re.MULTILINE)}
    except (OSError, ValueError, subprocess.SubprocessError):
        return set()


def service_state(service: dict, ts_addr: str | None, proxied: set[int]) -> str:
    """ONLINE (2xx), DEGRADED (process reachable, not healthy), OFFLINE."""
    port = service["port"]
    code = http_status(port, service.get("probe", "/health"))
    if code is not None:
        return "ONLINE" if 200 <= code < 300 else "DEGRADED"
    if port_open(port):
        return "DEGRADED"
    if ts_addr and port not in proxied and port_open(port, ts_addr):
        return "ONLINE"
    return "OFFLINE"


def probe_all() -> dict:
    ts_addr = tailscale_address()
    proxied = proxied_ports()
    with futures.ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
        states = list(pool.map(lambda s: service_state(s, ts_addr, proxied), SERVICES))
    results = []
    for service, state in zip(SERVICES, states):
        results.append({
            "service": service["name"],
            "port": service["port"],
            "status": state,
            "local_url": f"http://127.0.0.1:{service['port']}",
            "tailnet_url": f"http://{ts_addr}:{service['port']}" if ts_addr else "",
            "role": service["role"],
        })
    return {"tailscale_address": ts_addr, "services": results}
