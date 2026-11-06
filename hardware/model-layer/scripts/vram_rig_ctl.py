#!/usr/bin/env python3
"""
vram_rig_ctl.py — Smart GPU VRAM, Port Switcher & llama-swap Controller
Manages llama-swap (port 8000) and direct ports 8080-8090.
"""

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REGISTRY_PATH = BASE_DIR / "config" / "port_registry.json"
LLAMA_SWAP_CONFIG = BASE_DIR / "config" / "llama-swap.yaml"
LOG_DIR = Path("/tmp/local-llm-ports")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_registry():
    if not REGISTRY_PATH.is_file():
        return {
            "total_vram_budget_mb": 32000,
            "pinned_port": "8080",
            "models": {}
        }
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def get_vram_info():
    """Detect total and free VRAM (MB) across Linux AMD DRM, NVIDIA, or macOS Unified Memory."""
    total_mb, used_mb = 0, 0

    # 1. Linux DRM sysfs (AMD RX GPUs / ROCm)
    drm_cards = sorted(Path("/sys/class/drm").glob("card[0-9]/device"))
    found_sysfs = False
    for dev in drm_cards:
        t_file = dev / "mem_info_vram_total"
        u_file = dev / "mem_info_vram_used"
        if t_file.exists() and u_file.exists():
            try:
                total_mb += int(t_file.read_text().strip()) // (1024 * 1024)
                used_mb += int(u_file.read_text().strip()) // (1024 * 1024)
                found_sysfs = True
            except Exception:
                pass
    if found_sysfs and total_mb > 0:
        return {"total_mb": total_mb, "used_mb": used_mb, "free_mb": max(0, total_mb - used_mb), "backend": "amdgpu-sysfs"}

    # 2. NVIDIA SMI
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        for line in out.strip().splitlines():
            t, u = [int(x.strip()) for x in line.split(",")]
            total_mb += t
            used_mb += u
        return {"total_mb": total_mb, "used_mb": used_mb, "free_mb": max(0, total_mb - used_mb), "backend": "nvidia-smi"}
    except Exception:
        pass

    # 3. macOS Apple Silicon (Unified Memory)
    if sys.platform == "darwin":
        try:
            mem_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
            total_mb = mem_bytes // (1024 * 1024)
            vm = subprocess.check_output(["vm_stat"], text=True)
            page_size = 4096
            free_pages = 0
            for line in vm.splitlines():
                if "Pages free" in line or "Pages speculative" in line:
                    free_pages += int(line.split(":")[1].strip().rstrip("."))
            free_mb = (free_pages * page_size) // (1024 * 1024)
            return {"total_mb": total_mb, "used_mb": total_mb - free_mb, "free_mb": free_mb, "backend": "apple-silicon-unified"}
        except Exception:
            pass

    reg = load_registry()
    budget = reg.get("total_vram_budget_mb", 32000)
    return {"total_mb": budget, "used_mb": 0, "free_mb": budget, "backend": "simulated-budget"}


def _binds_loopback(line, port):
    """True when the listener's local address is loopback or a wildcard.

    `ss` also reports remote proxies such as `tailscale serve`, which bind the
    tailnet IP (e.g. `100.x.x.x%tailscale0:8083`) and would otherwise make a
    stopped service look alive. Only loopback/wildcard binds are the real
    service.
    """
    for tok in line.split():
        if tok.endswith(f":{port}"):
            addr = tok.rsplit(":", 1)[0].strip("[]")
            return addr.startswith("127.") or addr in {"0.0.0.0", "::", "::1", "*", "localhost"}
    return False


