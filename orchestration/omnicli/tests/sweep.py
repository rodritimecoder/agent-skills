"""Parameter sweep over the retriever's weight constants.

Tunes against tests/golden_eval.json. Prints the full accuracy surface so a
*robust* region can be chosen, not a knife-edge optimum — a setting that only
wins by one case is overfitted.

Usage:
    python3 tests/sweep.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from catalog import builder, search  # noqa: E402

GOLDEN = HERE / "golden_eval.json"


def evaluate(con, cases) -> tuple[int, int, int]:
    top1 = top3 = neg = 0
    for case in cases:
        res = search.search(con, case["query"], limit=3, rerank_enabled=False)
        ids = [r["skill"] for r in res["results"]]
        exp = case.get("expect", [])
        want = case.get("top1")
        if (want and ids and ids[0] == want) or (not want and ids and exp and ids[0] == exp[0]):
            top1 += 1
        if ids and all(e in ids for e in exp):
            top3 += 1
        if all(n not in ids for n in case.get("expect_not", [])):
            neg += 1
    return top1, top3, neg


def main() -> None:
    cases = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
    con = builder.connect()
    builder.ensure_built(con, progress=False)

    total = len(cases)
    print(f"sweeping over {total} golden cases\n")
    header = f"{'alias_w':>8} {'gamma':>6} | {'top1':>10} {'top3':>10} {'neg':>10} | {'all':>5}"
    print(header)
    print("-" * len(header))

    best = []
    for alias_w in (8.0, 12.0, 16.0, 20.0):
        for gamma in (0.0, 0.2, 0.4, 0.65, 0.9):
            for cands in (1, 3, 5, 8, 16):
                search.ALIAS_WEIGHT = alias_w
                search.COORDINATION_GAMMA = gamma
                search.COORDINATION_CANDIDATES = cands
                t1, t3, ng = evaluate(con, cases)
                allp = t1 + t3 + ng
                best.append((allp, t1, t3, ng, alias_w, gamma, cands))
                print(f"{alias_w:>6.1f} {gamma:>5.2f} {cands:>4} | {t1:>4}/{total:<5} {t3:>4}/{total:<5} {ng:>4}/{total:<5} | {allp:>5}")

    best.sort(reverse=True)
    print("\nTop configurations by combined score:")
    seen = set()
    for allp, t1, t3, ng, aw, g, cap in best:
        key = (allp, t1)
        if key in seen:
            continue
        seen.add(key)
        print(f"  alias_w={aw:<6.2f} gamma={g:<5.2f} cands={cap:<3} combined={allp:>3}  top1={t1} top3={t3} neg={ng}")
        if len(seen) >= 10:
            break


if __name__ == "__main__":
    main()
