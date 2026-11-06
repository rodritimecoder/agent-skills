#!/usr/bin/env python3
"""
kanban.py — Target-Local File-Based Kanban Board Engine
Manages .kanban/ state machine: 01_new -> 02_picked_up -> 03_review -> 04_done
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parent.parent
TEMPLATES_DIR = SKILL_DIR / "_templates"

COLUMNS = {
    "new": "01_new",
    "picked_up": "02_picked_up",
    "review": "03_review",
    "done": "04_done"
}

COLUMN_NAMES = {
    "01_new": "NEW",
    "02_picked_up": "PICKED UP",
    "03_review": "REVIEW",
    "04_done": "DONE"
}


def find_kanban_root(start_path: Path = None) -> Path:
    start = (start_path or Path.cwd()).resolve()
    for curr in [start] + list(start.parents):
        cand = curr / ".kanban"
        if cand.is_dir():
            return cand
    return start / ".kanban"


def init_kanban(target_dir: Path) -> Path:
    target = target_dir.resolve()
    kanban_dir = target / ".kanban"
    if kanban_dir.is_dir():
        print(f"ℹ️  Kanban board already exists at: {kanban_dir}")
        return kanban_dir

    src = TEMPLATES_DIR / "kanban"
    shutil.copytree(src, kanban_dir, dirs_exist_ok=True)
    print(f"✅ Initialized target-local Kanban board at: {kanban_dir}")
    print(f"   Created: 01_new/ (with CARD-001), 02_picked_up/, 03_review/, 04_done/")
    return kanban_dir


def parse_card(card_file: Path) -> dict:
    content = card_file.read_text(encoding="utf-8", errors="replace")
    card = {
        "file": str(card_file),
        "filename": card_file.name,
        "id": card_file.stem.split("_")[0],
        "title": card_file.stem,
        "status": "unknown",
        "priority": "P2",
        "model": "flash",
        "reqs": []
    }
    m = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL | re.MULTILINE)
    if m:
        fm = m.group(1)
        for line in fm.splitlines():
            kv = line.split(":", 1)
            if len(kv) == 2:
                k, v = kv[0].strip(), kv[1].strip().strip('"\'')
                card[k] = v

    reqs = re.findall(r"-\s*\[([ xX])\]\s*`?(\[REQ-[^\]]+\])`?:\s*(.+)", content)
    for r in reqs:
        card["reqs"].append({
            "checked": r[0].lower() == "x",
            "tag": r[1],
            "text": r[2].strip()
        })
    return card


def get_board_state(kanban_dir: Path) -> dict:
    state = {col: [] for col in COLUMNS.values()}
    if not kanban_dir.is_dir():
        return state

    for col_dir in sorted(kanban_dir.iterdir()):
        if col_dir.is_dir() and col_dir.name in state:
            for cf in sorted(col_dir.iterdir()):
                if cf.is_file() and cf.suffix == ".md":
                    state[col_dir.name].append(parse_card(cf))
    return state


def render_ascii_board(kanban_dir: Path, as_json: bool = False):
    state = get_board_state(kanban_dir)
    if as_json:
        print(json.dumps(state, indent=2))
        return

    print("\n" + "═" * 92)
    print(f"📋 AGENTIC KANBAN BOARD [{kanban_dir}]")
    print("═" * 92)

    col_headers = [f"{COLUMN_NAMES[c]} ({len(cards)})" for c, cards in state.items()]
    col_w = 21

    # Header
    hdr = " │ ".join(h.center(col_w) for h in col_headers)
    print(f"│ {hdr} │")
    print("├" + "─" * (col_w + 2) + ("┼" + "─" * (col_w + 2)) * 3 + "┤")

    max_rows = max([len(cards) for cards in state.values()] + [1])
    for r in range(max_rows):
        row_items = []
        for c in COLUMNS.values():
            cards = state[c]
            if r < len(cards):
                card = cards[r]
                summary = f"[{card['id']}] {card.get('title', '')[:12]}"
                row_items.append(summary.ljust(col_w))
            else:
                row_items.append("".ljust(col_w))
        print("│ " + " │ ".join(row_items) + " │")

    print("└" + "─" * (col_w + 2) + ("┴" + "─" * (col_w + 2)) * 3 + "┘\n")


def add_card(title: str, target_dir: Path = None, model: str = "flash", priority: str = "P1", req: str = None) -> Path:
    kanban_dir = find_kanban_root(target_dir)
    if not kanban_dir.is_dir():
        kanban_dir = init_kanban(target_dir or Path.cwd())

    # Calculate next ID
    existing = list(kanban_dir.rglob("CARD-*.md"))
    nums = [int(re.search(r"CARD-(\d+)", f.name).group(1)) for f in existing if re.search(r"CARD-(\d+)", f.name)]
    next_num = (max(nums) + 1) if nums else 1
    card_id = f"CARD-{next_num:03d}"

    slug = re.sub(r"[^a-zA-Z0-9]+", "_", title.lower()).strip("_")[:25]
    card_filename = f"{card_id}_{slug}.md"
    dest = kanban_dir / "01_new" / card_filename

    tpl = (TEMPLATES_DIR / "card.md.tpl").read_text(encoding="utf-8")
    content = tpl.replace("{CARD_ID}", card_id)\
                 .replace("{CARD_TITLE}", title)\
                 .replace("{TIMESTAMP}", datetime.now(timezone.utc).isoformat())\
                 .replace("{OBJECTIVE}", title)\
                 .replace("{REQ_01}", req or f"Implement {title}")\
                 .replace("{REQ_02}", "Zero regressions and full test coverage")

    dest.write_text(content, encoding="utf-8")
    print(f"✨ Card created: {dest.relative_to(kanban_dir.parent)}")
    return dest


def move_card(card_id: str, target_col: str, target_dir: Path = None) -> Path:
    kanban_dir = find_kanban_root(target_dir)
    if not kanban_dir.is_dir():
        sys.exit(f"❌ Error: No .kanban directory found at {kanban_dir}")

    col_target_name = COLUMNS.get(target_col.lower())
    if not col_target_name:
        sys.exit(f"❌ Error: Invalid column '{target_col}'. Choose: new, picked_up, review, done")

    target_card_id = card_id.upper()
    if not target_card_id.startswith("CARD-"):
        target_card_id = f"CARD-{int(card_id):03d}"

    matches = list(kanban_dir.rglob(f"{target_card_id}*.md"))
    if not matches:
        sys.exit(f"❌ Error: Card '{target_card_id}' not found on board.")

    src = matches[0]
    dest = kanban_dir / col_target_name / src.name
    if src == dest:
        print(f"ℹ️ Card {target_card_id} is already in {col_target_name}.")
        return dest

    content = src.read_text(encoding="utf-8")
    content = re.sub(r'^status:\s*".*?"', f'status: "{target_col.lower()}"', content, flags=re.MULTILINE)
    dest.write_text(content, encoding="utf-8")
    src.unlink()

    print(f"🚚 Moved {target_card_id} -> {col_target_name} ({dest.name})")
    return dest


def main():
    parser = argparse.ArgumentParser(prog="agentic-kanban", description="File-Based Kanban Board Engine")
    sub = parser.add_subparsers(dest="action", required=True)

    # init
    p_init = sub.add_parser("init", help="Initialize .kanban/ in target directory")
    p_init.add_argument("target", nargs="?", default=".", help="Target directory")

    # list
    p_list = sub.add_parser("list", help="Render ASCII Kanban board")
    p_list.add_argument("target", nargs="?", default=".", help="Target directory")
    p_list.add_argument("--json", action="store_true", help="Output board as JSON")

    # add
    p_add = sub.add_parser("add", help="Add a new card to 01_new/")
    p_add.add_argument("title", help="Title of task card")
    p_add.add_argument("--model", default="flash", help="Assigned model tier")
    p_add.add_argument("--req", help="Primary requirement [REQ-01]")
    p_add.add_argument("--target", default=".", help="Target directory")

    # move
    p_move = sub.add_parser("move", help="Move card between columns")
    p_move.add_argument("card_id", help="Card ID (e.g. CARD-001 or 1)")
    p_move.add_argument("column", choices=["new", "picked_up", "review", "done"], help="Target column")
    p_move.add_argument("--target", default=".", help="Target directory")

    args = parser.parse_args()
    target_path = Path(getattr(args, "target", ".")).resolve()

    if args.action == "init":
        init_kanban(target_path)
    elif args.action == "list":
        k_dir = find_kanban_root(target_path)
        render_ascii_board(k_dir, as_json=args.json)
    elif args.action == "add":
        add_card(args.title, target_dir=target_path, model=args.model, req=args.req)
    elif args.action == "move":
        move_card(args.card_id, args.column, target_dir=target_path)


if __name__ == "__main__":
    main()