def get_listening_ports(start_port=8080, end_port=8090):
    """Return dict of {port_str: {'pid': int, 'process': str}} for active TCP listeners."""
    active = {}
    target_ports = set(range(start_port, end_port + 1))

    # Try Linux 'ss -tulpn'
    if sys.platform.startswith("linux"):
        try:
            out = subprocess.check_output(["ss", "-tulpn"], stderr=subprocess.DEVNULL, text=True)
            for line in out.splitlines():
                for port in target_ports:
                    if f":{port} " in line and _binds_loopback(line, port):
                        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
                        if m:
                            entry = {"process": m.group(1), "pid": int(m.group(2))}
                        else:
                            entry = {"process": "unknown", "pid": None}
                        if active.get(str(port), {}).get("pid") is None:
                            active[str(port)] = entry
            return active
        except Exception:
            pass

    # Try macOS / POSIX 'lsof -nP -iTCP -sTCP:LISTEN'
    try:
        out = subprocess.check_output(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], stderr=subprocess.DEVNULL, text=True)
        for line in out.splitlines():
            for port in target_ports:
                if f":{port} " in line or f":{port}->" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        active[str(port)] = {"process": parts[0], "pid": int(parts[1])}
        return active
    except Exception:
        pass

    # Fallback to direct socket probing
    for port in target_ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.1)
        res = s.connect_ex(("127.0.0.1", port))
        s.close()
        if res == 0:
            active[str(port)] = {"process": "listening", "pid": None}

    return active


