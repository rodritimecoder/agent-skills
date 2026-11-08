"""Distilled questions — the document side of "a question meets a question".

The dense leg embeds each skill's *description* and compares it against a short
agent intent. That is a length-and-register mismatch: a 60-word author statement
against five words of user speech. Cerebras' internal RAG hit the same wall over
raw threads and fixed it by embedding the question someone would search for,
not the thread (Kem Glitch's artefact 02, "distil, then embed").

So each skill gets a handful of search intents, written in the operator's
vocabulary, and the query is compared against *those* as well as the
description. Max-pooling means more questions never buy a skill more chances;
the description row stays as the anchor.

The part that keeps this honest is the gate, and the gate is code:

* every question carries a ``quote`` that must be a verbatim span of that
  skill's own description — no quote, no entry;
* a question may not contain the skill's name (that would be the answer key);
* a question must share content tokens with the source, so a model cannot drift
  into generic phrasing that would route anywhere.

A snapshot is committed so the catalog builds the same way on a machine with no
model and no network. Regeneration is an explicit act, never a query-time cost.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SNAPSHOT_PATH = Path(
    os.environ.get("OMNICLI_QUESTIONS_FILE") or (HERE / "questions.json")
)

# A question short enough to be an intent and long enough to carry meaning.
MIN_WORDS = 4
MAX_WORDS = 18

# One content token must survive into the question from either its quote or its
# description. A *semantic* paraphrase is the point of the feature, so this is
# deliberately weak — it only rejects a question that shares no vocabulary at
# all with its own evidence, which is what a stolen quote looks like.
MIN_ANCHOR_TOKENS = 1

# The real relevance check is semantic and lives in question_build: a question
# must sit close to its own skill's description embedding. Measured on this
# catalog (275 generated questions): own-description cosine median 0.635, p10
# 0.550, min 0.409 — so the floor below rejects only genuine drift.
SELF_FLOOR = 0.45

STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "but", "by", "can", "did",
    "do", "does", "for", "from", "get", "has", "have", "how", "i", "if", "in",
    "is", "it", "its", "me", "my", "need", "of", "on", "or", "our", "please",
    "should", "so", "some", "that", "the", "their", "then", "there", "these",
    "they", "this", "to", "tool", "use", "want", "was", "we", "what", "when",
    "where", "which", "who", "why", "will", "with", "you", "your", "one",
    "something", "thing", "things", "make", "makes", "like", "just", "out",
}


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def content_tokens(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) >= 3 and w not in STOPWORDS
    }


def gate(question: str, quote: str, source: str, skill: str) -> tuple[bool, str]:
    """Decide whether one generated question may enter the index.

    Returns ``(True, "")`` or ``(False, reason)``. The reasons are stable
    strings so a build can report a rejection histogram instead of a shrug.
    """
    q = _norm(question)
    src = _norm(source)
    words = q.split()
    if not (MIN_WORDS <= len(words) <= MAX_WORDS):
        return False, "length"
    if not quote or _norm(quote) not in src:
        return False, "quote not verbatim in source"

    # The skill name is the answer key. Reject the *phrase*, not its individual
    # words: "memory" and "graph" are ordinary domain vocabulary that a good
    # question for graph-memory will legitimately contain.
    named = skill.replace("-", " ").replace("_", " ").lower()
    if named in q.lower() or skill.lower() in q.lower():
        return False, "names the skill"

    anchors = content_tokens(q) & (content_tokens(quote) | content_tokens(src))
    if len(anchors) < MIN_ANCHOR_TOKENS:
        return False, "no lexical anchor in source"
    return True, ""


def enabled() -> bool:
    """Whether the dense leg should embed the snapshot.

    Off by default. The feature is measured-neutral on this catalog (see
    SKILL.md), so it does not get to spend index rows or change rankings unless
    a caller asks for it: ``OMNICLI_QUESTIONS=1 omnicli index``.
    """
    return os.environ.get("OMNICLI_QUESTIONS", "0").strip().lower() in (
        "1", "true", "on", "yes",
    )


def load(path: Path | None = None) -> dict[str, list[dict[str, str]]]:
    """Read the committed snapshot. Missing means no questions."""
    p = path or SNAPSHOT_PATH
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    questions = data.get("questions")
    if not isinstance(questions, dict):
        return {}
    out: dict[str, list[dict[str, str]]] = {}
    for skill, entries in questions.items():
        if not isinstance(entries, list):
            continue
        clean = [
            {"question": _norm(e.get("question", "")), "quote": _norm(e.get("quote", ""))}
            for e in entries
            if isinstance(e, dict) and e.get("question")
        ]
        if clean:
            out[skill] = clean
    return out


def for_skill(
    snapshot: dict[str, list[dict[str, str]]], skill: str, source: str
) -> list[dict[str, str]]:
    """The gated questions for one skill, order preserved."""
    kept: list[dict[str, str]] = []
    for entry in snapshot.get(skill, []):
        ok, _reason = gate(entry["question"], entry["quote"], source, skill)
        if ok:
            kept.append(entry)
    return kept


def merge(raw: dict[str, Any], source_text: dict[str, str]) -> dict[str, Any]:
    """Gate a raw generation payload into a snapshot plus a rejection ledger.

    Used by ``omnicli index --questions``: the model proposes, this decides.
    """
    accepted: dict[str, list[dict[str, str]]] = {}
    rejected: list[dict[str, str]] = []
    for skill, entries in (raw.get("questions") or {}).items():
        src = source_text.get(skill, "")
        if not src:
            rejected.append({"skill": skill, "reason": "unknown skill"})
            continue
        for entry in entries if isinstance(entries, list) else []:
            q = _norm(entry.get("question", "")) if isinstance(entry, dict) else ""
            quote = _norm(entry.get("quote", "")) if isinstance(entry, dict) else ""
            ok, reason = gate(q, quote, src, skill)
            if ok:
                accepted.setdefault(skill, []).append({"question": q, "quote": quote})
            else:
                rejected.append({"skill": skill, "question": q, "reason": reason})
    return {"accepted": accepted, "rejected": rejected}


def write_snapshot(questions: dict[str, list[dict[str, str]]], path: Path | None = None,
                   meta: dict[str, Any] | None = None) -> Path:
    p = path or SNAPSHOT_PATH
    payload = {
        "version": 1,
        "note": (
            "Generated routing questions, one snapshot per catalog. Each entry "
            "carries a verbatim quote from its skill description; the build gate "
            "re-checks it, so an edited description that no longer contains the "
            "quote drops the question instead of indexing a stale claim."
        ),
        **(meta or {}),
        "questions": {k: v for k, v in sorted(questions.items())},
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p
