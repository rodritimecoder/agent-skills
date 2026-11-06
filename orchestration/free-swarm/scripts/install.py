#!/usr/bin/env python3
"""Publish the free-swarm agents into this machine's OpenCode config.

The agents live in ../agents and are symlinked, so editing the checkout changes
what OpenCode loads. Only files named free-*.md are ever touched.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "agents"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
TARGET = CONFIG / "opencode" / "agents"


def plan() -> list[tuple[Path, Path]]:
    return [(src, TARGET / src.name) for src in sorted(SOURCE.glob("free-*.md"))]


def status() -> list[tuple[str, str]]:
    rows = []
    for src, dst in plan():
        if dst.is_symlink() and dst.resolve() == src:
            rows.append((src.name, "linked"))
        elif dst.exists() or dst.is_symlink():
            rows.append((src.name, "conflict"))
        else:
            rows.append((src.name, "missing"))
    return rows


def install(dry: bool) -> int:
    rows = plan()
    if not rows:
        print(f"no agents in {SOURCE}", file=sys.stderr)
        return 1
    if dry:
        for src, dst in rows:
            print(f"  would link {dst} -> {src}")
        return 0
    TARGET.mkdir(parents=True, exist_ok=True)
    for src, dst in rows:
        if dst.is_symlink() and dst.resolve() == src:
            continue
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)
        print(f"  linked {dst.name}")
    return 0


def remove() -> int:
    for path in sorted(TARGET.glob("free-*.md")):
        if path.is_symlink():
            path.unlink()
            print(f"  removed {path.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report link state, exit 1 if anything is missing")
    parser.add_argument("--remove", action="store_true", help="unlink every free-*.md this script owns")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.remove:
        return remove()
    if args.check:
        rows = status()
        for name, state in rows:
            print(f"  {name:20} {state}")
        missing = [n for n, s in rows if s != "linked"]
        print(f"  {len(rows) - len(missing)}/{len(rows)} linked in {TARGET}")
        return 1 if missing else 0
    return install(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
