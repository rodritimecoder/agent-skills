#!/usr/bin/env python3
import argparse
import json
import os
import re
import sqlite3
import sys
import uuid
from pathlib import Path

# The three contract fields kem-mode contributes. Every stage answers who does the
# work, whether the step is deterministic, and what artifact proves it ran. Optional
# by default so existing workspaces keep validating; errors under `validate --kem`.
CONTRACT_FIELDS = ("**Actor:**", "**Step type:**", "**Proof:**")
STAGE_SECTIONS = ("## Inputs", "## Process", "## Outputs")
CHECK_SECTIONS = ("## Check", "## Human check")

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "templates"


def write_kem_contract(ws_path: Path):
    src_file = TEMPLATE_DIR / "kem-contract.md"
    if src_file.is_file():
        (ws_path / "_shared").mkdir(parents=True, exist_ok=True)
        (ws_path / "_shared" / "kem-contract.md").write_text(
            src_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

def parse_markdown_links(text: str) -> list[str]:
    matches = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text)
    links = []
    for _, href in matches:
        if href.startswith(("http://", "https://", "mailto:", "#")):
            continue
        clean_href = href.split("#")[0].strip()
        if clean_href:
            links.append(clean_href)
    return links


def scaffold_memory(ws_path: Path):
    mem_dir = ws_path / "_memory"
    mem_dir.mkdir(exist_ok=True)

    schema_sql = """CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    description TEXT,
    source_doc TEXT
);

CREATE TABLE IF NOT EXISTS relations (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    source_doc TEXT
);

CREATE TABLE IF NOT EXISTS aliases (
    entity_id TEXT NOT NULL,
    alias TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    title,
    content,
    path UNINDEXED
);
"""
    (mem_dir / "schema.sql").write_text(schema_sql, encoding="utf-8")

    db_path = mem_dir / "graph.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()

    bge_config = {
        "engine": "hybrid_rrf",
        "fts_enabled": True,
        "embedding_endpoints": [
            "http://127.0.0.1:8082/v1/embeddings",
            "http://127.0.0.1:8080/v1/embeddings"
        ],
        "model": "EmbeddingGemma-2",
        "dim": 768,
        "k_constant": 60
    }
    (mem_dir / "bge_config.json").write_text(json.dumps(bge_config, indent=2), encoding="utf-8")

    memory_py_content = """#!/usr/bin/env python3
import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "graph.db"
NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def make_entity_id(entity_type: str, name: str) -> str:
    clean = f"{entity_type.upper()}:{name.strip().lower()}"
    return str(uuid.uuid5(NAMESPACE, clean))

def insert_entity(name: str, entity_type: str, desc: str = "", source: str = ""):
    eid = make_entity_id(entity_type, name)
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO entities (id, name, type, description, source_doc) VALUES (?, ?, ?, ?, ?)",
            (eid, name, entity_type.upper(), desc, source)
        )
        conn.execute("INSERT OR IGNORE INTO aliases (entity_id, alias) VALUES (?, ?)", (eid, name))
    print(json.dumps({"status": "ok", "id": eid, "name": name, "type": entity_type}))

def insert_relation(source_name: str, target_name: str, predicate: str, source_type: str = "MODULE", target_type: str = "MODULE", source_doc: str = ""):
    sid = make_entity_id(source_type, source_name)
    tid = make_entity_id(target_type, target_name)
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO relations (source_id, target_id, predicate, source_doc) VALUES (?, ?, ?, ?)",
            (sid, tid, predicate.lower(), source_doc)
        )
    print(json.dumps({"status": "ok", "source": source_name, "target": target_name, "predicate": predicate}))

def k_hop(name: str, hops: int = 2):
    conn = get_db()
    clean_target = name.strip().lower()
    query = \"\"\"
    WITH RECURSIVE traverse(id, depth) AS (
        SELECT id, 0 FROM entities WHERE lower(name) = ?
        UNION
        SELECT entity_id, 0 FROM aliases WHERE lower(alias) = ?
        UNION
        SELECT r.target_id, t.depth + 1
        FROM relations r
        JOIN traverse t ON r.source_id = t.id
        WHERE t.depth < ?
        UNION
        SELECT r.source_id, t.depth + 1
        FROM relations r
        JOIN traverse t ON r.target_id = t.id
        WHERE t.depth < ?
    )
    SELECT DISTINCT e.id, e.name, e.type, e.description, r.predicate, e2.name AS related
    FROM traverse t
    JOIN entities e ON t.id = e.id
    LEFT JOIN relations r ON (r.source_id = e.id OR r.target_id = e.id)
    LEFT JOIN entities e2 ON (e2.id = CASE WHEN r.source_id = e.id THEN r.target_id ELSE r.source_id END)
    ORDER BY t.depth ASC;
    \"\"\"
    rows = conn.execute(query, (clean_target, clean_target, hops, hops)).fetchall()
    results = [dict(r) for r in rows]
    print(json.dumps(results, indent=2))

def index_doc(title: str, content: str, path: str):
    conn = get_db()
    with conn:
        conn.execute("INSERT INTO docs_fts (title, content, path) VALUES (?, ?, ?)", (title, content, path))
    print(json.dumps({"status": "indexed", "path": path}))

def search(query: str, limit: int = 5):
    conn = get_db()
    rows = conn.execute(
        "SELECT title, path, snippet(docs_fts, 1, '<b>', '</b>', '...', 15) as snippet FROM docs_fts WHERE docs_fts MATCH ? ORDER BY rank LIMIT ?",
        (query, limit)
    ).fetchall()
    results = [dict(r) for r in rows]
    print(json.dumps(results, indent=2))

def main():
    parser = argparse.ArgumentParser(description="Workspace Graph Memory & Hybrid RAG Engine")
    sub = parser.add_subparsers(dest="action", required=True)

    p_ent = sub.add_parser("add-entity")
    p_ent.add_argument("name")
    p_ent.add_argument("--type", default="MODULE")
    p_ent.add_argument("--desc", default="")
    p_ent.add_argument("--source", default="")

    p_rel = sub.add_parser("add-relation")
    p_rel.add_argument("source")
    p_rel.add_argument("target")
    p_rel.add_argument("--predicate", default="depends_on")
    p_rel.add_argument("--source-type", default="MODULE")
    p_rel.add_argument("--target-type", default="MODULE")

    p_hop = sub.add_parser("k-hop")
    p_hop.add_argument("name")
    p_hop.add_argument("--hops", type=int, default=2)

    p_idx = sub.add_parser("index")
    p_idx.add_argument("path")
    p_idx.add_argument("--title", default="")

    p_srch = sub.add_parser("search")
    p_srch.add_argument("query")
    p_srch.add_argument("--limit", type=int, default=5)

    args = parser.parse_args()
    if args.action == "add-entity":
        insert_entity(args.name, args.type, args.desc, args.source)
    elif args.action == "add-relation":
        insert_relation(args.source, args.target, args.predicate, args.source_type, args.target_type)
    elif args.action == "k-hop":
        k_hop(args.name, args.hops)
    elif args.action == "index":
        p = Path(args.path)
        content = p.read_text(encoding="utf-8", errors="replace")
        title = args.title or p.stem
        index_doc(title, content, str(p))
    elif args.action == "search":
        search(args.query, args.limit)

if __name__ == "__main__":
    main()
"""
    (mem_dir / "memory.py").write_text(memory_py_content, encoding="utf-8")
    (mem_dir / "memory.py").chmod(0o755)


