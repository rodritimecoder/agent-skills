#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "modules"))
from cache_engine import SemanticCache


def main():
    parser = argparse.ArgumentParser(description="Semantic Cache CLI — Sub-10ms Repeat Query Bypass")
    parser.add_argument("--db", default=str(Path.home() / ".cache" / "semantic_cache.db"), help="Path to SQLite cache DB")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # query
    p_q = subparsers.add_parser("query", help="Lookup cached response for question")
    p_q.add_argument("question", help="Inbound user question")
    p_q.add_argument("--threshold", type=float, default=0.85, metavar="THRESHOLD", help="Cosine similarity threshold (default: 0.85)")
    p_q.add_argument("--dry-run", action="store_true",
                     help="Print the planned lookup and exit without touching the cache")

    # store
    p_s = subparsers.add_parser("store", help="Store verified question-answer pair")
    p_s.add_argument("question", help="Question text")
    p_s.add_argument("answer", help="Verified answer text")
    p_s.add_argument("--dry-run", action="store_true",
                     help="Print the planned store and exit without writing to the cache")

    # stats
    subparsers.add_parser("stats", help="View cache hit statistics")

    # purge
    p_p = subparsers.add_parser("purge", help="Clear all cached questions")
    p_p.add_argument("--dry-run", action="store_true",
                     help="Print the planned purge and exit without clearing the cache")

    args = parser.parse_args()
    if getattr(args, "dry_run", False):
        plan = {"command": args.command, "dry_run": True, "db": args.db}
        for key in ("question", "answer", "threshold"):
            if hasattr(args, key):
                plan[key] = getattr(args, key)
        print(json.dumps(plan, indent=2) if args.json else
              f"[dry-run] {args.command}: {json.dumps(plan, sort_keys=True)}")
        return
    cache = SemanticCache(Path(args.db))

    if args.command == "query":
        res = cache.get(args.question, threshold=args.threshold)
        if args.json:
            print(json.dumps(res, indent=2))
        elif res["hit"]:
            print(f"⚡ [CACHE HIT] Similarity: {res['similarity'] * 100:.1f}% (Hits: {res['hit_count']})")
            print(f"Matched: \"{res['matched_query']}\"")
            print(f"Answer:\n{res['answer']}")
        else:
            print(f"❌ [CACHE MISS] Best Similarity: {res['best_similarity'] * 100:.1f}% (Threshold: {res['threshold'] * 100:.1f}%)")
        if not res["hit"]:
            sys.exit(2)

    elif args.command == "store":
        cache.set(args.question, args.answer)
        if args.json:
            print(json.dumps({"stored": True, "question": args.question}, indent=2))
        else:
            print(f"✓ Cached question: \"{args.question}\"")

    elif args.command == "stats":
        st = cache.stats()
        if args.json:
            print(json.dumps(st, indent=2))
        else:
            print(f"📊 Semantic Cache Statistics:")
            print(f"  • Total Cached Queries: {st['total_entries']}")
            print(f"  • Total Saved Model Hits: {st['total_cache_hits']}")
            print(f"  • Database: {st['db_path']}")

    elif args.command == "purge":
        deleted = cache.purge()
        if args.json:
            print(json.dumps({"purged": deleted}, indent=2))
        else:
            print(f"✓ Purged {deleted} cache entries.")


if __name__ == "__main__":
    main()
