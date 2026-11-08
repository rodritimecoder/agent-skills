#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

HUB = Path(os.environ.get("DECK_HUB", Path.home() / "src/my-agent-skills"))
VAULT = Path(os.environ.get("DECK_VAULT", "/run/media/rodri/AI/creator-vault"))
REPO = os.environ.get("DECK_REPO", "rodritimecoder/my-agent-skills")
ASSETS = Path(__file__).resolve().parent.parent / "assets"

SERVICES_FALLBACK: Tuple[Tuple[int, str, str], ...] = (
    (8080, "llm", "Qwen3.6 35B"),
    (8081, "audio", "Nemotron · Kokoro"),
    (8083, "decision", "TypeSafe view"),
    (8084, "ocr", "CrispEmbed"),
    (8085, "ocr", "LightOnOCR"),
    (8086, "rerank", "jina-reranker v2"),
    (8087, "embed", "bge-small"),
)


def load_services(hub: Path) -> Tuple[Tuple[int, str, str], ...]:
    """The manifest owns the port list; this page only renders it.

    Hardcoding ports here is how a retired slot keeps showing up as "down" and
    a new one stays invisible. Resolving the default candidate's model name
    keeps the label honest too.
    """
    try:
        data = json.loads((hub / "ports.json").read_text())
    except Exception:
        return SERVICES_FALLBACK
    rows = []
    for slot in data.get("slots") or []:
        port, default = slot.get("port"), slot.get("default")
        if not isinstance(port, int):
            continue
        name = next(
            (
                c.get("model")
                for c in slot.get("candidates") or []
                if Path(str(c.get("launcher", ""))).name == default
            ),
            None,
        )
        label = name or slot.get("service") or slot.get("id") or ""
        rows.append((port, str(slot.get("kind") or ""), str(label)[:30]))
    rows.sort()
    return tuple(rows) or SERVICES_FALLBACK


SERVICES: Tuple[Tuple[int, str, str], ...] = load_services(HUB)

GIB = 1024 ** 3
Source = Tuple[str, Optional[Dict[str, Any]], Optional[str]]


def augment_path() -> str:
    """systemd starts us with a minimal PATH; the tools live in ~/.local/bin and nvm."""
    extras = [Path.home() / ".local/bin"]
    nvm = Path.home() / ".nvm/versions/node"
    if nvm.is_dir():
        extras.extend(
            node / "bin" for node in sorted(nvm.iterdir(), reverse=True) if (node / "bin").is_dir()
        )
    current = os.environ.get("PATH", "")
    parts = [str(p) for p in extras if p.is_dir()]
    if current:
        parts.append(current)
    seen: List[str] = []
    for chunk in os.pathsep.join(parts).split(os.pathsep):
        if chunk and chunk not in seen:
            seen.append(chunk)
    return os.pathsep.join(seen)


def sh(cmd: List[str], timeout: float = 12.0) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]}: timeout after {timeout}s"


def _json(text: str) -> Any:
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i != -1), default=-1
    )
    if start == -1:
        return None
    stop = max(text.rfind("}"), text.rfind("]"))
    if stop <= start:
        return None
    try:
        return json.loads(text[start : stop + 1])
    except json.JSONDecodeError:
        return None


def parse_rocm(text: str) -> Optional[Dict[str, Any]]:
    raw = _json(text)
    if not isinstance(raw, dict) or not raw:
        return None
    cards: List[Dict[str, Any]] = []
    for key in sorted(raw):
        card = raw[key]
        if not isinstance(card, dict):
            continue
        try:
            total = int(card["VRAM Total Memory (B)"])
            used = int(card["VRAM Total Used Memory (B)"])
        except (KeyError, ValueError):
            continue
        cards.append(
            {
                "id": key.replace("card", "GPU "),
                "total_gb": round(total / GIB, 2),
                "used_gb": round(used / GIB, 2),
                "pct": round(used / total * 100, 1) if total else 0.0,
                "temp_c": float(card.get("Temperature (Sensor edge) (C)", 0) or 0),
                "busy_pct": int(card.get("GPU use (%)", 0) or 0),
            }
        )
    if not cards:
        return None
    used = sum(c["used_gb"] for c in cards)
    total = sum(c["total_gb"] for c in cards)
    return {
        "cards": cards,
        "used_gb": round(used, 2),
        "total_gb": round(total, 2),
        "pct": round(used / total * 100, 1) if total else 0.0,
    }


