#!/usr/bin/env python3
"""links — the gate. A dream that cannot fail is not a gate.

Checks, all code, no model:

  1. every wikilink in 03_wiki resolves to a page
  2. every note's `sources:` entry resolves to a transcript file
  3. 04_context/MEMORY.md is inside its line and byte budget
  4. no two layers claim the same fact id
  5. every entity page has at least one source or is explicitly a stub

Exit 0 clean, 1 on any finding. Run it after every dream; run it in CI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mem import (MAX_HEADER_BYTES, MAX_HEADER_LINES, iter_docs, parse_frontmatter,  # noqa: E402
                 root_path, slug)


def check(root: Path) -> dict:
    findings: list[dict] = []
    wiki = root / "03_wiki"
    pages = {p.stem: p for p in wiki.rglob("*.md") if not p.name.startswith("_")} \
        if wiki.is_dir() else {}

    # 1. wikilinks
    if wiki.is_dir():
        for path in wiki.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            for ref in re.findall(r"\[\[([^\]|#]+)", text):
                if slug(ref) not in pages:
                    findings.append({"rule": "dangling-wikilink",
                                     "file": str(path.relative_to(root)), "ref": ref})

    # 2. citations. A `sources:` entry is either a file path (a note citing its
    # transcript) or a doc id (a wiki page citing the notes it was built from).
    # Both are checked; neither is allowed to be dangling.
    docs = list(iter_docs(root))
    ids = {d["id"] for d in docs}
    seen: dict[str, str] = {}
    for doc in docs:
        for ref in doc["sources"].split():
            if (root / ref).is_file() or ref in ids:
                continue
            findings.append({"rule": "unresolved-source",
                             "id": doc["id"], "source": ref})

        # 4. one home per id
        if doc["id"] in seen and seen[doc["id"]] != doc["path"]:
            findings.append({"rule": "duplicate-id", "id": doc["id"],
                             "paths": [seen[doc["id"]], doc["path"]]})
        seen[doc["id"]] = doc["path"]

    # 3. header budget (the injected layer)
    header = root / "04_context" / "MEMORY.md"
    if header.is_file():
        text = header.read_text(encoding="utf-8")
        lines = len(text.splitlines())
        size = len(text.encode())
        if lines > MAX_HEADER_LINES:
            findings.append({"rule": "header-over-lines",
                             "lines": lines, "budget": MAX_HEADER_LINES})
        if size > MAX_HEADER_BYTES:
            findings.append({"rule": "header-over-bytes",
                             "bytes": size, "budget": MAX_HEADER_BYTES})

    # 5. entity pages need provenance, unless they are stubs
    for path in (wiki.rglob("*.md") if wiki.is_dir() else []):
        if path.name.startswith("_"):
            continue
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        sources = meta.get("sources") or []
        if not isinstance(sources, list):
            sources = [sources]
        if not sources and "Stub created" not in body:
            findings.append({"rule": "page-without-source",
                             "file": str(path.relative_to(root))})

    return {"ok": not findings, "findings": findings}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="links", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    root = root_path(a.root)
    result = check(root)
    if a.json:
        print(json.dumps(result, indent=2))
    elif result["ok"]:
        print(f"✅ memory links: clean ({root})")
    else:
        print(f"❌ memory links: {len(result['findings'])} finding(s)")
        for item in result["findings"][:40]:
            print(f"   - {item}")
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
