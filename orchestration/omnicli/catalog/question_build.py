"""Curation: raw generated questions -> committed, gated snapshot.

Generation is a model's job; admission is not. This module is the only path
from a batch of proposed questions to ``catalog/questions.json``, and it applies
two deterministic gates plus a dedupe pass:

1. **Lexical** (``questions.gate``) — the quote must be a verbatim span of the
   skill's own description, the question may not name the skill, and it must
   share at least one content token with its evidence.
2. **Semantic** — the question must sit close to its own skill's description
   embedding (cosine >= ``questions.SELF_FLOOR``). This is the check that a
   stolen quote cannot pass: an off-topic question is far from the description
   it claims to come from, however verbatim its quote.

Relative assignment (own description vs. the best other skill) is *not* used:
on this catalog 149 of 275 questions were closer to another skill's description
than their own, because short descriptions overlap semantically. Requiring a
margin would reject good questions for a ranking artefact.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import questions, vectors


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def build(
    raw: dict[str, Any],
    source_text: dict[str, str],
    embed=vectors.embed_texts,
) -> dict[str, Any]:
    """Gate ``raw`` into a snapshot payload plus a rejection ledger."""
    merged = questions.merge(raw, source_text)
    accepted: dict[str, list[dict[str, str]]] = merged["accepted"]
    rejected: list[dict[str, str]] = list(merged["rejected"])

    # Exact duplicates across skills mean two skills claim one intent. Keep the
    # first and log it: that is an alias/disambiguation signal, not an index row.
    seen: dict[str, str] = {}
    for skill in list(accepted):
        keep = []
        for entry in accepted[skill]:
            key = entry["question"].lower()
            if key in seen:
                rejected.append({
                    "skill": skill, "question": entry["question"],
                    "reason": f"duplicate of {seen[key]}",
                })
                continue
            seen[key] = skill
            keep.append(entry)
        accepted[skill] = keep

    skills = sorted(s for s in source_text if s in accepted)
    descs = [source_text[s] for s in skills]
    flat: list[tuple[str, dict[str, str]]] = []
    for skill in skills:
        for entry in accepted[skill]:
            flat.append((skill, entry))

    result: dict[str, Any] = {
        "accepted": accepted,
        "rejected": rejected,
        "self_cosine": {},
        "error": None,
    }
    if not flat:
        return result

    vecs = embed(descs + [entry["question"] for _skill, entry in flat])
    if vecs is None:
        result["error"] = f"{vectors.EMBEDDING_URL} unavailable; semantic gate skipped"
        return result

    desc_vecs = {s: _unit(v) for s, v in zip(skills, vecs[:len(skills)])}
    question_vecs = vecs[len(skills):]

    kept: dict[str, list[dict[str, str]]] = {}
    for (skill, entry), vec in zip(flat, question_vecs):
        self_score = _dot(_unit(vec), desc_vecs[skill])
        result["self_cosine"].setdefault(skill, []).append(round(self_score, 4))
        if self_score < questions.SELF_FLOOR:
            rejected.append({
                "skill": skill, "question": entry["question"],
                "reason": f"self-similarity {self_score:.2f} < {questions.SELF_FLOOR}",
            })
            continue
        kept.setdefault(skill, []).append(entry)

    result["accepted"] = kept
    return result


def from_dir(directory: Path, embed=vectors.embed_texts) -> dict[str, Any]:
    """Read every ``*.out.json`` in a directory and curate them together."""
    from . import registry

    raw: dict[str, Any] = {"questions": {}}
    files = sorted(Path(directory).glob("*.json"))
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload = data.get("questions") if isinstance(data, dict) else None
        if not isinstance(payload, dict):
            continue
        for skill, entries in payload.items():
            if isinstance(entries, list):
                raw["questions"].setdefault(skill, []).extend(entries)

    source_text = {
        name: " ".join((meta.get("description") or "").split())
        for name, meta in registry.load_all_skills().items()
        if (meta.get("description") or "").strip()
    }
    return build(raw, source_text, embed=embed)
