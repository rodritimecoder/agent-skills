"""Skill-level vectors — the dense leg of hybrid retrieval.

BM25 finds chunks; this finds skills by meaning. The vectors live in the
catalog so a search never pays to recompute them.

Two kinds of row per skill:

* ``description`` — the author's own statement of what the skill does. The
  anchor: it is the only per-skill text both legs see, and it is what the
  catalog was tuned on.
* ``question`` — a handful of distilled intents ("a question meets a
  question"), gated against a verbatim quote from that same description. See
  ``catalog/questions.py`` for why and for the gate.

Scoring takes the **best** row per skill, not the sum. Summing would let a skill
with five questions outrank one with two purely by having more text — the same
"more text wins" bias that ``CHUNK_PENALTY_ALPHA`` removed from the lexical leg.

Every row records the model and dimension that produced it. The embedding slot
rotates between bge-small (384d) and EmbeddingGemma-2 (768d), and a 384d query
dotted against a 768d row yields confident nonsense rather than an error, so
the mismatch is refused instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import time
from typing import Any

EMBEDDING_URL = os.environ.get(
    "OMNICLI_EMBEDDING_URL", "http://127.0.0.1:8087/v1/embeddings"
)
EMBEDDING_MODEL = os.environ.get("OMNICLI_EMBEDDING_MODEL", "bge-small-en-v1.5")

# bge-small v1.5 asks for this on the query side of a retrieval pair and for
# nothing on the document side. Measured value on this catalog: +8 top-1 on
# the golden set, +5 on held-out phrasings. The endpoint will not add it.
Q_PREFIX = "Represent this sentence for searching relevant passages: "

PROBE_TIMEOUT = 1.0
EMBED_TIMEOUT = 10.0

# Zero means pure max-pooling: a skill is as good as its single best row. A
# positive value adds that fraction of the description score to the best
# question score, so a skill whose questions are weakly phrased still benefits
# from an author-written description. Measured by tests/eval_runner.py; the
# default is the value that won across both eval sets.
DESC_BLEND = float(os.environ.get("OMNICLI_DESC_BLEND", "0"))

# Experiment/eval knob: score with only one kind of row. Empty means both.
ONLY_KIND = os.environ.get("OMNICLI_VECTORS_KIND", "")

SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_vectors (
    skill       TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'description',
    ord         INTEGER NOT NULL DEFAULT 0,
    text        TEXT NOT NULL DEFAULT '',
    quote       TEXT,
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    vec         BLOB NOT NULL,
    built_at    TEXT NOT NULL,
    PRIMARY KEY (skill, kind, ord)
);
"""


def _ensure_schema(con: sqlite3.Connection) -> None:
    """Create the table, or replace the pre-``kind`` layout.

    The vectors are a derived artifact, so an old layout is dropped rather than
    migrated. Nothing else in the catalog depends on these rows existing.
    """
    cols = {r["name"] for r in con.execute("PRAGMA table_info(skill_vectors)")}
    if cols and "kind" not in cols:
        con.execute("DROP TABLE skill_vectors")
    con.executescript(SCHEMA)