def scaffold_agentic_factory(ws_path: Path, name: str, with_memory: bool, as_json: bool):
    ws_path.mkdir(parents=True, exist_ok=True)
    template_dir = TEMPLATE_DIR / "agentic-factory"
    if not template_dir.is_dir():
        raise FileNotFoundError(f"agentic-factory template missing at {template_dir}")

    for item in sorted(template_dir.rglob("*")):
        rel = item.relative_to(template_dir)
        dest = ws_path / ("AGENTS.md" if rel.as_posix() == "entry.md" else rel)
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            item.read_text(encoding="utf-8").replace("{Workspace Name}", name),
            encoding="utf-8",
        )

    stage_dirs = sorted(d for d in ws_path.iterdir() if d.is_dir() and re.match(r"^\d{2}_", d.name))
    for s in stage_dirs:
        (s / "output").mkdir(exist_ok=True)
        (s / "output" / ".gitkeep").touch()

    for sub in ("todo", "doing", "done", "rejected"):
        k_sub = ws_path / "03_kanban" / sub
        k_sub.mkdir(parents=True, exist_ok=True)
        (k_sub / ".gitkeep").touch()

    (ws_path / "_archive").mkdir(exist_ok=True)
    (ws_path / "_archive" / ".gitkeep").touch()

    write_kem_contract(ws_path)

    if with_memory:
        scaffold_memory(ws_path)

    stages = [d.name for d in stage_dirs]
    result = {
        "workspace": str(ws_path),
        "name": name,
        "template": "agentic-factory",
        "stages": stages,
        "with_memory": with_memory,
        "status": "scaffolded",
    }

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"✅ Initialized Kem Glitch Agentic Software Factory at: {ws_path}")
        print(f"   Root Entry:  {ws_path / 'AGENTS.md'}")
        print(f"   Stages:      {len(stages)} folders ({stages[0]} -> {stages[-1]})")
        print(f"   Kanban:      {ws_path / '03_kanban'} (todo, doing, done, rejected)")
        if with_memory:
            print(f"   Memory:      {ws_path / '_memory'} (graph.db + FTS5 + BGE RRF hybrid)")


