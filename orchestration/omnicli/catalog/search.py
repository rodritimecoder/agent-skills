"""Retrieval for the omnicli catalog.

    BM25 (lexical)  ─┐
                     ├─ RRF → top-K
    dense (descriptions) ─┘        [optional leg, absent when :8087 is down]

Two legs fused by reciprocal rank, because they fail on different queries.
Measured on this catalog, 61 tuned + 30 held-out intents, top-1:

    BM25 alone      60/61 · 12/30
    dense alone     45/61 · 18/30
    RRF, always     52/61 · 17/30
    RRF, gated      56/61 · 15/30

Fusion buys unseen phrasings and costs tuned ones. The golden set shares the
catalog's own vocabulary, so BM25's exact-term prior wins there; a paraphrase
that only the dense leg can place is where fusion pays. Neither constant is
right for every caller, so the choice is a runtime argument (`fusion`), and
the default gates on BM25's own confidence.

The failure mode that justified the old chained design is real and still
guarded: this corpus contains generic meta-docs (``icm-architect``,
``review-hub``) that sit close to almost any question. RRF damps them because
a dense-only hit earns one 1/(k+rank) contribution and cannot outrank a skill
both legs place highly; the gate keeps fusion from demoting a confident win.

When the endpoint is down the dense leg reports why, the tier says so, and the
result set is what BM25 found. Ranking gets worse; retrieval does not break.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any

from . import textutil, vectors

# FTS5 column weights. Columns are (skill, kind, title, path, body, aliases);
# the first two are UNINDEXED and must still be counted.
#
# The alias column is weighted far above prose. A curated alias is the skill
# author stating "this vocabulary routes here"; incidental body text matching
# the same word says much less. Without this separation, a large generic
# document out-votes a precise curated signal purely on volume.
TITLE_WEIGHT = 5.0
BODY_WEIGHT = 1.0
ALIAS_WEIGHT = 12.0

CANDIDATE_POOL = 200     # chunks pulled from FTS5
DEFAULT_LIMIT = 6

STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "but", "by", "can", "did",
    "do", "does", "for", "from", "get", "has", "have", "how", "i", "if", "in",
    "is", "it", "its", "me", "my", "need", "of", "on", "or", "our", "please",
    "should", "so", "some", "that", "the", "their", "then", "there", "these",
    "they", "this", "to", "tool", "use", "want", "was", "we", "what", "when",
    "where", "which", "who", "why", "will", "with", "you", "your",
}

EMBEDDING_URL = vectors.EMBEDDING_URL
EMBEDDING_MODEL = vectors.EMBEDDING_MODEL

# A re-ranker is only worth its latency if the endpoint is actually up.
#
# Two separate timeouts, because the failure modes differ. A *probe* is a
# liveness check and must be near-instant: if the port is filtered rather
# than closed, a 20s probe would stall every search. The re-rank itself may
# legitimately take longer, since it embeds the query plus every candidate.
PROBE_TIMEOUT = 1.0
RERANK_TIMEOUT = 5.0
PROBE_TTL = 30.0
RERANK_CANDIDATES = 20
# Lexical confidence gate. BM25 is near-saturated on the golden set (60/61
# top-1) and the semantic re-ranker changes #1 on none of those cases, so
# paying ~130ms of embedding latency on every query buys nothing. The re-ranker
# only fires when BM25 itself is unsure: the gap between the top two hits is
# a small fraction of the top score.
RERANK_GATE_MARGIN = 0.25

# The re-ranker is a tri-state: off, gated, forced. Every caller passes it as
# a string (`--rerank auto|always|never`), and `search` used to compare that
# string against `True` — so `always` silently behaved like `never`. One
# normaliser, called once, so a new caller cannot re-introduce the bug.
RERANK_MODES = {
    "always": True, "on": True, "true": True, "force": True,
    "never": False, "off": False, "false": False, "none": False,
    "auto": "auto",
}


def normalize_rerank(mode: bool | str | None) -> bool | str:
    if isinstance(mode, bool):
        return mode
    if mode is None:
        return False
    if isinstance(mode, str):
        return RERANK_MODES.get(mode.strip().lower(), "auto")
    return "auto"


# Reciprocal rank fusion. K damps the head of each list so one leg's rank-1
# cannot outvote a skill both legs place in their top three.
FUSION_K = 60

FUSION_MODES = {
    "always": True, "on": True, "true": True, "force": True,
    "never": False, "off": False, "false": False, "none": False,
    "auto": "auto",
}


def normalize_fusion(mode: bool | str | None) -> bool | str:
    if isinstance(mode, bool):
        return mode
    if mode is None:
        return "auto"
    if isinstance(mode, str):
        return FUSION_MODES.get(mode.strip().lower(), "auto")
    return "auto"



# --------------------------------------------------------------------------
# query construction
# --------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """Query tokenizer: word tokens, with CJK runs split into bigrams."""
    return [t for t in textutil.tokenize(text) if t not in STOPWORDS]


def build_match(tokens: list[str]) -> str:
    """FTS5 MATCH expression: every token, quoted, OR-joined.

    Quoting keeps FTS5 from interpreting a token as a column filter or
    operator, which would silently drop results.
    """
    quoted = [f'"{t}"' for t in tokens if t]
    if not quoted:
        return ""
    return " OR ".join(quoted)


# --------------------------------------------------------------------------
# BM25
# --------------------------------------------------------------------------

def _bm25_leg(con: sqlite3.Connection, tokens: list[str], pool: int) -> list[sqlite3.Row]:
    """Return chunks ranked by BM25, best first.

    ``bm25()`` returns negative numbers (more negative = better match), so the
    sign is flipped to make "higher is better" hold everywhere downstream.
    """
    match = build_match(tokens)
    if not match:
        return []
    try:
        rows = con.execute(
            "SELECT d.rowid AS rid, d.skill, d.kind, d.title, d.path, d.body, "
            f"       bm25(docs, 0.0, 0.0, {TITLE_WEIGHT}, 0.0, {BODY_WEIGHT}, {ALIAS_WEIGHT}) AS raw "
            "FROM docs d WHERE docs MATCH ? "
            "ORDER BY raw LIMIT ?",
            (match, pool),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return rows


def _term_stats(con: sqlite3.Connection, tokens: list[str]) -> tuple[dict[str, int], dict[str, float]]:
    """Per-token skill-level document frequency and IDF.

    IDF is measured at the *skill* level, not the chunk level, because the
    question being asked is "which of my 27 skills should handle this?".
    A term that appears in 3 skills ("podcast") is highly discriminating; a
    term that appears in 20 ("text") barely narrows the field at all. The
    coordination factor below leans on exactly this distinction.
    """
    total = con.execute("SELECT count(DISTINCT skill) AS c FROM docs").fetchone()["c"] or 1
    df: dict[str, int] = {}
    idf: dict[str, float] = {}
    for tok in tokens:
        try:
            n = con.execute(
                "SELECT count(DISTINCT skill) AS c FROM docs WHERE docs MATCH ?", (f'"{tok}"',)
            ).fetchone()["c"]
        except sqlite3.OperationalError:
            n = 0
        df[tok] = n
        if n > 0:
            idf[tok] = math.log((total - n + 0.5) / (n + 0.5) + 1.0)
    return df, idf


def _token_hits(con: sqlite3.Connection, tokens: list[str]) -> dict[str, set[int]]:
    """Map each token to the set of doc rowids that contain it."""
    hits: dict[str, set[int]] = {}
    for tok in tokens:
        try:
            rows = con.execute(
                "SELECT rowid FROM docs WHERE docs MATCH ?", (f'"{tok}"',)
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        hits[tok] = {r[0] for r in rows}
    return hits


# Coordination strength. 0 = pure BM25 (ignore which terms matched),
# 1 = a skill must cover essentially the whole query to score well.
# Tuned against tests/golden_eval.json.
COORDINATION_GAMMA = 0.65

# How many extra matching chunks a skill may count towards its coverage
# bonus. Bounded, because an uncapped bonus lets a large generic document
# accumulate score purely by having more text to match in.
COVERAGE_CAP = 4
COVERAGE_WEIGHT = 0.15

# Coordination is applied only to the top candidates by lexical score. A
# skill that is not lexically competitive cannot be rescued by covering more
# of the query, and a decisively better lexical match is not thrown away by
# an unrelated skill happening to match more generic words.
#
# Without this, "use the local llm to write a python script" went to a skill
# whose docs merely *contain* a Python example, even though the local-llm
# skill had by far the strongest lexical match.
COORDINATION_CANDIDATES = 3

# Body-length penalty. BM25 already normalises per chunk (b=0.75), but the
# aggregation takes the best chunk per skill and then lets coordination reward
# coverage, so a skill with 93 chunks (icm-architect) gets 93 chances at one
# good chunk while omnicli gets one. The score is damped by chunks**-alpha so
# a large body has to be proportionally more relevant to win.
#
# Measured on this catalog; see tests/eval_runner.py --fusion. 0 disables it.
CHUNK_PENALTY_ALPHA = float(os.environ.get("OMNICLI_CHUNK_ALPHA", "0.2"))

_SIZES: dict[str, Any] = {"at": 0.0, "map": {}}


def _aggregate(
    rows: list[sqlite3.Row],
    token_hits: dict[str, set[int]],
    idf: dict[str, float],
) -> list[dict[str, Any]]:
    """Collapse chunk hits into per-skill scores.

    Two factors, deliberately separated:

    * **BM25 term score** — how well the single best chunk matches.
    * **Coordination** — which *distinct* query terms the skill matched,
      weighted by IDF. A skill that matches the rare, decisive term
      ("podcast") outranks one that matches only generic terms ("turn",
      "into") even when the generic ones score higher in isolation.

    The second factor is what stops a large, generic meta-document from
    winning every query purely by having more text to match in — the exact
    failure mode of the old substring scorer, and of a parallel semantic leg.
    """
    denom = sum(idf.values())
    by_skill: dict[str, dict[str, Any]] = {}

    for r in rows:
        score = -r["raw"]  # flip: higher is better
        matched = {t for t, ids in token_hits.items() if r["rid"] in ids}
        entry = by_skill.get(r["skill"])
        if entry is None:
            entry = {"skill": r["skill"], "score": 0.0, "chunks": [], "kinds": set(),
                     "_matched": set()}
            by_skill[r["skill"]] = entry
        entry["chunks"].append({
            "kind": r["kind"],
            "title": r["title"],
            "path": r["path"],
            "score": round(score, 4),
            "matched": sorted(matched),
            "snippet": _snippet(r["body"]),
        })
        entry["kinds"].add(r["kind"])
        entry["_matched"] |= matched
        if score > entry["score"]:
            entry["score"] = score

    out = []
    for entry in by_skill.values():
        n = len(entry["chunks"])
        bonus = COVERAGE_WEIGHT * min(n - 1, COVERAGE_CAP)
        lex = entry["score"] * (1.0 + bonus)

        covered = sum(idf[t] for t in entry["_matched"] if t in idf)
        coordination = (covered / denom) if denom > 0 else 0.0

        entry["lexical_score"] = round(lex, 4)
        entry["coordination"] = round(coordination, 4)
        entry["matched_terms"] = sorted(entry["_matched"])
        entry["coverage"] = n
        entry["kinds"] = sorted(entry["kinds"])
        entry["chunks"].sort(key=lambda c: c["score"], reverse=True)
        # The working set is not part of the result. Leaving a set in here
        # made `omnicli search --json` raise a TypeError.
        entry.pop("_matched", None)
        out.append(entry)

    # Stage 1: rank by lexical score, keep the competitive candidates.
    out.sort(key=lambda e: e["lexical_score"], reverse=True)
    head = out[:COORDINATION_CANDIDATES]
    tail = out[COORDINATION_CANDIDATES:]

    # Stage 2: coordination resolves ties among those candidates.
    for e in head:
        e["score"] = round(e["lexical_score"] * (e["coordination"] ** COORDINATION_GAMMA), 4)
    head.sort(key=lambda e: e["score"], reverse=True)

    # The tail keeps a meaningful order: it is damped by the weakest
    # coordination factor in the head, so it can never outrank a candidate
    # that was actually considered, and the score scale stays continuous.
    floor = min((e["coordination"] ** COORDINATION_GAMMA for e in head), default=0.0)
    for e in tail:
        e["score"] = round(e["lexical_score"] * floor, 4)
    tail.sort(key=lambda e: e["score"], reverse=True)

    return head + tail


def _snippet(body: str, width: int = 220) -> str:
    text = re.sub(r"\s+", " ", body or "").strip()
    return text[:width] + ("…" if len(text) > width else "")


# --------------------------------------------------------------------------
# optional embedding re-ranker
# --------------------------------------------------------------------------

def _embed(texts: list[str], timeout: float = RERANK_TIMEOUT) -> list[list[float]] | None:
    """Call the local embedding endpoint. None means it is not usable."""
    return vectors.embed_texts(texts, timeout=timeout)


def _cosine(a: list[float], b: list[float]) -> float:
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if not na or not nb:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def needs_rerank(results: list[dict[str, Any]]) -> bool:
    """Is BM25 unsure enough to be worth the embedding round trip?

    Confidence is the relative gap between the best and second-best hit. A
    single hit cannot be reordered, so it never qualifies.
    """
    if len(results) < 2:
        return False
    top = results[0].get("score", 0.0)
    second = results[1].get("score", 0.0)
    if top <= 0:
        return True
    margin = (top - second) / top
    return margin < RERANK_GATE_MARGIN


def rerank(con: sqlite3.Connection, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Reorder BM25 candidates by semantic similarity.

    Returns None when the embedding endpoint is unavailable, which leaves the
    caller with the untouched BM25 ordering. The endpoint is optional by
    design; the catalog must be fully usable with every model server down.
    """
    if not candidates:
        return None
    pool = candidates[:RERANK_CANDIDATES]
    texts = [query]
    for c in pool:
        texts.append(c["chunks"][0]["snippet"] if c["chunks"] else c["skill"])
    vecs = _embed(texts)
    if vecs is None or len(vecs) < 2:
        return None
    q = vecs[0]
    scored = []
    for c, v in zip(pool, vecs[1:]):
        c = dict(c)
        c["semantic"] = round(_cosine(q, v), 4)
        scored.append(c)
    # Blend: lexical score keeps primacy, semantic only reorders near-ties.
    max_lex = max((c["score"] for c in scored), default=1.0) or 1.0
    for c in scored:
        c["score"] = round(c["score"] / max_lex * 0.7 + c["semantic"] * 0.3, 4)
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored + candidates[RERANK_CANDIDATES:]