def embed_texts(
    texts: list[str], timeout: float = EMBED_TIMEOUT
) -> list[list[float]] | None:
    """Embed with the local endpoint. None means the endpoint is not usable."""
    import urllib.error
    import urllib.request

    if not texts:
        return []
    payload = json.dumps({"input": texts, "model": EMBEDDING_MODEL}).encode("utf-8")
    req = urllib.request.Request(
        EMBEDDING_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    items = data.get("data")
    if not isinstance(items, list) or len(items) != len(texts):
        return None
    try:
        return [item["embedding"] for item in items]
    except (KeyError, TypeError):
        return None


def _normalise(vec: list[float]) -> tuple[float, ...]:
    norm = sum(x * x for x in vec) ** 0.5
    if not norm:
        return tuple(0.0 for _ in vec)
    return tuple(x / norm for x in vec)


def _pack(vec: tuple[float, ...]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> tuple[float, ...]:
    return struct.unpack(f"{len(blob) // 4}f", blob)


def fingerprint(text: str, model: str = EMBEDDING_MODEL) -> str:
    return hashlib.sha256(f"{model}\x00{text}".encode("utf-8")).hexdigest()


def _wanted_rows(force: bool) -> list[tuple[str, str, int, str, str | None]]:
    """Every (skill, kind, ord, text, quote) this build should contain."""
    from . import questions, registry

    skills = registry.load_all_skills()
    snapshot = questions.load() if questions.enabled() else {}
    rows: list[tuple[str, str, int, str, str | None]] = []
    for name, meta in skills.items():
        text = (meta.get("description") or "").strip()
        if not text:
            continue
        rows.append((name, "description", 0, text, None))
        for i, entry in enumerate(questions.for_skill(snapshot, name, text)):
            rows.append((name, "question", i, entry["question"], entry["quote"]))
    return rows


def ensure(con: sqlite3.Connection, force: bool = False) -> dict[str, Any]:
    """Build or refresh the vector rows for every indexed skill.

    Cheap to call repeatedly: a row whose text and model are unchanged is
    skipped without touching the endpoint, and a row that the current snapshot
    no longer produces is deleted rather than left to win a stale match.
    """
    _ensure_schema(con)
    rows = _wanted_rows(force)
    skill_count = len({r[0] for r in rows})

    existing = {
        (r["skill"], r["kind"], r["ord"]): r["fingerprint"]
        for r in con.execute("SELECT skill, kind, ord, fingerprint FROM skill_vectors")
    }
    stale = [
        r for r in rows
        if force or existing.get((r[0], r[1], r[2])) != fingerprint(r[3])
    ]
    unwanted = set(existing) - {(r[0], r[1], r[2]) for r in rows}
    for key in unwanted:
        con.execute(
            "DELETE FROM skill_vectors WHERE skill = ? AND kind = ? AND ord = ?", key
        )
    if unwanted:
        con.commit()

    if not stale:
        return {
            "built": 0,
            "skipped": len(rows),
            "dim": _stored_dim(con),
            "questions": len([r for r in rows if r[1] == "question"]),
            "error": None,
        }

    vecs = embed_texts([r[3] for r in stale])
    if vecs is None:
        return {
            "built": 0,
            "skipped": len(rows) - len(stale),
            "dim": _stored_dim(con),
            "questions": len([r for r in rows if r[1] == "question"]),
            "error": f"{EMBEDDING_URL} unavailable",
        }

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for (skill, kind, ord_, text, quote), vec in zip(stale, vecs):
        norm = _normalise(vec)
        con.execute(
            "INSERT INTO skill_vectors(skill, kind, ord, text, quote, model, dim, "
            "fingerprint, vec, built_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(skill, kind, ord) DO UPDATE SET "
            "text=excluded.text, quote=excluded.quote, model=excluded.model, "
            "dim=excluded.dim, fingerprint=excluded.fingerprint, "
            "vec=excluded.vec, built_at=excluded.built_at",
            (skill, kind, ord_, text, quote, EMBEDDING_MODEL, len(norm),
             fingerprint(text), _pack(norm), now),
        )
    con.commit()
    return {
        "built": len(stale),
        "skipped": len(rows) - len(stale),
        "dim": len(vecs[0]) if vecs else 0,
        "questions": len([r for r in rows if r[1] == "question"]),
        "skills": skill_count,
        "error": None,
    }


def _stored_dim(con: sqlite3.Connection) -> int:
    try:
        row = con.execute("SELECT dim FROM skill_vectors LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["dim"]) if row else 0


def status(con: sqlite3.Connection) -> dict[str, Any]:
    try:
        rows = con.execute(
            "SELECT kind, model, dim, COUNT(*) AS n FROM skill_vectors "
            "GROUP BY kind, model, dim"
        ).fetchall()
    except sqlite3.OperationalError:
        return {"vectors": 0, "model": None, "dim": 0}
    total = sum(r["n"] for r in rows)
    first = rows[0] if rows else None
    return {
        "vectors": total,
        "model": first["model"] if first else None,
        "dim": int(first["dim"]) if first else 0,
        "description": sum(r["n"] for r in rows if r["kind"] == "description"),
        "question": sum(r["n"] for r in rows if r["kind"] == "question"),
    }


def query_vector(text: str, timeout: float = EMBED_TIMEOUT) -> tuple[tuple[float, ...] | None, str | None]:
    """Embed a query with the prefix. Returns (vector, None) or (None, reason)."""
    vecs = embed_texts([Q_PREFIX + text], timeout=timeout)
    if vecs is None:
        return None, f"{EMBEDDING_URL} unavailable"
    return _normalise(vecs[0]), None


def score_skills(
    con: sqlite3.Connection, query: str
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Best cosine per skill, plus the row that produced it.

    Returns ``({skill: {"score", "kind", "ord", "text"}}, None)`` or
    ``({}, reason)`` when the leg cannot run, so the caller can report why the
    tier fell back instead of silently pretending the leg was absent.
    """
    try:
        rows = con.execute(
            "SELECT skill, kind, ord, dim, text, vec FROM skill_vectors"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}, "no vectors (run `omnicli index`)"
    if not rows:
        return {}, "no vectors (run `omnicli index`)"

    stored_dims = {int(r["dim"]) for r in rows}
    q, reason = query_vector(query)
    if q is None:
        return {}, reason
    if len(q) not in stored_dims:
        return {}, (
            f"dimension mismatch: index is {sorted(stored_dims)}d, "
            f"{EMBEDDING_URL} returned {len(q)}d"
        )

    best: dict[str, dict[str, Any]] = {}
    desc: dict[str, float] = {}
    for row in rows:
        if ONLY_KIND and row["kind"] != ONLY_KIND:
            continue
        vec = _unpack(row["vec"])
        if len(vec) != len(q):
            continue
        score = sum(a * b for a, b in zip(q, vec))
        if row["kind"] == "description":
            desc[row["skill"]] = score
        # Uniform max over every row of the skill, regardless of read order.
        # A description row is an anchor, not a floor: when a question row is a
        # better match for the query it must win, and vice versa.
        current = best.get(row["skill"])
        if current is None or score > current["score"]:
            best[row["skill"]] = {
                "score": score, "kind": row["kind"], "ord": int(row["ord"]),
                "text": row["text"],
            }

    if DESC_BLEND:
        for skill, entry in best.items():
            if entry["kind"] == "question":
                entry["score"] = entry["score"] + DESC_BLEND * desc.get(skill, 0.0)
    return best, None


def dense_rank(
    con: sqlite3.Connection, query: str, limit: int = 50
) -> tuple[list[str], str | None]:
    """Skills ordered by best cosine to the query."""
    best, reason = score_skills(con, query)
    if reason:
        return [], reason
    ordered = sorted(best.items(), key=lambda kv: -kv[1]["score"])
    return [skill for skill, _ in ordered[:limit]], None
