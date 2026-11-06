#!/usr/bin/env python3
"""Semantic cache engine: SQLite rows, local embeddings, and a judge gate.

A cosine score is not a correctness measure, it only ranks candidates. The
known failure is a direction flip -- "Fahrenheit to Celsius" and "Celsius to
Fahrenheit" are the same bag of words, so they score about 0.998 against each
other, higher than most honest rewordings of the same question. `SemanticCache.get`
therefore treats the threshold as a candidate filter and lets an optional
`judge` decide whether a candidate may actually be served.
"""
import datetime
import hashlib
import json
import math
import re
import sqlite3
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


class LocalEmbedder:
    """Embed against the embedding slot, with a labelled offline fallback.

    The slot at :8087 hosts exactly two candidates -- bge-small-en-v1.5 (384d)
    and EmbeddingGemma-2 (768d) -- and the offline fallback is a third, 128d
    hash space. Vectors from different spaces are not comparable, so every
    embedded row records which space it came from and `get` skips the rest
    instead of silently scoring them 0.0. Vectors from the *same* space are
    comparable, but comparability stops at "these texts look alike": it never
    says the cached answer answers this question, which is why `get` can be
    given a judge.
    """

    def __init__(self, endpoint: str = "http://127.0.0.1:8087/v1/embeddings", timeout: float = 0.5):
        self.endpoint = endpoint
        self.timeout = timeout
        self.last_source = "unknown"

    def embed(self, text: str) -> List[float]:
        clean_text = text.strip()
        try:
            # No "model" field: the server owns exactly one loaded model, and
            # naming one here just goes stale when the slot's candidate swaps.
            payload = json.dumps({"input": clean_text}).encode("utf-8")
            req = urllib.request.Request(self.endpoint, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.last_source = "endpoint"
                    return data["data"][0]["embedding"]
        except Exception:
            pass

        # Pure-Python bag-of-words normalized embedding fallback. The digest is
        # blake2b rather than hash(): str hashing is salted per process, and a
        # persisted cache written by one process has to stay comparable in the
        # next one.
        words = re.findall(r"[a-z0-9]+", clean_text.lower())
        vec_dim = 128
        vec = [0.0] * vec_dim
        for w in words:
            digest = hashlib.blake2b(w.encode("utf-8"), digest_size=8).digest()
            vec[int.from_bytes(digest, "big") % vec_dim] += 1.0

        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        self.last_source = "hash-bow"
        return vec


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if len(v1) != len(v2) or not v1:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


class SemanticCache:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = LocalEmbedder()
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS semantic_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL UNIQUE,
                    embedding TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    hit_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_accessed TEXT NOT NULL
                )
            """)
            # Which space each row's vector came from, so a row written by the
            # offline fallback (or by the other embedding candidate) can never
            # be scored against a query vector of a different width.
            cols = {r[1] for r in conn.execute("PRAGMA table_info(semantic_cache)")}
            for col, decl in (("embedding_source", "TEXT"), ("embedding_dim", "INTEGER")):
                if col not in cols:
                    conn.execute(f"ALTER TABLE semantic_cache ADD COLUMN {col} {decl}")
            conn.commit()

    def get(self, query: str, threshold: float = 0.85,
            judge: Optional[Callable[[str, str, str], bool]] = None) -> Dict[str, Any]:
        """Look up `query`, optionally gating the candidate on a judge.

        `threshold` only decides which rows are *candidates*: cosine similarity
        orders text, it does not measure correctness. When a candidate clears
        the threshold and `judge` is given, `judge(query, cached_query, answer)`
        is asked and only a true verdict serves the answer. A false verdict is
        a miss with `reason == "judge_rejected"` and the candidate's row id in
        `rejected_id`; a judge that raises fails closed the same way, with the
        exception text in `judge_error`. The judge is never consulted when no
        candidate clears the threshold, and a rejected candidate accrues no
        hit and does not move `last_accessed`.
        """
        query_vec = self.embedder.embed(query)
        qdim = len(query_vec)
        best_hit = None
        best_sim = 0.0
        incompatible = 0

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, query, embedding, answer, hit_count, embedding_dim FROM semantic_cache"
            )
            rows = cursor.fetchall()

            for row_id, cached_q, emb_json, ans, hits, row_dim in rows:
                cached_vec = json.loads(emb_json)
                if (row_dim or len(cached_vec)) != qdim:
                    incompatible += 1
                    continue
                sim = cosine_similarity(query_vec, cached_vec)
                if sim > best_sim:
                    best_sim = sim
                    best_hit = (row_id, cached_q, ans, hits)

            if best_hit and best_sim >= threshold:
                row_id, cached_q, ans, hits = best_hit
                if judge is not None:
                    judge_error = None
                    try:
                        accepted = bool(judge(query, cached_q, ans))
                    except Exception as exc:  # noqa: BLE001 - fail closed, not open
                        accepted = False
                        judge_error = f"{type(exc).__name__}: {exc}"
                    if not accepted:
                        rejected = {
                            "hit": False,
                            "query": query,
                            "reason": "judge_rejected",
                            "rejected_id": row_id,
                            "matched_query": cached_q,
                            "similarity": round(best_sim, 4),
                            "best_similarity": round(best_sim, 4),
                            "threshold": threshold,
                            "embedding_source": self.embedder.last_source,
                            "skipped_incompatible": incompatible,
                        }
                        if judge_error is not None:
                            rejected["judge_error"] = judge_error
                        return rejected
                cursor.execute(
                    "UPDATE semantic_cache SET hit_count = hit_count + 1, last_accessed = ? WHERE id = ?",
                    (datetime.datetime.now(datetime.timezone.utc).isoformat(), row_id)
                )
                conn.commit()
                return {
                    "hit": True,
                    "query": query,
                    "matched_query": cached_q,
                    "answer": ans,
                    "similarity": round(best_sim, 4),
                    "hit_count": hits + 1,
                }

        return {
            "hit": False,
            "query": query,
            "best_similarity": round(best_sim, 4),
            "threshold": threshold,
            "embedding_source": self.embedder.last_source,
            "skipped_incompatible": incompatible,
        }

    def set(self, query: str, answer: str) -> None:
        query_vec = self.embedder.embed(query)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO semantic_cache
                    (query, embedding, answer, hit_count, created_at, last_accessed,
                     embedding_source, embedding_dim)
                VALUES (?, ?, ?, 0, ?, ?, ?, ?)
                ON CONFLICT(query) DO UPDATE SET
                    answer = excluded.answer,
                    embedding = excluded.embedding,
                    embedding_source = excluded.embedding_source,
                    embedding_dim = excluded.embedding_dim,
                    last_accessed = excluded.last_accessed
            """, (
                query.strip(), json.dumps(query_vec), answer.strip(), now, now,
                self.embedder.last_source, len(query_vec),
            ))
            conn.commit()

    def stats(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), COALESCE(SUM(hit_count), 0) FROM semantic_cache")
            total_entries, total_hits = cursor.fetchone()
            return {
                "total_entries": total_entries,
                "total_cache_hits": total_hits,
                "db_path": str(self.db_path),
            }

    def purge(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM semantic_cache")
            deleted = cursor.rowcount
            conn.commit()
            return deleted
