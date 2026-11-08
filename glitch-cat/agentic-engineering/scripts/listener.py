#!/usr/bin/env python3
"""
listener.py — The Event Listener & Autonomous Task Dispatcher (Kem's Step 3)
Monitors .kanban/01_new/, claims ready cards, and triggers pipeline execution.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
sys.path.insert(0, str(SCRIPT_PATH.parent))
import kanban


def poll_and_dispatch(kanban_dir: Path, worker_cmd: str = None) -> list[str]:
    new_dir = kanban_dir / "01_new"
    if not new_dir.is_dir():
        return []

    dispatched = []
    cards = sorted([f for f in new_dir.iterdir() if f.is_file() and f.suffix == ".md"])

    for card_file in cards:
        card = kanban.parse_card(card_file)
        card_id = card["id"]
        print(f"\n🔔 [Listener Trigger] New task detected: {card_id} — '{card.get('title', '')}'")

        # Step 2 -> 3: Pick up the card
        picked_file = kanban.move_card(card_id, "picked_up", target_dir=kanban_dir.parent)
        dispatched.append(card_id)

        # Execute worker if provided
        if worker_cmd:
            cmd = worker_cmd.replace("{CARD_ID}", card_id).replace("{CARD_PATH}", str(picked_file))
            print(f"🚀 [Listener Dispatch] Executing worker: {cmd}")
            res = subprocess.run(cmd, shell=True)
            if res.returncode == 0:
                print(f"✅ Worker completed execution for {card_id}.")
            else:
                print(f"⚠️ Worker returned non-zero code {res.returncode} for {card_id}.")

    return dispatched


def listen_loop(kanban_dir: Path, interval: int = 5, once: bool = False, worker_cmd: str = None):
    print(f"🎧 [The Listener] Watching {kanban_dir}/01_new for inbound task cards (interval: {interval}s)...")
    try:
        while True:
            dispatched = poll_and_dispatch(kanban_dir, worker_cmd=worker_cmd)
            if once:
                if not dispatched:
                    print("ℹ️  No new cards found in 01_new/.")
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n🛑 Listener stopped by user.")


def main():
    parser = argparse.ArgumentParser(prog="agentic-listener", description="The Event Listener & Auto-Dispatcher")
    parser.add_argument("target", nargs="?", default=".", help="Target project directory")
    parser.add_argument("--once", action="store_true", help="Run single poll pass and exit")
    parser.add_argument("--interval", type=int, default=5, metavar="N", help="Polling interval in seconds")
    parser.add_argument("--worker", default=None, help="Command to run when card is picked up (e.g. 'agentic run {CARD_ID}')")

    args = parser.parse_args()
    target_path = Path(args.target).resolve()
    kanban_dir = kanban.find_kanban_root(target_path)
    if not kanban_dir.is_dir():
        sys.exit(f"❌ Error: No .kanban directory found at {kanban_dir}. Run 'agentic kanban init' first.")

    listen_loop(kanban_dir, interval=args.interval, once=args.once, worker_cmd=args.worker)


if __name__ == "__main__":
    main()
