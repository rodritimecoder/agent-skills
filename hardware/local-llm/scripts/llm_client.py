#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = SKILL_DIR / "config.json"


def _load_env_keys():
    for env_path in [Path.home() / ".agent_keys.env", Path.home() / ".env", Path.cwd() / ".env"]:
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[7:].strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass


_load_env_keys()


def load_config() -> Dict[str, Any]:
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "default_endpoint": "http://127.0.0.1:8080",
        "model_name": "qwen3.6-35b-genesis",
        "launcher_script": "/run/media/rodri/AI/sh/luffy_nothink.sh",
        "defaults": {"temperature": 0.7, "top_p": 0.8, "max_tokens": 4096}
    }


def find_ports_manifest() -> Optional[Path]:
    candidates = [
        SKILL_DIR.parent / "ports.json",
        Path("/run/media/rodri/AI/workstation-clis/skills/ports.json"),
        Path("/run/media/rodri/AI/skills/ports.json"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def get_llm_candidates() -> List[Dict[str, Any]]:
    manifest_p = find_ports_manifest()
    candidates: List[Dict[str, Any]] = []
    if manifest_p:
        try:
            data = json.loads(manifest_p.read_text(encoding="utf-8"))
            llm_slot = next((s for s in data.get("slots", []) if s.get("id") == "llm"), None)
            if llm_slot and "candidates" in llm_slot:
                for c in llm_slot["candidates"]:
                    launcher_rel = c.get("launcher", "")
                    launcher_abs = Path("/run/media/rodri/AI") / launcher_rel
                    candidates.append({
                        "model": c.get("model", "unknown"),
                        "quant": c.get("quant", ""),
                        "status": c.get("status", "candidate"),
                        "launcher": launcher_rel,
                        "launcher_path": str(launcher_abs),
                        "launcher_exists": launcher_abs.is_file(),
                        "notes": c.get("notes", ""),
                    })
                return candidates
        except Exception:
            pass

    cfg = load_config()
    default_launcher = cfg.get("launcher_script", "/run/media/rodri/AI/sh/luffy_nothink.sh")
    return [
        {
            "model": cfg.get("model_name", "qwen3.6-35b-genesis"),
            "quant": "Q4_K_M",
            "status": "default",
            "launcher": default_launcher,
            "launcher_path": default_launcher,
            "launcher_exists": Path(default_launcher).is_file(),
            "notes": "Default configured model launcher",
        }
    ]


def is_genesis_online(endpoint: str = "http://127.0.0.1:8080") -> bool:
    res = subprocess.run("pgrep -f '[l]lama-server.*([Q]wen|[G]emma|[S]wift|[T]hinking)'", shell=True, capture_output=True)
    if res.returncode != 0:
        return False

    try:
        url = f"{endpoint.rstrip('/')}/v1/models"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_genesis(timeout_s: float = 60.0) -> bool:
    """Mirror OCR's self-healing pattern: if the local LLM server is down,
    start it via `vram-rig-ctl up 8080` and poll health for up to timeout_s.
    Returns True when the server answers, False otherwise (callers then fall
    through to their existing offline error path unchanged)."""
    if is_genesis_online():
        return True
    ctl = shutil.which("vram-rig-ctl")
    if not ctl:
        return False
    try:
        subprocess.run(
            [ctl, "up", "8080"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        return False
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if is_genesis_online():
            return True
        time.sleep(0.5)
    return False


def call_local_genesis(
    prompt: str,
    system: Optional[str] = None,
    stream: bool = False,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    endpoint: str = "http://127.0.0.1:8080"
) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream
    }

    url = f"{endpoint.rstrip('/')}/v1/chat/completions"
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"}, method="POST")

    if not stream:
        with urllib.request.urlopen(req, timeout=180) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            return res_json["choices"][0]["message"]["content"]
    else:
        full_content = []
        with urllib.request.urlopen(req, timeout=180) as resp:
            for line in resp:
                line_str = line.decode("utf-8").strip()
                if not line_str or line_str == "data: [DONE]":
                    continue
                if line_str.startswith("data: "):
                    try:
                        chunk = json.loads(line_str[6:])
                        delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            sys.stdout.write(delta)
                            sys.stdout.flush()
                            full_content.append(delta)
                    except Exception:
                        pass
        sys.stdout.write("\n")
        return "".join(full_content)


def call_cloud_fallback(prompt: str, system: Optional[str] = None) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if api_key:
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": prompt})
            payload = {"model": "nvidia/nemotron-3-ultra-550b-a55b:free", "messages": msgs, "temperature": 0.2}
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
        except Exception:
            pass

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    raise RuntimeError("No working fallback cloud endpoints available.")


def doctor_check(json_mode: bool = False) -> Dict[str, Any]:
    cfg = load_config()
    endpoint = cfg.get("default_endpoint", "http://127.0.0.1:8080")
    launcher = cfg.get("launcher_script", "")

    online = is_genesis_online(endpoint)
    proc_running = subprocess.run("pgrep -f '[l]lama-server.*([Q]wen|[G]emma|[S]wift|[T]hinking)'", shell=True, capture_output=True).returncode == 0
    candidates = get_llm_candidates()

    res = {
        "status": "ok",
        "online": online,
        "process_running": proc_running,
        "endpoint": endpoint,
        "model_name": cfg.get("model_name", "qwen3.6-35b-genesis"),
        "launcher_path": launcher,
        "available_models_count": len(candidates),
    }

    if json_mode:
        print(json.dumps(res, indent=2))
        return res

    print("\n" + "=" * 55)
    print(" 🏥 LOCAL-LLM DOCTOR — Dual-GPU Model Status")
    print("=" * 55)
    print(f" Target Endpoint   : {endpoint}")
    print(f" Service Status    : {'ONLINE ✅' if online else 'OFFLINE ⚠️'}")
    print(f" Process Active    : {'YES (running)' if proc_running else 'NO (idle)'}")
    print(f" Launcher Path     : {launcher}")
    print(f" Candidate Models  : {len(candidates)} registered in ports.json")

    if not online:
        print("\n💡 LLM server is not running on :8080.")
        print("   To start the dual-GPU server, run in another terminal:")
        print(f"   bash {launcher}")
        print("   (Or use `scripts/llm_client.py start` to launch in background)")
    print("=" * 55 + "\n")

    return res


def list_models(status_filter: str = "all", json_mode: bool = False) -> List[Dict[str, Any]]:
    candidates = get_llm_candidates()
    if status_filter != "all":
        candidates = [c for c in candidates if c.get("status") == status_filter]

    if json_mode:
        print(json.dumps(candidates, indent=2))
        return candidates

    print("-" * 88)
    print(f"{'Status':<12} {'Model':<38} {'Quant':<16} {'Launcher':<20}")
    print("-" * 88)
    for c in candidates:
        launcher_name = Path(c.get("launcher", "")).name
        exists_mark = "✓" if c.get("launcher_exists") else "✗"
        print(f"[{c.get('status', 'unknown'):<10}] {c.get('model', ''):<38} {c.get('quant', ''):<16} {launcher_name} ({exists_mark})")
    print("-" * 88)
    return candidates


def start_server(launcher_script: Optional[str] = None, json_mode: bool = False) -> Dict[str, Any]:
    cfg = load_config()
    launcher = launcher_script or cfg.get("launcher_script", "/run/media/rodri/AI/sh/luffy_nothink.sh")
    online = is_genesis_online()

    if online:
        res = {"status": "already_running", "online": True, "launcher": launcher}
        if json_mode:
            print(json.dumps(res, indent=2))
        else:
            sys.stderr.write("[local-llm] LLM is already running and healthy on :8080.\n")
        return res

    launcher_p = Path(launcher)
    if not launcher_p.is_file():
        # Check in /run/media/rodri/AI/sh/
        alt_p = Path("/run/media/rodri/AI") / launcher
        if alt_p.is_file():
            launcher_p = alt_p

    if not launcher_p.is_file():
        err = f"Error: launcher script not found: {launcher}"
        if json_mode:
            print(json.dumps({"status": "error", "message": err}, indent=2))
        else:
            sys.stderr.write(f"❌ [local-llm] {err}\n")
        sys.exit(1)

    sys.stderr.write(f"[local-llm] Launching LLM daemon in background via {launcher_p}...\n")
    proc = subprocess.Popen(["bash", str(launcher_p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    res = {"status": "started", "pid": proc.pid, "launcher": str(launcher_p), "online": False}

    if json_mode:
        print(json.dumps(res, indent=2))
    else:
        sys.stderr.write(f"[local-llm] Process started (pid {proc.pid}). Loading model into dual-GPU VRAM takes ~15-20s.\n")
        sys.stderr.write("           Run `scripts/llm_client.py doctor` to monitor readiness.\n")
    return res


def emit(res: str, args) -> None:
    """Write the result, keeping as much of it out of the caller's context as asked.

    --out       full payload goes to disk, confirmation to stderr (or JSON with 'out' on stdout)
    --json      wrap the reply in JSON
    --project   keep only these JSON keys (implies --json)
    """
    payload = {"content": res, "model": load_config().get("model_name", "qwen3.6-35b-genesis")}

    if getattr(args, "project", None):
        keys = [k.strip() for k in args.project.split(",") if k.strip()]
        missing = [k for k in keys if k not in payload]
        if missing:
            raise SystemExit(f"[local-llm] unknown field(s): {', '.join(missing)} (available: {', '.join(payload)})")
        payload = {k: payload[k] for k in keys}

    is_json = getattr(args, "json", False) or getattr(args, "project", False)
    text = json.dumps(payload, ensure_ascii=False) if is_json else res

    if getattr(args, "out", None):
        Path(args.out).write_text(text, encoding="utf-8")
        if is_json:
            print(json.dumps({"status": "ok", "out": args.out, "bytes": len(text), **payload}, indent=2))
        else:
            sys.stderr.write(f"[local-llm] written to {args.out} ({len(text)} chars)\n")
            print(f"Written to {args.out}")
    else:
        if is_json:
            print(text)
        else:
            print(res)


def main():
    p = argparse.ArgumentParser(description="local-llm — local LLM client (:8080)")
    sub = p.add_subparsers(dest="cmd")

    # chat
    chat_p = sub.add_parser("chat", help="Send a prompt to local model (:8080)")
    chat_p.add_argument("prompt", help="Prompt or instruction")
    chat_p.add_argument("--system", help="Optional system instruction")
    chat_p.add_argument("--stream", action="store_true", help="Stream response tokens in real-time")
    chat_p.add_argument("--temp", type=float, default=0.7, metavar="TEMPERATURE", help="Sampling temperature (default: 0.7)")
    chat_p.add_argument("--max-tokens", type=int, default=4096, metavar="LIMIT", help="Max completion tokens (default: 4096)")
    chat_p.add_argument("--out", help="Buffer output to disk file")
    chat_p.add_argument("--json", action="store_true", help="Wrap the reply in JSON")
    chat_p.add_argument("--project", help="Keep only these JSON fields, e.g. content")
    chat_p.add_argument("--fallback", action="store_true", help="Fallback to cloud if :8080 is offline")
    chat_p.add_argument("--no-autostart", action="store_true", help="Skip auto-starting the local LLM server via vram-rig-ctl before reporting offline")

    # models
    models_p = sub.add_parser("models", help="List available model candidates registered for :8080")
    models_p.add_argument("--status", choices=["all", "candidate", "retired", "legacy"], default="all", help="Filter by candidate status")
    models_p.add_argument("--json", action="store_true", help="Emit JSON formatted list of models")

    # doctor
    doc_p = sub.add_parser("doctor", help="Check status of port :8080 and model daemon")
    doc_p.add_argument("--json", action="store_true", help="Output diagnostic health check in JSON format")

    # start
    start_p = sub.add_parser("start", help="Launch LLM server daemon in background")
    start_p.add_argument("--launcher", help="Path or filename of launcher script to start")
    start_p.add_argument("--json", action="store_true", help="Output start status in JSON format")

    # If first arg is not a subcommand, default to chat
    if len(sys.argv) > 1 and sys.argv[1] not in ("chat", "models", "doctor", "start", "-h", "--help"):
        args = p.parse_args(["chat"] + sys.argv[1:])
    else:
        args = p.parse_args()

    if args.cmd == "chat":
        if is_genesis_online():
            res = call_local_genesis(args.prompt, system=args.system, stream=args.stream, temperature=args.temp, max_tokens=args.max_tokens)
            if not args.stream:
                emit(res, args)
        elif args.fallback:
            sys.stderr.write("[local-llm] :8080 offline. Dispatching to cloud fallback...\n")
            res = call_cloud_fallback(args.prompt, system=args.system)
            emit(res, args)
        elif not getattr(args, "no_autostart", False) and ensure_genesis():
            res = call_local_genesis(args.prompt, system=args.system, stream=args.stream, temperature=args.temp, max_tokens=args.max_tokens)
            if not args.stream:
                emit(res, args)
        else:
            sys.stderr.write("⚠️ [local-llm] LLM is not running on :8080.\n")
            sys.stderr.write("   Start server: bash /run/media/rodri/AI/sh/luffy_nothink.sh\n")
            sys.stderr.write("   Or run `scripts/llm_client.py start` to launch it in background.\n")
            sys.stderr.write("   Or pass `--fallback` to use OpenRouter Free / Gemini.\n")
            if getattr(args, "json", False):
                print(json.dumps({"error": "server_offline", "port": 8080, "hint": "use --fallback or start server"}, indent=2))
            sys.exit(1)
    elif args.cmd == "models":
        list_models(status_filter=args.status, json_mode=args.json)
    elif args.cmd == "doctor":
        doctor_check(json_mode=args.json)
    elif args.cmd == "start":
        start_server(launcher_script=args.launcher, json_mode=args.json)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
