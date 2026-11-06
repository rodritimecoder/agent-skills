"""The legacy substring scorer, preserved verbatim for benchmarking.

This is the algorithm that shipped in ``local-hub``'s ``cmd_search``:

    for t in query.lower().split():
        if t in name:    score += 10
        if t in desc:    score += 5
        score += min(md_content.count(t), 10)

It is kept here so that ``omnicli eval`` can report a measured delta against
the BM25 catalog rather than an asserted one. Do not use it for retrieval —
it is a baseline, not a fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import registry


def score_all(query: str, skills: dict[str, dict[str, Any]] | None = None) -> list[tuple[int, str]]:
    """Return [(score, skill_name)] using the legacy substring algorithm."""
    if skills is None:
        skills = registry.load_all_skills()
    q_tokens = query.lower().split()
    scored: list[tuple[int, str]] = []
    for name, s in skills.items():
        score = 0
        md_path = s.get("md_path")
        md_content = ""
        if md_path:
            try:
                md_content = Path(md_path).read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                md_content = ""
        desc = s["description"].lower()
        n = name.lower()
        for t in q_tokens:
            if t in n:
                score += 10
            if t in desc:
                score += 5
            score += min(md_content.count(t), 10)
        if score > 0:
            scored.append((score, name))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored
