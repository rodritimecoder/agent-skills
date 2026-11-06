"""Curated alias management for the omnicli catalog.

The alias set is the routing surface of a skill: the words a user would
type that appear in no document. It lives in a single JSON file next to the
catalog code, and this module is the only thing that should write it.

Keeping the writes behind one API means a publisher never has to know
where the file is, which matters because the catalog has a canonical copy
and a mirror.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ALIASES_PATH = HERE / "aliases.json"


def load(path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or ALIASES_PATH
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    p = path or ALIASES_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get(skill: str, path: Path | None = None) -> dict[str, Any]:
    return load(path).get(skill, {})


def set_aliases(
    skill: str,
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
    *,
    index_body: bool | None = None,
    body_budget: int | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Set a skill's curated metadata. Returns the stored record.

    Passing None for a field leaves it unchanged; passing an empty list
    clears it. Unknown skills are created, because a publisher may register
    a skill before its directory exists in the collection.

    ``body_budget`` overrides the token gate's body limit for a skill. A
    *command surface* is read to find a command, so its body has a tight
    budget. A *method* skill is read to learn the method, and the method is
    the product — so it may claim a larger one. The override lives here
    rather than in the gate so the budget a skill claims and the budget the
    gate enforces cannot drift apart.
    """
    data = load(path)
    record = dict(data.get(skill) or {})
    if aliases is not None:
        record["aliases"] = [a.strip() for a in aliases if a.strip()]
    if tags is not None:
        record["tags"] = [t.strip() for t in tags if t.strip()]
    if index_body is not None:
        record["index_body"] = bool(index_body)
    if body_budget is not None:
        record["body_budget"] = int(body_budget)
    record.setdefault("aliases", [])
    record.setdefault("tags", [])
    data[skill] = record
    save(data, path)
    return record


def remove(skill: str, path: Path | None = None) -> bool:
    data = load(path)
    if skill not in data:
        return False
    del data[skill]
    save(data, path)
    return True


def candidates(skill_body: str, name: str, description: str, limit: int = 25) -> list[str]:
    """Mine likely alias candidates from a skill's own text.

    The vocabulary gap is computable: a term the body uses that neither the
    name nor the description uses is a word a user might type and the skill
    would fail to match on. This is a starting point for curation, not a
    finished alias set — single words that are already in the name or the
    description are not gaps, and stopwords are not vocabulary.
    """
    from .textutil import tokenize

    known = set(tokenize(name)) | set(tokenize(description))
    counts: dict[str, int] = {}
    for tok in tokenize(skill_body):
        if tok in known or len(tok) < 4:
            continue
        counts[tok] = counts.get(tok, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _ in ranked[:limit]]