def cmd_init(
    ws_path: Path,
    name: str,
    stages: list[str],
    form: str = "pipeline",
    template: str = "pipeline",
    with_memory: bool = False,
    as_json: bool = False,
):
    ws_path = ws_path.resolve()

    if template in ("agentic-factory", "software-factory"):
        scaffold_agentic_factory(ws_path, name, with_memory=True, as_json=as_json)
        return

    ws_path.mkdir(parents=True, exist_ok=True)

    shared_dir = ws_path / "_shared"
    archive_dir = ws_path / "_archive"
    shared_dir.mkdir(exist_ok=True)
    archive_dir.mkdir(exist_ok=True)

    (shared_dir / "rules.md").write_text(
        "# Shared Workspace Constraints\n\n"
        "Global rules, voice constraints, and schemas applicable across all pipeline stages.\n",
        encoding="utf-8",
    )
    write_kem_contract(ws_path)
    (archive_dir / ".gitkeep").touch()

    agents_content = [
        f"# AGENTS.md — {name}",
        "",
        f"**Workspace Form**: {form.capitalize()}",
        f"**Methodology**: Interpretable Context Methodology (ICM; arXiv:2603.16021)",
        "",
        "## Hierarchy & Control Map",
        "| Layer | File / Directory | Scope & Role |",
        "|---|---|---|",
        "| **L0** | `AGENTS.md` | Root workspace routing & identity |",
        "| **L1** | `CONTEXT.md` | Stage pipeline index & execution order |",
        "| **L2** | `NN_*/CONTEXT.md` | Stage contracts (Actor, Step type, Proof, Inputs, Process, Outputs, Check) |",
        "| **L3** | `_shared/`, `references/` | Immutable guidelines, constraints, schemas, and the Kem contract |",
        "| **L4** | `NN_*/output/` | Per-run editable product artifacts |",
    ]

    if with_memory:
        agents_content.extend([
            "| **L3** | `_memory/` | Dual-legged graph memory (`graph.db`) & hybrid RRF search (`memory.py`) |",
            "",
            "## Memory & Blast Radius Queries",
            "Before modifying code across stages, query the local entity graph:",
            "```bash",
            "python3 _memory/memory.py k-hop <EntityName> --hops 2",
            "python3 _memory/memory.py search \"query string\"",
            "```",
        ])

    agents_content.extend([
        "",
        "## Stage Pipeline",
    ])

    context_content = [
        f"# {name} — Stage Pipeline Index",
        "",
        "Sequential stage execution order:",
        "",
    ]

    for idx, st in enumerate(stages, start=1):
        slug = re.sub(r"[^a-zA-Z0-9_-]", "-", st.lower().strip())
        stage_dir_name = f"{idx:02d}_{slug}"
        agents_content.append(f"- [{stage_dir_name}]({stage_dir_name}/CONTEXT.md): Stage {idx} contract and artifacts")
        context_content.append(f"{idx}. [{stage_dir_name}]({stage_dir_name}/CONTEXT.md)")

        s_dir = ws_path / stage_dir_name
        s_dir.mkdir(exist_ok=True)
        out_dir = s_dir / "output"
        out_dir.mkdir(exist_ok=True)
        (out_dir / ".gitkeep").touch()

        prev_input = (
            f"../{idx-1:02d}_{re.sub(r'[^a-zA-Z0-9_-]', '-', stages[idx-2].lower().strip())}/output/"
            if idx > 1
            else "External input / prompt"
        )

        s_contract = f"""# {stage_dir_name} — {st.capitalize()} Stage

One job: Execute {slug} according to workspace constraints.

**Actor:** agent
**Step type:** P
**Proof:** output/result.md

## Inputs
- Working (this run): {prev_input}
- Reference (every run): ../_shared/rules.md

## Process
1. Inspect input artifacts from preceding layer.
2. Transform according to shared constraints in `_shared/rules.md`.
3. Emit structured deliverables to `output/`.

## Outputs
- `output/result.md`: Primary deliverable for stage {idx}

## Check
Inspect `output/result.md` before advancing to the next stage. Edit in place; downstream stages consume this directory. A check that is not a person writes `check.md` beside the output, first line `pass` or `fail: <why>`.
"""
        (s_dir / "CONTEXT.md").write_text(s_contract, encoding="utf-8")

    agents_content.extend([
        "",
        "## Stage contract",
        "Every stage names who does the work (`**Actor:**`), how (`**Step type:**` D/P/H),",
        "and what proves it (`**Proof:**`). The five moves behind those fields are in",
        "`_shared/kem-contract.md`. Fail the build on an incomplete contract:",
        "`icm-architect validate . --kem`.",
        "",
        "## Reference Integrity",
        "Before renaming or moving any file, run `icm-architect validate .` to prevent broken relative links.",
    ])

    (ws_path / "AGENTS.md").write_text("\n".join(agents_content) + "\n", encoding="utf-8")
    (ws_path / "CONTEXT.md").write_text("\n".join(context_content) + "\n", encoding="utf-8")

    if with_memory:
        scaffold_memory(ws_path)

    result = {
        "workspace": str(ws_path),
        "name": name,
        "form": form,
        "stages": [f"{i:02d}_{re.sub(r'[^a-zA-Z0-9_-]', '-', s.lower().strip())}" for i, s in enumerate(stages, 1)],
        "with_memory": with_memory,
        "status": "scaffolded",
    }

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"✅ Initialized ICM workspace at: {ws_path}")
        print(f"   Root Entry: {ws_path / 'AGENTS.md'}")
        print(f"   Stages:     {', '.join(result['stages'])}")
        if with_memory:
            print(f"   Memory:     {ws_path / '_memory'} (graph.db + FTS5 + BGE RRF hybrid)")


