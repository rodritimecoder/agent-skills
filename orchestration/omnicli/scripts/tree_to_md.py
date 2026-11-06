#!/usr/bin/env python3
"""Convert a NaviDC-OCR transcription of an ASCII-art directory tree into a
Markdown nested list.

NaviDC-OCR is a transcriber, not a formatter: a prompt asking for Markdown is
ignored, and box-drawing glyphs get substituted. Observed for "├──":

    ├── README.md   ->  |--- README.md   or   —— README.md

so the structure has to be recovered afterwards.

Recovering depth
----------------
Indentation WIDTH is the signal; counting vertical bars is not. Measured on a
rendered tree after OCR:

    w=3  bars=0/1  -> depth 1     (src/)
    w=10 bars=2     -> depth 2     (__init__.py)
    w=14 bars=2     -> depth 3     (user.py)    <-- same bar count as depth 2

Widths are also noisy: OCR renders the same level with different spacing on
different lines, and ranking widths naively lets one stray line invent an extra
level. See _levels() for how that is handled.
"""
import re
import sys

TREE = "│├└┬┴┼─—|-"
# a space followed by something that is NOT structure and NOT another space
# marks the end of the structural prefix
SPLIT = re.compile(r"(?<= )(?=[^\s" + re.escape(TREE) + r"])")


def _split(raw):
    """-> (prefix, name). The name starts after the last structural space."""
    hits = list(SPLIT.finditer(raw))
    if not hits:
        return "", raw.strip()
    i = hits[-1].start()
    return raw[:i], raw[i:].strip()


def _levels(rows):
    """Map each row's prefix to an indentation depth.

    rows: list of (prefix, name).

    Root lines are detected structurally, not by width: a row whose prefix has
    no structural glyph left after spaces are stripped is the root, whatever its
    width. OCR sometimes prefixes the whole block with a stray space, and
    ranking widths naively turned that into "everything is one level deeper".

    Non-root widths are noisy too - the same level renders with different
    spacing on different lines - so widths seen on 2+ lines are the real levels
    and one-off widths are snapped to the nearest, ties going deeper (safer for a
    listing: it keeps a lone file inside its parent rather than promoting it).

    Trade-off: a genuine level holding exactly one entry is indistinguishable
    from jitter and gets folded into a neighbour.
    """
    counts = {}
    for prefix, _ in rows:
        if prefix.strip():                      # skip the root line
            counts[len(prefix)] = counts.get(len(prefix), 0) + 1

    real = sorted(w for w, c in counts.items() if c >= 2)
    rank = {w: i + 1 for i, w in enumerate(real)}   # real levels start at depth 1

    out = []
    for prefix, _ in rows:
        if not prefix.strip():
            out.append(0)
            continue
        w = len(prefix)
        out.append(rank[w] if w in rank
                   else rank[min(real, key=lambda r: (abs(r - w), -r))])
    return out


def to_markdown(text):
    rows = []
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        prefix, name = _split(raw)
        if not name:
            continue
        rows.append((prefix, name))

    depths = _levels(rows)

    out = []
    for (prefix, name), depth in zip(rows, depths):
        pad = "  " * depth
        if name.endswith("/"):
            out.append(f"{pad}- `{name}`")
        else:
            out.append(f"{pad}- {name}")
    return "\n".join(out)


if __name__ == "__main__":
    src = sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1]).read()
    print(to_markdown(src))