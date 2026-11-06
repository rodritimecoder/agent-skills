#!/usr/bin/env python3
"""roster.py — OpenCode Go model roster with sourced limits and tier roles.

Facts (ids, prices, monthly limits, estimated requests, privacy) are transcribed
from https://opencode.ai/v2/docs/console/go/ and https://opencode.ai/go on
2026-10-25. Ids are what the provider actually serves: `--verify` re-checks them
against `opencode models` and fails when the catalog has moved.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

PROVIDER = "opencode-go"
DOCS_URL = "https://opencode.ai/v2/docs/console/go/"
CAPTURED = "2026-10-25"

TIERS = {1: "frontier", 2: "flash", 3: "specialist"}
RUNGS = {1: "harpoon", 2: "lure", 3: "specialist"}
ROLES = ("judge", "builder", "specialist")

MODELS: List[Dict[str, Any]] = [
    # ── Tier 1: judges and architects. Tight allowances, highest price per token.
    {
        "id": "claude-haiku-5-5",
        "name": "Claude Haiku 5.5",
        "tier": 1,
        "role": "judge",
        "req_5h": 3850,
        "monthly": 15,
        "price_in": 0.10,
        "price_out": 0.50,
        "cached_read": 0.01,
        "trains": False,
        "retention": "30 days",
        "note": "price doubles above 100K tokens",
        "strengths": "Premier unbiased judge: strict schema following, zero sycophancy.",
    },
    {
        "id": "kimi-k3.1-pro",
        "name": "Kimi K3.1 Pro",
        "tier": 1,
        "role": "judge",
        "req_5h": 147,
        "monthly": 15,
        "price_in": 2.00,
        "price_out": 10.00,
        "cached_read": 0.20,
        "trains": False,
        "retention": "0 days",
        "note": "tightest allowance in the catalog",
        "strengths": "Long-horizon algorithmic reasoning and race-condition holdouts.",
    },
    {
        "id": "deepseek-v4-pro",
        "name": "DeepSeek V4 Pro",
        "tier": 1,
        "role": "judge",
        "req_5h": 1050,
        "monthly": 15,
        "price_in": 0.66,
        "price_out": 1.98,
        "cached_read": 0.022,
        "trains": False,
        "retention": "0 days (ZDR to 2026-10-31)",
        "note": "peak 01-04 and 06-10 UTC weekdays costs double",
        "strengths": "Deep AST refactoring and root-cause triage.",
    },
    {
        "id": "gpt-6-luna",
        "name": "GPT 6 Luna",
        "tier": 1,
        "role": "judge",
        "req_5h": 4230,
        "monthly": 15,
        "price_in": 0.10,
        "price_out": 0.50,
        "cached_read": 0.01,
        "trains": False,
        "retention": "30 days",
        "note": "above 272K tokens: $0.20 / $0.75",
        "strengths": "Architecture specs and holdout test authoring.",
    },
    {
        "id": "grok-4.7",
        "name": "Grok 4.7",
        "tier": 1,
        "role": "judge",
        "req_5h": 169,
        "monthly": 15,
        "price_in": 2.00,
        "price_out": 6.00,
        "cached_read": 0.50,
        "trains": False,
        "retention": "30 days",
        "note": "above 200K tokens: $4.00 / $12.00",
        "strengths": "Adversarial review: names failure modes instead of approving.",
    },
    {
        "id": "gpt-5.6-luna",
        "name": "GPT 5.6 Luna",
        "tier": 1,
        "role": "judge",
        "req_5h": 2050,
        "monthly": 15,
        "price_in": 0.20,
        "price_out": 1.20,
        "cached_read": 0.02,
        "trains": False,
        "retention": "30 days",
        "note": "above 272K tokens: $0.40 / $1.80",
        "strengths": "Deterministic tool calling and schema generation.",
    },
    {
        "id": "gemini-4-argon",
        "name": "Gemini 4 Argon",
        "tier": 1,
        "role": "judge",
        "req_5h": 440,
        "monthly": 30,
        "price_in": 2.00,
        "price_out": 10.00,
        "cached_read": 0.10,
        "trains": False,
        "retention": "0 days",
        "note": "50% discount runs through 2026-11-30 ($4/$20 after)",
        "strengths": "Wide-context cross-referencing across modules.",
    },
    {
        "id": "qwen3.8-max",
        "name": "Qwen3.8 Max",
        "tier": 1,
        "role": "judge",
        "req_5h": 160,
        "monthly": 15,
        "price_in": 2.00,
        "price_out": 6.00,
        "cached_read": 0.25,
        "trains": False,
        "retention": "0 days",
        "note": "",
        "strengths": "Polyglot rewrites and migrations where the whole shape changes.",
    },

    # ── Tier 2: the flash swarm. Cheap tokens, huge allowances, run in worktrees.
    {
        "id": "deepseek-v4.1-flash",
        "name": "DeepSeek V4.1 Flash",
        "tier": 2,
        "role": "builder",
        "req_5h": 34670,
        "monthly": 80,
        "price_in": 0.15,
        "price_out": 0.60,
        "cached_read": 0.003,
        "trains": False,
        "retention": "0 days (ZDR to 2026-10-31)",
        "note": "peak 01-04 and 06-10 UTC weekdays: $0.30 / $1.20",
        "strengths": "Highest allowance of any paid model. Clean diffs, few missing imports.",
    },
    {
        "id": "glm-5.3-flash",
        "name": "GLM-5.3-Flash",
        "tier": 2,
        "role": "builder",
        "req_5h": 6320,
        "monthly": 60,
        "price_in": 0.15,
        "price_out": 0.50,
        "cached_read": 0.03,
        "trains": False,
        "retention": "0 days",
        "note": "",
        "strengths": "Structured code and shell/script authoring; strong JSON discipline.",
    },
    {
        "id": "mimo-v2.6-flash",
        "name": "MiMo-V2.6-Flash",
        "tier": 2,
        "role": "builder",
        "req_5h": 30100,
        "monthly": 60,
        "price_in": 0.14,
        "price_out": 0.28,
        "cached_read": 0.0028,
        "trains": False,
        "retention": "0 days",
        "note": "cheapest output token in the catalog",
        "strengths": "Bulk parallel builders: regex, sed, unit-test scaffolds.",
    },
    {
        "id": "qwen3.8-flash",
        "name": "Qwen3.8 Flash",
        "tier": 2,
        "role": "builder",
        "req_5h": 5400,
        "monthly": 30,
        "price_in": 0.15,
        "price_out": 0.47,
        "cached_read": 0.016,
        "trains": False,
        "retention": "0 days",
        "note": "",
        "strengths": "Boilerplate classes, types and test bodies at speed.",
    },
    {
        "id": "minimax-m3.1-flash",
        "name": "MiniMax M3.1 Flash",
        "tier": 2,
        "role": "builder",
        "req_5h": 3880,
        "monthly": 20,
        "price_in": 0.15,
        "price_out": 0.60,
        "cached_read": 0.015,
        "trains": False,
        "retention": "0 days",
        "note": "small monthly allowance for its price tier",
        "strengths": "Whole-file rewrites where truncation is the usual failure.",
    },
    {
        "id": "qwen3.7-plus",
        "name": "Qwen3.7 Plus",
        "tier": 2,
        "role": "builder",
        "req_5h": 4300,
        "monthly": 60,
        "price_in": 0.40,
        "price_out": 1.60,
        "cached_read": 0.04,
        "trains": False,
        "retention": "0 days",
        "note": "above 256K tokens: $1.20 / $4.80",
        "strengths": "General refactoring workhorse with a large weekly allowance.",
    },
    {
        "id": "kimi-k2.7-code",
        "name": "Kimi K2.7 Code",
        "tier": 2,
        "role": "builder",
        "req_5h": 1350,
        "monthly": 60,
        "price_in": 0.95,
        "price_out": 4.00,
        "cached_read": 0.19,
        "trains": False,
        "retention": "0 days",
        "note": "",
        "strengths": "Pinpoint bug patches and syntax corrections.",
    },
    {
        "id": "glm-5.2",
        "name": "GLM-5.2",
        "tier": 2,
        "role": "builder",
        "req_5h": 880,
        "monthly": 60,
        "price_in": 1.40,
        "price_out": 4.40,
        "cached_read": 0.26,
        "trains": False,
        "retention": "0 days",
        "note": "same price as GLM-5.3 with a 4x allowance",
        "strengths": "Backup when GLM-5.3 upstream is loaded.",
    },

    # ── Tier 3: specialists, long context, and the free/frontier oddities.
    {
        "id": "step-5-preview",
        "name": "Step 5 Preview",
        "tier": 3,
        "role": "specialist",
        "req_5h": 430,
        "monthly": 15,
        "price_in": 1.00,
        "price_out": 2.70,
        "cached_read": 0.10,
        "trains": False,
        "retention": "0 days",
        "note": "",
        "strengths": "Step-by-step logic tracing and state-machine verification.",
    },
    {
        "id": "mimo-v2.6-pro",
        "name": "MiMo-V2.6-Pro",
        "tier": 3,
        "role": "specialist",
        "req_5h": 3250,
        "monthly": 15,
        "price_in": 0.435,
        "price_out": 0.87,
        "cached_read": 0.003625,
        "trains": False,
        "retention": "0 days",
        "note": "",
        "strengths": "Reasoning bridge between flash and frontier tiers.",
    },
    {
        "id": "kimi-k3",
        "name": "Kimi K3",
        "tier": 3,
        "role": "specialist",
        "req_5h": 110,
        "monthly": 15,
        "price_in": 3.00,
        "price_out": 15.00,
        "cached_read": 0.30,
        "trains": False,
        "retention": "0 days",
        "note": "110 requests per 5 hours: reserve for one hard problem",
        "strengths": "Hardest algorithmic circuits; costly in both dollars and allowance.",
    },
    {
        "id": "longcat-2.0",
        "name": "LongCat-2.0",
        "tier": 3,
        "role": "specialist",
        "req_5h": 11400,
        "monthly": 60,
        "price_in": 0.30,
        "price_out": 1.20,
        "cached_read": 0.006,
        "trains": False,
        "retention": "0 days",
        "note": "cheapest cached read among the paid models",
        "strengths": "Repository-wide reading and documentation ingestion.",
    },
    {
        "id": "minimax-m3",
        "name": "MiniMax M3",
        "tier": 3,
        "role": "specialist",
        "req_5h": 3200,
        "monthly": 60,
        "price_in": 0.30,
        "price_out": 1.20,
        "cached_read": 0.06,
        "trains": False,
        "retention": "0 days",
        "note": "served through the Anthropic-shaped endpoint per the docs table",
        "strengths": "Long specification analysis and PR summary synthesis.",
    },
    {
        "id": "glm-5.3",
        "name": "GLM-5.3",
        "tier": 3,
        "role": "specialist",
        "req_5h": 220,
        "monthly": 15,
        "price_in": 1.40,
        "price_out": 4.40,
        "cached_read": 0.26,
        "trains": False,
        "retention": "0 days",
        "note": "the full model costs 80x the flash allowance",
        "strengths": "Interface and schema design where the flash model drifts.",
    },
    {
        "id": "mimo-v2.5-pro",
        "name": "MiMo-V2.5-Pro",
        "tier": 3,
        "role": "specialist",
        "req_5h": 3250,
        "monthly": 15,
        "price_in": 0.435,
        "price_out": 0.87,
        "cached_read": 0.003625,
        "trains": False,
        "retention": "0 days",
        "note": "",
        "strengths": "Same price and allowance as V2.6 Pro; keep as a fallback.",
    },
    {
        "id": "mimo-v2.5",
        "name": "MiMo-V2.5",
        "tier": 3,
        "role": "specialist",
        "req_5h": 30100,
        "monthly": 60,
        "price_in": 0.14,
        "price_out": 0.28,
        "cached_read": 0.0028,
        "trains": False,
        "retention": "0 days",
        "note": "identical numbers to V2.6 Flash; either fills the volume lane",
        "strengths": "Everyday assistant work at the cheapest paid rate.",
    },
    {
        "id": "muse-spark-1.3-contributor",
        "name": "Muse Spark 1.3 Contributor",
        "tier": 3,
        "role": "specialist",
        "req_5h": 45300,
        "monthly": 60,
        "price_in": 0.10,
        "price_out": 0.20,
        "cached_read": 0.002,
        "trains": True,
        "retention": "Not ZDR",
        "note": "trains on your prompts; limited regions; highest allowance in the catalog",
        "strengths": "Bulk volume only, and only if you accept training on your code.",
    },
    {
        "id": "muse-spark-1.2-contributor",
        "name": "Muse Spark 1.2 Contributor",
        "tier": 3,
        "role": "specialist",
        "req_5h": 45300,
        "monthly": 60,
        "price_in": 0.10,
        "price_out": 0.20,
        "cached_read": 0.002,
        "trains": True,
        "retention": "Not ZDR",
        "note": "trains on your prompts; limited regions",
        "strengths": "Second ensemble opinion that carries the same data term.",
    },
    {
        "id": "hy4-preview",
        "name": "Hy4 preview",
        "tier": 3,
        "role": "specialist",
        "req_5h": 1350,
        "monthly": 30,
        "price_in": 0.834,
        "price_out": 2.501,
        "cached_read": 0.042,
        "trains": False,
        "retention": "0 days",
        "note": "",
        "strengths": "Experimental architecture checks in a sandbox.",
    },
    {
        "id": "hy3",
        "name": "Hy3",
        "tier": 3,
        "role": "specialist",
        "req_5h": 4300,
        "monthly": 60,
        "price_in": 0.14,
        "price_out": 0.58,
        "cached_read": 0.035,
        "trains": False,
        "retention": "0 days",
        "note": "",
        "strengths": "Cheap generalist with a large allowance.",
    },
    {
        "id": "beam-free",
        "name": "Beam Free",
        "tier": 3,
        "role": "specialist",
        "req_5h": None,
        "monthly": None,
        "price_in": 0.0,
        "price_out": 0.0,
        "cached_read": 0.0,
        "trains": False,
        "retention": "30 days",
        "note": "free for a limited time; not available in 22 listed regions",
        "strengths": "Zero-cost long reads while the promotion lasts.",
    },
    {
        "id": "iceman-contributor-free",
        "name": "Iceman Contributor Free",
        "tier": 3,
        "role": "specialist",
        "req_5h": None,
        "monthly": None,
        "price_in": 0.0,
        "price_out": 0.0,
        "cached_read": 0.0,
        "trains": None,
        "retention": "unpublished",
        "documented": False,
        "note": "served but absent from the plan docs; terms unknown, assume the name is literal",
        "strengths": "Free, undocumented. Do not put private code through it until its terms are known.",
    },
]


def documented(model: Dict[str, Any]) -> bool:
    return model.get("documented", True)


def rung(model: Dict[str, Any]) -> str:
    if model["price_in"] == 0 and model["price_out"] == 0:
        return "free"
    return RUNGS[model["tier"]]


def ordered(rows: List[Dict[str, Any]], profile: Optional[Tuple[int, int, int]] = None) -> List[Dict[str, Any]]:
    """Tier first, then cheapest request first, then id. Price is measurable; capability is not."""
    def key(model: Dict[str, Any]) -> Tuple[int, float, str]:
        cost = cost_per_request(model, profile)
        return (model["tier"], float("inf") if cost is None else cost, model["id"])

    return sorted(rows, key=key)


def diff_catalog(live_ids: List[str]) -> Tuple[List[str], List[str]]:
    curated = [m["id"] for m in MODELS]
    missing = [mid for mid in curated if mid not in live_ids]
    extra = [mid for mid in live_ids if mid not in curated]
    return missing, extra


# (input, cached read, output) tokens per request. These are the profiles OpenCode
# used to publish its own request estimates, so the arithmetic below can be checked
# against the documented numbers instead of trusting it.
PROFILES: Dict[str, Tuple[int, int, int]] = {
    "claude-haiku-5-5": (1100, 55000, 240),
    "kimi-k3.1-pro": (1050, 76500, 300),
    "deepseek-v4-pro": (750, 82000, 290),
    "gpt-6-luna": (1000, 50000, 220),
    "grok-4.7": (390, 32500, 120),
    "gpt-5.6-luna": (1000, 50000, 220),
    "qwen3.8-max": (420, 66000, 200),
    "deepseek-v4.1-flash": (410, 71300, 310),
    "glm-5.3-flash": (1000, 55000, 200),
    "mimo-v2.6-flash": (830, 71500, 295),
    "qwen3.8-flash": (600, 58000, 200),
    "minimax-m3.1-flash": (500, 49400, 360),
    "qwen3.7-plus": (500, 57000, 190),
    "kimi-k2.7-code": (870, 55000, 200),
    "glm-5.2": (700, 52000, 150),
    "step-5-preview": (1000, 55000, 200),
    "mimo-v2.6-pro": (790, 86000, 305),
    "kimi-k3": (1050, 76500, 300),
    "longcat-2.0": (920, 88900, 200),
    "minimax-m3": (510, 56000, 190),
    "glm-5.3": (700, 52000, 150),
    "mimo-v2.5-pro": (790, 86000, 305),
    "mimo-v2.5": (830, 71500, 295),
    "muse-spark-1.3-contributor": (620, 71400, 300),
    "muse-spark-1.2-contributor": (620, 71400, 300),
    "hy4-preview": (830, 71500, 295),
    "hy3": (830, 71500, 295),
}


def cost_per_request(model: Dict[str, Any], profile: Optional[Tuple[int, int, int]] = None) -> Optional[float]:
    tokens = profile or PROFILES.get(model["id"])
    if tokens is None:
        return None
    tokens_in, tokens_cached, tokens_out = tokens
    return (
        tokens_in * model["price_in"]
        + tokens_cached * model["cached_read"]
        + tokens_out * model["price_out"]
    ) / 1_000_000


def window_allowance(model: Dict[str, Any], hours: float) -> Optional[float]:
    if model["monthly"] is None:
        return None
    return model["monthly"] * min(1.0, 0.2 * (hours / 5.0))


def estimate_requests(model: Dict[str, Any], hours: float = 5.0) -> Optional[int]:
    allowance = window_allowance(model, hours)
    per_request = cost_per_request(model)
    if allowance is None or not per_request:
        return None
    return int(allowance / per_request)


def parse_lanes(spec: str) -> List[Tuple[str, int]]:
    lanes: List[Tuple[str, int]] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        model_id, _, agents_text = chunk.partition(":")
        agents = int(agents_text) if agents_text.strip() else 1
        if agents < 1:
            raise ValueError(f"{model_id}: agents must be at least 1")
        lanes.append((model_id.strip(), agents))
    ids = [lane[0] for lane in lanes]
    repeated = sorted({mid for mid in ids if ids.count(mid) > 1})
    if repeated:
        raise ValueError(f"one lane per model; listed twice: {', '.join(repeated)}")
    return lanes


def plan_lanes(
    lanes: List[Tuple[str, int]],
    hours: float = 5.0,
    profile: Optional[Tuple[int, int, int]] = None,
) -> List[Dict[str, Any]]:
    by_id = {m["id"]: m for m in MODELS}
    rows = []
    for model_id, agents in lanes:
        model = by_id.get(model_id)
        if model is None:
            raise KeyError(model_id)
        allowance = window_allowance(model, hours)
        per_request = cost_per_request(model, profile)
        if allowance is None:
            tasks_per_agent: Optional[int] = None
        elif per_request is None:
            tasks_per_agent = None
        else:
            tasks_per_agent = int(allowance / (per_request * agents))
        rows.append(
            {
                "model": model,
                "agents": agents,
                "per_request": per_request,
                "allowance": allowance,
                "tasks_per_agent": tasks_per_agent,
                "tasks_total": None if tasks_per_agent is None else tasks_per_agent * agents,
                "spend": None
                if tasks_per_agent is None or per_request is None
                else tasks_per_agent * agents * per_request,
            }
        )
    return rows


def render_plan(rows: List[Dict[str, Any]], hours: float) -> str:
    headers = ["Lane", "Agents", "$/task", f"Allowance/{hours:g}h", "Tasks/agent", f"Tasks/{hours:g}h", "Spend"]
    widths = {"Lane": 27, "Agents": 6, "$/task": 9, f"Allowance/{hours:g}h": 13, "Tasks/agent": 11, f"Tasks/{hours:g}h": 12, "Spend": 9}

    def cell(text: str, width: int) -> str:
        return text[:width].ljust(width)

    lines = [
        "| " + " | ".join(cell(h, widths[h]) for h in headers) + " |",
        "|" + "|".join("-" * widths[h] for h in headers) + "|",
    ]
    for row in rows:
        model = row["model"]
        if row["per_request"] is None:
            per_task, tasks, total, spend = "unknown", "?", "?", "?"
        elif row["allowance"] is None:
            per_task, tasks, total, spend = f"{row['per_request']:.4f}", "∞", "∞", "free"
        else:
            per_task = f"{row['per_request']:.4f}"
            tasks = f"{row['tasks_per_agent']:,}" if row["tasks_per_agent"] is not None else "?"
            total = f"{row['tasks_total']:,}" if row["tasks_total"] is not None else "?"
            spend = f"${row['spend']:,.2f}" if row["spend"] is not None else "?"
        cells = [
            model["id"],
            str(row["agents"]),
            per_task,
            money(row["allowance"]),
            tasks,
            total,
            spend,
        ]
        lines.append("| " + " | ".join(cell(c, widths[h]) for c, h in zip(cells, headers)) + " |")
    return "\n".join(lines)


def live_catalog(timeout: int = 60) -> Tuple[Optional[List[str]], Optional[str]]:
    exe = shutil.which("opencode")
    if not exe:
        return None, "the opencode CLI is not on PATH"
    try:
        proc = subprocess.run([exe, "models"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"could not run `opencode models`: {exc}"
    if proc.returncode != 0:
        return None, f"`opencode models` exited {proc.returncode}"
    ids = [
        line.strip().split("/", 1)[1]
        for line in proc.stdout.splitlines()
        if line.strip().startswith(PROVIDER + "/")
    ]
    if not ids:
        return None, f"no {PROVIDER}/ models listed"
    return ids, None


def cmd_check() -> int:
    ids, err = live_catalog()
    print("🔍 [OpenCode Go — live catalog]")
    if ids is None:
        print(f"  status      : ⚪ not detected ({err})")
        print("  connect     : opencode auth login → OpenCode Go → paste the console key")
        print("  alternative : /connect inside the TUI")
        return 1
    print(f"  status      : ✅ {len(ids)} models served by {PROVIDER}")
    undocumented = [m["id"] for m in MODELS if not documented(m) and m["id"] in ids]
    print(f"  documented  : {len(ids) - len(undocumented)} on the plan page, {len(undocumented)} served only" +
          (f" ({', '.join(undocumented)})" if undocumented else ""))
    print(f"  call form   : {PROVIDER}/<id>  e.g. {PROVIDER}/deepseek-v4.1-flash")
    print(f"  run         : opencode run -m {PROVIDER}/<id> \"prompt\"")
    missing, extra = diff_catalog(ids)
    if missing or extra:
        print(f"  drift       : {len(missing)} roster-only, {len(extra)} catalog-only — run --verify")
    else:
        print("  drift       : none, roster matches the catalog")
    return 0


def cmd_verify() -> int:
    ids, err = live_catalog()
    if ids is None:
        print(f"error: {err}", file=sys.stderr)
        return 2
    missing, extra = diff_catalog(ids)
    if not missing and not extra:
        print(f"✅ roster matches all {len(ids)} served {PROVIDER} models")
        return 0
    if missing:
        print("❌ in the roster, no longer served:")
        for mid in missing:
            print(f"   - {PROVIDER}/{mid}")
    if extra:
        print("❌ served, missing from the roster:")
        for mid in extra:
            print(f"   + {PROVIDER}/{mid}")
    print(f"\nUpdate MODELS in {sys.argv[0]} and {DOCS_URL}")
    return 1


def money(value: Optional[float]) -> str:
    if value is None:
        return "∞"
    if value == 0:
        return "free"
    return f"${value:g}"


def render_table(rows: List[Dict[str, Any]], profile: Optional[Tuple[int, int, int]] = None) -> str:
    headers = ["Rung", "Model", "ID", "Role", "Req/5h", "Monthly", "In/Out", "Trains", "Use"]
    widths = {"Rung": 10, "Model": 26, "ID": 27, "Role": 10, "Req/5h": 9, "Monthly": 7, "In/Out": 11, "Trains": 6, "Use": 44}

    def cell(text: str, width: int) -> str:
        return text[:width].ljust(width)

    lines = [
        "| " + " | ".join(cell(h, widths[h]) for h in headers) + " |",
        "|" + "|".join("-" * widths[h] for h in headers) + "|",
    ]
    for row in ordered(rows, profile):
        req = "∞" if row["req_5h"] is None else f"{row['req_5h']:,}"
        trains = "no" if row["trains"] is False else ("YES" if row["trains"] else "?")
        if row["price_in"] == 0 and row["price_out"] == 0:
            price = "free"
        else:
            price = f"{row['price_in']:g}/{row['price_out']:g}"
        cells = [
            rung(row),
            row["name"],
            row["id"],
            row["role"],
            req,
            money(row["monthly"]),
            price,
            trains,
            row["strengths"],
        ]
        lines.append("| " + " | ".join(cell(c, widths[h]) for c, h in zip(cells, headers)) + " |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenCode Go roster, limits and tier roles")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3], help="1=frontier judges, 2=flash builders, 3=specialists")
    parser.add_argument("--role", choices=ROLES, help="Filter by operational role")
    parser.add_argument("--free", action="store_true", help="Only models with no monthly dollar limit")
    parser.add_argument("--json", action="store_true", help="Machine-readable output for swarm routers")
    parser.add_argument("--check", action="store_true", help="Is the provider connected, and does the roster match it")
    parser.add_argument("--verify", action="store_true", help="Fail when an id in the roster is no longer served")
    parser.add_argument("--plan", metavar="SPEC", help='Lanes as "model:agents,..." e.g. "deepseek-v4.1-flash:3,glm-5.3-flash:2"')
    parser.add_argument("--hours", type=float, default=5.0, help="Block length for --plan (default 5)")
    parser.add_argument("--profile", metavar="IN,CACHED,OUT", help="Override tokens per request for every lane")
    args = parser.parse_args()

    if args.check:
        return cmd_check()
    if args.verify:
        return cmd_verify()

    if args.plan:
        profile = None
        if args.profile:
            try:
                profile = tuple(int(part) for part in args.profile.split(","))  # type: ignore[assignment]
            except ValueError:
                print("error: --profile wants three integers: input,cached,output", file=sys.stderr)
                return 2
            if len(profile) != 3:
                print("error: --profile wants three integers: input,cached,output", file=sys.stderr)
                return 2
        try:
            lanes = parse_lanes(args.plan)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        try:
            rows = plan_lanes(lanes, args.hours, profile)
        except KeyError as exc:
            print(f"error: no such model in the roster: {exc.args[0]}", file=sys.stderr)
            print("       run --verify, or list the ids with no flags", file=sys.stderr)
            return 2
        print(f"### Sizing plan — {args.hours:g}-hour block, {sum(r['agents'] for r in rows)} agents")
        print()
        print(render_plan(rows, args.hours))
        print()
        finite = [r for r in rows if r["tasks_total"] is not None]
        if finite:
            total = sum(r["tasks_total"] for r in finite)
            spend = sum(r["spend"] or 0 for r in finite)
            print(f"Total: ~{total:,} tasks of this size, ${spend:,.2f} of allowance spent.")
        print("Allowance = monthly limit x 20% per 5 hours (weekly 50%, monthly 100%).")
        print("A 'task' here is one request at the documented token profile; a real task is usually several.")
        return 0

    rows = MODELS
    if args.tier:
        rows = [m for m in rows if m["tier"] == args.tier]
    if args.role:
        rows = [m for m in rows if m["role"] == args.role]
    if args.free:
        rows = [m for m in rows if m["price_in"] == 0 and m["price_out"] == 0]

    if args.json:
        payload = [dict(model, rung=rung(model)) for model in ordered(rows)]
        print(json.dumps({"captured": CAPTURED, "source": DOCS_URL, "protocol": f"{PROVIDER}/<id>", "models": payload}, indent=2))
        return 0

    print(f"### OpenCode Go roster ({len(rows)} models, cheapest first within each rung)")
    print()
    print(render_table(rows))
    print()
    print(f"Prices are $ per 1M tokens. Monthly is the Go plan's dollar allowance; 5h = 20% of it.")
    print(f"Source: {DOCS_URL} (captured {CAPTURED}). Verify ids with --verify.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
