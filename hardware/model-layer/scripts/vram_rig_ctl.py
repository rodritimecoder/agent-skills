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
REPO_ROOT = BASE_DIR.parent.parent
REGISTRY_PATH = BASE_DIR / "config" / "port_registry.json"
MANIFEST_PATH = REPO_ROOT / "ports.json"
LAUNCH_ROOT = REPO_ROOT / "launchers"
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


def load_manifest():
    """ports.json is the source of truth; port_registry.json is a rendered cache.

    The registry flattens each slot to its default launcher, so anything that
    asks it "what can run here" can only ever answer "the default". Reading the
    manifest keeps every candidate launchable, and keeps a missing `vram_mb`
    from being rendered as an explicit `null` that beats a default.
    """
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _launcher_cmd(launcher: str) -> str:
    return f"bash {LAUNCH_ROOT}/{Path(launcher).name}"


def _candidate_keys(c: dict) -> set:
    keys = set()
    for raw in (c.get("model"), Path(c.get("launcher", "")).stem):
        raw = str(raw or "").strip().lower()
        if raw:
            keys.add(raw)
    return keys


def _manifest_slot(s: dict, slot_range: list) -> dict:
    candidates, seen = [], set()
    for c in s.get("candidates", []):
        launcher = Path(c.get("launcher", "")).name
        if not launcher or launcher in seen:
            continue
        seen.add(launcher)
        candidates.append({
            "keys": _candidate_keys(c),
            "model": c.get("model", launcher),
            "launcher": launcher,
            "cmd": _launcher_cmd(c.get("launcher", launcher)),
            "vram_mb": c.get("vram_mb"),
            "dim": c.get("dim"),
            "status": c.get("status", ""),
        })
    default = Path(s.get("default", "")).name
    for idx, c in enumerate(candidates):
        if c["launcher"] == default:
            candidates.insert(0, candidates.pop(idx))
            break
    return {
        "port": str(s["port"]),
        "id": s.get("id", str(s["port"])),
        "alias": s.get("alias", s.get("id", str(s["port"]))),
        "vram_mb": s.get("vram_mb"),
        "pinned": bool(s.get("pinned")),
        "candidates": candidates,
        "range": slot_range,
    }


def load_slots():
    """Return ({port: slot}, registry) with every candidate the manifest declares."""
    registry = load_registry()
    manifest = load_manifest()
    slots = {}
    if manifest:
        slot_range = manifest.get("slot_range", [8080, 8091])
        for s in manifest.get("slots", []):
            slot = _manifest_slot(s, slot_range)
            slots[slot["port"]] = slot
    if not slots:
        # Cache fallback: one launcher per slot, same contract, fewer options.
        for port, meta in registry.get("models", {}).items():
            cmd = meta.get("cmd", "")
            name = meta.get("name") or meta.get("alias") or port
            slots[str(port)] = {
                "port": str(port),
                "id": meta.get("alias", str(port)),
                "alias": meta.get("alias", str(port)),
                "vram_mb": meta.get("vram_mb"),
                "pinned": bool(meta.get("pinned")),
                "candidates": [{
                    "keys": {str(name).strip().lower()},
                    "model": name,
                    "launcher": Path(cmd).name,
                    "cmd": cmd,
                    "vram_mb": meta.get("vram_mb"),
                    "status": "current",
                }],
                "range": registry.get("port_range", [8080, 8090]),
            }
    return slots, registry


def port_bounds(registry: dict, slots: dict) -> tuple:
    """The declared slot range, never a hardcoded ceiling."""
    rng = registry.get("port_range")
    if not rng:
        rng = next((s["range"] for s in slots.values() if s.get("range")), None)
    try:
        return int(rng[0]), int(rng[1])
    except (TypeError, ValueError, IndexError):
        return 8080, 8090


def _find_slot(slots: dict, needle: str):
    if needle in slots:
        return slots[needle]
    for slot in slots.values():
        if needle in (slot["id"].lower(), slot["alias"].lower()):
            return slot
    synonym = SLOT_SYNONYMS.get(needle)
    if synonym and synonym in slots:
        return slots[synonym]
    for slot in slots.values():
        if needle in slot["alias"].lower():
            return slot
    return None


