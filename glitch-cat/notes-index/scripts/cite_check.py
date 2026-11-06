#!/usr/bin/env python3
"""Cite check — prove that an answer's citations are real.

Kem Glitch measured the cheap half of this on reel `DfFSZDvN6oV`: telling plain
Claude Code to cite a source before answering lifted verified answers from 70%
to 92.5% on a 200-file test. The instruction produces the behaviour; this module
is the gate that refuses an answer whose citations do not exist.

Two citation styles are checked:

    path         `notes.md`, `../other/notes.md:12`, `source.md:4-9`
    timestamp    `— [01:35]`, resolved against a transcript whose blocks are
                 headed `**[01:35]** ...`

A paragraph that names a file or a timestamp is held to its citations: every
quoted span in that paragraph must appear inside the cited text. Editorial
insertions in brackets (`[Claude Code]`), ellipses and whitespace changes are
tolerated. Paraphrase is not.

What this cannot check: whether the quote supports the claim. That needs a judge
with fresh context, not a substring.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PATH_EXTENSIONS = (
    "md markdown mdx txt rst py ipynb js jsx ts tsx json jsonl yaml yml toml "
    "sh bash zsh rs go rb php java kt swift c h cpp hpp cs sql csv tsv html "
    "css svelte vue log ini cfg conf env"
).split()

PATH_RE = re.compile(
    r"(?<![\w/])((?:\.{0,2}/)?(?:[\w.\-]+/)*[\w.\-]+\.(?:%s))(?::(\d+)(?:-(\d+))?)?(?![\w])"
    % "|".join(PATH_EXTENSIONS)
)
QUOTE_RE = re.compile(r'"([^"\n]{20,})"|“([^”\n]{20,})”')
TIMESTAMP_CITE_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]")
TIMESTAMP_BLOCK_RE = re.compile(r"^\s*\**\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\**(.*)$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
LIST_ITEM_RE = re.compile(r"^(?:[-*+]|\d+\.)\s")


def _norm(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split()).lower()


def _fragments(quote: str) -> List[str]:
    quote = re.sub(r"\[[^\]]*\]", " … ", quote)
    parts = re.split(r"\.\.\.|…", quote)
    return [n for n in (_norm(p) for p in parts) if len(n) >= 4]


def _contains(haystack: str, fragments: List[str]) -> bool:
    if not fragments:
        return False
    pos = 0
    for frag in fragments:
        idx = haystack.find(frag, pos)
        if idx < 0:
            return False
        pos = idx + len(frag)
    return True


def _seconds(h: str, m: str, s: Optional[str]) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s or 0)


def paragraphs(text: str) -> List[Tuple[int, str]]:
    """Blocks with their 1-based start line: blank lines, headings, fences and list items break them."""
    blocks: List[Tuple[int, str]] = []
    buf: List[str] = []
    start = 0
    fenced = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if FENCE_RE.match(line):
            if buf:
                blocks.append((start, "\n".join(buf)))
                buf, start = [], 0
            fenced = not fenced
            continue
        if fenced:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if buf:
                blocks.append((start, "\n".join(buf)))
                buf, start = [], 0
            continue
        if LIST_ITEM_RE.match(stripped) and buf:
            blocks.append((start, "\n".join(buf)))
            buf, start = [], 0
        if not buf:
            start = number
        buf.append(stripped)
    if buf:
        blocks.append((start, "\n".join(buf)))
    return blocks


def transcript_blocks(path: Path) -> Dict[int, str]:
    blocks: Dict[int, str] = {}
    if not path.is_file():
        return blocks
    current: Optional[int] = None
    chunk: List[str] = []

    def flush() -> None:
        if current is not None:
            blocks[current] = _norm(" ".join(chunk))

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = TIMESTAMP_BLOCK_RE.match(line)
        if match:
            flush()
            current = _seconds(match.group(1), match.group(2), match.group(3))
            chunk = [match.group(4)]
            continue
        if current is not None:
            chunk.append(line)
    flush()
    return blocks


def _resolve(raw: str, answer_dir: Path, root: Path) -> Optional[Path]:
    candidate = Path(raw).expanduser()
    options = [candidate] if candidate.is_absolute() else [answer_dir / candidate, root / candidate]
    for option in options:
        if option.is_file():
            return option
    return None


def check(
    answer: Path,
    root: Optional[Path] = None,
    transcript: Optional[Path] = None,
    strict_lines: bool = False,
    coverage_chars: int = 80,
) -> dict:
    answer = Path(answer).expanduser()
    if not answer.is_file():
        raise FileNotFoundError(f"no such answer file: {answer}")
    root = Path(root).expanduser() if root else answer.parent
    transcript_path = Path(transcript).expanduser() if transcript else answer.parent / "transcript.md"

    text = answer.read_text(encoding="utf-8", errors="replace")
    stamps = transcript_blocks(transcript_path)

    files: Dict[str, str] = {}
    violations: List[dict] = []
    warnings: List[dict] = []
    citation_count = 0
    quote_count = 0
    verified_count = 0
    inherited: Tuple[List, List] = ([], [])

    for line, block in paragraphs(text):
        flat = " ".join(block.splitlines())
        paths = []
        for match in PATH_RE.finditer(flat):
            before = flat[max(0, match.start() - 12):match.start()]
            if "://" in before:
                continue
            raw = match.group(1)
            first = int(match.group(2)) if match.group(2) else None
            last = int(match.group(3)) if match.group(3) else None
            citation_count += 1
            resolved = _resolve(raw, answer.parent, root)
            if resolved is None:
                kind = "missing_file" if (match.group(2) or raw.startswith(("./", "../")) ) else "unresolved_reference"
                item = {"line": line, "kind": kind, "detail": raw}
                (violations if kind == "missing_file" else warnings).append(item)
                continue
            try:
                body = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                violations.append({"line": line, "kind": "unreadable_file", "detail": f"{raw}: {exc}"})
                continue
            files[str(resolved)] = body
            total = len(body.splitlines())
            if first and first > total:
                violations.append({"line": line, "kind": "line_out_of_range", "detail": f"{raw}:{first} > {total} lines"})
            if last and last > total:
                violations.append({"line": line, "kind": "line_out_of_range", "detail": f"{raw}:{last} > {total} lines"})
            paths.append((str(resolved), first, last, body))

        stamps_here = []
        for match in TIMESTAMP_CITE_RE.finditer(flat):
            citation_count += 1
            seconds = _seconds(match.group(1), match.group(2), match.group(3))
            if not stamps:
                violations.append({"line": line, "kind": "missing_transcript", "detail": str(transcript_path)})
                continue
            keys = sorted(stamps)
            prior = [k for k in keys if k <= seconds]
            index_at = keys.index(prior[-1]) if prior else 0
            window = [stamps[k] for k in keys[max(0, index_at - 1): index_at + 2]]
            stamps_here.append((seconds, "\n".join(window)))

        is_table = block.lstrip().startswith("|")
        if block.lstrip().startswith(">") and not paths and not stamps_here:
            paths, stamps_here = inherited
        if paths or stamps_here:
            inherited = (paths, stamps_here)
        if not paths and not stamps_here:
            if not is_table and len(_norm(block)) >= coverage_chars:
                warnings.append({"line": line, "kind": "uncited_claim", "detail": _norm(block)[:90]})
            continue
        if is_table:
            continue

        quotes = [m.group(1) or m.group(2) for m in QUOTE_RE.finditer(flat)]
        for quote in quotes:
            quote_count += 1
            fragments = _fragments(quote)
            corpus = [body for _, _, _, body in paths] + [body for _, body in stamps_here if body]
            hit = next((body for body in corpus if _contains(_norm(body), fragments)), None)
            if hit is None:
                violations.append({"line": line, "kind": "quote_not_found", "detail": quote[:70]})
                continue
            if strict_lines:
                ranged = [(first, last, body) for _, first, last, body in paths if first]
                if ranged:
                    in_range = False
                    for first, last, body in ranged:
                        window = "\n".join(body.splitlines()[first - 1:(last or first)])
                        if _contains(_norm(window), fragments):
                            in_range = True
                            break
                    if not in_range:
                        violations.append({"line": line, "kind": "quote_outside_lines", "detail": quote[:70]})
                        continue
            verified_count += 1

    return {
        "answer": str(answer),
        "transcript": str(transcript_path),
        "citations": citation_count,
        "quotes": quote_count,
        "verified_quotes": verified_count,
        "violations": violations,
        "warnings": warnings,
        "pass": not violations,
    }


def render(report: dict) -> str:
    head = (
        f"{'✅' if report['pass'] else '🛑'} [cite] {report['citations']} citations · "
        f"{report['verified_quotes']}/{report['quotes']} quotes verbatim · "
        f"{len(report['violations'])} violations · {len(report['warnings'])} uncited paragraphs"
    )
    lines = [head]
    for item in report["violations"]:
        lines.append(f"  ✗ line {item['line']}: {item['kind']} — {item['detail']}")
    for item in report["warnings"]:
        lines.append(f"  ⚠ line {item['line']}: {item['kind']} — {item['detail']}…")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prove that an answer's citations are real."
    )
    parser.add_argument(
        "answer",
        type=Path,
        help="Markdown answer file, or '-' to read the answer from stdin",
    )
    parser.add_argument(
        "--transcript",
        type=Path,
        help="Transcript markdown whose blocks are headed **[MM:SS]**",
    )
    parser.add_argument(
        "--strict-lines",
        action="store_true",
        help="Require quotes to sit inside the cited line range",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON instead of the rendered summary",
    )
    args = parser.parse_args(argv)

    from_stdin = str(args.answer) == "-"
    temporary: Optional[tempfile.TemporaryDirectory] = None
    root: Optional[Path] = None
    transcript: Optional[Path] = args.transcript

    if from_stdin:
        temporary = tempfile.TemporaryDirectory(prefix="cite_check_")
        answer = Path(temporary.name) / "stdin.md"
        answer.write_text(sys.stdin.read(), encoding="utf-8")
        root = Path.cwd()
        if transcript is None:
            transcript = root / "transcript.md"
    else:
        answer = args.answer

    try:
        report = check(
            answer,
            root=root,
            transcript=transcript,
            strict_lines=args.strict_lines,
        )
    except FileNotFoundError as exc:
        print(f"[cite] {exc}", file=sys.stderr)
        return 2
    finally:
        if temporary is not None:
            temporary.cleanup()

    if from_stdin:
        report["answer"] = "<stdin>"

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render(report))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
