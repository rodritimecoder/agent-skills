#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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

def is_genesis_online(endpoint: str = "http://127.0.0.1:8080") -> bool:
    # First verify real llama-server process
    res = subprocess.run("pgrep -f 'llama-server.*Qwen3.6-35B'", shell=True, capture_output=True)
    if res.returncode != 0:
        return False

    try:
        url = f"{endpoint.rstrip('/')}/v1/models"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
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

def doctor_check() -> Dict[str, Any]:
    cfg = load_config()
    endpoint = cfg.get("default_endpoint", "http://127.0.0.1:8080")
    launcher = cfg.get("launcher_script", "")

    online = is_genesis_online(endpoint)
    proc_running = subprocess.run("pgrep -f 'luffy_nothink|Qwen3.6-35B'", shell=True, capture_output=True).returncode == 0

    print("\n" + "=" * 55)
    print(" 🏥 LLM-CLI DOCTOR — Qwen3.6-35B Genesis Status")
    print("=" * 55)
    print(f" Target Endpoint   : {endpoint}")
    print(f" Service Status    : {'ONLINE ✅' if online else 'OFFLINE ⚠️'}")
    print(f" Process Active    : {'YES (running)' if proc_running else 'NO (idle)'}")
    print(f" Launcher Path     : {launcher}")

    if not online:
        print("\n💡 Genesis 35B is not running on :8080.")
        print("   To start the dual-GPU server, run in another terminal:")
        print(f"   bash {launcher}")
        print("   (Or use `llm-cli start` to launch in background)")
    print("=" * 55 + "\n")

    return {"online": online, "process_running": proc_running, "endpoint": endpoint}

def start_server():
    cfg = load_config()
    launcher = cfg.get("launcher_script", "/run/media/rodri/AI/sh/luffy_nothink.sh")
    if is_genesis_online():
        print("[llm-cli] Genesis 35B is already running and healthy on :8080.")
        return

    print(f"[llm-cli] Launching Genesis 35B in background via {launcher}...")
    subprocess.Popen(["bash", launcher], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("[llm-cli] Server process started. Loading 22GB model into dual-GPU VRAM takes ~15-20 seconds.")
    print("           Run `llm-cli doctor` to monitor readiness.")

def main():
    p = argparse.ArgumentParser(description="llm-cli — Local Qwen3.6-35B Genesis Client")
    sub = p.add_subparsers(dest="cmd")

    chat_p = sub.add_parser("chat", help="Send a prompt to local Genesis 35B (:8080)")
    chat_p.add_argument("prompt", help="Prompt or instruction")
    chat_p.add_argument("--system", help="Optional system instruction")
    chat_p.add_argument("--stream", action="store_true", help="Stream response tokens in real-time")
    chat_p.add_argument("--temp", type=float, default=0.7, help="Temperature (default: 0.7)")
    chat_p.add_argument("--out", help="Buffer output to disk file")
    chat_p.add_argument("--fallback", action="store_true", help="Fallback to cloud if :8080 is offline")

    sub.add_parser("doctor", help="Check status of port :8080 and model daemon")
    sub.add_parser("start", help="Launch Genesis 35B server daemon in background")

    # If first arg is not a subcommand, default to chat
    if len(sys.argv) > 1 and sys.argv[1] not in ("chat", "doctor", "start", "-h", "--help"):
        args = p.parse_args(["chat"] + sys.argv[1:])
    else:
        args = p.parse_args()

    if args.cmd == "chat":
        if is_genesis_online():
            res = call_local_genesis(args.prompt, system=args.system, stream=args.stream, temperature=args.temp)
            if not args.stream:
                if args.out:
                    Path(args.out).write_text(res, encoding="utf-8")
                    print(f"[llm-cli] Response written to {args.out}")
                else:
                    print(res)
        elif args.fallback:
            print("[llm-cli] :8080 offline. Dispathing to cloud fallback...")
            res = call_cloud_fallback(args.prompt, system=args.system)
            if args.out:
                Path(args.out).write_text(res, encoding="utf-8")
                print(f"[llm-cli] Response written to {args.out}")
            else:
                print(res)
        else:
            print("⚠️ [llm-cli] Genesis 35B is not running on :8080.", file=sys.stderr)
            print("   Start server: bash /run/media/rodri/AI/sh/luffy_nothink.sh", file=sys.stderr)
            print("   Or pass `--fallback` to use OpenRouter Free / Gemini.", file=sys.stderr)
            sys.exit(1)
    elif args.cmd == "doctor":
        doctor_check()
    elif args.cmd == "start":
        start_server()
    else:
        p.print_help()

if __name__ == "__main__":
    main()
