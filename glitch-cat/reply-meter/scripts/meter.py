#!/usr/bin/env python3
"""reply-meter — a deterministic fault meter for agent replies.

score(text) returns words, sentences, longest_sentence, faults_per_100w and a
list of faults ({rule, line, excerpt}). Every rule is a regex: same text in,
same faults out, on every machine, with no model and no network.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\u2019\-]*")

SLOP_WORDS = (
    "leverage", "utilize", "utilise", "robust", "seamless", "delve", "tapestry",
    "realm", "unlock", "unleash", "elevate", "empower", "streamline", "holistic",
    "synergy", "paradigm", "pivotal", "crucial", "meticulous", "myriad",
    "plethora", "foster", "embark", "testament", "vibrant", "intricate",
    "cutting-edge", "game-changer", "nestled", "boasts",
)

SLOP = re.compile(
    r"\b(?:%s)\w*\b" % "|".join(w.replace("-", r"\-") for w in SLOP_WORDS), re.I
)
BANNED_MODAL = re.compile(r"\b(should|must|might)\b", re.I)
CONTRACTION = re.compile(
    r"\b(?:\w+n['\u2019]t"
    r"|(?:i|you|we|they|he|she|it|that|there|who|what|here)['\u2019](?:s|re|ll|ve|d|m)"
    r"|let['\u2019]s)\b",
    re.I,
)
SEMICOLON = re.compile(r";")
LATIN = re.compile(r"(?<!\w)(?:e\.g|i\.e|etc)\.", re.I)
EM_DASH = re.compile(r"\u2014|(?<=\s)--(?=\s)")
EXCLAIM = re.compile(r"!")
SUMMARY = re.compile(
    r"\b(?:in conclusion|in summary|to sum up|to summarise|to summarize"
    r"|all in all|at the end of the day)\b",
    re.I,
)
SYNONYMS = ("check", "verify", "confirm", "validate")
ING_STOP = frozenset(
    "during nothing something everything anything morning evening spring string "
    "ring bring thing king sing wing ceiling sibling".split()
)

_ABBREV = re.compile(r"\b(e\.g|i\.e|etc|vs|cf|No|Fig|Dr|Mr|Mrs|Ms)\.", re.I)
_LIST_NO = re.compile(r"(?m)^([ \t]*)(\d{1,2})\.")
_SPLIT = re.compile(r"[.!?]+[\"'\u2019)\]]*(?=\s|$)|\n+")


def _mask(text: str) -> str:
    """Neutralise the dots that do not end a sentence, keeping offsets 1:1."""
    text = _LIST_NO.sub(lambda m: m.group(1) + m.group(2) + "\u00b7", text)
    return _ABBREV.sub(lambda m: m.group(0)[:-1] + "\u00b7", text)


def _sentences(text: str):
    """(start, end, body) per sentence, in document order. Offsets index text."""
    masked = _mask(text)
    spans, pos = [], 0
    for m in _SPLIT.finditer(masked):
        if m.end() > pos:
            spans.append((pos, m.end()))
        pos = m.end()
    if pos < len(masked):
        spans.append((pos, len(masked)))
    out = []
    for start, end in spans:
        body = text[start:end]
        if not WORD.search(body):
            continue
        lead = len(body) - len(body.lstrip())
        out.append((start + lead, end, body.strip()))
    return out


def _line(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _excerpt(text: str, start: int, end: int, pad: int = 30) -> str:
    a, b = max(0, start - pad), min(len(text), end + pad)
    frag = " ".join(text[a:b].split())
    if a > 0:
        frag = "\u2026" + frag
    if b < len(text):
        frag = frag + "\u2026"
    if len(frag) > 100:
        frag = frag[:99].rstrip() + "\u2026"
    return frag


# --- rules: each takes (text, sentences) and yields (start, end) spans --------


def _long_sentence(text, sents):
    return [(s, e) for s, e, body in sents if len(WORD.findall(body)) > 25]


def _banned_modal(text, sents):
    return [m.span() for m in BANNED_MODAL.finditer(text)]


def _contraction(text, sents):
    return [m.span() for m in CONTRACTION.finditer(text)]


def _semicolon(text, sents):
    return [m.span() for m in SEMICOLON.finditer(text)]


def _latin(text, sents):
    return [m.span() for m in LATIN.finditer(text)]


def _slop_word(text, sents):
    return [m.span() for m in SLOP.finditer(text)]


def _ing_clause_start(text, sents):
    hits = []
    for s, _e, body in sents:
        m = re.match(
            r"[\s\"'(*>#\-\u2022]*(?:(?:And|But|So|Yet|Then)\s+)?([A-Za-z]+ing)\b",
            body,
            re.I,
        )
        if not m or m.group(1).lower() in ING_STOP:
            continue
        head = body.split(",", 1)
        if len(head) < 2 or len(WORD.findall(head[0])) > 8:
            continue
        hits.append((s, s + m.end()))
    return hits


def _synonym_rotation(text, sents):
    found = {}
    for word in SYNONYMS:
        occ = [m.span() for m in re.finditer(rf"\b{word}(?:s|es|ed|ing)?\b", text, re.I)]
        if occ:
            found[word] = occ
    if len(found) < 2:
        return []
    return [span for occ in found.values() for span in occ]


def _em_dash(text, sents):
    return [m.span() for m in EM_DASH.finditer(text)]


def _exclamation(text, sents):
    return [m.span() for m in EXCLAIM.finditer(text)]


def _summary_boilerplate(text, sents):
    return [m.span() for m in SUMMARY.finditer(text)]


RULES = (
    ("sentence_over_25_words", _long_sentence),
    ("banned_modal", _banned_modal),
    ("contraction", _contraction),
    ("semicolon", _semicolon),
    ("latin_abbrev", _latin),
    ("slop_word", _slop_word),
    ("ing_clause_start", _ing_clause_start),
    ("synonym_rotation", _synonym_rotation),
    ("em_dash", _em_dash),
    ("exclamation_mark", _exclamation),
    ("summary_boilerplate", _summary_boilerplate),
)


def score(text: str) -> dict:
    """Measure a reply. Deterministic: rules are regex, never a model."""
    text = text if isinstance(text, str) else str(text or "")
    sents = _sentences(text)
    rows = []
    for rule, scan in RULES:
        for start, end in scan(text, sents):
            line = _line(text, start)
            rows.append((line, start, {"rule": rule, "line": line,
                                       "excerpt": _excerpt(text, start, end)}))
    rows.sort(key=lambda r: (r[0], r[1]))
    faults = [r[2] for r in rows]
    words = len(WORD.findall(text))
    longest = max((len(WORD.findall(b)) for _s, _e, b in sents), default=0)
    return {
        "words": words,
        "sentences": len(sents),
        "longest_sentence": longest,
        "faults_per_100w": round(len(faults) * 100.0 / words, 1) if words else 0.0,
        "faults": faults,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="reply-meter", description="Score a reply for named prose faults."
    )
    parser.add_argument("--file", required=True,
                        help="Reply to score. Use - to read stdin.")
    parser.add_argument("--json", action="store_true", help="Emit the score as JSON.")
    args = parser.parse_args(argv)

    if args.file == "-":
        text = sys.stdin.read()
    else:
        path = Path(args.file)
        if not path.is_file():
            print(f"reply-meter: no such file: {args.file}", file=sys.stderr)
            return 2
        text = path.read_text(encoding="utf-8", errors="replace")

    result = score(text)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(
        f"words {result['words']}  sentences {result['sentences']}  "
        f"longest {result['longest_sentence']}w  "
        f"faults/100w {result['faults_per_100w']}"
    )
    for fault in result["faults"]:
        print(f"  L{fault['line']:<4} {fault['rule']:<22} {fault['excerpt']}")
    if not result["faults"]:
        print("  clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