def _find_candidate(slot: dict, needle: str) -> dict:
    exact = [c for c in slot["candidates"] if needle in c["keys"]]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        builds = ", ".join(c["launcher"] for c in exact)
        raise LookupError(
            f"'{needle}' matches {len(exact)} registered builds on {slot['id']} "
            f"(:{slot['port']}): {builds}. Pass the launcher name instead."
        )
    partial = [c for c in slot["candidates"] if any(needle in k for k in c["keys"])]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(sorted(c["model"] for c in partial))
        raise LookupError(f"'{needle}' is ambiguous on {slot['id']} (:{slot['port']}): {names}")
    names = ", ".join(c["model"] for c in slot["candidates"])
    raise LookupError(f"'{needle}' is not a candidate of {slot['id']} (:{slot['port']}). Options: {names}")


def resolve_launch(slots: dict, target: str, candidate: str = None) -> tuple:
    """Resolve '<slot|alias|port> [candidate]' or a bare candidate model name."""
    needle = str(target or "").strip().lower().lstrip(":")
    if not needle:
        raise LookupError("a slot, alias, port or candidate name is required")
    slot = _find_slot(slots, needle)
    if slot is not None:
        if candidate:
            return slot, _find_candidate(slot, str(candidate).strip().lower())
        if not slot["candidates"]:
            raise LookupError(f"{slot['id']} (:{slot['port']}) has no registered launcher")
        return slot, slot["candidates"][0]
    hits = [(s, c) for s in slots.values() for c in s["candidates"] if needle in c["keys"]]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        if len({s["port"] for s, _c in hits}) == 1:
            # Same slot, several builds of one model: let the slot resolver name them.
            return hits[0][0], _find_candidate(hits[0][0], needle)
        where = ", ".join(f"{s['id']}:{s['port']}/{c['model']}" for s, c in hits)
        raise LookupError(
            f"'{needle}' matches several candidates: {where}. "
            f"Disambiguate with: up <slot> {needle}"
        )
    raise LookupError(f"'{needle}' is not a slot, alias, port or registered candidate")


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


SLOT_SYNONYMS = {
    "llm": "8080",
    "coder": "8080",
    "genesis": "8080",
    "luffy": "8080",
    "audio": "8081",
    "asr": "8081",
    "tts": "8081",
    "audiocpp": "8081",
    "decision": "8083",
    "decide": "8083",
    "jev": "8083",
    "h2o": "8083",
    "decision-engine": "8082",
    "startlux": "8082",
    "decision-fallback": "8089",
    "imajev": "8089",
    "ocr-crispembed": "8084",
    "crispembed": "8084",
    "ocr": "8085",
    "ocr-lighton": "8085",
    "lighton": "8085",
    "reranker": "8086",
    "rerank": "8086",
    "jina": "8086",
    "embed": "8087",
    "bge": "8087",
    "grounding": "8088",
    "wevisone": "8088",
    "ocr-jev": "8090",
    "minicpm": "8090",
    "llm-rp": "8091",
    "rp": "8091",
    "lfm3": "8091",
}


