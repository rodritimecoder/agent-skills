"""Search the index: keyword leg + meaning leg, merged with rank fusion.

Usage: python search.py "your question"
Prints the top hits with the lines around them, and which leg found each.
"""

import json
import os
import re
import sqlite3
import struct
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = Path(os.environ.get("RAG_DB_PATH", str(HERE / "rag.db")))
K = 60  # rank fusion smoothing constant
TOP = 3
CONTEXT_LINES = 6
EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://127.0.0.1:8087/v1/embeddings")


STOPWORDS = {
    "a", "an", "and", "are", "at", "can", "do", "does", "for", "how", "i",
    "in", "is", "it", "my", "of", "on", "or", "our", "the", "to", "we",
    "what", "when", "where", "who", "why", "with", "you", "your",
}


def keyword_leg(db, query):
    terms = [t for t in re.findall(r"\w+", query.lower()) if t not in STOPWORDS]
    if not terms:
        return []
    match = " OR ".join(f'"{t}"' for t in terms)
    rows = db.execute(
        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT 10",
        (match,),
    ).fetchall()
    return [r[0] for r in rows]


def index_embedding(db):
    """What built this index: (model, dim, endpoint).

    The embedding slot may host bge-small (384d) or EmbeddingGemma-2 (768d).
    Vectors from the two are not comparable, so the index remembers which one
    it was built with and the meaning leg checks the server against it.
    """
    try:
        rows = dict(db.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.OperationalError:
        return "", 0, ""
    return (
        rows.get("embedding_model", ""),
        int(rows.get("embedding_dim") or 0),
        rows.get("embedding_endpoint", ""),
    )


def meaning_leg(db, query, floor=0.0):
    """Return (rowids, reason). reason is set only when the leg could not run.

    `floor` drops vectors whose cosine is below it. Dense similarity always
    returns a full list, so a leg with no floor cannot abstain: ask an
    out-of-vocabulary question and it still names ten notes, confidently.
    The injection hook passes a floor; the CLI leaves it at 0 to show the
    best hits anyway.
    """
    rows = db.execute("SELECT id, vec FROM vectors").fetchall()
    if not rows:
        model, dim, _ = index_embedding(db)
        if dim:
            return None, f"index has no vectors (built {model} {dim}d, embedding leg failed)"
        return None, None
    model, dim, _ = index_embedding(db)
    try:
        payload = json.dumps({"input": query}).encode("utf-8")
        req = urllib.request.Request(
            EMBEDDING_URL, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            q = res_data["data"][0]["embedding"]
    except Exception as exc:
        return None, f"{EMBEDDING_URL} unavailable ({exc})"

    if dim and len(q) != dim:
        # Refuse rather than compare incomparable vectors: a 384d query dotted
        # against 768d rows would silently return nonsense.
        return None, (
            f"dimension mismatch — index was built with {model} ({dim}d) "
            f"but {EMBEDDING_URL} returned {len(q)}d. Start the matching model "
            f"(see ports.json slot 'embed') or rebuild with build_index.py"
        )

    qnorm = sum(x * x for x in q) ** 0.5 or 1.0
    q = [x / qnorm for x in q]
    scored = []
    for rowid, blob in rows:
        vec = struct.unpack(f"{len(blob) // 4}f", blob)
        if len(vec) != len(q):
            continue
        scored.append((sum(a * b for a, b in zip(q, vec)), rowid))
    scored.sort(reverse=True)
    return [rowid for score, rowid in scored[:10] if score >= floor], None


def fuse(legs):
    scores, found_by = {}, {}
    for name, ids in legs.items():
        for rank, rowid in enumerate(ids):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (K + rank)
            found_by.setdefault(rowid, []).append(name)
    ranked = sorted(scores, key=scores.get, reverse=True)
    return ranked, found_by


def show(db, rowid, position, legs):
    file, section, start, end, text, kind = db.execute(
        "SELECT file, section, start_line, end_line, text, kind FROM chunks WHERE id=?",
        (rowid,),
    ).fetchone()
    print(f"{position}. [{file} § {section}]  legs: {'+'.join(legs)}")
    out = []
    if kind == "distilled":
        out = text.splitlines()
    else:
        corpus = db.execute("SELECT value FROM meta WHERE key='corpus'").fetchone()
        source = Path(corpus[0]) / file if corpus else HERE.parent / "corpus-before" / file
        if source.is_file():
            lines = source.read_text(encoding="utf-8").splitlines()
            s = max(0, start - 1 - CONTEXT_LINES)
            e = min(len(lines), end + CONTEXT_LINES)
            # context lines wear a dot; the chunk itself is bare
            out = ["· " + l for l in lines[s : start - 1]]
            out += lines[start - 1 : end]
            out += ["· " + l for l in lines[end:e]]
        else:
            out = text.splitlines()
    print("\n".join("   " + l for l in out).rstrip())
    print()


def render_table(rows, columns=None, headers=None):
    if not rows:
        return "*(no records)*\n"
    if columns is None:
        columns = list(rows[0].keys())
    if headers is None:
        headers = [col.replace("_", " ").title() for col in columns]

    col_widths = [len(h) for h in headers]
    for r in rows:
        for idx, col in enumerate(columns):
            val_str = str(r.get(col, "")).replace("\n", " ").strip()
            if len(val_str) > col_widths[idx]:
                col_widths[idx] = len(val_str)

    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * col_widths[i] for i in range(len(headers))) + " |"
    row_lines = []
    for r in rows:
        row_str = "| " + " | ".join(str(r.get(col, "")).replace("\n", " ").strip().ljust(col_widths[i]) for i, col in enumerate(columns)) + " |"
        row_lines.append(row_str)
    return "\n".join([header_line, sep_line] + row_lines) + "\n"


def fetch_hit(db, rowid, position, legs):
    file, section, start, end, text, kind = db.execute(
        "SELECT file, section, start_line, end_line, text, kind FROM chunks WHERE id=?",
        (rowid,),
    ).fetchone()
    first_non_empty = ""
    for l in text.splitlines():
        cl = l.strip().lstrip("#").strip()
        if cl and not cl.startswith("source:"):
            first_non_empty = cl
            break
    snippet = first_non_empty[:85] + "..." if len(first_non_empty) > 85 else first_non_empty
    line_range = f"{start}-{end}" if start > 0 else "-"
    return {
        "rank": position,
        "file": file,
        "section": section,
        "lines": line_range,
        "legs": "+".join(legs),
        "snippet": snippet,
        "text": text,
    }


def utf8_out():
    """Write UTF-8 whatever the console's code page is."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main():
    import argparse
    utf8_out()

    parser = argparse.ArgumentParser(description="Search local graph-memory index")
    parser.add_argument("query", nargs="+", help="Query terms")
    parser.add_argument("--table", "-t", action="store_true", help="Render results as high-density Markdown table")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--project", "-p", help="Comma-separated fields to project")
    parser.add_argument("--limit", "-n", type=int, default=TOP, metavar="LIMIT", help=f"Max number of hits (default: {TOP})")
    parser.add_argument("--out", "-o", help="Buffer full text hits to file and return table receipt")

    args = parser.parse_args()
    query = " ".join(args.query)

    if not DB.is_file():
        sys.exit("no index yet: run python build_index.py first")
    db = sqlite3.connect(DB)

    legs = {"keyword": keyword_leg(db, query)}
    meaning, why = meaning_leg(db, query)
    if meaning is None:
        if why and not (args.json or args.table or args.out):
            print(f"meaning leg off: {why} — keyword only\n")
    else:
        legs["meaning"] = meaning

    ranked, found_by = fuse(legs)
    if not ranked:
        if args.json:
            print("[]")
        else:
            print("no matches")
        return

    hits = []
    for position, rowid in enumerate(ranked[:args.limit], start=1):
        hits.append(fetch_hit(db, rowid, position, found_by[rowid]))

    if args.out:
        out_p = Path(args.out).expanduser()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(hits, indent=2, ensure_ascii=False), encoding="utf-8")
        sys.stderr.write(f"### Buffered {len(hits)} memory hits to `{args.out}`\n")

    if args.project:
        proj = [k.strip().lower() for k in args.project.split(",") if k.strip()]
        hits = [{k: h[k] for k in h if k.lower() in proj} for h in hits]

    if args.json:
        print(json.dumps(hits, indent=2, ensure_ascii=False))
    elif args.table or args.out:
        cols = ["rank", "file", "section", "lines", "legs", "snippet"]
        if args.project:
            proj = [k.strip().lower() for k in args.project.split(",") if k.strip()]
            cols = [c for c in cols if c in proj] or cols
        table_rows = [{k: h[k] for k in cols if k in h} for h in hits]
        print(render_table(table_rows, cols))
    else:
        # Backward-compatible verbose show
        for position, rowid in enumerate(ranked[:args.limit], start=1):
            show(db, rowid, position, found_by[rowid])


if __name__ == "__main__":
    main()
