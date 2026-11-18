#!/usr/bin/env python3
"""Golden-set evaluation for the pplx-decider client.

Usage: eval_golden.py [--port N] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pplx_decider import PplxDecider

GOLDEN = [
    {
        "id": "refund_late",
        "state": "User wants a refund after 60 days. The purchase was 2 months ago.",
        "questions": {"a": {"type": "noul", "instructions": "Is this within the 30-day refund policy?"}},
        "expect": {"a": False},
    },
    {
        "id": "refund_early",
        "state": "User wants a refund 5 days after buying a laptop. The receipt is attached.",
        "questions": {"a": {"type": "noul", "instructions": "Is this within the 30-day refund policy?"}},
        "expect": {"a": True},
    },
    {
        "id": "route_billing",
        "state": "I was charged twice for my order last week and nobody has replied.",
        "questions": {
            "a": {
                "type": "choice",
                "instructions": "Which team should handle this?",
                "criteria": {"billing": "Charges and refunds", "shipping": "Delivery issues", "technical": "Software faults"},
            }
        },
        "expect": {"a": "billing"},
    },
    {
        "id": "route_technical",
        "state": "The desktop app crashes every time I open the settings panel. Error code E402.",
        "questions": {
            "a": {
                "type": "choice",
                "instructions": "Which team should handle this?",
                "criteria": {"billing": "Charges and refunds", "shipping": "Delivery issues", "technical": "Software faults"},
            }
        },
        "expect": {"a": "technical"},
    },
    {
        "id": "blocked",
        "state": "My production API stopped working and 4000 customers cannot checkout. I cannot fix it myself.",
        "questions": {"a": {"type": "noul", "instructions": "Is the customer blocked right now?"}},
        "expect": {"a": True},
    },
    {
        "id": "not_blocked",
        "state": "I have a question about the documentation for the export feature. Everything else works.",
        "questions": {"a": {"type": "noul", "instructions": "Is the customer blocked right now?"}},
        "expect": {"a": False},
    },
    {
        "id": "urgent",
        "state": "The payment system is down and revenue is lost every minute.",
        "questions": {
            "a": {
                "type": "score",
                "instructions": "How urgent is this?",
                "criteria": ["can wait", "this week", "today", "right now"],
            }
        },
        "expect": {"a": 3},
    },
    {
        "id": "not_urgent",
        "state": "The colour of the footer links could be slightly different from the design mockup.",
        "questions": {
            "a": {
                "type": "score",
                "instructions": "How urgent is this?",
                "criteria": ["can wait", "this week", "today", "right now"],
            }
        },
        "expect": {"a": 0},
    },
    {
        "id": "lang",
        "state": "Bonjour, je n'arrive pas a me connecter a mon compte depuis ce matin.",
        "questions": {
            "a": {
                "type": "choice",
                "instructions": "What language is this message written in?",
                "criteria": {"english": None, "french": None, "spanish": None, "german": None},
            }
        },
        "expect": {"a": "french"},
    },
    {
        "id": "pii",
        "state": "My card number is 4111 1111 1111 1111 and my SSN is 123-45-6789. Please fix my account.",
        "questions": {"a": {"type": "noul", "instructions": "Does this message contain sensitive personal data?"}},
        "expect": {"a": True},
    },
]


def _make_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A solid-colour PNG, so the vision cases need no image assets."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--json", default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    client = PplxDecider(host=args.host, port=args.port)
    if not client.is_online():
        print("server offline", file=sys.stderr)
        sys.exit(2)

    red = _make_png(64, 64, (220, 30, 30))
    blue = _make_png(64, 64, (30, 30, 220))

    cases = list(GOLDEN) + [
        {
            "id": "vision_red",
            "state": "A photo.",
            "questions": {"a": {"type": "noul", "instructions": "Is there a red square in the image?"}},
            "expect": {"a": True},
            "images": [red],
        },
        {
            "id": "vision_not_red",
            "state": "A photo.",
            "questions": {"a": {"type": "noul", "instructions": "Is there a blue square in the image?"}},
            "expect": {"a": False},
            "images": [red],
        },
        {
            "id": "vision_blue",
            "state": "A photo.",
            "questions": {"a": {"type": "noul", "instructions": "Is there a blue square in the image?"}},
            "expect": {"a": True},
            "images": [blue],
        },
    ]

    rows = []
    correct = 0
    for case in cases:
        result = client.decide(case["state"], case["questions"], images=case.get("images"))
        answers = result["answers"]
        ok = True
        detail = {}
        for qid, expected in case["expect"].items():
            answer = answers[qid]
            if isinstance(expected, bool):
                got = bool(answer["noul"] >= 0.5)
                hit = got == expected
            elif isinstance(expected, str):
                got = answer["argmax"]
                hit = got == expected
            else:
                got = round(answer["score"], 3)
                hit = abs(answer["score"] - expected) < 0.5
            detail[qid] = {"got": got, "expected": expected, "hit": hit}
            ok = ok and hit
        correct += int(ok)
        rows.append({"id": case["id"], "correct": ok, "detail": detail, "answers": answers})
        if args.verbose or not ok:
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {case['id']:16} {detail}")

    total = len(cases)
    print(f"\naccuracy: {correct}/{total} = {correct / total:.1%}")
    if args.json:
        Path(args.json).write_text(json.dumps({"correct": correct, "total": total, "rows": rows}, indent=2))
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
