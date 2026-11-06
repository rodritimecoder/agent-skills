"""Read a SKILL.md back on demand, in pieces.

The catalog indexes a skill's body to search it, but the Agent Skills spec
also expects an agent to be able to *read* the skill it picked: the usage
guide, the caveats, the worked examples. When the gateway is the front line,
that read has to go through the gateway too, or the agent either over-fetches
(the whole body every time) or under-fetches (guesses the flags).

So a skill document is split into its sections, and the agent pulls the
outline first and then only the section it needs. Nothing here modifies the
file on disk; this is a read-side view of it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# ~4 characters per token is the usual English approximation. Used for sizing
# only, never for exact accounting.
CHARS_PER_TOKEN = 4

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def estimate_tokens(text: str) -> int:
    """Rough token count for a piece of text."""
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN) if text.strip() else 0


def parse_frontmatter(text: str) -> dict[str, str]:
    """Top-level scalar fields of the frontmatter.

    Deliberately not a YAML parser: the frontmatter in this collection uses
    folded scalars and nested maps, and the control plane stays
    dependency-free. Nested values are returned as their raw block.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    block = match.group(1)
    fields: dict[str, str] = {}
    key = None
    buf: list[str] = []
    for line in block.splitlines():
        if line[:1] not in (" ", "\t") and ":" in line:
            if key:
                fields[key] = "\n".join(buf).strip()
            key, _, rest = line.partition(":")
            key = key.strip()
            buf = [rest] if rest.strip() else []
        elif key is not None:
            buf.append(line)
    if key:
        fields[key] = "\n".join(buf).strip()
    return fields


def split_sections(body: str) -> list[dict[str, Any]]:
    """Split a markdown body into heading-delimited sections."""
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return [{"heading": "", "level": 0, "body": body.strip(), "tokens": estimate_tokens(body)}]
    sections: list[dict[str, Any]] = []
    preamble = body[: matches[0].start()].strip()
    if preamble:
        sections.append({
            "heading": "", "level": 0, "body": preamble,
            "tokens": estimate_tokens(preamble),
        })
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[match.end(): end].strip()
        sections.append({
            "heading": match.group(2).strip(),
            "level": len(match.group(1)),
            "body": chunk,
            "tokens": estimate_tokens(chunk),
        })
    return sections


def load_skill_doc(md_path: str | Path) -> dict[str, Any]:
    """Read one SKILL.md into a document the gateway can serve in pieces."""
    path = Path(md_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    match = _FRONTMATTER_RE.match(text)
    frontmatter = parse_frontmatter(text)
    body = text[match.end():] if match else text
    sections = split_sections(body)
    return {
        "path": str(path),
        "frontmatter": frontmatter,
        "sections": sections,
        "tokens": estimate_tokens(body),
        "section_count": len(sections),
    }


def outline(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The section index: heading, level and a token estimate per section."""
    return [
        {"heading": s["heading"], "level": s["level"], "tokens": s["tokens"]}
        for s in doc["sections"]
    ]


def _normalize(heading: str) -> str:
    """Strip leading emoji and punctuation so 'Quick' finds '🛠️ CLI Quickstart'."""
    return re.sub(r"^[^0-9A-Za-z]+", "", heading).strip().lower()


def pick_section(doc: dict[str, Any], wanted: str) -> dict[str, Any] | None:
    """Find a section by heading, case-insensitively and prefix-tolerant.

    Headings in the wild carry emoji and prefixes ('🛠️ CLI Quickstart'), so a
    caller asking for 'quick' should still find it.
    """
    needle = (wanted or "").strip().lower()
    if not needle:
        return None
    normalized = _normalize(wanted)
    for section in doc["sections"]:
        heading = section["heading"].lower()
        if heading == needle or heading.startswith(needle):
            return section
    for section in doc["sections"]:
        heading = _normalize(section["heading"])
        if not heading:
            continue
        if heading == normalized or heading.startswith(normalized):
            return section
    for section in doc["sections"]:
        heading = _normalize(section["heading"])
        if heading and normalized and normalized in heading:
            return section
    return None
