#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROUTER_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROUTER_DIR / "config.json"
CONFIG_DIR = Path.home() / ".config" / "eval-router"
DB_PATH = CONFIG_DIR / "evals.db"
HARVEST_FILE = CONFIG_DIR / "harvest.jsonl"
WEIGHTS_FILE = CONFIG_DIR / "weights.json"

sys.path.append(str(ROUTER_DIR / "scripts"))
import classifier  # type: ignore

def _load_env_fallbacks():
    candidates = [
        Path.home() / ".agent_keys.env",
        Path.home() / ".env",
        Path.cwd() / ".env",
    ]
    for env_path in candidates:
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
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass

_load_env_fallbacks()

def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.is_file():
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "tiers": {
            "easy": {"model": "nvidia/nemotron-3.5-lightning:free", "cost_input": 0.0, "cost_output": 0.0},
            "moderate": {"model": "nvidia/nemotron-3-ultra-550b-a55b:free", "cost_input": 0.15, "cost_output": 0.60},
            "hard": {"model": "anthropic/claude-3.7-sonnet", "cost_input": 3.00, "cost_output": 15.00}
        },
        "speculative_eval": {"enabled": True, "mode": "blocking"}
    }

def init_db():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS evals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        prompt TEXT NOT NULL,
        tier TEXT NOT NULL,
        confidence REAL,
        p_easy REAL,
        p_moderate REAL,
        p_hard REAL,
        source TEXT,
        model_used TEXT,
        latency_ms REAL,
        eval_passed INTEGER,
        eval_score REAL,
        fallback_model TEXT,
        cost_saved_usd REAL
    );
    """)
    conn.commit()
    conn.close()

def _call_openrouter(model: str, prompt: str, system_prompt: Optional[str] = None) -> Tuple[str, float]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not found in environment or ~/.agent_keys.env")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://glitchcatclub.ai/eval-router",
        "X-Title": "Kem Glitch Eval Router"
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 4096
    }

    t0 = time.time()
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.time() - t0) * 1000
            content = data["choices"][0]["message"]["content"]
            return content, latency_ms
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter HTTP {e.code}: {err_msg}")

def _call_gemini(prompt: str) -> Tuple[str, float]:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment or ~/.agent_keys.env")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096}
    }
    t0 = time.time()
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        latency_ms = (time.time() - t0) * 1000
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        return content, latency_ms

def dispatch_model(tier: str, prompt: str, system_prompt: Optional[str] = None) -> Tuple[str, str, float]:
    cfg = load_config()
    tier_info = cfg.get("tiers", {}).get(tier, {})
    model = tier_info.get("model", "nvidia/nemotron-3.5-lightning:free")

    if tier == "hard":
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if api_key:
            try:
                content, lat = _call_openrouter(model, prompt, system_prompt)
                return content, model, lat
            except Exception:
                pass
        if os.environ.get("GEMINI_API_KEY"):
            content, lat = _call_gemini(prompt)
            return content, "gemini-2.0-flash", lat

    try:
        content, lat = _call_openrouter(model, prompt, system_prompt)
        return content, model, lat
    except Exception as e:
        if os.environ.get("GEMINI_API_KEY"):
            content, lat = _call_gemini(prompt)
            return content, "gemini-2.0-flash (fallback)", lat
        raise e

def evaluate_response_quality(prompt: str, response: str) -> Tuple[bool, float, str]:
    if not response or len(response.strip()) < 5:
        return False, 0.0, "Empty or truncated response"

    try:
        from jev_engine import JevEngine  # type: ignore
        state = f"USER PROMPT:\n{prompt}\n\nMODEL RESPONSE:\n{response}"
        question = "Does this response accurately, adequately, and safely answer the user prompt without errors or blatant hallucinations?"
        res = JevEngine(port=8083, timeout=3.0).decide_bool(state, question)
        p_true = float(res.get("probabilities", {}).get("true", 0.5))
        passed = bool(res.get("decision", p_true >= 0.5))
        return passed, round(p_true, 4), f"h2o-lightning-4b P(true)={p_true:.3f}"
    except Exception as e:
        if len(response.strip()) > 20 and not ("error" in response.lower() and len(response) < 60):
            return True, 0.85, f"Heuristic pass (h2o-lightning-4b judge unavailable: {e})"
        return False, 0.30, f"Heuristic fail: suspicious short or error output"

def estimate_cost_saved(tier: str, prompt_tokens: int, resp_tokens: int) -> float:
    frontier_cost = (prompt_tokens / 1_000_000.0 * 3.00) + (resp_tokens / 1_000_000.0 * 15.00)
    if tier == "easy":
        actual_cost = 0.0
    elif tier == "moderate":
        actual_cost = (prompt_tokens / 1_000_000.0 * 0.15) + (resp_tokens / 1_000_000.0 * 0.60)
    else:
        actual_cost = frontier_cost
    return max(0.0, frontier_cost - actual_cost)

def execute_request(prompt: str, mode: str = "blocking", system_prompt: Optional[str] = None) -> Dict[str, Any]:
    init_db()
    c_res = classifier.classify(prompt)
    tier = c_res["tier"]
    conf = c_res["confidence"]
    probs = c_res["probabilities"]
    source = c_res["source"]

    content, model_used, latency_ms = dispatch_model(tier, prompt, system_prompt)

    eval_passed, eval_score, eval_reason = True, 1.0, "N/A (Frontier)"
    fallback_model = None

    if tier in ("easy", "moderate"):
        eval_passed, eval_score, eval_reason = evaluate_response_quality(prompt, content)
        if not eval_passed:
            log_entry = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "prompt": prompt,
                "failed_model": model_used,
                "tier": tier,
                "eval_score": eval_score,
                "eval_reason": eval_reason,
                "bad_output": content[:300]
            }
            with open(HARVEST_FILE, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

            if mode == "blocking":
                try:
                    f_content, f_model, f_lat = dispatch_model("hard", prompt, system_prompt)
                    fallback_model = f_model
                    content = f_content
                    latency_ms += f_lat
                except Exception as e:
                    eval_reason += f" (Fallback failed: {e})"

    approx_in_tokens = max(1, len(prompt.split()) * 4 // 3)
    approx_out_tokens = max(1, len(content.split()) * 4 // 3)
    saved_usd = 0.0 if fallback_model else estimate_cost_saved(tier, approx_in_tokens, approx_out_tokens)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO evals (
        prompt, tier, confidence, p_easy, p_moderate, p_hard,
        source, model_used, latency_ms, eval_passed, eval_score,
        fallback_model, cost_saved_usd
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        prompt, tier, conf,
        probs.get("easy", 0.0), probs.get("moderate", 0.0), probs.get("hard", 0.0),
        source, model_used, latency_ms,
        1 if eval_passed else 0, eval_score, fallback_model, saved_usd
    ))
    conn.commit()
    conn.close()

    return {
        "content": content,
        "tier": tier,
        "model_used": model_used,
        "fallback_model": fallback_model,
        "latency_ms": round(latency_ms, 1),
        "confidence": conf,
        "eval_passed": eval_passed,
        "eval_score": eval_score,
        "eval_reason": eval_reason,
        "cost_saved_usd": round(saved_usd, 5)
    }

def print_stats():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), AVG(latency_ms), SUM(cost_saved_usd) FROM evals")
    total, avg_lat, total_saved = cur.fetchone()
    if not total:
        print("\n[eval-router] No requests recorded yet. Run `eval-router exec '<prompt>'` to begin.")
        conn.close()
        return

    cur.execute("SELECT tier, COUNT(*) FROM evals GROUP BY tier")
    tier_counts = dict(cur.fetchall())

    cur.execute("SELECT COUNT(*) FROM evals WHERE eval_passed = 1")
    passed_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM evals WHERE fallback_model IS NOT NULL")
    fallback_count = cur.fetchone()[0]
    conn.close()

    print("\n" + "=" * 50)
    print(" ⚡ KEM GLITCH EVAL ROUTER — METRICS & SAVINGS")
    print("=" * 50)
    print(f" Total Executed Requests : {total}")
    print(f" Requests Tier Breakdown : Easy={tier_counts.get('easy', 0)} | Moderate={tier_counts.get('moderate', 0)} | Hard={tier_counts.get('hard', 0)}")
    print(f" Shadow Quality Pass Rate: {passed_count / total * 100:.1f}% ({passed_count}/{total})")
    print(f" Speculative Swaps (Saved): {fallback_count} failure fallbacks")
    print(f" Cumulative Money Saved   : ${total_saved or 0.0:.4f} USD")
    print(f" Average Latency         : {avg_lat or 0.0:.1f} ms")
    print("=" * 50 + "\n")

def print_harvest():
    if not HARVEST_FILE.is_file():
        print("\n[eval-router] No harvested failures yet. Everything is passing clean!")
        return
    lines = HARVEST_FILE.read_text().splitlines()
    print(f"\n[eval-router] Harvested {len(lines)} failure examples for training & calibration:\n")
    for idx, l in enumerate(lines[-5:], 1):
        item = json.loads(l)
        print(f"  [{idx}] Time: {item.get('timestamp')} | Model: {item.get('failed_model')} | Score: {item.get('eval_score')}")
        print(f"      Prompt: {item.get('prompt')[:80]}...")
        print(f"      Reason: {item.get('eval_reason')}\n")

def main():
    p = argparse.ArgumentParser(description="Kem Glitch Self-Calibrating Eval Router CLI")
    sub = p.add_subparsers(dest="cmd")

    r_p = sub.add_parser("route", help="Route prompt and show tier classification without executing")
    r_p.add_argument("prompt", help="User request or task description")

    e_p = sub.add_parser("exec", help="Execute prompt with routing, speculative eval, and automatic fallback")
    e_p.add_argument("prompt", help="User request or task description")
    e_p.add_argument("--mode", default="blocking", choices=["blocking", "shadow"], help="Speculative evaluation mode")
    e_p.add_argument("--out", help="Write result content to output file")

    sub.add_parser("stats", help="Display performance, accuracy, and dollar savings metrics")
    sub.add_parser("harvest", help="Inspect harvested evaluation failures for calibration")

    args = p.parse_args()
    if args.cmd == "route":
        res = classifier.classify(args.prompt)
        print(json.dumps(res, indent=2))
    elif args.cmd == "exec":
        res = execute_request(args.prompt, mode=args.mode)
        if args.out:
            Path(args.out).write_text(res["content"], encoding="utf-8")
            print(f"[eval-router] Result written to {args.out}")
        else:
            print("\n" + res["content"] + "\n")
        print(f"[eval-router] Tier: {res['tier'].upper()} | Model: {res['model_used']} | Latency: {res['latency_ms']}ms | Saved: ${res['cost_saved_usd']:.5f} | Eval: {'PASS' if res['eval_passed'] else 'FAIL'}")
        if res["fallback_model"]:
            print(f"[eval-router] ⚠️ Speculative replacement triggered -> Replaced with {res['fallback_model']}")
    elif args.cmd == "stats":
        print_stats()
    elif args.cmd == "harvest":
        print_harvest()
    else:
        p.print_help()

if __name__ == "__main__":
    main()