_PROBE: dict[str, Any] = {"at": 0.0, "ok": False}


def embedding_available(max_age: float = PROBE_TTL) -> bool:
    """Liveness probe for the optional re-ranker, cached briefly.

    The probe uses a short timeout and its result is cached for half a
    minute, so a filtered (rather than closed) port costs one second once
    instead of stalling every status call.
    """
    now = time.monotonic()
    if now - _PROBE["at"] < max_age:
        return bool(_PROBE["ok"])
    ok = _embed(["ping"], timeout=PROBE_TIMEOUT) is not None
    _PROBE["at"] = now
    _PROBE["ok"] = ok
    return ok


# --------------------------------------------------------------------------
# projections
# --------------------------------------------------------------------------

def compact(results: list[dict[str, Any]], *, why_chars: int = 140) -> list[dict[str, Any]]:
    """A routing-sized view of the results.

    The full result carries every matching chunk of every skill: 25 KB for a
    ten-result query, about 6.3k tokens. An agent choosing a skill needs the
    name, the score, the terms that matched, and one line of evidence — not
    the evidence archive. `--chunks` returns the full shape when the caller
    actually wants to read it.
    """
    out = []
    for r in results:
        chunks = r.get("chunks") or []
        top = chunks[0] if chunks else {}
        out.append({
            "skill": r.get("skill"),
            "score": r.get("score"),
            "matched": r.get("matched_terms", []),
            "why": (top.get("snippet") or "")[:why_chars],
            "top": {"kind": top.get("kind"), "title": top.get("title")},
            "chunk_count": len(chunks),
        })
    return out


