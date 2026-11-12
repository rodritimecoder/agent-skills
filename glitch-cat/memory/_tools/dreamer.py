#!/usr/bin/env python3
"""dreamer — offline consolidation. Notes in, representations and header out.

Four jobs, all automatic, all reversible (every write is a plain markdown diff
in a git-tracked tree):

  crossref  test each note against the transcript it cites  (notes -> transcript)
  wiki      one page per entity, merged and linked          (notes -> wiki)
  promote   float durable facts into 04_context/MEMORY.md    (wiki -> header)
  gaps      repoint dangling links, add missing pages        (wiki -> wiki)

The guard is not an approval gate, it is ownership: this process is the only
writer of 03_wiki and 04_context, one page per writer, so no two runs overwrite
each other's lines. The budget gate is code and it fails red.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mem import (MAX_HEADER_BYTES, MAX_HEADER_LINES, connect, dump_frontmatter,  # noqa: E402
                 ensure_index, iter_docs, parse_frontmatter, reindex, root_path,
                 slug)

DURABLE = {"decision", "invariant", "rule", "policy", "preference"}
DEMOTE_ORDER = ("context", "note", "wiki")


def wiki_dir(root: Path) -> Path:
    return root / "03_wiki"


def header_path(root: Path) -> Path:
    return root / "04_context" / "MEMORY.md"


def kind_of(entity: str) -> str:
    suffix = Path(entity).suffix.lower()
    if suffix in {".py", ".ts", ".tsx", ".js", ".rs", ".go", ".sh", ".sql"}:
        return "code"
    if suffix in {".md", ".json", ".yaml", ".yml", ".toml", ".jsonl"}:
        return "data"
    if suffix in {".png", ".jpg", ".svg", ".webp"}:
        return "media"
    return "topic"


def wiki_id(name: str) -> str:
    if len(name) <= 24:
        return f"wiki-{name}"
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
    return f"wiki-{name[:17]}-{digest}"


# --------------------------------------------------------------------------
# crossref
# --------------------------------------------------------------------------

def crossref(root: Path) -> dict:
    """A note is verified only when its claims appear in the transcript it cites."""
    checked = verified = 0
    broken = []
    for doc in iter_docs(root):
        if doc["layer"] != "note":
            continue
        sources = [s for s in doc["sources"].split() if s]
        if not sources:
            continue
        checked += 1
        haystack = ""
        for rel in sources:
            path = root / rel
            if path.is_file():
                haystack += path.read_text(encoding="utf-8", errors="replace")
        claims = re.findall(r"`([^`\n]{4,160})`", doc["body"])
        missing = [c for c in claims
                   if c.split("/")[-1].strip() and c.strip() not in haystack]
        path = root / doc["path"]
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        if not missing:
            meta["verified"] = True
            meta["confidence"] = max(float(meta.get("confidence") or 0.7), 0.9)
            verified += 1
        else:
            meta["verified"] = False
            meta["unverified_claims"] = missing[:5]
            broken.append({"id": doc["id"], "missing": missing[:5]})
        path.write_text(dump_frontmatter(meta) + "\n" + body, encoding="utf-8")
    return {"checked": checked, "verified": verified, "broken": broken}


# --------------------------------------------------------------------------
# wiki
# --------------------------------------------------------------------------

def _page_project(projects: dict[str, str], note_ids) -> str:
    """A page belongs to the project its notes came from, or to `shared`."""
    found = {projects[n] for n in note_ids if n in projects}
    if len(found) == 1:
        return found.pop()
    return "shared" if found else "global"


def build_wiki(root: Path) -> dict:
    """One page per entity. Merged, never clobbered: pages are rewritten whole."""
    groups: dict[tuple[str, str], dict] = {}
    projects: dict[str, str] = {}
    for doc in iter_docs(root):
        if doc["layer"] not in ("note", "wiki"):
            continue
        if doc["layer"] == "note" and doc["project"]:
            projects[doc["id"]] = doc["project"]
        for entity in doc["entities"].split():
            key = (kind_of(entity), slug(entity))
            page = groups.setdefault(key, {"label": entity, "notes": set(), "co": set()})
            if doc["layer"] == "note":
                page["notes"].add(doc["id"])
            for other in doc["entities"].split():
                if other != entity:
                    page["co"].add(other)

    base = wiki_dir(root)
    written = 0
    for (kind, name), page in sorted(groups.items()):
        folder = base / "entities" / kind
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{name}.md"
        note_links = sorted(page["notes"])[:30]
        related = sorted(page["co"])[:12]
        body = [f"# {page['label']}", "",
                f"Entity `{page['label']}` ({kind}).", ""]
        if note_links:
            body += ["## Seen in", ""]
            body += [f"- `{nid}` — `mem get {nid}`" for nid in note_links]
            body += [""]
        if related:
            body += ["## Related", ""]
            body += [f"- [[{slug(r)}]]" for r in related]
            body += [""]
        meta = {
            "id": wiki_id(name),
            "title": page["label"],
            "type": "entity",
            "kind": kind,
            "project": _page_project(projects, page["notes"]),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": "dreamer",
            "entities": [page["label"]] + related,
            "sources": note_links[:20],
            "confidence": 0.8,
            "verified": True,
        }
        content = f"{dump_frontmatter(meta)}\n" + "\n".join(body)
        if not target.is_file() or target.read_text(encoding="utf-8") != content:
            target.write_text(content, encoding="utf-8")
            written += 1

    # Generated index. Never hand-edited (ICM invariant 9).
    index = ["# Wiki index", "",
             "_Generated by the dreamer. Do not hand-edit._", ""]
    for kind in sorted({k for k, _ in groups}):
        index += [f"## {kind}", ""]
        for k, name in sorted(groups):
            if k == kind:
                index.append(f"- [[{name}]] — {groups[(k, name)]['label']}")
        index.append("")
    base.mkdir(parents=True, exist_ok=True)
    (base / "_index.md").write_text("\n".join(index), encoding="utf-8")
    return {"pages": len(groups), "written": written}


# --------------------------------------------------------------------------
# promote
# --------------------------------------------------------------------------

def promote(root: Path) -> dict:
    """Keep the injected layer small: durable facts only, links for the rest."""
    con = ensure_index(root)
    durable = con.execute(
        "SELECT * FROM docs WHERE kind IN ({}) ORDER BY verified DESC, confidence DESC"
        .format(",".join("?" * len(DURABLE))), tuple(DURABLE)).fetchall()
    recent = con.execute(
        "SELECT * FROM docs WHERE layer = 'note' ORDER BY COALESCE(ts,'') DESC LIMIT 8"
    ).fetchall()
    con.close()

    lines = ["# Memory",
             "",
             "_Injected every session. Header only: facts and links, never bodies._",
             "_Generated by the dreamer. Do not hand-edit._", ""]
    if durable:
        lines += ["## Standing", ""]
        for row in durable:
            mark = "✓" if row["verified"] else "?"
            fact = _one_line(row["body"]) or row["title"]
            lines.append(f"- [{mark}] {fact[:150]} → `mem get {row['id']}`")
        lines.append("")
    if recent:
        lines += ["## Recent", ""]
        for row in recent:
            lines.append(f"- {row['ts'] or '-'} {row['title'][:90]} → `mem get {row['id']}`")
        lines.append("")
    lines += ["## How to recall", "",
              "- `mem search \"<intent>\"` for the index, `mem get <id...>` for bodies.",
              "- Search the wiki and the notes together; neither alone is enough.", ""]

    text = "\n".join(lines)
    demoted = 0
    while _over_budget(text):
        trimmed = _trim(text)
        if trimmed == text:
            break
        text = trimmed
        demoted += 1

    target = header_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    changed = not target.is_file() or target.read_text(encoding="utf-8") != text
    if changed:
        target.write_text(text, encoding="utf-8")
    return {"lines": len(text.splitlines()), "bytes": len(text.encode()),
            "demoted": demoted, "changed": changed,
            "over_budget": _over_budget(text)}


def _over_budget(text: str) -> bool:
    return len(text.splitlines()) > MAX_HEADER_LINES or len(text.encode()) > MAX_HEADER_BYTES


def _trim(text: str) -> str:
    """Budget pressure demotes the least durable lines first, leaving the link."""
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if not line.startswith("- ") or "Standing" in "\n".join(lines[max(0, i - 30):i]):
            if line.startswith("- ") and not line.startswith("- [`"):
                continue
        if line.startswith("- ") and "mem get" in line:
            del lines[i]
            return "\n".join(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("- "):
            del lines[i]
            return "\n".join(lines)
    return text


def _one_line(body: str) -> str:
    for line in body.splitlines():
        text = line.strip().lstrip("#-* ").strip()
        if text and not text.startswith("_"):
            return text
    return ""


# --------------------------------------------------------------------------
# gaps
# --------------------------------------------------------------------------

def close_gaps(root: Path) -> dict:
    base = wiki_dir(root)
    if not base.is_dir():
        return {"dangling": 0, "repointed": 0, "added": 0}
    pages = {p.stem: p for p in base.rglob("*.md") if not p.name.startswith("_")}
    dangling = []
    repointed = 0
    for path in base.rglob("*.md"):
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        for ref in re.findall(r"\[\[([^\]|#]+)", text):
            target = slug(ref.strip())
            if target in pages or Path(target).stem in pages:
                continue
            candidates = [s for s in pages if target.startswith(s) or s.startswith(target)]
            if len(candidates) == 1:
                text = text.replace(f"[[{ref}]]", f"[[{candidates[0]}]]")
                repointed += 1
            else:
                dangling.append({"page": str(path.relative_to(root)), "ref": ref})
        if text != original:
            path.write_text(text, encoding="utf-8")

    added = 0
    for item in dangling:
        name = slug(item["ref"])
        if name in pages:
            continue
        target = base / "entities" / "topic" / f"{name}.md"
        if target.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        meta = {"id": wiki_id(name), "title": item["ref"], "type": "entity",
                "kind": "topic", "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source": "dreamer", "entities": [item["ref"]],
                "sources": [item["page"]], "confidence": 0.4, "verified": False}
        target.write_text(f"{dump_frontmatter(meta)}\n# {item['ref']}\n\n"
                          "Stub created to close a dangling link. Confirm or merge.\n",
                          encoding="utf-8")
        added += 1
    return {"dangling": len(dangling), "repointed": repointed, "added": added}


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def run(root: Path, jobs: set[str], as_json: bool) -> int:
    report: dict = {}
    if "all" in jobs or "crossref" in jobs:
        report["crossref"] = crossref(root)
    if "all" in jobs or "wiki" in jobs:
        report["wiki"] = build_wiki(root)
    if "all" in jobs or "gaps" in jobs:
        report["gaps"] = close_gaps(root)
    if "all" in jobs or "promote" in jobs:
        report["promote"] = promote(root)
    reindex(root, quiet=True)

    failing = bool(report.get("promote", {}).get("over_budget"))
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print("\n🌙 [dreamer] consolidation pass")
        if "crossref" in report:
            c = report["crossref"]
            print(f"   crossref : {c['verified']}/{c['checked']} note(s) verified"
                  + (f" · {len(c['broken'])} with unsupported claims" if c["broken"] else ""))
        if "wiki" in report:
            w = report["wiki"]
            print(f"   wiki     : {w['pages']} page(s) · {w['written']} rewritten")
        if "gaps" in report:
            g = report["gaps"]
            print(f"   gaps     : {g['repointed']} repointed · {g['added']} stub(s) added")
        if "promote" in report:
            p = report["promote"]
            print(f"   header   : {p['lines']} lines / {p['bytes']} bytes"
                  f" · {p['demoted']} demoted")
            if p["over_budget"]:
                print("   ❌ header still over budget — dreaming failed its gate")
        print()
    return 1 if failing else 0


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="dreamer", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root")
    p.add_argument("--only", choices=["crossref", "wiki", "gaps", "promote"])
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    jobs = {a.only} if a.only else {"all"}
    sys.exit(run(root_path(a.root), jobs, a.json))


if __name__ == "__main__":
    main()
