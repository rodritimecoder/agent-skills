"""Skill-level vectors — the dense leg of hybrid retrieval.

BM25 finds chunks; this finds skills by meaning. The vectors live in the
catalog so a search never pays to recompute them.

What is embedded is the skill *description*, not its chunks. Measured on this
catalog (53 skills, 91 queries): descriptions beat chunk bodies by 9 points of
top-1, and chunk bodies cost about three times the embedding time. A chunk is
often a code sample; a description is the author stating what the skill does,
which is the thing an intent should be compared against.

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

SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_vectors (
    skill       TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    vec         BLOB NOT NULL,
    built_at    TEXT NOT NULL
);
"""


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


def ensure(con: sqlite3.Connection, force: bool = False) -> dict[str, Any]:
    """Build or refresh the vector rows for every indexed skill.

    Cheap to call repeatedly: a skill whose description and model are
    unchanged is skipped without touching the endpoint.
    """
    con.executescript(SCHEMA)
    from . import registry

    skills = registry.load_all_skills()
    stale = []
    for name, meta in skills.items():
        text = (meta.get("description") or "").strip()
        if not text:
            continue
        fp = fingerprint(text)
        if force:
            stale.append((name, text, fp))
            continue
        row = con.execute(
            "SELECT fingerprint FROM skill_vectors WHERE skill = ?", (name,)
        ).fetchone()
        if row is None or row["fingerprint"] != fp:
            stale.append((name, text, fp))

    if not stale:
        return {"built": 0, "skipped": len(skills), "dim": _stored_dim(con), "error": None}

    vecs = embed_texts([text for _n, text, _f in stale])
    if vecs is None:
        return {
            "built": 0,
            "skipped": len(skills) - len(stale),
            "dim": _stored_dim(con),
            "error": f"{EMBEDDING_URL} unavailable",
        }

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for (name, _text, fp), vec in zip(stale, vecs):
        norm = _normalise(vec)
        con.execute(
            "INSERT INTO skill_vectors(skill, model, dim, fingerprint, vec, built_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(skill) DO UPDATE SET "
            "model=excluded.model, dim=excluded.dim, fingerprint=excluded.fingerprint, "
            "vec=excluded.vec, built_at=excluded.built_at",
            (name, EMBEDDING_MODEL, len(norm), fp, _pack(norm), now),
        )
    con.commit()
    return {"built": len(stale), "skipped": len(skills) - len(stale), "dim": len(vecs[0]) if vecs else 0, "error": None}


def _stored_dim(con: sqlite3.Connection) -> int:
    try:
        row = con.execute("SELECT dim FROM skill_vectors LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["dim"]) if row else 0


def status(con: sqlite3.Connection) -> dict[str, Any]:
    try:
        rows = con.execute(
            "SELECT model, dim, COUNT(*) AS n FROM skill_vectors GROUP BY model, dim"
        ).fetchall()
    except sqlite3.OperationalError:
        return {"vectors": 0, "model": None, "dim": 0}
    total = sum(r["n"] for r in rows)
    first = rows[0] if rows else None
    return {
        "vectors": total,
        "model": first["model"] if first else None,
        "dim": int(first["dim"]) if first else 0,
    }


def query_vector(text: str, timeout: float = EMBED_TIMEOUT) -> tuple[tuple[float, ...] | None, str | None]:
    """Embed a query with the prefix. Returns (vector, None) or (None, reason)."""
    vecs = embed_texts([Q_PREFIX + text], timeout=timeout)
    if vecs is None:
        return None, f"{EMBEDDING_URL} unavailable"
    return _normalise(vecs[0]), None


def dense_rank(
    con: sqlite3.Connection, query: str, limit: int = 50
) -> tuple[list[str], str | None]:
    """Skills ordered by cosine similarity to the query.

    Returns ([], reason) when the leg cannot run, so the caller can report why
    the tier fell back instead of silently pretending the leg was absent.
    """
    try:
        rows = con.execute("SELECT skill, dim, vec FROM skill_vectors").fetchall()
    except sqlite3.OperationalError:
        return [], "no vectors (run `omnicli index`)"
    if not rows:
        return [], "no vectors (run `omnicli index`)"

    stored_dims = {int(r["dim"]) for r in rows}
    q, reason = query_vector(query)
    if q is None:
        return [], reason
    if len(q) not in stored_dims:
        return [], f"dimension mismatch: index is {sorted(stored_dims)}d, {EMBEDDING_URL} returned {len(q)}d"

    scored = []
    for row in rows:
        vec = _unpack(row["vec"])
        if len(vec) != len(q):
            continue
        scored.append((sum(a * b for a, b in zip(q, vec)), row["skill"]))
    if not scored:
        return [], "no comparable vectors"
    scored.sort(reverse=True)
    return [skill for _score, skill in scored[:limit]], None