def _skill_sizes(con: sqlite3.Connection, max_age: float = 5.0) -> dict[str, int]:
    """Chunks per skill, cached briefly: the catalog changes on reindex only."""
    now = time.monotonic()
    if now - _SIZES["at"] < max_age and _SIZES["map"]:
        return _SIZES["map"]
    try:
        rows = con.execute("SELECT skill, COUNT(*) AS n FROM docs GROUP BY skill").fetchall()
    except sqlite3.OperationalError:
        return {}
    _SIZES["map"] = {r["skill"]: int(r["n"]) for r in rows}
    _SIZES["at"] = now
    return _SIZES["map"]


def _apply_length_penalty(con: sqlite3.Connection, results: list[dict[str, Any]]) -> None:
    """Damp scores by body size, then restore a meaningful order."""
    if not CHUNK_PENALTY_ALPHA or not results:
        return
    sizes = _skill_sizes(con)
    for r in results:
        n = max(sizes.get(r["skill"], 1), 1)
        penalty = round(n ** -CHUNK_PENALTY_ALPHA, 4)
        r["length_penalty"] = penalty
        r["score"] = round(r["score"] * penalty, 4)
    results.sort(key=lambda r: r["score"], reverse=True)


# --------------------------------------------------------------------------
# fusion
# --------------------------------------------------------------------------

