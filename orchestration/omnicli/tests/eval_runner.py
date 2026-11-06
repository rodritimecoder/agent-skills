"""Golden routing evaluation: measure the catalog against the legacy scorer.

Usage:
    python3 tests/eval_runner.py            # summary
    python3 tests/eval_runner.py --verbose  # per-case detail
    python3 tests/eval_runner.py --json     # machine readable
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
sys.path.insert(0, str(SKILL_ROOT))

from catalog import builder, legacy, search  # noqa: E402

GOLDEN = HERE / "golden_eval.json"


def run(verbose: bool = False, as_json: bool = False, rerank: str = "never",
        fusion: str = "never") -> dict:
    cases = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
    con = builder.connect()
    builder.ensure_built(con, progress=False)

    skills = None
    rows = []
    new_top1 = new_top3 = leg_top1 = leg_top3 = 0
    forbidden_top3 = 0

    for case in cases:
        q = case["query"]
        res = search.search(con, q, limit=3, rerank_enabled=rerank, fusion=fusion)
        new_ids = [r["skill"] for r in res["results"]]
        new_scores = {r["skill"]: r["score"] for r in res["results"]}

        if skills is None:
            skills = legacy.registry.load_all_skills()
        leg = legacy.score_all(q, skills)
        leg_ids = [name for _, name in leg[:3]]

        exp = case.get("expect", [])
        top1 = case.get("top1")
        notexp = case.get("expect_not", [])
        min_margin = case.get("min_margin")

        # The router's guarantee is that the right skill WINS. A forbidden
        # skill must not take the top slot, and when a margin is specified it
        # must also lose by that factor — a stronger and more meaningful
        # assertion than "must be absent from the top 3", which would only
        # measure how many irrelevant runners-up the corpus happens to have.
        ok_top1 = ((top1 in new_ids[0]) if top1 else (not exp or exp[0] in new_ids)) if new_ids else False
        ok_top3 = bool(new_ids) and all(e in new_ids for e in exp)
        ok_neg = all(n not in new_ids[:1] for n in notexp)

        margin = None
        if notexp and new_ids:
            forbidden_scores = [new_scores[n] for n in notexp if n in new_scores]
            if forbidden_scores and new_scores.get(new_ids[0]):
                margin = round(new_scores[new_ids[0]] / max(forbidden_scores), 3)
        ok_margin = (margin is None) or (min_margin is None) or (margin >= min_margin)

        leg_ok_top1 = ((top1 in leg_ids[0]) if top1 else (not exp or exp[0] in leg_ids)) if leg_ids else False
        leg_ok_top3 = bool(leg_ids) and all(e in leg_ids for e in exp)

        new_top1 += ok_top1
        new_top3 += ok_top3
        leg_top1 += leg_ok_top1
        leg_top3 += leg_ok_top3
        if notexp:
            forbidden_top3 += all(n not in new_ids for n in notexp)

        rows.append({
            "query": q,
            "kind": case.get("kind", ""),
            "expected": top1 or (exp[0] if exp else None),
            "new_top1": new_ids[0] if new_ids else None,
            "new_top3": new_ids,
            "legacy_top1": leg_ids[0] if leg_ids else None,
            "pass_top1": ok_top1,
            "pass_top3": ok_top3,
            "pass_negative": ok_neg,
            "pass_margin": ok_margin,
            "margin": margin,
            "min_margin": min_margin,
            "legacy_pass_top1": leg_ok_top1,
            "legacy_pass_top3": leg_ok_top3,
        })

    total = len(cases)
    summary = {
        "cases": total,
        "bm25": {
            "top1": f"{new_top1}/{total} ({100.0*new_top1/total:.1f}%)",
            "top3": f"{new_top3}/{total} ({100.0*new_top3/total:.1f}%)",
            "top1_raw": new_top1,
            "top3_raw": new_top3,
        },
        "legacy": {
            "top1": f"{leg_top1}/{total} ({100.0*leg_top1/total:.1f}%)",
            "top3": f"{leg_top3}/{total} ({100.0*leg_top3/total:.1f}%)",
            "top1_raw": leg_top1,
            "top3_raw": leg_top3,
        },
        "rows": rows,
    }

    if as_json:
        print(json.dumps(summary, indent=2))
        return summary

    if verbose:
        for r in rows:
            flag = "PASS" if (r["pass_top1"] and r["pass_top3"] and r["pass_negative"]
                              and r["pass_margin"]) else "FAIL"
            print(f"[{flag}] {r['query']}")
            print(f"        expected : {r['expected']}")
            print(f"        bm25     : {r['new_top1']}   (legacy: {r['legacy_top1']})")
            if r.get("margin") is not None:
                print(f"        margin   : {r['margin']}x over forbidden skill"
                      + (f" (required {r['min_margin']}x)" if r["min_margin"] else ""))
            if not r["pass_top3"] or not r["pass_negative"] or not r["pass_margin"]:
                print(f"        top3     : {r['new_top3']}")
            print()

    b1, b3 = summary["bm25"]["top1_raw"], summary["bm25"]["top3_raw"]
    l1, l3 = summary["legacy"]["top1_raw"], summary["legacy"]["top3_raw"]
    print("=" * 66)
    print(f"  GOLDEN ROUTING EVAL   ({total} cases)   rerank={rerank}")
    print("=" * 66)
    print(f"  BM25 catalog    top1 {b1:>3}/{total} ({100.0*b1/total:5.1f}%)   top3 {b3:>3}/{total} ({100.0*b3/total:5.1f}%)")
    print(f"  legacy scorer   top1 {l1:>3}/{total} ({100.0*l1/total:5.1f}%)   top3 {l3:>3}/{total} ({100.0*l3/total:5.1f}%)")
    print(f"  delta           top1 {b1-l1:+d}   top3 {b3-l3:+d}")
    print("=" * 66)

    failures = [r for r in rows if not (r["pass_top1"] and r["pass_top3"]
                                        and r["pass_negative"] and r["pass_margin"])]
    if failures:
        print(f"\n  {len(failures)} failing case(s):\n")
        for r in failures:
            reasons = []
            if not r["pass_top1"]:
                reasons.append(f"top1 expected {r['expected']} got {r['new_top1']}")
            if not r["pass_top3"]:
                reasons.append("missing from top3")
            if not r["pass_negative"]:
                reasons.append("forbidden skill won")
            if not r["pass_margin"]:
                reasons.append(f"margin {r['margin']}x < required {r['min_margin']}x")
            print(f"    - {r['query']}")
            print(f"        {'; '.join(reasons)}   [legacy gave: {r['legacy_top1']}]")
    return summary


if __name__ == "__main__":
    mode = "never"
    fusion = "never"
    for arg in sys.argv[1:]:
        if arg.startswith("--rerank="):
            mode = arg.split("=", 1)[1]
        elif arg.startswith("--fusion="):
            fusion = arg.split("=", 1)[1]
    run(verbose="--verbose" in sys.argv, as_json="--json" in sys.argv,
        rerank=mode, fusion=fusion)
