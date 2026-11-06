#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

CONFIG_DIR = Path.home() / ".config" / "eval-router"
DB_PATH = CONFIG_DIR / "evals.db"
HARVEST_FILE = CONFIG_DIR / "harvest.jsonl"
WEIGHTS_FILE = CONFIG_DIR / "weights.json"

def train_from_harvest():
    if not DB_PATH.is_file():
        print("[harvest] No evals database found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT prompt, tier, eval_passed FROM evals")
    rows = cur.fetchall()
    conn.close()

    if len(rows) < 3:
        print(f"[harvest] Need at least 3 historical evaluations to train (currently {len(rows)}).")
        return

    features: Dict[str, Dict[str, float]] = {}
    counts: Dict[str, int] = {"easy": 0, "moderate": 0, "hard": 0}

    for prompt, tier, passed in rows:
        target_tier = tier
        if passed == 0:
            target_tier = "hard" if tier == "moderate" else "moderate"

        counts[target_tier] = counts.get(target_tier, 0) + 1
        tokens = set(re.findall(r"\b[a-zA-Z0-9_\-\.]{3,}\b", prompt.lower()))
        for t in tokens:
            if t not in features:
                features[t] = {"easy": 0.0, "moderate": 0.0, "hard": 0.0}
            features[t][target_tier] += 1.0

    total_samples = sum(counts.values())
    biases = {k: math.log(v / total_samples) if v > 0 else -4.0 for k, v in counts.items()}

    normalized_features: Dict[str, Dict[str, float]] = {}
    for token, weights in features.items():
        token_total = sum(weights.values())
        if token_total >= 1:
            normalized_features[token] = {
                k: round(math.log((v + 0.1) / (token_total + 0.3)), 3)
                for k, v in weights.items()
            }

    model_dump = {
        "version": "1.0",
        "total_samples": total_samples,
        "biases": biases,
        "features": normalized_features
    }

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(WEIGHTS_FILE, "w") as f:
        json.dump(model_dump, f, indent=2)

    print(f"[harvest] Successfully trained calibrated weights on {total_samples} requests with {len(normalized_features)} tokens.")
    print(f"[harvest] Weights saved to {WEIGHTS_FILE}")

def export_benchmark(out_path: str):
    if not DB_PATH.is_file():
        print("[harvest] No evals database found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT prompt, tier, eval_passed, eval_score, cost_saved_usd FROM evals")
    rows = cur.fetchall()
    conn.close()

    bench = []
    for p, tier, passed, score, saved in rows:
        bench.append({
            "prompt": p,
            "tier": tier,
            "passed": bool(passed),
            "score": score,
            "cost_saved": saved
        })

    with open(out_path, "w") as f:
        json.dump(bench, f, indent=2)

    print(f"[harvest] Exported {len(bench)} evaluation cases to {out_path}")

def main():
    p = argparse.ArgumentParser(description="Eval Router Harvesting & Continuous Calibration")
    p.add_argument("--train", action="store_true", help="Re-calibrate classifier weights from logged evaluations")
    p.add_argument("--export", metavar="FILE", help="Export evaluation benchmark dataset to JSON")
    args = p.parse_args()

    if args.train:
        train_from_harvest()
    elif args.export:
        export_benchmark(args.export)
    else:
        p.print_help()

if __name__ == "__main__":
    main()