def cmd_validate(target_dir: Path, as_json: bool = False, kem: bool = False) -> int:
    target_dir = target_dir.resolve()
    errors = []
    warnings = []
    checks_passed = 0

    agents_md = target_dir / "AGENTS.md"
    if not agents_md.is_file():
        errors.append("Missing root L0 entry file 'AGENTS.md'")
    else:
        checks_passed += 1

    root_context = target_dir / "CONTEXT.md"
    if not root_context.is_file():
        warnings.append("Missing root L1 index file 'CONTEXT.md'")
    else:
        checks_passed += 1

    stage_dirs = sorted([d for d in target_dir.iterdir() if d.is_dir() and re.match(r"^\d{2}_", d.name)])
    if not stage_dirs:
        warnings.append("No numbered stage folders (format: NN_name) found in workspace root.")
    else:
        checks_passed += 1

    for s in stage_dirs:
        s_context = s / "CONTEXT.md"
        if not s_context.is_file():
            errors.append(f"Stage '{s.name}' missing required L2 contract 'CONTEXT.md'")
            continue

        checks_passed += 1
        content = s_context.read_text(encoding="utf-8", errors="replace")
        for sec in STAGE_SECTIONS:
            if sec not in content:
                errors.append(f"Stage '{s.name}/CONTEXT.md' missing required section: '{sec}'")
            else:
                checks_passed += 1
        if any(sec in content for sec in CHECK_SECTIONS):
            checks_passed += 1
        else:
            errors.append(f"Stage '{s.name}/CONTEXT.md' missing required section: '## Check'")

        for field in CONTRACT_FIELDS:
            if field in content:
                checks_passed += 1
                continue
            gap = f"Stage '{s.name}/CONTEXT.md' missing contract field '{field}' (who / how / proof)"
            if kem:
                errors.append(gap)
            else:
                warnings.append(gap)

        out_dir = s / "output"
        if not out_dir.is_dir():
            warnings.append(f"Stage '{s.name}' missing 'output/' directory")

    md_files = list(target_dir.rglob("*.md"))
    broken_links = []
    for mf in md_files:
        if any(p in mf.parts for p in [".git", "node_modules", ".venv"]):
            continue
        txt = mf.read_text(encoding="utf-8", errors="replace")
        links = parse_markdown_links(txt)
        for link in links:
            dest = (mf.parent / link).resolve()
            if not dest.exists():
                broken_links.append({"source": str(mf.relative_to(target_dir)), "target": link})

    if broken_links:
        for bl in broken_links:
            errors.append(f"Broken link in '{bl['source']}': target '{bl['target']}' does not exist")
    else:
        checks_passed += 1

    status_ok = len(errors) == 0

    if as_json:
        report = {
            "workspace": str(target_dir),
            "status": "PASS" if status_ok else "FAIL",
            "passed_checks": checks_passed,
            "errors": errors,
            "warnings": warnings,
            "stage_count": len(stage_dirs),
            "markdown_files_inspected": len(md_files),
            "kem_strict": kem,
        }
        print(json.dumps(report, indent=2))
    else:
        print(f"\n🔬 [ICM Reference Integrity Validator] Workspace: {target_dir}")
        print(f"   Stage Folders: {len(stage_dirs)} | Markdown Files: {len(md_files)}")
        print("   " + "─" * 60)
        if status_ok:
            print(f"   ✅ ALL {checks_passed} STRUCTURAL CHECKS PASSED")
            if warnings:
                print("\n   ⚠️  Warnings:")
                for w in warnings:
                    print(f"      • {w}")
        else:
            print(f"   ❌ INTEGRITY FAILED ({len(errors)} error(s), {len(warnings)} warning(s)):")
            for err in errors:
                print(f"      • ❌ {err}")
            for w in warnings:
                print(f"      • ⚠️  {w}")

    return 0 if status_ok else 1


