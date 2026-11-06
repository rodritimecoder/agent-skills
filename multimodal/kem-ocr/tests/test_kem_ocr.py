#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from kem_ocr import assert_structure

CASES = [
    ("text", "", "non_empty", False),
    ("text", "48520 Electronics & Circuits", None, True),
    ("text", "Refunds", None, True),
    ("text", "line one\nline two\nline three\nline four", None, True),
    ("text", "same line\nsame line\nsame line\nsame line", "no_line_loop", False),
    ("text", "A" * 400 + "\nsome text", "no_char_flood", False),
    ("table", "<otsl><fcel>Jan<fcel>12<nl><fcel>Feb<fcel>19</otsl>", None, True),
    ("table", "<table><tr><td>Jan</td><td>12</td></tr></table>", None, True),
    ("table", "| Jan | 12 |\n| Feb | 19 |", None, True),
    ("table", "a paragraph with no table at all", "table_structure", False),
    ("formula", r"\frac{a}{b} = c", None, True),
    ("formula", "E = mc^2", None, True),
    ("formula", "just some prose about maths", "latex_marker", False),
    ("text", "   \n\n  ", "non_empty", False),
]


def main():
    failures = 0
    for i, (kind, candidate, expected, ok) in enumerate(CASES):
        res = assert_structure(candidate, kind)
        label = f"[{i:02d}] {kind:8s} ok={res['ok']!s:5s} failed={res['failed']}"
        if res["ok"] != ok:
            print(f"FAIL {label} — expected ok={ok}")
            failures += 1
        elif expected and expected not in res["failed"]:
            print(f"FAIL {label} — expected failure {expected!r}")
            failures += 1
        else:
            print(f"pass {label}")

    for kind in ("text", "table", "formula"):
        if assert_structure("", kind)["ok"]:
            print(f"FAIL empty {kind} was accepted — gate cannot fail")
            failures += 1

    print(f"\n{len(CASES)} cases, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
