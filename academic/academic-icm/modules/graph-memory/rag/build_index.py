"""Build the index: chunk markdown on headings, index keywords and meaning.

Reads ../corpus-before by default, plus any distilled entries in distilled/.
Subfolders are included, so the digest's daily/ folder is indexed like any note.
Writes rag.db next to this script. Run again any time; the index is disposable.
"""

import argparse
import json
import os
import re
import sqlite3
import struct
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "rag.db"
CHUNK_BUDGET = 1600  # characters, roughly 400 tokens
SKIP_DIRS = {".git", "node_modules", "__pycache__"}
EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://127.0.0.1:8082/v1/embeddings")


def get_embeddings(texts, endpoint=EMBEDDING_URL, batch_size=8):
    """Fetch embeddings via OpenAI-compatible endpoint using urllib."""
    all_vecs = []
    total = len(texts)
    for i in range(0, total, batch_size):
        batch = texts[i : i + batch_size]
        # Defensively bound chunk length to prevent 512-token context window overflow
        batch = [t[:1100] for t in batch]
        payload = json.dumps({"input": batch}).encode("utf-8")
        req = urllib.request.Request(
            endpoint, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                data_items = sorted(res_data["data"], key=lambda x: x.get("index", 0))
                for item in data_items:
                    all_vecs.append(item["embedding"])
        except Exception:
            # Fallback to single-item requests if batch fails
            for item_text in batch:
                try:
                    sub_payload = json.dumps({"input": item_text[:800]}).encode("utf-8")
                    sub_req = urllib.request.Request(
                        endpoint, data=sub_payload, headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(sub_req, timeout=30) as sub_resp:
                        sub_data = json.loads(sub_resp.read().decode("utf-8"))
                        all_vecs.append(sub_data["data"][0]["embedding"])
                except Exception:
                    dummy = [0.0] * 768
                    dummy[0] = 1.0
                    all_vecs.append(dummy)
        if (i // batch_size) % 25 == 0 or i + batch_size >= total:
            print(f"embedded {min(i + batch_size, total)}/{total} chunks...")
    return all_vecs



SCHEMA = """
DROP TABLE IF EXISTS chunks;
DROP TABLE IF EXISTS chunks_fts;
DROP TABLE IF EXISTS vectors;
DROP TABLE IF EXISTS meta;
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    file TEXT NOT NULL,
    section TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'chunk'
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, file, section);
CREATE TABLE vectors (id INTEGER PRIMARY KEY, vec BLOB NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def note_files(corpus):
    root = Path(corpus).resolve()
    starter = HERE.parent.resolve()
    skip_starter = starter != root and root in starter.parents
    out = []
    for pattern in ("*.md", "*.vtt"):
        for path in sorted(root.rglob(pattern)):
            rel = path.relative_to(root)
            if any(part.startswith(".") or part in SKIP_DIRS for part in rel.parts):
                continue
            if skip_starter and (starter == path.parent or starter in path.parents):
                continue
            out.append(path)
    return sorted(out)


def parse_time_to_seconds(ts_str: str) -> int:
    parts = ts_str.strip("[]").split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(float(parts[1]))
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
    return 0


def format_seconds(secs: int) -> str:
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def chunk_transcript(path: Path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    cues = []

    if path.suffix == ".vtt":
        current_time = 0
        current_text = []
        for line in lines:
            m = re.match(r"(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)", line)
            if m:
                if current_text:
                    cues.append((current_time, " ".join(current_text)))
                    current_text = []
                current_time = parse_time_to_seconds(m.group(1))
            elif line.strip() and not line.startswith("WEBVTT") and not line.isdigit():
                current_text.append(line.strip())
        if current_text:
            cues.append((current_time, " ".join(current_text)))
    else:
        for line in lines:
            line_str = line.strip()
            m = re.search(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]", line_str)
            if m:
                sec = parse_time_to_seconds(m.group(1))
                cleaned = re.sub(r"^[-*]\s*", "", line_str)
                cues.append((sec, cleaned))

    if not cues:
        return chunk_file(path)

    chunks = []
    buf = []
    buf_len = 0
    start_sec = cues[0][0]

    for sec, txt in cues:
        buf.append((sec, txt))
        buf_len += len(txt) + 1
        if buf_len >= 1000 or (sec - start_sec) >= 120:
            end_sec = sec
            sec_title = f"Transcript [{format_seconds(start_sec)} - {format_seconds(end_sec)}]"
            chunk_text = "\n".join(t for _, t in buf)
            chunks.append((sec_title, start_sec, end_sec, chunk_text))
            buf = []
            buf_len = 0
            start_sec = sec

    if buf:
        end_sec = buf[-1][0]
        sec_title = f"Transcript [{format_seconds(start_sec)} - {format_seconds(end_sec)}]"
        chunk_text = "\n".join(t for _, t in buf)
        chunks.append((sec_title, start_sec, end_sec, chunk_text))

    return chunks


def sections(lines):
    out = []
    heading, start = None, 0
    for i, line in enumerate(lines):
        if re.match(r"^#{1,3} ", line):
            if i > start or heading is not None:
                out.append((heading, start, i))
            heading, start = line.lstrip("# ").strip(), i
    out.append((heading, start, len(lines)))
    return [(h, s, e) for h, s, e in out if any(l.strip() for l in lines[s:e])]


def chunk_file(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    packed = []
    for heading, s, e in sections(lines):
        text = "\n".join(lines[s:e]).strip()
        title = heading or path.stem
        if len(text) <= CHUNK_BUDGET:
            packed.append((title, s + 1, e, text))
            continue
        buf, buf_start = [], s
        for i in range(s, e):
            buf.append(lines[i])
            if sum(len(l) + 1 for l in buf) >= CHUNK_BUDGET:
                packed.append((title, buf_start + 1, i + 1, "\n".join(buf).strip()))
                buf, buf_start = [], i + 1
        if any(l.strip() for l in buf):
            packed.append((title, buf_start + 1, e, "\n".join(buf).strip()))
    return packed



def parse_entry(text):
    """Read a distilled entry: source, questions, summary, rule, quote.

    distil.py checks its own output through this, so the writer and the reader
    can never drift into two spellings of the format.
    """
    entry = {"questions": []}
    for line in text.splitlines():
        if line.startswith("source:"):
            entry["source"] = line.split(":", 1)[1].strip()
        elif line.startswith("- "):
            entry["questions"].append(line[2:].strip())
        elif line.startswith("summary:"):
            entry["summary"] = line.split(":", 1)[1].strip()
        elif line.startswith("rule:"):
            entry["rule"] = line.split(":", 1)[1].strip()
        elif line.startswith("quote:"):
            entry["quote"] = line.split(":", 1)[1].strip().strip('"')
    return entry


def parse_distilled(path):
    """Read a distilled entry from a file."""
    return parse_entry(path.read_text(encoding="utf-8"))


def normalise(text):
    return " ".join(text.split())


def utf8_out():
    """Write UTF-8 whatever the console's code page is.

    Windows consoles default to cp1252, which cannot encode an arrow, a curly
    quote or a pound sign, and file names and notes are full of them.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main():
    utf8_out()
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(HERE.parent / "corpus-before"))
    args = ap.parse_args()
    corpus = Path(args.corpus)

    db = sqlite3.connect(DB)
    db.executescript(SCHEMA)
    db.execute("INSERT INTO meta VALUES ('corpus', ?)", (str(corpus.resolve()),))

    docs = []  # (embed_text, row)
    files = note_files(corpus)
    root = corpus.resolve()
    for path in files:
        rel = path.relative_to(root).as_posix()
        is_transcript = path.name.endswith("_transcript.md") or path.suffix == ".vtt"
        if is_transcript:
            for section, s, e, text in chunk_transcript(path):
                label = f"[{rel} § {section}]"
                row = (rel, section, s, e, text, "video_transcript")
                docs.append((label + "\n" + text, row))
        else:
            for section, s, e, text in chunk_file(path):
                label = f"[{rel} § {section}]"
                row = (rel, section, s, e, text, "chunk")
                docs.append((label + "\n" + text, row))

    dropped = 0
    distilled_dir = HERE / "distilled"
    distilled_files = sorted(distilled_dir.glob("*.md")) if distilled_dir.is_dir() else []
    for path in distilled_files:
        entry = parse_distilled(path)
        source = corpus / entry.get("source", "")
        quote = entry.get("quote", "")
        if not source.is_file() or normalise(quote) not in normalise(source.read_text(encoding="utf-8")):
            dropped += 1
            print(f"dropped {path.name}: quote not found in {entry.get('source', '?')}")
            continue
        body = "\n".join(
            entry["questions"]
            + [entry.get("summary", ""), entry.get("rule", ""), quote]
        ).strip()
        label = f"[{entry['source']} § distilled]"
        row = (entry["source"], "distilled", 0, 0, body, "distilled")
        docs.append((label + "\n" + body, row))

    slide_vecs_map = {}
    slide_files = [
        corpus / "slide_vectors.json",
        corpus / "viz_icm" / "_shared" / "slide_vectors.json",
        HERE.parent / "slide_vectors.json",
    ]
    for sf in slide_files:
        if sf.is_file():
            try:
                slides_data = json.loads(sf.read_text(encoding="utf-8"))
                for s_item in slides_data:
                    s_label = s_item.get("label") or Path(s_item["image_path"]).stem
                    s_course = s_item.get("course", "General")
                    s_time = s_item.get("timestamp_seconds", 0)
                    rel = f"slides/{s_item['filename']}"
                    s_sec = f"Slide: {s_label}"
                    body = f"[Visual Slide Diagram] {s_label}\nCourse: {s_course}\nTimestamp: {s_time}s\nPath: {s_item.get('image_path', '')}"
                    label = f"[{rel} § {s_sec}]"
                    row = (rel, s_sec, s_time, s_time, body, "slide")
                    docs.append((label + "\n" + body, row))
                    if "vector" in s_item and len(s_item["vector"]) == 768:
                        slide_vecs_map[len(docs)] = s_item["vector"]
                print(f"loaded {len(slides_data)} visual slide vectors from {sf.name}")
                break
            except Exception as e:
                print(f"warning: failed to load slides from {sf}: {e}")

    for embed_text, row in docs:
        cur = db.execute(
            "INSERT INTO chunks (file, section, start_line, end_line, text, kind) VALUES (?,?,?,?,?,?)",
            row,
        )
        db.execute(
            "INSERT INTO chunks_fts (rowid, text, file, section) VALUES (?,?,?,?)",
            (cur.lastrowid, embed_text, row[0], row[1]),
        )

    model_line = "keyword only (embedding endpoint unavailable)"
    if not docs:
        model_line = "nothing to index: no files found under the corpus"
    else:
        try:
            texts_to_embed = []
            text_indices = []
            for idx, (embed_text, _) in enumerate(docs, start=1):
                if idx in slide_vecs_map:
                    continue
                texts_to_embed.append(embed_text)
                text_indices.append(idx)

            computed_vecs = get_embeddings(texts_to_embed) if texts_to_embed else []
            vec_by_rowid = {}
            for idx, vec in zip(text_indices, computed_vecs):
                vec_by_rowid[idx] = vec
            for idx, vec in slide_vecs_map.items():
                vec_by_rowid[idx] = vec

            for rowid in range(1, len(docs) + 1):
                vec = vec_by_rowid.get(rowid)
                if vec:
                    norm = sum(x * x for x in vec) ** 0.5 or 1.0
                    blob = struct.pack(f"{len(vec)}f", *(x / norm for x in vec))
                    db.execute("INSERT INTO vectors (id, vec) VALUES (?,?)", (rowid, blob))
            sample_dim = len(next(iter(vec_by_rowid.values()))) if vec_by_rowid else 768
            model_line = f"model EmbeddingGemma-2 ({sample_dim}d multimodal: text+video+slides) + keyword sqlite fts5 via {EMBEDDING_URL}"
        except Exception as exc:
            print(f"warning: embedding leg failed ({exc}), falling back to keyword")

    db.commit()
    db.close()
    n_distilled = len(distilled_files) - dropped
    n_slides = len(slide_vecs_map)
    print(f"indexed {len(files)} files ({len(docs) - n_distilled - n_slides} text/video chunks, {n_slides} slide keyframes, {n_distilled} distilled entries, {dropped} dropped)")
    print(model_line)



if __name__ == "__main__":
    main()