def parse_tailscale(text: str) -> Optional[Dict[str, Any]]:
    raw = _json(text)
    if not isinstance(raw, dict):
        return None
    backend = raw.get("BackendState") or "Unknown"
    devices: List[Dict[str, Any]] = []
    self_node = raw.get("Self") or {}
    if self_node:
        devices.append(
            {
                "name": self_node.get("HostName") or "self",
                "os": self_node.get("OS") or "",
                "ip": (self_node.get("TailscaleIPs") or [""])[0],
                "online": backend == "Running",
                "self": True,
                "last_seen": None,
                "exit_node": bool(self_node.get("ExitNode")),
            }
        )
    for peer in (raw.get("Peer") or {}).values():
        devices.append(
            {
                "name": peer.get("HostName") or peer.get("DNSName", "").split(".")[0],
                "os": peer.get("OS") or "",
                "ip": (peer.get("TailscaleIPs") or [""])[0],
                "online": bool(peer.get("Online")),
                "self": False,
                "last_seen": peer.get("LastSeen"),
                "exit_node": bool(peer.get("ExitNode")),
            }
        )
    devices.sort(key=lambda d: (not d["self"], not d["online"], d["name"]))
    return {
        "backend": backend,
        "version": raw.get("Version"),
        "devices": devices,
        "online": sum(1 for d in devices if d["online"]),
    }


def probe_port(port: int, timeout: float = 1.5) -> Dict[str, Any]:
    started = time.monotonic()
    up = False
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=timeout
        ) as response:
            up = response.status == 200
    except Exception:
        up = False
    return {"up": up, "ms": int((time.monotonic() - started) * 1000)}


def source_gpus() -> Source:
    rc, out, err = sh(
        ["rocm-smi", "--showmeminfo", "vram", "--showtemp", "--showuse", "--json"],
        timeout=6,
    )
    if rc != 0:
        return "stale", None, (err or out).strip()[:160] or "rocm-smi failed"
    parsed = parse_rocm(out)
    if parsed is None:
        return "stale", None, "unparseable rocm-smi output"
    return "live", parsed, None


def source_ports() -> Source:
    rows = []
    for port, kind, label in SERVICES:
        health = probe_port(port)
        rows.append({"port": port, "kind": kind, "label": label, **health})
    return "live", {"services": rows}, None


def source_tailscale() -> Source:
    rc, out, err = sh(["tailscale", "status", "--json"], timeout=8)
    if rc != 0:
        return "stale", None, (err or out).strip()[:160] or "tailscale failed"
    parsed = parse_tailscale(out)
    if parsed is None:
        return "stale", None, "unparseable tailscale output"
    state = "live" if parsed["backend"] == "Running" else "idle"
    return state, parsed, None if state == "live" else "backend stopped — run: tailscale up"


def source_github() -> Source:
    rc, out, err = sh(
        [
            "gh", "pr", "list", "--repo", REPO, "--state", "open",
            "--json", "number,title,url,mergeable", "--limit", "10",
        ],
        timeout=15,
    )
    if rc != 0:
        return "stale", None, (err or out).strip()[:160] or "gh failed"
    prs = _json(out) or []
    rc2, out2, _ = sh(
        ["gh", "api", f"repos/{REPO}/commits?per_page=1"], timeout=15
    )
    commit = None
    if rc2 == 0:
        commits = _json(out2) or []
        if commits:
            entry = commits[0]
            commit = {
                "sha": entry.get("sha", "")[:7],
                "message": (entry.get("commit", {}).get("message") or "").split("\n")[0],
                "date": entry.get("commit", {}).get("author", {}).get("date"),
            }
    return "live", {"repo": REPO, "prs": prs, "commit": commit}, None


def source_cloudflare() -> Source:
    exe = shutil.which("cf-architect")
    if not exe:
        return "idle", None, "cf-architect not installed"
    error = "probe failed"
    for attempt in range(2):
        rc, out, err = sh([exe, "probe", "--json"], timeout=60)
        report = _json(out)
        if isinstance(report, dict) and rc == 0:
            return "live", report, None
        if isinstance(report, dict) and report.get("authenticated") is False:
            error = "cf CLI not authenticated — run: cf auth login"
        else:
            text = (err or out).strip()
            error = text.splitlines()[0][:160] if text else error
        if attempt == 0:
            time.sleep(2)
    return "stale", None, error


def source_vault() -> Source:
    if not VAULT.is_dir():
        return "idle", None, f"{VAULT} not mounted"
    creators: Dict[str, int] = {}
    newest: Optional[Dict[str, Any]] = None
    total = 0
    for creator in VAULT.iterdir():
        if not creator.is_dir():
            continue
        reels = [
            child
            for child in creator.iterdir()
            if child.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}", child.name)
        ]
        creators[creator.name] = len(reels)
        total += len(reels)
        for reel in reels:
            mtime = int(reel.stat().st_mtime)
            if newest is None or mtime > newest["mtime"]:
                newest = {"name": reel.name, "creator": creator.name, "mtime": mtime}
    return "live", {"reels": total, "newest": newest, "creators": creators}, None

def source_skills() -> Source:
    if not HUB.is_dir():
        return "idle", None, f"{HUB} missing"
    rc, out, _ = sh(["git", "-C", str(HUB), "log", "-1", "--format=%h\t%s"], timeout=6)
    rc2, status, _ = sh(["git", "-C", str(HUB), "status", "--porcelain"], timeout=8)
    surface = HUB / "surface"
    return (
        "live",
        {
            "head": out.strip().split("\t")[0] if rc == 0 and out.strip() else None,
            "subject": out.strip().split("\t")[1] if rc == 0 and "\t" in out else None,
            "dirty": len([ln for ln in status.splitlines() if ln.strip()]) if rc2 == 0 else None,
            "skills": len(list(surface.iterdir())) if surface.is_dir() else None,
        },
        None,
    )


