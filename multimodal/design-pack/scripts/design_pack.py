#!/usr/bin/env python3
"""design-pack — the token gate.

A pack is only a system if something refuses to step outside it. This checks a
page or stylesheet against a look's declared tokens. By default it fails on any
drift: colours, fonts, type sizes, corner radii, and eased motion. `--loose`
demotes everything but colour to a warning, for a first pass on an old page.

    design-pack look                     # what looks exist
    design-pack tokens glitch-console    # the declared values
    design-pack sprite conductor         # the ASCII map, for debugging
    design-pack verify page.html [...]   # the gate

Exit codes: 0 pass, 1 fail, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOOKS = ROOT / "looks"

HEX = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
FUNC_COLOUR = re.compile(r"\b(?:rgba?|hsla?|oklch|lab)\s*\(", re.I)
FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;}]+)", re.I)
FONT_SIZE = re.compile(r"font-size\s*:\s*([^;}]+)", re.I)
RADIUS = re.compile(r"border-radius\s*:\s*([^;}]+)", re.I)
EASING = re.compile(r"(?:transition|animation)\s*:\s*([^;}]+)", re.I)
COLOUR_PROP = re.compile(r"--[a-z0-9-]+\s*:\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)|hsla?\([^)]*\))")

SAFE_KEYWORDS = {
    "inherit", "initial", "unset", "revert", "none", "transparent",
    "currentcolor", "auto", "normal", "0", "0px",
}


def norm_hex(value: str) -> str:
    v = value.lower()
    if len(v) == 4:
        v = "#" + "".join(c * 2 for c in v[1:])
    if len(v) == 5:
        v = "#" + "".join(c * 2 for c in v[1:])
    return v


def load_tokens(look: str) -> dict[str, str]:
    css = LOOKS / look / "tokens.css"
    if not css.exists():
        sys.exit(f"design-pack: no such look: {look}")
    text = css.read_text()
    tokens = {}
    for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", text, re.I):
        tokens[name.strip()] = value.strip()
    return tokens


def declared(tokens: dict[str, str]) -> dict[str, set[str]]:
    out = {"colours": set(), "fonts": set(), "sizes": set(), "radii": set()}
    for name, value in tokens.items():
        if name.startswith("--font-"):
            for fam in value.split(","):
                fam = fam.strip().strip('"').strip("'").lower()
                if fam and not fam.startswith("var("):
                    out["fonts"].add(fam)
        elif name.startswith("--fs-"):
            out["sizes"].add(value.replace(" ", ""))
        elif name.startswith("--r-") or name.startswith("--b-"):
            out["radii"].add(value.replace(" ", ""))
        for colour in HEX.findall(value) + FUNC_COLOUR.findall(value):
            out["colours"].add(norm_hex(colour) if colour.startswith("#") else colour.lower())
    return out


def check(path: Path, tokens: dict[str, str]) -> tuple[list[str], list[str]]:
    allow = declared(tokens)
    fail: list[str] = []
    warn: list[str] = []
    text = path.read_text(errors="replace")
    lines = text.splitlines()

    for n, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("//", "*", "#")) and not stripped.startswith("#"):
            continue

        for m in HEX.finditer(line):
            value = norm_hex(m.group(0))
            if value not in allow["colours"]:
                fail.append(f"{path.name}:{n}  undeclared colour {m.group(0)}")

        for m in FUNC_COLOUR.finditer(line):
            snippet = line[m.start(): m.start() + 32].split(")")[0].lower()
            if not any(snippet in c or c in snippet for c in allow["colours"]):
                fail.append(f"{path.name}:{n}  undeclared colour {m.group(0).strip()}(…)")

        for m in FONT_FAMILY.finditer(line):
            for fam in m.group(1).split(","):
                fam = fam.strip().strip('"').strip("'").lower()
                if not fam or fam.startswith("var(") or fam in allow["fonts"]:
                    continue
                warn.append(f"{path.name}:{n}  font not in the pack: {fam}")

        for m in FONT_SIZE.finditer(line):
            value = m.group(1).strip().replace(" ", "")
            if value in SAFE_KEYWORDS or value.startswith("var(") or value.startswith("calc("):
                continue
            if value.endswith(("em", "%")):
                continue
            if value not in allow["sizes"]:
                warn.append(f"{path.name}:{n}  type size off the scale: {value}")

        for m in RADIUS.finditer(line):
            for value in m.group(1).split():
                value = value.strip()
                if value in SAFE_KEYWORDS or value.startswith("var("):
                    continue
                # percentages are geometry, not decoration: 50% is the one disc
                if value.endswith("%"):
                    continue
                if value not in allow["radii"]:
                    warn.append(f"{path.name}:{n}  corner radius outside the look: {value}")

        for m in EASING.finditer(line):
            value = m.group(1).lower()
            if "steps(" in value or "linear" in value or value.strip() in SAFE_KEYWORDS:
                continue
            if re.search(r"ease|cubic-bezier|spring|bounce", value):
                warn.append(f"{path.name}:{n}  eased motion — this look steps: {value.strip()}")

    return fail, warn


def cmd_verify(args) -> int:
    tokens = load_tokens(args.look)
    targets: list[Path] = []
    for pattern in args.files:
        p = Path(pattern)
        if p.is_dir():
            targets.extend(sorted(p.rglob("*.html")) + sorted(p.rglob("*.css")))
        elif p.exists():
            targets.append(p)
        else:
            sys.exit(f"design-pack: no such file: {pattern}")
    if not targets:
        sys.exit("design-pack: nothing to verify")

    total_fail = total_warn = 0
    strict = not args.loose
    report = {"look": args.look, "strict": strict, "files": [], "pass": True}
    for target in targets:
        if target.name == "tokens.css" and target.parent.name == args.look:
            continue
        fail, warn = check(target, tokens)
        if strict:
            fail, warn = fail + warn, []
        total_fail += len(fail)
        total_warn += len(warn)
        report["files"].append({"path": str(target), "fail": fail, "warn": warn})
        if args.json:
            continue
        for line in fail:
            print(f"FAIL  {line}")
        for line in warn:
            print(f"WARN  {line}")

    report["pass"] = total_fail == 0
    report["fail_count"] = total_fail
    report["warn_count"] = total_warn

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        verdict = "PASS" if total_fail == 0 else "FAIL"
        print(f"\n{verdict}  {args.look} · {len(targets)} file(s) · "
              f"{total_fail} fail · {total_warn} warn")
        if total_fail:
            print("Every colour must come from tokens.css. Copy the token, never the hex.")
    return 0 if total_fail == 0 else 1


def cmd_look(_args) -> int:
    for look in sorted(LOOKS.iterdir()):
        if not (look / "tokens.css").exists():
            continue
        readme = look / "README.md"
        blurb = ""
        if readme.exists():
            blocks = [b for b in re.split(r"\n\s*\n", readme.read_text()) if b.strip()]
            quote = next((b for b in blocks if b.strip().startswith(">")), None)
            if quote:
                blurb = " ".join(line.lstrip("> ").strip() for line in quote.strip().splitlines())
            else:
                for block in blocks:
                    first = block.strip().splitlines()[0].strip()
                    if first.startswith(("#", "|", "```", "**", "!", "-")):
                        continue
                    blurb = " ".join(block.split())
                    break
        print(f"{look.name:<18} {blurb[:110]}")
    return 0


def cmd_tokens(args) -> int:
    tokens = load_tokens(args.look)
    groups: dict[str, list[tuple[str, str]]] = {}
    for name, value in tokens.items():
        parts = [p for p in name.lstrip("-").split("-") if p]
        key = parts[0] if parts else "other"
        groups.setdefault(key, []).append((name, value))
    for key in sorted(groups):
        print(f"\n[{key}]")
        for name, value in groups[key]:
            print(f"  {name:<26} {value}")
    return 0


def cmd_sprite(args) -> int:
    js = (LOOKS / args.look / "sprites.js").read_text()
    maps = {name: re.findall(r'"([.#A-Za-z]+)"', body)
            for name, body in re.findall(r"(\w+):\s*\[(.*?)\]", js, re.S)}
    aliases = dict(re.findall(r"(\w+):\s*\{\s*map:\s*\"(\w+)\"", js))
    wanted = maps if args.name in ("all", "*") else None
    if wanted is None:
        key = args.name if args.name in maps else aliases.get(args.name)
        if key not in maps:
            sys.exit(f"design-pack: no sprite '{args.name}' in {args.look} "
                     f"(have: {', '.join(maps)})")
        wanted = {args.name: maps[key]}
    for name, rows in wanted.items():
        if not rows:
            continue
        width = len(rows[0])
        bad = [i for i, r in enumerate(rows) if len(r) != width]
        print(f"\n{name}  {width}x{len(rows)}" + (f"  ragged rows {bad}" if bad else ""))
        for row in rows:
            print("  " + row)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="design-pack", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("verify", help="check files against a look's tokens")
    p.add_argument("files", nargs="+")
    p.add_argument("--look", default="glitch-console")
    p.add_argument("--json", action="store_true")
    p.add_argument("--loose", action="store_true", help="demote everything but colour to a warning")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("look", help="list looks")
    p.set_defaults(func=cmd_look)

    p = sub.add_parser("tokens", help="print a look's tokens")
    p.add_argument("look", nargs="?", default="glitch-console")
    p.set_defaults(func=cmd_tokens)

    p = sub.add_parser("sprite", help="print a sprite map")
    p.add_argument("name")
    p.add_argument("--look", default="glitch-console")
    p.set_defaults(func=cmd_sprite)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
