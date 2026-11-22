#!/usr/bin/env python3
"""
srs_review.py - Spaced Repetition (SM-2) engine for Cornell Notes.

Manages review scheduling for cue-note pairs using a sidecar `.srs.json` file.
Implements the classic SM-2 algorithm:
- Fail (Again): resets interval to 1 day.
- Hard: 1-2 days.
- Good: 3 days (then scaled by ease factor: 3d -> 7d -> 18d...).
- Easy: 4+ days with bonus.

Usage:
  # Check review status / due cards across notes
  python3 srs_review.py status <notes.json>

  # List due cards with their cue IDs (non-interactive)
  python3 srs_review.py review <notes.json>

  # Record a rating for one card; never reads stdin
  python3 srs_review.py review <notes.json> --cue-id <id> --rating 1-4

  # Synchronize / initialize SRS state from notes JSON
  python3 srs_review.py init <notes.json>
"""

import sys
import os
import json
import hashlib
from datetime import datetime, date, timedelta
from pathlib import Path
import argparse


def card_id(heading: str, cue: str) -> str:
    """Generate a stable, human-readable hash key for a cue."""
    content = f"{heading.strip()}||{cue.strip()}".encode("utf-8")
    return hashlib.sha256(content).hexdigest()[:12]


def load_srs_state(srs_path: Path) -> dict:
    if srs_path.exists():
        try:
            with open(srs_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_srs_state(srs_path: Path, state: dict):
    srs_path.parent.mkdir(parents=True, exist_ok=True)
    with open(srs_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def extract_cards(notes_data: dict) -> list[dict]:
    cards = []
    for section in notes_data.get("sections", []):
        heading = section.get("heading", "General")
        for entry in section.get("entries", []):
            cue = entry.get("cue", "").strip()
            notes = entry.get("notes", "").strip()
            cid = card_id(heading, cue)
            cards.append({
                "id": cid,
                "heading": heading,
                "cue": cue,
                "notes": notes,
                "type": entry.get("type", "concept")
            })
    return cards


def calculate_sm2(quality: int, reps: int, interval_days: int, ease_factor: float) -> tuple[int, int, float, str]:
    """
    Quality ratings:
      0: Total blackout (Again / Fail)
      1: Incorrect answer
      2: Hard (Correct with hesitation)
      3: Good (Correct with normal effort) -> 1d -> 3d -> (prev * ease)
      4: Easy (Flawless recall)
    """
    today = date.today()

    if quality < 2:
        # Failed / Again
        reps = 0
        interval_days = 1
    elif quality == 2:
        # Hard: short interval, ease penalty
        if reps == 0:
            interval_days = 1
        elif reps == 1:
            interval_days = 2
        else:
            interval_days = max(2, int(interval_days * 1.2))
        reps += 1
    elif quality == 3:
        # Good: Standard SM-2 interval progression (1 -> 3 -> prev * ease)
        if reps == 0:
            interval_days = 1
        elif reps == 1:
            interval_days = 3
        else:
            interval_days = int(round(interval_days * ease_factor))
        reps += 1
    else:
        # Easy (quality >= 4): Accelerated interval
        if reps == 0:
            interval_days = 2
        elif reps == 1:
            interval_days = 4
        else:
            interval_days = int(round(interval_days * ease_factor * 1.3))
        reps += 1

    # Adjust ease factor (minimum 1.3)
    ease_factor = max(1.3, ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    due_date = (today + timedelta(days=interval_days)).isoformat()

    return reps, interval_days, round(ease_factor, 2), due_date


def cmd_status(notes_path: Path):
    srs_path = notes_path.with_suffix(".srs.json")
    with open(notes_path, "r", encoding="utf-8") as f:
        notes_data = json.load(f)

    cards = extract_cards(notes_data)
    state = load_srs_state(srs_path)

    today = date.today().isoformat()
    due_cards = []
    unreviewed_cards = []
    future_cards = []

    for card in cards:
        cid = card["id"]
        c_state = state.get(cid)
        if not c_state:
            unreviewed_cards.append(card)
        else:
            due_date = c_state.get("due_date", today)
            if due_date <= today:
                due_cards.append((card, c_state))
            else:
                future_cards.append((card, c_state))

    print(f"\n=======================================================")
    print(f"SRS Status: {notes_data.get('title', notes_path.stem)}")
    print(f"State file: {srs_path.name}")
    print(f"Total cards: {len(cards)}")
    print(f"  - New / Unreviewed: {len(unreviewed_cards)}")
    print(f"  - Due Today:        {len(due_cards)}")
    print(f"  - Future / Learned: {len(future_cards)}")
    print(f"=======================================================\n")

    if due_cards:
        print("Cards Due Today:")
        for card, c_state in due_cards[:5]:
            print(f"  * [{card['heading']}] {card['cue'][:60]}... (Interval: {c_state.get('interval_days', 1)}d)")
        if len(due_cards) > 5:
            print(f"  ... and {len(due_cards) - 5} more.")
    elif unreviewed_cards:
        print("Ready to start! Run 'srs_review.py review' to study new cards.")
    else:
        print("🎉 All caught up for today! Come back tomorrow.")


def _require_review_args(deck: list[dict], cue_id: str | None, rating: int | None) -> bool:
    """Enforce the explicit-flag contract; never read stdin.

    Returns True when both answers were supplied, otherwise prints an
    actionable message on stderr and returns False.
    """
    if cue_id and rating is not None:
        return True
    print("Error: review requires --cue-id and --rating; stdin prompts are disabled.", file=sys.stderr)
    print("Available cue IDs in the due deck:", file=sys.stderr)
    for card in deck:
        print(f"  {card['id']}  [{card['heading']}] {card['cue'][:60]}", file=sys.stderr)
    print("Re-run as: srs_review.py review <notes.json> --cue-id <id> --rating 1-4", file=sys.stderr)
    return False


def cmd_review(notes_path: Path, cue_id: str | None = None, rating: int | None = None) -> int:
    """Non-interactive review of one card in a single notes file."""
    srs_path = notes_path.with_suffix(".srs.json")
    with open(notes_path, "r", encoding="utf-8") as f:
        notes_data = json.load(f)

    cards = extract_cards(notes_data)
    state = load_srs_state(srs_path)
    today = date.today().isoformat()

    # Prioritize cards due today, then new cards
    due_queue = []
    new_queue = []
    for card in cards:
        cid = card["id"]
        if cid in state:
            if state[cid].get("due_date", today) <= today:
                due_queue.append(card)
        else:
            new_queue.append(card)

    deck = due_queue + new_queue
    if not deck:
        print("No cards are due for review right now.", file=sys.stderr)
        return 1
    if not _require_review_args(deck, cue_id, rating):
        return 2

    matches = [c for c in deck if c["id"] == cue_id]
    if not matches:
        print(f"Error: cue id '{cue_id}' is not in the due deck.", file=sys.stderr)
        return 2
    card = matches[0]
    c_state = state.get(cue_id, {
        "reps": 0, "interval_days": 1, "ease_factor": 2.5, "due_date": today
    })

    reps, interval, ease, next_due = calculate_sm2(
        rating,
        c_state.get("reps", 0),
        c_state.get("interval_days", 1),
        c_state.get("ease_factor", 2.5)
    )
    state[cue_id] = {
        "heading": card["heading"],
        "cue": card["cue"],
        "reps": reps,
        "interval_days": interval,
        "ease_factor": ease,
        "due_date": next_due,
        "last_reviewed": today
    }
    save_srs_state(srs_path, state)
    print(f"Reviewed {cue_id} [{card['heading']}] "
          f"({card['cue'][:60]}); next review in {interval} day(s) on {next_due}.")
    return 0


def discover_notes_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    elif target.is_dir():
        return sorted(list(target.rglob("*_cornell.json")))
    return []


def render_table(rows: list[dict], columns: list[str] | None = None, headers: list[str] | None = None) -> str:
    if not rows:
        return "*(no records)*\n"
    if columns is None:
        columns = list(rows[0].keys())
    if headers is None:
        headers = [col.replace("_", " ").title() for col in columns]

    col_widths = [len(h) for h in headers]
    for r in rows:
        for idx, col in enumerate(columns):
            val_str = str(r.get(col, "")).replace("\n", " ").strip()
            if len(val_str) > col_widths[idx]:
                col_widths[idx] = len(val_str)

    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * col_widths[i] for i in range(len(headers))) + " |"
    row_lines = []
    for r in rows:
        row_str = "| " + " | ".join(str(r.get(col, "")).replace("\n", " ").strip().ljust(col_widths[i]) for i, col in enumerate(columns)) + " |"
        row_lines.append(row_str)
    return "\n".join([header_line, sep_line] + row_lines) + "\n"


def cmd_status_all(target: Path, as_table: bool = False, as_json: bool = False, project_keys: list[str] | None = None, limit: int = 0):
    notes_files = discover_notes_files(target)
    if not notes_files:
        if as_json:
            print("[]")
        else:
            print(f"No '*_cornell.json' notes found in {target}")
        return

    today = date.today().isoformat()
    records = []

    for nf in notes_files:
        srs_path = nf.with_suffix(".srs.json")
        try:
            with open(nf, "r", encoding="utf-8") as f:
                data = json.load(f)
            cards = extract_cards(data)
            state = load_srs_state(srs_path)
            due_count = sum(1 for c in cards if c["id"] in state and state[c["id"]].get("due_date", today) <= today)
            new_count = sum(1 for c in cards if c["id"] not in state)
            reviewed_count = len(cards) - new_count
            records.append({
                "file": nf.name,
                "title": data.get("title", nf.stem),
                "cards": len(cards),
                "due_today": due_count,
                "new": new_count,
                "reviewed": reviewed_count,
                "path": str(nf.resolve())
            })
        except Exception as e:
            records.append({
                "file": nf.name,
                "title": "Error",
                "cards": 0,
                "due_today": 0,
                "new": 0,
                "reviewed": 0,
                "path": str(nf.resolve()),
                "error": str(e)
            })

    if limit and limit > 0:
        records = records[:limit]

    if as_json:
        if project_keys:
            records = [{k: v for k, v in r.items() if k.lower() in project_keys} for r in records]
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return

    if as_table:
        cols = ["file", "title", "cards", "due_today", "new", "reviewed"]
        if project_keys:
            cols = [c for c in cols if c.lower() in project_keys] or cols
        table_rows = [{k: r.get(k, "") for k in cols} for r in records]
        print(f"### Spaced Repetition (SRS) Status ({len(records)} note documents)\n")
        print(render_table(table_rows, cols))
        return

    total_cards = sum(r["cards"] for r in records)
    total_due = sum(r["due_today"] for r in records)
    total_new = sum(r["new"] for r in records)

    print(f"\n=======================================================")
    print(f"📚 Spaced Repetition Status across {len(notes_files)} note document(s)")
    print(f"=======================================================")

    for r in records:
        print(f"• {r['title']}")
        print(f"    Cards: {r['cards']} | Due Today: \033[1;33m{r['due_today']}\033[0m | New: {r['new']}")

    print(f"-------------------------------------------------------")
    print(f"Total across all subjects: {total_cards} cards")
    print(f"  - Due for review today: \033[1;32m{total_due}\033[0m")
    print(f"  - Unreviewed / New:     \033[1;36m{total_new}\033[0m")
    print(f"=======================================================\n")


def cmd_review_all(target: Path, cue_id: str | None = None, rating: int | None = None) -> int:
    """Non-interactive cross-subject review of one card; never reads stdin."""
    notes_files = discover_notes_files(target)
    if not notes_files:
        print(f"No '*_cornell.json' notes found in {target}", file=sys.stderr)
        return 1

    today = date.today().isoformat()
    due_cards = []
    new_cards = []

    for nf in notes_files:
        srs_path = nf.with_suffix(".srs.json")
        try:
            with open(nf, "r", encoding="utf-8") as f:
                data = json.load(f)
            cards = extract_cards(data)
            state = load_srs_state(srs_path)
            for c in cards:
                c["_srs_path"] = srs_path
                c["_doc_title"] = data.get("title", nf.stem)
                cid = c["id"]
                if cid in state:
                    if state[cid].get("due_date", today) <= today:
                        due_cards.append((c, state))
                else:
                    new_cards.append((c, state))
        except Exception:
            continue

    deck = due_cards + new_cards
    if not deck:
        print("No cards are due for review across your notes right now.", file=sys.stderr)
        return 1
    if not _require_review_args([card for card, _ in deck], cue_id, rating):
        return 2

    matches = [(card, state) for card, state in deck if card["id"] == cue_id]
    if not matches:
        print(f"Error: cue id '{cue_id}' is not in the due deck.", file=sys.stderr)
        return 2
    card, state = matches[0]
    c_state = state.get(cue_id, {
        "reps": 0, "interval_days": 1, "ease_factor": 2.5, "due_date": today
    })

    reps, interval, ease, next_due = calculate_sm2(
        rating,
        c_state.get("reps", 0),
        c_state.get("interval_days", 1),
        c_state.get("ease_factor", 2.5)
    )
    state[cue_id] = {
        "heading": card["heading"],
        "cue": card["cue"],
        "reps": reps,
        "interval_days": interval,
        "ease_factor": ease,
        "due_date": next_due,
        "last_reviewed": today
    }
    save_srs_state(card["_srs_path"], state)
    print(f"Reviewed {cue_id} [{card['_doc_title']} / {card['heading']}] "
          f"({card['cue'][:60]}); next review in {interval} day(s) on {next_due}.")
    return 0


def main():
    parser = argparse.ArgumentParser(epilog='Exit codes: 0 success; 1 runtime/validation error; 2 invalid arguments (usage error); other non-zero values are script-specific.', description="Spaced Repetition (SM-2) Engine for Cornell Notes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show review stats and due cards (file or folder)")
    status_parser.add_argument("notes_target", help="Path to Cornell JSON file or folder containing Cornell notes")
    status_parser.add_argument("-t", "--table", action="store_true", help="Emit review stats as compact Markdown table")
    status_parser.add_argument("--json", action="store_true", help="Emit review stats as structured JSON")
    status_parser.add_argument("-p", "--project", nargs="*", help="Filter fields in output table or JSON")
    status_parser.add_argument("-n", "--limit", type=int, default=0, help="Limit number of documents inspected")

    review_parser = subparsers.add_parser("review", help="List due cards or record a rating (file or folder)")
    review_parser.add_argument("notes_target", help="Path to Cornell JSON file or folder containing Cornell notes")
    review_parser.add_argument("-c", "--cue-id", help="Card ID to review (from the cue list)")
    review_parser.add_argument("-r", "--rating", type=int, choices=[1, 2, 3, 4],
                               help="Recall rating: 1=Again 2=Hard 3=Good 4=Easy")

    args = parser.parse_args()
    target = Path(args.notes_target)

    if not target.exists():
        print(f"Error: Target '{target}' does not exist.", file=sys.stderr)
        sys.exit(1)

    if args.command == "status":
        project_keys = [k.lower() for k in args.project] if args.project else None
        cmd_status_all(target, as_table=args.table, as_json=args.json, project_keys=project_keys, limit=args.limit)
    elif args.command == "review":
        sys.exit(cmd_review_all(target, args.cue_id, args.rating))


if __name__ == "__main__":
    main()
