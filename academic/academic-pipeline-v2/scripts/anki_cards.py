#!/usr/bin/env python3
"""Card extraction for the Anki hub: markdown note -> atomic review cards.

A card is one fact with one question.  Extraction is deterministic and
extractive: it never invents an answer, it only decides which slice of the note
is worth testing.  Rules, in order:

* a markdown heading becomes the question;
* the text under it, up to the next heading, becomes the answer;
* PDF artefacts (``(cid:N)``) are removed;
* an answer longer than one sentence is cut to its first sentence, because a
  whole exercise block cannot be recalled in one step;
* empty answers, bare prompts ("...:") and cross-references ("See Lecture
  Notes") are dropped: they point at a fact instead of being one.
"""

from __future__ import annotations

import re

_CID_RE = re.compile(r"\(cid:\d+\)")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_HEADING_RE = re.compile(r"^#{1,6}\s*(.*\S)\s*$")
_CROSSREF_RE = re.compile(r"^(see|refer|check|read|watch|review)\b", re.IGNORECASE)

CARD_CHAR_LIMIT = 240
MIN_CARD_CHARS = 20


def clean(text):
    """Drop PDF extraction artefacts and collapse whitespace."""
    return re.sub(r"\s+", " ", _CID_RE.sub(" ", str(text or ""))).strip()


def atomic(answer, limit=CARD_CHAR_LIMIT):
    """First sentence of a block: the one fact a card should test."""
    answer = clean(answer)
    if len(answer) <= limit:
        return answer
    first = _SENTENCE_RE.split(answer)[0]
    if first and len(first) <= limit:
        return first
    return answer[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "..."


def is_cardable(answer):
    """A card must carry a fact: not blank, not a pointer, not a bare prompt."""
    if len(answer) < MIN_CARD_CHARS:
        return False
    if answer.endswith(":"):
        return False
    if _CROSSREF_RE.match(answer) and len(answer) < 120:
        return False
    return True


def heading_text(line):
    """The question text of one markdown heading line."""
    match = _HEADING_RE.match(line.strip())
    return clean(match.group(1)) if match else ""


def document_title(text):
    """The ``title:`` a note declares in its frontmatter, if it declares one."""
    body = str(text or "")
    if not body.startswith("---"):
        return ""
    end = body.find("\n---", 3)
    if end == -1:
        return ""
    for line in body[3:end].strip("\n").splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "title":
            return clean(value).strip("\"'")
    return ""


def extract_cards(text, skip_title=None):
    """Return [{'q': str, 'a': str}] - one card per markdown heading.

    ``skip_title`` is the note's own document title.  Stage 1 writes it as the
    first heading, so without this a PDF's filename becomes a card whose answer
    is the course name.
    """
    cards = []
    lines = str(text or "").splitlines()
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("#"):
            continue
        question = heading_text(line)
        if not question:
            continue
        if skip_title and question.casefold() == str(skip_title).strip().casefold():
            continue
        collected = []
        cursor = index + 1
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        while (
            cursor < len(lines)
            and lines[cursor].strip()
            and not lines[cursor].lstrip().startswith("#")
        ):
            collected.append(lines[cursor].strip())
            cursor += 1
        answer = atomic(" ".join(collected))
        if answer and is_cardable(answer):
            cards.append({"q": question, "a": answer})
    return cards
