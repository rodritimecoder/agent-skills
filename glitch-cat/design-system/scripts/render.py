#!/usr/bin/env python3
"""Render one standalone HTML page from tokens.css and a named look.

    from render import render, write
    html = render("Title", "<h1>hello</h1>", look="paper")
    write("page.html", "Title", body, look="paper")

    python3 scripts/render.py --title T --body file.html --look house --out page.html

Stdlib only. The page inlines the base rules and exactly one look block, so it
makes no external requests: no <link>, no <script>, no font fetch. The body is
trusted markup and is inserted unchanged -- this module renders, it does not
sanitise and it does not design.
"""

from __future__ import annotations

import argparse
import re
import sys
from html import escape
from pathlib import Path

LOOKS = ("house", "paper", "terminal")
DEFAULT_LOOK = "house"

TOKENS_CSS = Path(__file__).resolve().parent.parent / "tokens.css"

_LOOK_RE = re.compile(r'\[data-look="([a-z-]+)"\]\s*\{')

_PAGE = """<!DOCTYPE html>
<html lang="en" data-look="{look}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
{body}
</body>
</html>
"""


class RenderError(ValueError):
    """Bad look name, or a tokens.css that cannot be read as expected."""


def check_look(look: str) -> str:
    """Return ``look`` unchanged, or raise RenderError listing the valid ones."""
    if look not in LOOKS:
        raise RenderError(
            f"unknown look {look!r}; valid looks are: {', '.join(LOOKS)}"
        )
    return look


def _block_end(css: str, open_brace: int) -> int:
    """Index just past the brace that closes the block opened at ``open_brace``."""
    depth = 0
    for i in range(open_brace, len(css)):
        char = css[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    raise RenderError("unbalanced braces in tokens.css")


def _look_block(css: str, look: str) -> str:
    """The single ``[data-look="<look>"]`` block, with its selector."""
    for match in _LOOK_RE.finditer(css):
        if match.group(1) == look:
            return css[match.start():_block_end(css, match.end() - 1)]
    raise RenderError(f"tokens.css has no [data-look=\"{look}\"] block")


def _leading_comment_start(css: str, floor: int, start: int) -> int:
    """Index of the comment heading directly above ``start``, else ``start``."""
    begin = css.rfind("/*", floor, start)
    if begin == -1:
        return start
    end = css.find("*/", begin + 2)
    if end != -1 and not css[end + 2:start].strip():
        return begin
    return start


def _without_look_blocks(css: str) -> str:
    """tokens.css minus every look block and the comment heading above it."""
    kept, pos = [], 0
    for match in _LOOK_RE.finditer(css):
        start = _leading_comment_start(css, pos, match.start())
        kept.append(css[pos:start])
        pos = _block_end(css, match.end() - 1)
    kept.append(css[pos:])
    return "".join(kept)


def page_css(look: str = DEFAULT_LOOK) -> str:
    """Base rules plus one look block, as text ready for a <style> tag."""
    check_look(look)
    try:
        css = TOKENS_CSS.read_text(encoding="utf-8")
    except OSError as exc:
        raise RenderError(f"cannot read {TOKENS_CSS}: {exc}") from exc

    base = _without_look_blocks(css).strip()
    block = _look_block(css, look)
    return f"{base}\n\n/* look: {look} */\n{block}\n"


def render(title: str, body_html: str, look: str = DEFAULT_LOOK) -> str:
    """A full standalone HTML document: tokens inlined, no external requests."""
    check_look(look)
    return _PAGE.format(
        look=look,
        title=escape(title, quote=False),
        css=page_css(look),
        body=body_html,
    )


def write(path, title: str, body_html: str, look: str = DEFAULT_LOOK) -> Path:
    """Render and write to ``path`` (parents created); returns the path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(title, body_html, look=look), encoding="utf-8")
    return out


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render.py",
        description="Render one standalone HTML page in a named look.",
    )
    parser.add_argument("--title", required=True, help="document <title>")
    parser.add_argument(
        "--body",
        required=True,
        metavar="FILE",
        help="HTML fragment file, or - to read stdin",
    )
    parser.add_argument(
        "--look",
        default=DEFAULT_LOOK,
        help=f"one of: {', '.join(LOOKS)} (default: {DEFAULT_LOOK})",
    )
    parser.add_argument(
        "--out",
        metavar="FILE",
        help="write the page here instead of stdout",
    )
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.body == "-":
            body = sys.stdin.read()
        else:
            body = Path(args.body).read_text(encoding="utf-8")
        if args.out:
            path = write(args.out, args.title, body, look=args.look)
            print(f"wrote {path}", file=sys.stderr)
        else:
            sys.stdout.write(render(args.title, body, look=args.look))
    except (RenderError, OSError) as exc:
        print(f"render: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