def _dense_record(con: sqlite3.Connection, skill: str) -> dict[str, Any]:
    """A result row for a skill only the dense leg found.

    The lexical leg never touched it, so there is no chunk hit to carry. The
    skill's own description stands in as the evidence line, which keeps the
    downstream shape identical (`chunks[0]` always exists).
    """
    row = con.execute(
        "SELECT kind, title, path, body FROM docs WHERE skill = ? "
        "ORDER BY LENGTH(body) DESC LIMIT 1",
        (skill,),
    ).fetchone()
    kind = row["kind"] if row else "doc"
    return {
        "skill": skill,
        "score": 0.0,
        "lexical_score": 0.0,
        "coordination": 0.0,
        "matched_terms": [],
        "coverage": 0,
        "kinds": [kind],
        "chunks": [
            {
                "kind": kind,
                "title": row["title"] if row else skill,
                "path": row["path"] if row else "",
                "score": 0.0,
                "matched": [],
                "snippet": _snippet(row["body"]) if row else "",
            }
        ],
    }


def _fuse(
    con: sqlite3.Connection,
    lexical: list[dict[str, Any]],
    dense_ids: list[str],
    k: int = FUSION_K,
) -> list[dict[str, Any]]:
    """Reciprocal rank fusion of the two legs, rescaled to 0-1.

    `lexical_score` is preserved on every row so a caller can still see how
    the BM25 leg alone ranked it; `score` becomes the fused relevance, and
    `found_by` names the legs that produced the hit.
    """
    by_skill = {r["skill"]: r for r in lexical}
    scores: dict[str, float] = {}
    found: dict[str, list[str]] = {}
    for leg, ids in (("bm25", [r["skill"] for r in lexical]), ("dense", dense_ids)):
        for rank, skill in enumerate(ids):
            scores[skill] = scores.get(skill, 0.0) + 1.0 / (k + rank + 1)
            found.setdefault(skill, []).append(leg)

    top = max(scores.values(), default=1.0) or 1.0
    fused = []
    for skill, score in sorted(scores.items(), key=lambda kv: -kv[1]):
        entry = dict(by_skill.get(skill) or _dense_record(con, skill))
        entry["rrf"] = round(score, 6)
        entry["found_by"] = found.get(skill, [])
        entry["score"] = round(score / top, 4)
        fused.append(entry)
    return fused


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------

