#!/usr/bin/env python3
"""mem — four-layer agent memory over plain markdown.

Layers follow Anthropic, "The components of agent memory" (Nov 2026):

  01_transcripts  append-only event log            code owns
  02_notes        salient observations             observer owns
  03_wiki         linked representations           dreamer owns, one writer/page
  04_context      injected header, <=200 lines     dreamer promotes

Markdown is the truth. `db/memory.db` is a derived FTS5 index: delete it and
nothing is lost, `mem reindex` rebuilds it. One home per fact; a link beats a
copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"
MAX_HEADER_LINES = 200
MAX_HEADER_BYTES = 25600

LAYERS = {
    "01_transcripts": "transcript",
    "02_notes": "note",
    "03_wiki": "wiki",
    "04_context": "context",
}


# --------------------------------------------------------------------------
# paths and frontmatter
# --------------------------------------------------------------------------

def root_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("MEMORY_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".memory"


def db_path(root: Path) -> Path:
    return root / "db" / "memory.db"


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse the small YAML subset these files use. No dependency, no surprises."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    block = text[4:end]
    body = text[end + 4:].lstrip("\n")
    meta: dict[str, Any] = {}
    key = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) or line.lstrip().startswith("- "):
            item = line.strip().lstrip("- ").strip()
            if item:
                if key is None:
                    continue
                if not isinstance(meta.get(key), list):
                    meta[key] = []
                meta[key].append(_unquote(item))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value in ("", "|", ">"):
            meta[key] = []
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [_unquote(p) for p in inner.split(",") if p.strip()] if inner else []
        else:
            meta[key] = _unquote(value)
    return meta, body


def dump_frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif value is None:
            continue
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def slug(value: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return out or "untitled"


def doc_id(rel: str, meta: dict[str, Any]) -> str:
    explicit = meta.get("id")
    if explicit:
        return str(explicit).strip()
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]
    return f"{slug(Path(rel).parents[0].name if Path(rel).parent.name else 'root')[:16]}-{digest}"


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    layer       TEXT NOT NULL,
    project     TEXT,
    kind        TEXT,
    title       TEXT,
    body        TEXT NOT NULL,
    entities    TEXT NOT NULL DEFAULT '',
    sources     TEXT NOT NULL DEFAULT '',
    ts          TEXT,
    confidence  REAL DEFAULT 1.0,
    verified    INTEGER DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    title, body, entities, tokenize='porter unicode61'
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(root: Path) -> sqlite3.Connection:
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def iter_docs(root: Path):
    """Yield every indexable markdown file. Markdown is the truth."""
    for layer_dir in ("02_notes", "03_wiki"):
        base = root / layer_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.name.startswith("_"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = parse_frontmatter(text)
            rel = str(path.relative_to(root))
            project = meta.get("project") or _project_from_path(rel)
            yield {
                "id": doc_id(rel, meta),
                "path": rel,
                "layer": LAYERS.get(layer_dir, layer_dir),
                "project": project if isinstance(project, str) else None,
                "kind": meta.get("type") or meta.get("kind"),
                "title": meta.get("title") or _title(body, path),
                "body": body,
                "entities": _join(meta.get("entities")),
                "sources": _join(meta.get("sources")),
                "ts": meta.get("ts") or meta.get("created"),
                "confidence": _num(meta.get("confidence"), 1.0),
                "verified": 1 if str(meta.get("verified", "false")).lower() == "true" else 0,
            }


def _project_from_path(rel: str) -> str | None:
    """Only notes carry a project folder. A wiki page lives under a kind, not a
    project, so inferring one from the path invented `entities`."""
    parts = Path(rel).parts
    if len(parts) > 2 and parts[0] == "02_notes":
        return parts[1]
    return None


def _title(body: str, path: Path) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ")


def _join(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value)
    return str(value or "")


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def reindex(root: Path, quiet: bool = False) -> dict[str, Any]:
    con = connect(root)
    con.execute("DELETE FROM docs")
    con.execute("DELETE FROM docs_fts")
    rows = 0
    for doc in iter_docs(root):
        con.execute(
            "INSERT OR REPLACE INTO docs(id,path,layer,project,kind,title,body,"
            "entities,sources,ts,confidence,verified) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (doc["id"], doc["path"], doc["layer"], doc["project"], doc["kind"],
             doc["title"], doc["body"], doc["entities"], doc["sources"],
             doc["ts"], doc["confidence"], doc["verified"]),
        )
        con.execute(
            "INSERT INTO docs_fts(rowid,title,body,entities) VALUES(?,?,?,?)",
            (con.execute("SELECT last_insert_rowid()").fetchone()[0],
             doc["title"], doc["body"], doc["entities"]),
        )
        rows += 1
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                (SCHEMA_VERSION,))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('built_at',?)",
                (str(time.time()),))
    con.commit()
    con.close()
    if not quiet:
        print(f"📇 memory index rebuilt: {rows} doc(s) · {db_path(root)}")
    return {"docs": rows}


def ensure_index(root: Path) -> sqlite3.Connection:
    """Rebuild when the markdown is newer than the index. Cheap: 58-file scale."""
    target = db_path(root)
    if not target.is_file():
        reindex(root, quiet=True)
        return connect(root)
    built = target.stat().st_mtime
    newest = 0.0
    for layer_dir in ("02_notes", "03_wiki"):
        base = root / layer_dir
        if base.is_dir():
            for path in base.rglob("*.md"):
                try:
                    newest = max(newest, path.stat().st_mtime)
                except OSError:
                    continue
    if newest > built:
        reindex(root, quiet=True)
    return connect(root)


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

def cmd_search(args) -> None:
    root = root_path(args.root)
    con = ensure_index(root)
    sql = ("SELECT d.*, bm25(docs_fts) AS rank FROM docs_fts "
           "JOIN docs d ON d.rowid = docs_fts.rowid WHERE docs_fts MATCH ?")
    params: list[Any] = [_fts_query(args.query)]
    if args.project:
        sql += " AND d.project = ?"
        params.append(args.project)
    if args.layer:
        sql += " AND d.layer = ?"
        params.append(args.layer)
    if args.kind:
        sql += " AND d.kind = ?"
        params.append(args.kind)
    sql += " ORDER BY rank LIMIT ?"
    params.append(args.limit)
    try:
        rows = con.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        sys.exit(f"❌ memory: bad query ({exc})")
    finally:
        con.close()

    if args.json:
        print(json.dumps([_compact(r) for r in rows], indent=2, ensure_ascii=False))
        return
    if not rows:
        print(f"\n🔍 no memory match for {args.query!r}\n   Try `mem recent` or a broader term.\n")
        return
    print(f"\n🔍 [memory] intent: {args.query!r}   hits={len(rows)}\n")
    for row in rows:
        mark = "✓" if row["verified"] else "·"
        print(f"  {mark} {row['id']}   [{row['layer']}/{row['kind'] or 'note'}]"
              f"   {row['project'] or '-'}")
        print(f"       {row['title'][:90]}")
        print(f"       {_snippet(row['body'])}")
        print(f"       → mem get {row['id']}")
        print()
    print("   Next: `mem timeline <id>` for context, `mem get <id...>` for full text.\n")


def _compact(row) -> dict[str, Any]:
    return {"id": row["id"], "title": row["title"], "layer": row["layer"],
            "kind": row["kind"], "project": row["project"], "path": row["path"],
            "ts": row["ts"], "verified": bool(row["verified"])}


def _snippet(body: str, width: int = 150) -> str:
    text = " ".join(body.split())
    return text[:width] + ("…" if len(text) > width else "")


def _fts_query(raw: str) -> str:
    terms = [t for t in re.findall(r"[A-Za-z0-9_./:-]+", raw) if len(t) > 1]
    if not terms:
        sys.exit("❌ memory: query has no searchable terms")
    return " OR ".join(f'"{t}"' for t in terms[:12])


def cmd_get(args) -> None:
    root = root_path(args.root)
    con = ensure_index(root)
    marks = ",".join("?" * len(args.ids))
    rows = con.execute(f"SELECT * FROM docs WHERE id IN ({marks})", args.ids).fetchall()
    con.close()
    if not rows:
        sys.exit(f"❌ memory: no doc(s) for {', '.join(args.ids)}")
    if args.json:
        print(json.dumps([dict(r) for r in rows], indent=2, ensure_ascii=False))
        return
    for row in rows:
        print(f"\n📄 [{row['id']}] {row['title']}")
        print(f"   {row['path']}  ·  {row['layer']}/{row['kind'] or 'note'}"
              f"  ·  verified={bool(row['verified'])}")
        print()
        print(row["body"].strip())
        print()


def cmd_recent(args) -> None:
    root = root_path(args.root)
    con = ensure_index(root)
    sql = "SELECT * FROM docs"
    params: list[Any] = []
    if args.project:
        sql += " WHERE project = ?"
        params.append(args.project)
    sql += " ORDER BY COALESCE(ts,'') DESC, rowid DESC LIMIT ?"
    params.append(args.limit)
    rows = con.execute(sql, params).fetchall()
    con.close()
    if args.json:
        print(json.dumps([_compact(r) for r in rows], indent=2, ensure_ascii=False))
        return
    print(f"\n🕒 [memory] recent {len(rows)} doc(s)\n")
    for row in rows:
        print(f"  {row['ts'] or '-':<12} {row['id']}   {row['title'][:70]}")
    print()


def cmd_timeline(args) -> None:
    root = root_path(args.root)
    con = ensure_index(root)
    anchor = con.execute("SELECT * FROM docs WHERE id = ?", (args.id,)).fetchone()
    if anchor is None:
        sys.exit(f"❌ memory: no doc {args.id!r}")
    rows = con.execute(
        "SELECT * FROM docs WHERE project IS ? ORDER BY COALESCE(ts,'') ASC",
        (anchor["project"],),
    ).fetchall()
    con.close()
    idx = next((i for i, r in enumerate(rows) if r["id"] == anchor["id"]), 0)
    lo = max(0, idx - args.window)
    hi = min(len(rows), idx + args.window + 1)
    print(f"\n🧭 timeline around {anchor['id']}  (project={anchor['project'] or '-'})\n")
    for row in rows[lo:hi]:
        mark = "▶" if row["id"] == anchor["id"] else " "
        print(f" {mark} {row['ts'] or '-':<12} {row['id']}   {row['title'][:70]}")
    print()


def cmd_context(args) -> None:
    """The injected layer, budgeted. This is what SessionStart reads."""
    root = root_path(args.root)
    header = root / "04_context" / "MEMORY.md"
    if not header.is_file():
        print("_(memory context is empty — run the dreamer)_")
        return
    text = header.read_text(encoding="utf-8")
    budget = args.budget
    lines = text.splitlines()
    if len(lines) > budget:
        text = "\n".join(lines[:budget]) + "\n\n_(truncated: header over budget)_\n"
    print(text)


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------

def cmd_save(args) -> None:
    """Main-agent write. The only path the coder owns; marked source=manual."""
    root = root_path(args.root)
    body = args.body or ""
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    if not body.strip():
        sys.exit("❌ memory: refusing to save an empty observation")

    project = args.project or "global"
    day = time.strftime("%Y-%m-%d")
    folder = root / "02_notes" / project
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}-{slug(args.title)}.md"
    if path.exists() and not args.force:
        digest = hashlib.sha1(body.encode()).hexdigest()[:6]
        path = folder / f"{day}-{slug(args.title)}-{digest}.md"

    meta = {
        "id": f"{slug(project)[:12]}-{hashlib.sha1(str(path).encode()).hexdigest()[:8]}",
        "title": args.title,
        "type": args.type,
        "project": project,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "manual",
        "entities": [e for e in (args.entities or "").split(",") if e.strip()],
        "sources": [s for s in (args.sources or "").split(",") if s.strip()],
        "confidence": 1.0,
        "verified": False,
    }
    path.write_text(dump_frontmatter(meta) + f"\n# {args.title}\n\n{body.strip()}\n",
                    encoding="utf-8")
    reindex(root, quiet=True)
    print(f"✅ saved {meta['id']} → {path.relative_to(root)}")


def cmd_forget(args) -> None:
    """Archive, never delete: the negative control proves this works."""
    root = root_path(args.root)
    con = ensure_index(root)
    row = con.execute("SELECT path FROM docs WHERE id = ?", (args.id,)).fetchone()
    con.close()
    if row is None:
        sys.exit(f"❌ memory: no doc {args.id!r}")
    src = root / row["path"]
    dest = root / "_archive" / row["path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.move(str(src), str(dest))
    reindex(root, quiet=True)
    print(f"🗑️  archived {args.id} → _archive/{row['path']}")


def cmd_init(args) -> None:
    """Scaffold the runtime root. Idempotent: never touches existing files."""
    root = root_path(args.root)
    layout = {
        "01_transcripts": None,
        "02_notes": None,
        "03_wiki/entities": None,
        "03_wiki/topics": None,
        "04_context": None,
        "db": None,
        "_archive": None,
    }
    created = []
    for rel in layout:
        path = root / rel
        if not path.is_dir():
            path.mkdir(parents=True, exist_ok=True)
            created.append(rel)
    header = root / "04_context" / "MEMORY.md"
    if not header.is_file():
        header.write_text(
            "# Memory\n\n_Injected every session. Header only: facts and links._\n"
            "_Generated by the dreamer. Do not hand-edit._\n",
            encoding="utf-8")
        created.append("04_context/MEMORY.md")
    if not (root / "AGENTS.md").is_file():
        (root / "AGENTS.md").write_text(
            "# Memory store\n\n"
            "Four layers: `01_transcripts` -> `02_notes` -> `03_wiki` -> `04_context`.\n"
            "Read with `mem search`, `mem get`. Consolidate with `memory-dream`.\n"
            "Gate with `python3 _tools/links.py --root <this dir>`.\n",
            encoding="utf-8")
        created.append("AGENTS.md")
    print(f"🧠 memory root: {root}"
          + (f"  (created {len(created)})" if created else "  (already initialised)"))


def cmd_stats(args) -> None:
    root = root_path(args.root)
    con = ensure_index(root)
    total = con.execute("SELECT count(*) FROM docs").fetchone()[0]
    by_layer = con.execute(
        "SELECT layer, count(*) AS n FROM docs GROUP BY layer ORDER BY n DESC"
    ).fetchall()
    verified = con.execute("SELECT count(*) FROM docs WHERE verified = 1").fetchone()[0]
    con.close()
    header = root / "04_context" / "MEMORY.md"
    print(f"\n🧠 [memory] {root}")
    print(f"   docs      : {total}   verified: {verified}")
    for row in by_layer:
        print(f"   {row['layer']:<11}: {row['n']}")
    if header.is_file():
        text = header.read_text(encoding="utf-8")
        print(f"   header    : {len(text.splitlines())} lines / {len(text.encode())} bytes"
              f"  (budget {MAX_HEADER_LINES}/{MAX_HEADER_BYTES})")
    print()


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mem", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", help="memory root (default $MEMORY_ROOT or ~/.memory)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="find docs by intent")
    s.add_argument("query")
    s.add_argument("-n", "--limit", type=int, default=8)
    s.add_argument("--project")
    s.add_argument("--layer", choices=["note", "wiki", "context"])
    s.add_argument("--kind")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("get", help="full text for one or more ids")
    s.add_argument("ids", nargs="+")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_get)

    s = sub.add_parser("recent", help="latest docs")
    s.add_argument("-n", "--limit", type=int, default=20)
    s.add_argument("--project")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_recent)

    s = sub.add_parser("timeline", help="neighbours of one doc")
    s.add_argument("id")
    s.add_argument("--window", type=int, default=5)
    s.set_defaults(func=cmd_timeline)

    s = sub.add_parser("context", help="budgeted injected header")
    s.add_argument("--budget", type=int, default=MAX_HEADER_LINES)
    s.set_defaults(func=cmd_context)

    s = sub.add_parser("save", help="write a manual observation")
    s.add_argument("--title", required=True)
    s.add_argument("--type", default="note")
    s.add_argument("--project")
    s.add_argument("--entities")
    s.add_argument("--sources")
    s.add_argument("--body")
    s.add_argument("--body-file")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_save)

    s = sub.add_parser("forget", help="archive a doc (never delete)")
    s.add_argument("id")
    s.set_defaults(func=cmd_forget)

    s = sub.add_parser("init", help="scaffold the runtime root (idempotent)")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("reindex", help="rebuild the derived index")
    s.set_defaults(func=lambda a: reindex(root_path(a.root)))

    s = sub.add_parser("stats", help="layer counts and header budget")
    s.set_defaults(func=cmd_stats)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