SOURCES: Tuple[Tuple[str, int, Callable[[], Source]], ...] = (
    ("gpus", 3, source_gpus),
    ("ports", 5, source_ports),
    ("tailscale", 5, source_tailscale),
    ("vault", 60, source_vault),
    ("github", 60, source_github),
    ("cloudflare", 300, source_cloudflare),
    ("skills", 120, source_skills),
)


class Deck:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: Dict[str, Dict[str, Any]] = {}
        self._cv = threading.Condition()
        self._started = time.time()

    def publish(self, name: str, state: str, data: Any, error: Optional[str], latency: int) -> None:
        slot = {
            "state": state,
            "data": data,
            "error": error,
            "latency_ms": latency,
            "ts": time.time(),
        }
        with self._lock:
            self._slots[name] = slot
        with self._cv:
            self._cv.notify_all()

    def last(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            slot = self._slots.get(name)
            return dict(slot) if slot else None

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            slots = dict(self._slots)
        return {
            "generated_at": time.time(),
            "uptime_s": int(time.time() - self._started),
            "host": os.uname().nodename,
            "sources": slots,
        }

    def wait(self, timeout: float) -> None:
        with self._cv:
            self._cv.wait(timeout)


def retain_last_known(
    deck: "Deck", name: str, state: str, data: Any, error: Optional[str]
) -> Tuple[str, Any, Optional[str]]:
    if data is not None:
        return state, data, error
    previous = deck.last(name)
    if previous and previous.get("data") is not None:
        return state, previous["data"], f"{error or 'collection failed'} — showing last known"
    return state, data, error


def run_source(deck: Deck, name: str, interval: int, fn: Callable[[], Source]) -> None:
    while True:
        started = time.monotonic()
        try:
            state, data, error = fn()
        except Exception as exc:  # a broken source must never kill the page
            state, data, error = "stale", None, f"{type(exc).__name__}: {exc}"
        state, data, error = retain_last_known(deck, name, state, data, error)
        deck.publish(name, state, data, error, int((time.monotonic() - started) * 1000))
        time.sleep(max(1.0, interval - (time.monotonic() - started)))


class Handler(BaseHTTPRequestHandler):
    deck: Deck
    server_version = "deck/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet by default
        if os.environ.get("DECK_DEBUG"):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/snapshot.json":
            body = json.dumps(self.deck.snapshot()).encode()
            self._send(200, body, "application/json")
        elif path == "/healthz":
            self._send(200, b"ok\n", "text/plain; charset=utf-8")
        elif path == "/events":
            self._stream()
        elif path in ("/", "/index.html"):
            index = ASSETS / "index.html"
            if not index.is_file():
                self._send(500, b"assets/index.html missing\n", "text/plain")
                return
            self._send(200, index.read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found\n", "text/plain")

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last = ""
        idle = 0
        try:
            while True:
                payload = json.dumps(self.deck.snapshot())
                if payload != last:
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    last = payload
                    idle = 0
                else:
                    idle += 1
                    if idle >= 10:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        idle = 0
                time.sleep(1.5)
        except (BrokenPipeError, ConnectionResetError):
            return


def serve(host: str, port: int) -> int:
    deck = Deck()
    Handler.deck = deck
    threads = [
        threading.Thread(target=run_source, args=(deck, name, interval, fn), daemon=True)
        for name, interval, fn in SOURCES
    ]
    for thread in threads:
        thread.start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print(f"deck listening on http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def snapshot_once() -> int:
    deck = Deck()
    for name, _interval, fn in SOURCES:
        started = time.monotonic()
        try:
            state, data, error = fn()
        except Exception as exc:
            state, data, error = "stale", None, f"{type(exc).__name__}: {exc}"
        deck.publish(name, state, data, error, int((time.monotonic() - started) * 1000))
    print(json.dumps(deck.snapshot(), indent=2))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    os.environ["PATH"] = augment_path()
    parser = argparse.ArgumentParser(prog="deck", description="Homelab activity page.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_serve = sub.add_parser("serve", help="run the collector and web server")
    p_serve.add_argument("--host", default=os.environ.get("DECK_HOST", "127.0.0.1"))
    p_serve.add_argument("--port", type=int, default=int(os.environ.get("DECK_PORT", "7777")))
    p_snapshot = sub.add_parser("snapshot", help="collect once and print JSON")
    p_snapshot.add_argument("--json", action="store_true",
                            help="explicit alias for the default JSON output")
    args = parser.parse_args(argv)
    if args.command == "serve":
        return serve(args.host, args.port)
    if args.command == "snapshot":
        try:
            return snapshot_once()
        except Exception as exc:
            if not args.json:
                raise
            print(f"deck snapshot failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
