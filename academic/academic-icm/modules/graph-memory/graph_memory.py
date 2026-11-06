#!/usr/bin/env python3
"""
graph_memory.py — Unified CLI for Local Graph Memory & RAG (Glitch Cat Club Architecture)
"""

import argparse
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
RAG_DIR = SKILL_DIR / "rag"
GRAPH_DIR = SKILL_DIR / "graph"


def main():
    parser = argparse.ArgumentParser(
        prog="graph-memory",
        description="Glitch Cat Club Hybrid Graph Memory & RAG Engine (Kem Architecture)"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # --- 1. Graph Leg ---
    # build-graph
    p_build = sub.add_parser("build-graph", aliases=["build"], help="Build deterministic SQLite knowledge graph from extracted JSONs")
    p_build.add_argument("--db", default=str(SKILL_DIR / "graph.db"), help="Output SQLite database path")
    p_build.add_argument("--extraction", default=str(SKILL_DIR / "extraction"), help="Path to extraction JSONs directory")
    p_build.add_argument("--schema", default=str(GRAPH_DIR / "schema.sql"), help="Path to schema.sql")

    # recall
    p_recall = sub.add_parser("recall", help="Deterministic k-hop SQL walk over graph knowledge")
    p_recall.add_argument("question", nargs="*", help="Question to seed entities and traverse facts")
    p_recall.add_argument("--db", default=str(SKILL_DIR / "graph.db"), help="Path to graph SQLite database")
    p_recall.add_argument("--hops", type=int, default=3, help="Max traversal depth (default: 3)")
    p_recall.add_argument("--top-k", type=int, default=8, help="Max facts returned (default: 8)")

    # hook
    p_hook = sub.add_parser("hook", help="Run UserPromptSubmit injection hook from stdin")

    # --- 2. RAG Leg ---
    # search
    p_search = sub.add_parser("search", help="Search the index via hybrid BM25 + vector reciprocal rank fusion")
    p_search.add_argument("query", help="Query string")
    p_search.add_argument("--table", "-t", action="store_true", help="Render search results as high-density Markdown table")
    p_search.add_argument("--json", action="store_true", help="Output results as JSON")
    p_search.add_argument("--project", "-p", help="Comma-separated fields to project")
    p_search.add_argument("--limit", "-n", type=int, default=3, help="Max number of hits (default: 3)")
    p_search.add_argument("--out", "-o", help="Buffer full hits to file and emit table receipt")

    # index
    p_index = sub.add_parser("index", help="Rebuild the index over notes corpus")
    p_index.add_argument("--corpus", default="/run/media/rodri/AI/University/notes", help="Path to notes directory")

    # distil
    p_distil = sub.add_parser("distil", help="Distil markdown notes into verified question-rule-quote triplets")
    p_distil.add_argument("corpus", nargs="?", default="/run/media/rodri/AI/University/notes", help="Path to notes directory")
    p_distil.add_argument("--limit", type=int, default=None, help="Limit number of notes to process")

    args = parser.parse_args()

    if args.action in ("build-graph", "build"):
        cmd = [sys.executable, str(GRAPH_DIR / "build_graph.py"), "--db", args.db, "--schema", args.schema, "--extraction", args.extraction]
        sys.exit(subprocess.run(cmd).returncode)
    elif args.action == "recall":
        q = " ".join(args.question)
        cmd = [sys.executable, str(GRAPH_DIR / "recall.py"), q, "--db", args.db, "--hops", str(args.hops), "--top-k", str(args.top_k)]
        sys.exit(subprocess.run(cmd).returncode)
    elif args.action == "hook":
        cmd = [sys.executable, str(GRAPH_DIR / "recall_hook.py")]
        sys.exit(subprocess.run(cmd).returncode)
    elif args.action == "search":
        cmd = [sys.executable, str(RAG_DIR / "search.py"), args.query]
        if args.table:
            cmd.append("--table")
        if args.json:
            cmd.append("--json")
        if args.project:
            cmd.extend(["--project", args.project])
        if args.limit:
            cmd.extend(["--limit", str(args.limit)])
        if args.out:
            cmd.extend(["--out", args.out])
        sys.exit(subprocess.run(cmd).returncode)
    elif args.action == "index":
        cmd = [sys.executable, str(RAG_DIR / "build_index.py"), "--corpus", args.corpus]
        sys.exit(subprocess.run(cmd).returncode)
    elif args.action == "distil":
        cmd = [sys.executable, str(RAG_DIR / "distil.py"), args.corpus]
        if args.limit:
            cmd += ["--limit", str(args.limit)]
        sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