def is_port_open(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    res = s.connect_ex(("127.0.0.1", int(port)))
    s.close()
    return res == 0


def kill_port(port_str):
    p_int = int(port_str)
    active = get_listening_ports(p_int, p_int)
    info = active.get(str(port_str))
    if not info and not is_port_open(p_int):
        print(f"Port {port_str} is already free.")
        return False

    pid = info.get("pid") if info else None
    if pid:
        print(f"Stopping PID {pid} ({info.get('process')}) on port {port_str}...")
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(10):
                time.sleep(0.3)
                if not is_port_open(p_int):
                    print(f"✅ Port {port_str} freed.")
                    return True
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        except ProcessLookupError:
            pass

    subprocess.run(f"lsof -ti:{port_str} | xargs kill -9", shell=True, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    print(f"✅ Port {port_str} freed.")
    return True


def get_llama_swap_info(port=8000):
    if not is_port_open(port):
        return {"status": "OFFLINE", "port": port, "running_models": [], "configured_models": []}

    running = []
    configured = []
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/running", headers={"User-Agent": "vram-rig-ctl"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            running = data if isinstance(data, list) else data.get("models", [])
    except Exception:
        pass

    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models", headers={"User-Agent": "vram-rig-ctl"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            configured = [m.get("id") for m in data.get("data", [])]
    except Exception:
        pass

    return {
        "status": "ONLINE",
        "port": port,
        "running_models": running,
        "configured_models": configured
    }


def cmd_status():
    registry = load_registry()
    vram = get_vram_info()
    active = get_listening_ports(8080, 8090)
    swap_info = get_llama_swap_info(8000)

    pinned_port = registry.get("pinned_port", "8080")
    report = {
        "vram": vram,
        "llama_swap_8000": swap_info,
        "pinned_king_port": pinned_port,
        "ports_8080_8090": {},
    }
    for p_str, meta in registry.get("models", {}).items():
        state = active.get(p_str)
        report["ports_8080_8090"][p_str] = {
            "alias": meta.get("alias"),
            "name": meta.get("name", meta.get("alias")),
            "pinned": meta.get("pinned", False),
            "est_vram_mb": meta.get("vram_mb"),
            "status": "RUNNING" if state else "STOPPED",
            "pid": state.get("pid") if state else None,
        }
    for p_str, state in active.items():
        if p_str not in report["ports_8080_8090"]:
            report["ports_8080_8090"][p_str] = {
                "alias": f"untracked-port-{p_str}",
                "name": f"Unknown service on :{p_str}",
                "pinned": False,
                "est_vram_mb": None,
                "status": "RUNNING",
                "pid": state.get("pid"),
            }
    print(json.dumps(report, indent=2))


def cmd_llama_swap_up(port=8000):
    if is_port_open(port):
        print(f"ℹ️  llama-swap is already listening on port {port}.")
        return

    if not LLAMA_SWAP_CONFIG.is_file():
        sys.exit(f"❌ Error: Config file not found at {LLAMA_SWAP_CONFIG}")

    log_file = LOG_DIR / f"llama_swap_{port}.log"
    cmd = f"llama-swap -listen 127.0.0.1:{port} -config {LLAMA_SWAP_CONFIG} -watch-config"
    print(f"🚀 Starting llama-swap on port {port} (Logs: {log_file})...")
    with open(log_file, "ab") as out:
        subprocess.Popen(cmd, shell=True, stdout=out, stderr=out, start_new_session=True)

    for _ in range(20):
        time.sleep(0.3)
        if is_port_open(port):
            print(f"✅ SUCCESS: llama-swap running on http://127.0.0.1:{port}")
            info = get_llama_swap_info(port)
            print(f"   Configured models: {', '.join(info.get('configured_models', []))}")
            return

    print(f"⚠️  Started llama-swap, waiting for port {port} to bind. Check logs: {log_file}")


def cmd_llama_swap_down(port=8000):
    if not is_port_open(port):
        print(f"ℹ️  llama-swap is not running on port {port}.")
        return

    # Gracefully unload models via API first
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/models/unload", method="POST")
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass

    kill_port(str(port))
    print(f"✅ llama-swap on port {port} stopped.")


def cmd_llama_swap_status(port=8000):
    info = get_llama_swap_info(port)
    print(json.dumps(info, indent=2))


def cmd_swap(target_port):
    registry = load_registry()
    models = registry.get("models", {})
    if str(target_port) not in models:
        sys.exit(f"❌ Error: Port {target_port} is not defined in {REGISTRY_PATH}")

    target_meta = models[str(target_port)]
    active = get_listening_ports(8080, 8090)
    if str(target_port) in active:
        print(f"ℹ️  Port {target_port} ({target_meta['alias']}) is already running.")
        return

    needed_mb = target_meta.get("vram_mb", 4000)
    vram = get_vram_info()
    pinned_port = registry.get("pinned_port", "8080")

    if vram["free_mb"] < needed_mb:
        print(f"⚠️ Need {needed_mb} MB VRAM, but only {vram['free_mb']} MB available.")
        print("   Evicting non-pinned auxiliary ports...")
        for p_str in sorted(active.keys()):
            if p_str != pinned_port and p_str != str(target_port):
                kill_port(p_str)
                time.sleep(0.5)
                vram = get_vram_info()
                if vram["free_mb"] >= needed_mb:
                    break

    if vram["free_mb"] < needed_mb and pinned_port in active and str(target_port) != pinned_port:
        print(f"⚠️ Heavy task requires {needed_mb} MB. Temporarily evicting pinned King (port {pinned_port})...")
        kill_port(pinned_port)
        time.sleep(1.0)

    cmd_str = os.path.expanduser(target_meta["cmd"])
    log_file = LOG_DIR / f"port_{target_port}.log"
    print(f"🚀 Starting {target_meta['alias']} on port {target_port}...")
    with open(log_file, "ab") as out:
        subprocess.Popen(cmd_str, shell=True, stdout=out, stderr=out, start_new_session=True)

    for _ in range(40):
        time.sleep(0.5)
        if str(target_port) in get_listening_ports(int(target_port), int(target_port)):
            print(f"✅ SUCCESS: {target_meta['alias']} listening on port {target_port}. Logs: {log_file}")
            return

    print(f"Launched process on port {target_port} (still loading weights—check {log_file}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GPU VRAM & Port Switcher with llama-swap")
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("status")
    sub.add_parser("evict-all")

    p_swap_up = sub.add_parser("llama-swap-up")
    p_swap_up.add_argument("--port", type=int, default=8000)

    p_swap_down = sub.add_parser("llama-swap-down")
    p_swap_down.add_argument("--port", type=int, default=8000)

    p_swap_status = sub.add_parser("llama-swap-status")
    p_swap_status.add_argument("--port", type=int, default=8000)

    p_kill = sub.add_parser("kill")
    p_kill.add_argument("--port", required=True)

    p_swap = sub.add_parser("swap")
    p_swap.add_argument("--port", required=True)

    args = parser.parse_args()
    if args.action == "status":
        cmd_status()
    elif args.action == "kill":
        kill_port(str(args.port))
    elif args.action == "evict-all":
        reg = load_registry()
        pinned = reg.get("pinned_port", "8080")
        for p in list(get_listening_ports(8080, 8090).keys()):
            if p != pinned:
                kill_port(p)
        print("✅ Evicted auxiliary ports. Headroom reclaimed.")
    elif args.action == "swap":
        cmd_swap(str(args.port))
    elif args.action == "llama-swap-up":
        cmd_llama_swap_up(args.port)
    elif args.action == "llama-swap-down":
        cmd_llama_swap_down(args.port)
    elif args.action == "llama-swap-status":
        cmd_llama_swap_status(args.port)
