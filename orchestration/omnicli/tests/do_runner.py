"""Measure `omnicli do` as one hop instead of three.

`eval_runner.py` answers *does search find the right skill*. This answers the
question the session log actually raised: an agent that must call `search`,
read the result, call `describe`, read the contract, then call `invoke` pays
two context reads and three process launches before anything runs. `do` claims
to collapse that to one. The claim is only worth anything if it still lands on
the right skill, and if the refusals land on the cases that would have gone
wrong anyway.

Four numbers, per set:

* **resolved**  — the skill `do` picked matches the expected skill.
* **executes**  — `do` returned ``ok`` rather than refusing.
* **both**      — correct *and* executable. The only cell that ships.
* **refusal quality** — of the cases `do` refused, how many were ones search
  would have got wrong anyway. A refusal that blocks a would-have-been-correct
  route costs more than the wrong execution it prevents.

Timing compares `do --dry-run` against `search` + `describe` as separate
process launches, because hop count is the whole argument.

Usage:
    python3 tests/do_runner.py                     # golden, summary
    python3 tests/do_runner.py --set=paraphrase    # blind set
    python3 tests/do_runner.py --verbose           # per-case detail
    python3 tests/do_runner.py --json              # machine readable
    python3 tests/do_runner.py --timing            # add wall-clock comparison
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
sys.path.insert(0, str(SKILL_ROOT))

from catalog import builder, resolve, search  # noqa: E402

SETS = {
    "golden": HERE / "golden_eval.json",
    "paraphrase": HERE / "paraphrase_eval.json",
}


def expected_skills(case: dict) -> list[str]:
    """Every skill the case accepts — the soft reading of `expect`."""
    exp = [e for e in (case.get("expect") or []) if e]
    if not exp and case.get("top1"):
        exp = [case["top1"]]
    return exp


def is_correct(case: dict, got: str | None, strict: bool = True) -> bool:
    """Did `got` satisfy this case?

    Two readings exist and they disagree on 5 of 39 paraphrase cases, so both
    are reported rather than one being chosen silently:

    * ``strict``   — mirrors ``eval_runner`` exactly (``top1 in actual_top1``,
      else ``expect[0]``). This is the rule behind the published baselines
      (golden 57/61, paraphrase 23/39), so it is the headline. Landing on the
      designated `top1` is what those numbers count.
    * ``strict=False`` — `got` anywhere in `expect`. The five disagreements are
      all cases where retrieval found a *different skill the author also
      accepted* (e.g. `expect=['jev-decision','model-layer']`, got
      `model-layer`). Legitimate to want to see, but not what the baseline
      scores, so it is never the headline.

    Returns False when nothing resolved.
    """
    if not got:
        return False
    exp = case.get("expect", [])
    top1 = case.get("top1")
    if strict:
        if top1:
            return top1 in got
        return (not exp) or (exp[0] in got)
    if exp:
        return got in exp
    return bool(top1) and top1 in got


def run(eval_set: str = "golden", verbose: bool = False,
        margin: float | None = None) -> dict:
    path = SETS.get(eval_set)
    if path is None:
        raise SystemExit(f"unknown eval set {eval_set!r}; choose from {sorted(SETS)}")
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    con = builder.connect()
    builder.ensure_built(con, progress=False)

    rows = []
    resolved = resolved_soft = executes = both = both_soft = 0
    refused = refused_saved = refused_costly = 0

    for case in cases:
        q = case["query"]
        exp = expected_skills(case)
        decision = resolve.resolve(con, q, do_margin=margin)
        status = decision.get("status", "no_match")
        got = decision.get("skill")
        # strict is the headline (matches eval_runner's published baselines);
        # soft counts any skill the case author also accepted.
        ok_skill = is_correct(case, got, strict=True)
        ok_soft = is_correct(case, got, strict=False)

        # What search alone would have done, for the refusal-quality column.
        top = search.search(con, q, limit=1, rerank_enabled="never",
                            fusion="never")["results"]
        search_top = top[0]["skill"].split("/")[0] if top else None
        search_ok = is_correct(case, search_top, strict=True)

        if ok_skill:
            resolved += 1
        if ok_soft:
            resolved_soft += 1
        if status == "ok":
            executes += 1
            if ok_skill:
                both += 1
            if ok_soft:
                both_soft += 1
        else:
            refused += 1
            # Split the refusals: one kind saved us from a route search would
            # have taken wrongly, the other blocked a route that was correct.
            if search_ok:
                refused_costly += 1
            else:
                refused_saved += 1

        rows.append({
            "query": q,
            "expected": exp,
            "status": status,
            "skill": got,
            "tool": decision.get("tool"),
            "reason": decision.get("reason"),
            "resolved": ok_skill,
            "resolved_soft": ok_soft,
            "executes": status == "ok",
            "search_would_be_right": search_ok,
        })
        if verbose:
            flag = "ok " if (ok_skill and status == "ok") else "   "
            print(f"  [{flag}] {status:14} {str(got):24} {q[:58]!r}")

    total = len(cases)
    return {
        "set": eval_set,
        "total": total,
        "resolved": resolved,
        "resolved_soft": resolved_soft,
        "executes": executes,
        "both": both,
        "both_soft": both_soft,
        "refused": refused,
        "refused_saved_us": refused_saved,
        "refused_blocked_correct": refused_costly,
        "rows": rows,
    }


def sweep(margins: tuple[float, ...] = (1.0, 1.1, 1.2, 1.3, 1.5, 1.7, 2.0)) -> None:
    """What each skill-margin threshold buys and costs, end to end.

    This is the evidence for the `OMNICLI_DO_MARGIN` default. Reported both
    strict (eval_runner-compatible) and soft (any accepted skill), because the
    two readings differ on paraphrase and a threshold chosen on the soft
    reading would look better than it is.

    `caught` counts cases search would have ranked wrongly that `do` refused —
    the only thing the margin actually buys. Everything it refuses beyond that
    is coverage surrendered.
    """
    print("\n  MARGIN SWEEP — end to end (tier1 + tier2 + tier3)")
    print("  margin | set        | strict right/exec | wrongExec | refused | caught search err")
    print("  -------|------------|-------------------|-----------|---------|-------------------")
    for m in margins:
        for st in ("golden", "paraphrase"):
            res = run(st, margin=m)
            rows = res["rows"]
            strict_exec = sum(1 for r in rows if r["resolved"] and r["executes"])
            wrong_exec = sum(1 for r in rows if r["executes"] and not r["resolved"])
            refused = sum(1 for r in rows if r["status"] == "ambiguous")
            caught = sum(1 for r in rows
                         if not r["search_would_be_right"] and not r["executes"])
            print(f"  {m:6} | {st:10} | {strict_exec:3}/{len(rows):3}"
                  f" ({100 * strict_exec / len(rows):4.1f}%)      | {wrong_exec:2} | "
                  f"{refused:2} | {caught:2}")
        print()


def timing(eval_set: str = "golden", sample: int = 15) -> dict:
    """Wall clock: one `do --dry-run` vs `search` then `describe`."""
    cases = json.loads(SETS[eval_set].read_text(encoding="utf-8"))["cases"][:sample]
    py = sys.executable
    cli = str(SKILL_ROOT / "omnicli.py")

    def timed(argv: list[str]) -> float:
        t0 = time.perf_counter()
        subprocess.run([py, cli] + argv, capture_output=True, text=True, timeout=120)
        return time.perf_counter() - t0

    do_total = three_total = 0.0
    ran = 0
    for case in cases:
        q = case["query"]
        do_total += timed(["do", q, "--dry-run"])
        # The three-hop path an agent actually pays: search, then describe of
        # whatever came back.
        t0 = time.perf_counter()
        proc = subprocess.run([py, cli, "search", q, "--json", "--limit", "1"],
                              capture_output=True, text=True, timeout=120)
        try:
            top = json.loads(proc.stdout)["results"][0]["skill"]
        except (json.JSONDecodeError, IndexError, KeyError):
            top = None
        if top:
            subprocess.run([py, cli, "describe", top, "--json"],
                           capture_output=True, text=True, timeout=120)
        three_total += time.perf_counter() - t0
        ran += 1

    return {
        "set": eval_set, "n": ran,
        "do_seconds": round(do_total, 2),
        "search_describe_seconds": round(three_total, 2),
        "speedup": round(three_total / do_total, 2) if do_total else None,
    }


def report(res: dict) -> None:
    total = res["total"]
    print(f"\n  {res['set'].upper()}  omnicli do   (n={total})")
    print(f"    resolved (strict, = eval_runner) : {res['resolved']:3}/{total}"
          f"  ({100 * res['resolved'] / total:4.1f}%)")
    print(f"    resolved (soft, any expected)   : {res['resolved_soft']:3}/{total}"
          f"  ({100 * res['resolved_soft'] / total:4.1f}%)")
    print(f"    would execute (status ok)       : {res['executes']:3}/{total}"
          f"  ({100 * res['executes'] / total:4.1f}%)")
    print(f"    correct AND executable (strict)  : {res['both']:3}/{total}"
          f"  ({100 * res['both'] / total:4.1f}%)")
    print(f"    correct AND executable (soft)    : {res['both_soft']:3}/{total}"
          f"  ({100 * res['both_soft'] / total:4.1f}%)")
    print(f"    refused                          : {res['refused']:3}/{total}")
    if res["refused"]:
        print(f"      ...search was also wrong  : {res['refused_saved_us']:3}"
              f"  ({100 * res['refused_saved_us'] / res['refused']:4.1f}% of"
              f" refusals blocked a route that would have gone wrong)")
        print(f"      ...search was right      : {res['refused_blocked_correct']:3}"
              f"  ({100 * res['refused_blocked_correct'] / res['refused']:4.1f}%"
              f" blocked a correct route)")
    bad = [r for r in res["rows"] if not (r["resolved"] and r["executes"])]
    wrong_exec = [r for r in res["rows"] if r["executes"] and not r["resolved"]]
    print(f"    wrong skill but executed         : {len(wrong_exec):3}"
          f"   <- the costly cell")
    print(f"    blocked or wrong (strict)        : {len(bad):3}")


def main(argv: list[str]) -> None:
    eval_set, verbose, as_json, do_timing, do_sweep = "golden", False, False, False, False
    margin = None
    for arg in argv:
        if arg.startswith("--set="):
            eval_set = arg.split("=", 1)[1]
        elif arg.startswith("--margin="):
            margin = float(arg.split("=", 1)[1])
        elif arg == "--verbose":
            verbose = True
        elif arg == "--json":
            as_json = True
        elif arg == "--timing":
            do_timing = True
        elif arg == "--sweep":
            do_sweep = True
        else:
            raise SystemExit(f"unknown arg {arg!r}")

    res = run(eval_set, verbose=verbose, margin=margin)
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        report(res)
    if do_timing:
        t = timing(eval_set)
        print(f"\n  TIMING  {t['n']} prompts, {t['set']}")
        print(f"    do --dry-run               : {t['do_seconds']}s")
        print(f"    search + describe (2 hops) : {t['search_describe_seconds']}s")
        print(f"    speedup                    : {t['speedup']}x")


if __name__ == "__main__":
    main(sys.argv[1:])