def search(
    con: sqlite3.Connection,
    query: str,
    limit: int = DEFAULT_LIMIT,
    *,
    rerank_enabled: bool | str = "auto",
    fusion: bool | str = "auto",
    explain: bool = False,
) -> dict[str, Any]:
    """Search the catalog. Returns a dict with results and retrieval metadata."""
    rerank_enabled = normalize_rerank(rerank_enabled)
    fusion = normalize_fusion(fusion)
    tokens = tokenize(query)
    if not tokens:
        return {
            "query": query,
            "tier": "bm25",
            "results": [],
            "tokens": [],
            "note": "Query contained only stopwords; nothing to search for.",
        }

    rows = _bm25_leg(con, tokens, CANDIDATE_POOL)
    df, idf = _term_stats(con, tokens)
    token_hits = _token_hits(con, tokens)
    results = _aggregate(rows, token_hits, idf)
    _apply_length_penalty(con, results)

    tier = "bm25"
    dense = {"ran": False, "reason": None}

    if fusion and results:
        wants = fusion is True or (fusion == "auto" and needs_rerank(results))
        if wants:
            dense_ids, dense_reason = vectors.dense_rank(con, query, CANDIDATE_POOL)
            dense["reason"] = dense_reason
            if dense_ids:
                results = _fuse(con, results, dense_ids)
                dense["ran"] = True
                tier = "bm25+dense(rrf)" if fusion is True else "bm25+dense(rrf:gated)"

    # The blend re-ranker is a second semantic mechanism; it never runs on top
    # of a fused ranking, where it would re-score the same signal twice.
    if not dense["ran"] and rerank_enabled and results:
        # rerank_enabled may be True (always), False (never) or "auto" (only
        # when the lexical ranking is unsure).
        wants = rerank_enabled is True or (rerank_enabled == "auto" and needs_rerank(results))
        if wants:
            reordered = rerank(con, query, results)
            if reordered is not None:
                results = reordered
                tier = "bm25+rerank"
            elif rerank_enabled == "auto":
                tier = "bm25(gated)"
        elif rerank_enabled == "auto":
            tier = "bm25(gated:confident)"

    results = results[:limit]

    if explain:
        for r in results:
            r["term_idf"] = {t: round(idf[t], 3) for t in r.get("matched_terms", []) if t in idf}

    return {
        "query": query,
        "tier": tier,
        "tokens": tokens,
        "candidate_chunks": len(rows),
        "dense": dense,
        "results": results,
    }
