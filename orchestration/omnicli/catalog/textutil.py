"""Text utilities shared by the indexer and the retriever.

CJK segmentation is the reason this module exists. Chinese, Japanese and
Korean do not delimit words with spaces, so a query like
"调研一下这个话题在网上的讨论" is a single whitespace-delimited token. The
FTS5 ``unicode61`` tokenizer treats an unbroken CJK run in a document as one
token too, so the two never line up and the query matches nothing.

The fix is character bigrams, applied identically on both sides: the indexer
expands every CJK run in the body into its overlapping character pairs, and
the retriever expands every CJK run in the query the same way. "调研" then
matches whether the document wrote it as part of a longer run or not.
"""

from __future__ import annotations

import re

# Han, Hiragana/Katakana, Hangul, plus CJK punctuation that delimits runs.
CJK_RUN = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]+")
WORD = re.compile(r"[\w']+", re.UNICODE)


def cjk_runs(text: str) -> list[str]:
    return CJK_RUN.findall(text or "")


def cjk_bigrams(text: str) -> list[str]:
    """Overlapping character pairs for every CJK run in ``text``."""
    out: list[str] = []
    for run in cjk_runs(text):
        for i in range(len(run) - 1):
            out.append(run[i:i + 2])
    return out


def expand_cjk(text: str) -> str:
    """Append CJK bigrams to ``text`` so they are independently indexable."""
    grams = cjk_bigrams(text)
    if not grams:
        return text
    return f"{text} {' '.join(grams)}"


def tokenize(text: str) -> list[str]:
    """Whitespace/word tokenizer that also splits CJK into bigrams.

    Latin words stay whole; a CJK run contributes every character pair.
    """
    tokens: list[str] = []
    for m in WORD.finditer((text or "").lower()):
        tok = m.group(0)
        if CJK_RUN.fullmatch(tok):
            if len(tok) == 1:
                tokens.append(tok)
            else:
                tokens.extend(tok[i:i + 2] for i in range(len(tok) - 1))
        else:
            tokens.append(tok)
    return tokens
