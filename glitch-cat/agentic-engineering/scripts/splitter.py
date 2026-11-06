#!/usr/bin/env python3
"""
splitter.py — The Task Splitter & Sandbox Allocator (Kem's Step 5 & 6)
Partitions high-level tasks into parallel single-writer lanes across isolated sandboxes.
"""

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_TIERS = [
    {"sandbox": "lane-1-agy", "model": "agy-subagent", "role": "Deep Architecture, AST Refactor & Orchestration"},
    {"sandbox": "lane-2-nim-glm", "model": "glm-5.3-lite", "role": "Fast Component Scaffolding, UI & DOM Layout"},
    {"sandbox": "lane-3-nim-deepseek", "model": "deepseek-r1", "role": "Complex Algorithmic Reasoning & Graph Physics"},
    {"sandbox": "lane-4-gemini", "model": "gemini-2.5-flash", "role": "API Schema Integration, Notes & Data Synthesis"},
    {"sandbox": "lane-5-openrouter", "model": "openrouter-free", "role": "Adversarial Test Lanes & Boundary Regressions"}
]


def split_task(title: str, subtasks: list[str] = None) -> dict:
    if not subtasks:
        subtasks = [f"{title} - Component A", f"{title} - Component B", f"{title} - Component C"]

    plan = {
        "title": title,
        "total_lanes": len(subtasks),
        "lanes": []
    }

    for idx, st in enumerate(subtasks):
        tier = DEFAULT_TIERS[idx % len(DEFAULT_TIERS)]
        lane = {
            "lane_id": f"lane-{idx + 1}",
            "task": st,
            "sandbox": tier["sandbox"],
            "model": tier["model"],
            "role": tier["role"],
            "output_target": f"output/page_{chr(65 + idx)}.html"
        }
        plan["lanes"].append(lane)

    return plan


def print_split_plan(plan: dict):
    print("\n" + "═" * 78)
    print(f"🔀 [THE SPLITTER] Parallel Execution Plan: {plan['title']}")
    print("═" * 78)
    print(f"{'Lane':<8} {'Sandbox':<12} {'Model':<10} {'Target Output':<22} {'Role'}")
    print("─" * 78)
    for lane in plan["lanes"]:
        print(f"{lane['lane_id']:<8} {lane['sandbox']:<12} {lane['model']:<10} {lane['output_target']:<22} {lane['role']}")
    print("═" * 78 + "\n")


def main():
    parser = argparse.ArgumentParser(prog="agentic-splitter", description="The Splitter & Sandbox Allocator")
    parser.add_argument("title", help="High-level task to split")
    parser.add_argument("--subtasks", help="Comma-separated subtasks")
    parser.add_argument("--json", action="store_true", help="Output plan as JSON")

    args = parser.parse_args()
    st_list = [s.strip() for s in args.subtasks.split(",")] if args.subtasks else None
    plan = split_task(args.title, st_list)

    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print_split_plan(plan)


if __name__ == "__main__":
    main()