def cmd_map(target_dir: Path, mermaid: bool = False):
    target_dir = target_dir.resolve()
    stage_dirs = sorted([d for d in target_dir.iterdir() if d.is_dir() and re.match(r"^\d{2}_", d.name)])

    if not stage_dirs:
        sys.exit("❌ Error: No stage folders (NN_name) found to map.")

    if mermaid:
        print("```mermaid")
        print("flowchart LR")
        for idx, s in enumerate(stage_dirs):
            clean_name = s.name.replace("_", " ").title()
            print(f"    S{idx}[\"{clean_name}\"]")
            if idx > 0:
                print(f"    S{idx-1} --> S{idx}")
        print("```")
        return

    print(f"\n🗺️  [ICM Stage Pipeline Map] {target_dir.name}\n")
    for idx, s in enumerate(stage_dirs, start=1):
        s_context = s / "CONTEXT.md"
        inputs, outputs = "None specified", "None specified"
        if s_context.is_file():
            text = s_context.read_text(encoding="utf-8", errors="replace")
            in_m = re.search(r"## Inputs\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
            if in_m:
                inputs = ", ".join(
                    [line.strip("- *") for line in in_m.group(1).strip().splitlines() if line.strip()][:2]
                )
            out_m = re.search(r"## Outputs\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
            if out_m:
                outputs = ", ".join(
                    [line.strip("- *") for line in out_m.group(1).strip().splitlines() if line.strip()][:2]
                )

        print(f"  [{s.name}]")
        print(f"    ├─ In:  {inputs}")
        print(f"    └─ Out: {outputs}")
        if idx < len(stage_dirs):
            print("       │\n       ▼")


def main():
    parser = argparse.ArgumentParser(
        prog="icm-architect",
        description="Autonomous Interpretable Context Methodology (ICM) Workspace Architect & Validator",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_init = sub.add_parser("init", aliases=["scaffold"], help="Scaffold a new production ICM workspace")
    p_init.add_argument("path", help="Target directory for workspace")
    p_init.add_argument("--name", default=None, help="Workspace human-readable name")
    p_init.add_argument(
        "--stages",
        default="plan,extract,synthesize,verify",
        help="Comma-separated stage names (ignored when using --template agentic-factory)",
    )
    p_init.add_argument(
        "--form",
        choices=[
            "pipeline", "umbrella", "library", "record-library",
            "knowledge-bundle", "context-map", "system-map", "agentic-factory", "map",
        ],
        default="pipeline",
        help="ICM architectural form (see references/forms.md; 'map' and 'library' are legacy aliases)",
    )
    p_init.add_argument(
        "--template",
        choices=["pipeline", "agentic-factory", "software-factory"],
        default="pipeline",
        help="Pre-baked workspace template (agentic-factory: Kem's six-phase software factory as folders)",
    )
    p_init.add_argument(
        "--with-memory",
        action="store_true",
        help="Scaffold SQLite graph memory and hybrid BGE/FTS search in _memory/",
    )
    p_init.add_argument("--json", action="store_true", help="Output as JSON")

    p_val = sub.add_parser("validate", aliases=["check"], help="Validate reference integrity & ICM hierarchy")
    p_val.add_argument("path", nargs="?", default=".", help="Target workspace directory (default: current)")
    p_val.add_argument("--json", action="store_true", help="Output as JSON")
    p_val.add_argument(
        "--kem",
        action="store_true",
        help="Strict kem-mode contract: missing Actor / Step type / Proof in any stage is an error",
    )

    p_map = sub.add_parser("map", help="Render stage pipeline topology")
    p_map.add_argument("path", nargs="?", default=".", help="Target workspace directory (default: current)")
    p_map.add_argument("--mermaid", action="store_true", help="Output as Mermaid flowchart")

    p_doc = sub.add_parser("doctor", help="Run diagnostic health checks on workspace")
    p_doc.add_argument("path", nargs="?", default=".", help="Target workspace directory (default: current)")
    p_doc.add_argument("--json", action="store_true", help="Output as JSON")
    p_doc.add_argument("--kem", action="store_true", help="Strict kem-mode contract fields")

    args = parser.parse_args()

    if args.action in ("init", "scaffold"):
        p = Path(args.path)
        name = args.name or p.name.replace("-", " ").title()
        stages = [s.strip() for s in args.stages.split(",") if s.strip()]
        cmd_init(
            p,
            name,
            stages,
            form=args.form,
            template=args.template,
            with_memory=args.with_memory,
            as_json=args.json,
        )
    elif args.action in ("validate", "check", "doctor"):
        ret = cmd_validate(Path(args.path), as_json=args.json, kem=getattr(args, "kem", False))
        sys.exit(ret)
    elif args.action == "map":
        cmd_map(Path(args.path), mermaid=args.mermaid)


if __name__ == "__main__":
    main()