def kill_port(target_arg):
    slots, _ = load_slots()
    raw = str(target_arg or "").strip().lstrip(":")
    if raw.isdigit():
        port_str = raw
    else:
        try:
            slot, _cand = resolve_launch(slots, raw)
        except LookupError as exc:
            print(f"❌ Error: {exc}")
            return False
        port_str = slot["port"]
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
    slots, _ = load_slots()
    low, high = port_bounds(registry, slots)
    vram = get_vram_info()
    active = get_listening_ports(low, high)
    swap_info = get_llama_swap_info(8000)

    pinned_port = registry.get("pinned_port", "8080")
    report = {
        "vram": vram,
        "llama_swap_8000": swap_info,
        "pinned_king_port": pinned_port,
        "port_range": [low, high],
        "ports_8080_8090": {},
    }
    for p_str, slot in sorted(slots.items()):
        state = active.get(p_str)
        declared = slot["candidates"][0] if slot["candidates"] else None
        report["ports_8080_8090"][p_str] = {
            "alias": slot["alias"],
            "name": declared["model"] if declared else slot["alias"],
            "pinned": slot["pinned"],
            "est_vram_mb": slot.get("vram_mb"),
            "candidates": [c["model"] for c in slot["candidates"]],
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


def _pick_by_dim(slot: dict, dim: int):
    """Choose the embedding candidate by dimension, the slot's real identity.

    bge-small (384d) and EmbeddingGemma-2 (768d) vectors are not comparable, so
    "the default" is the wrong answer whenever an index exists.
    """
    known = [c for c in slot["candidates"] if c.get("dim")]
    if not known:
        return None
    for c in known:
        if int(c["dim"]) == dim:
            return c
    options = ", ".join(f"{c['model']} ({c['dim']}d)" for c in known)
    raise LookupError(f"no candidate on {slot['id']} (:{slot['port']}) has dim={dim}. Options: {options}")


def _needed_mb(candidate: dict, slot: dict) -> int:
    """VRAM estimate that tolerates a null/absent value instead of comparing int to None."""
    needed = candidate.get("vram_mb")
    if needed is None:
        needed = slot.get("vram_mb")
    if needed is None:
        return 4000
    try:
        return max(0, int(needed))
    except (TypeError, ValueError):
        return 4000


def cmd_swap(target_arg, candidate_arg=None, dry_run=False, dim=None):
    slots, registry = load_slots()
    try:
        slot, cand = resolve_launch(slots, target_arg, candidate_arg)
    except LookupError as exc:
        sys.exit(f"❌ Error: {exc}")

    if dim:
        try:
            dim = int(dim)
        except (TypeError, ValueError):
            sys.exit("❌ Error: --dim must be an integer (e.g. 384 or 768)")
        if candidate_arg is None:
            try:
                picked = _pick_by_dim(slot, dim)
            except LookupError as exc:
                sys.exit(f"❌ Error: {exc}")
            if picked is not None:
                cand = picked

    target_port = slot["port"]
    low, high = port_bounds(registry, slots)
    active = get_listening_ports(low, high)
    needed_mb = _needed_mb(cand, slot)
    if dry_run:
        print(json.dumps({
            "slot": slot["id"],
            "port": target_port,
            "alias": slot["alias"],
            "model": cand["model"],
            "launcher": cand["launcher"],
            "dim": cand.get("dim"),
            "cmd": cand["cmd"],
            "needed_mb": needed_mb,
            "pinned": slot["pinned"],
            "declared": slot["candidates"][0]["model"] if slot["candidates"] else None,
            "running": target_port in active,
            "port_range": [low, high],
        }, indent=2))
        return
    if target_port in active:
        print(f"ℹ️  Port {target_port} ({slot['alias']}) is already running.")
        if len(slot["candidates"]) > 1:
            print(f"    Stop it first to change candidates: vram-rig-ctl down {target_port}")
        return

    vram = get_vram_info()
    pinned_port = registry.get("pinned_port", "8080")
    king_evicted = False

    if vram["free_mb"] < needed_mb:
        print(f"⚠️ Need {needed_mb} MB VRAM, but only {vram['free_mb']} MB available.")
        print("   Evicting non-pinned auxiliary ports...")
        for p_str in sorted(active.keys()):
            if p_str != pinned_port and p_str != target_port:
                kill_port(p_str)
                time.sleep(0.5)
                vram = get_vram_info()
                if vram["free_mb"] >= needed_mb:
                    break

    if vram["free_mb"] < needed_mb and pinned_port in active and target_port != pinned_port:
        print(f"⚠️ Heavy task requires {needed_mb} MB. Temporarily evicting pinned King (port {pinned_port})...")
        kill_port(pinned_port)
        king_evicted = True
        time.sleep(1.0)

    log_file = LOG_DIR / f"port_{target_port}.log"
    print(f"🚀 Starting {slot['alias']} — {cand['model']} on port {target_port}...")
    with open(log_file, "ab") as out:
        subprocess.Popen(cand["cmd"], shell=True, stdout=out, stderr=out, start_new_session=True)

    if len(slot["candidates"]) > 1 and cand is not slot["candidates"][0]:
        print(f"ℹ️  {cand['model']} is not the declared default for {slot['id']} "
              f"({slot['candidates'][0]['model']}). ports.json is unchanged.")
        print(f"    Persist it: python3 ports.py swap {slot['id']} "
              f"--model '{cand['model']}' --launcher {cand['launcher']}")
    if king_evicted:
        print(f"ℹ️  Pinned King on :{pinned_port} was evicted. "
              f"Restore it with: vram-rig-ctl up {pinned_port}")

    for _ in range(40):
        time.sleep(0.5)
        if target_port in get_listening_ports(int(target_port), int(target_port)):
            print(f"✅ SUCCESS: {cand['model']} listening on port {target_port}. Logs: {log_file}")
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

    p_kill = sub.add_parser("kill", help="Stop a service by port, slot id, or alias (e.g. 8085, ocr, asr)")
    p_kill.add_argument("target", nargs="?", help="Port, slot id, or alias")
    p_kill.add_argument("--port", dest="opt_port", type=int, metavar="PORT", help="Optional port flag")

    p_down = sub.add_parser("down", help="Alias for kill (e.g. vram-rig-ctl down ocr)")
    p_down.add_argument("target", nargs="?", help="Port, slot id, or alias")
    p_down.add_argument("--port", dest="opt_port", type=int, metavar="PORT", help="Optional port flag")

    p_swap = sub.add_parser("swap", help="Start/swap a service by port, slot id, alias, or candidate (e.g. 8085, ocr)")
    p_swap.add_argument("target", nargs="?", help="Port, slot id, alias, or candidate model")
    p_swap.add_argument("candidate", nargs="?", help="Candidate within that slot (e.g. up embed embeddinggemma-2)")
    p_swap.add_argument("--port", dest="opt_port", type=int, metavar="PORT", help="Optional port flag")
    p_swap.add_argument("--dry-run", action="store_true", help="Resolve and print the launch plan, start nothing")
    p_swap.add_argument("--dim", type=int, metavar="N", help="Embedding dimension to match (e.g. 384, 768)")

    p_up = sub.add_parser("up", help="Alias for swap (e.g. vram-rig-ctl up ocr)")
    p_up.add_argument("target", nargs="?", help="Port, slot id, alias, or candidate model")
    p_up.add_argument("candidate", nargs="?", help="Candidate within that slot (e.g. up embed embeddinggemma-2)")
    p_up.add_argument("--port", dest="opt_port", type=int, metavar="PORT", help="Optional port flag")
    p_up.add_argument("--dry-run", action="store_true", help="Resolve and print the launch plan, start nothing")
    p_up.add_argument("--dim", type=int, metavar="N", help="Embedding dimension to match (e.g. 384, 768)")

    args = parser.parse_args()
    if args.action == "status":
        cmd_status()
    elif args.action in ("kill", "down"):
        target = args.target or getattr(args, "opt_port", None)
        if not target:
            sys.exit("❌ Error: Target port or slot is required (e.g. vram-rig-ctl kill ocr)")
        kill_port(target)
    elif args.action == "evict-all":
        slots, reg = load_slots()
        pinned = reg.get("pinned_port", "8080")
        for p in list(get_listening_ports(*port_bounds(reg, slots)).keys()):
            if p != pinned:
                kill_port(p)
        print("✅ Evicted auxiliary ports. Headroom reclaimed.")
    elif args.action in ("swap", "up"):
        target = args.target or getattr(args, "opt_port", None)
        if not target:
            sys.exit("❌ Error: Target port or slot is required (e.g. vram-rig-ctl swap ocr)")
        cmd_swap(target, args.candidate, args.dry_run, getattr(args, "dim", None))
    elif args.action == "llama-swap-up":
        cmd_llama_swap_up(args.port)
    elif args.action == "llama-swap-down":
        cmd_llama_swap_down(args.port)
    elif args.action == "llama-swap-status":
        cmd_llama_swap_status(args.port)
