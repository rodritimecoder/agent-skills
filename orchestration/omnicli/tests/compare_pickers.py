#!/usr/bin/env python3
"""Compare the two front lines on the same queries with the same model.

  shelf   the agent reads every skill's frontmatter and picks one
  gateway omnicli ranks the skills from a BM25 index over the full bodies

Both are measured on the same golden routing set, with the same local model
doing the picking, so the only variable is how the candidate list reaches the
model.

Usage:
    python3 tests/compare_pickers.py --model qwen3.6-35b --endpoint http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
sys.path.insert(0, str(SKILL_ROOT))

from catalog import builder, registry, search  # noqa: E402

GOLDEN = HERE / "golden_eval.json"

SYSTEM = (
    "You route a request to exactly one skill. Each skill has a name and a "
    "description. Reply with the name of the single best skill and nothing "
    "else. If two are plausible, pick the one whose description covers the "
    "request more directly."
)


def frontmatter_description(skill: dict) -> str:
    """The description a harness would inject, straight from the frontmatter."""
    path = skill.get("md_path")
    if not path:
        return skill.get("description", "")
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return skill.get("description", "")
    match = re.search(r"^description:\s*(?:[>|][-+]?\s*\n((?:[ \t]+[^\n]*\n?)+))?([^\n]*)",
                      text, re.MULTILINE)
    if not match:
        return skill.get("description", "")
    block, inline = match.group(1), match.group(2)
    if block:
        return " ".join(line.strip() for line in block.strip().splitlines())
    return inline.strip().strip("\"'")


def build_shelf_prompt(skills: list[dict]) -> str:
    """Exactly the shape a harness injects: name + description per skill."""
    parts = ["<available_skills>"]
    for s in skills:
        parts.append("<skill>")
        parts.append(f"<name>{s['name']}</name>")
        parts.append(f"<description>{frontmatter_description(s)}</description>")
        parts.append("</skill>")
    parts.append("</available_skills>")
    return "\n".join(parts)


def ask(model: str, endpoint: str, prompt: str, timeout: float) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt + "\n\nRequest: "},
        ],
        # The model reasons before it answers, and the reasoning is billed as
        # completion tokens. A router that gets its budget cut off by its own
        # thinking returns nothing, which would measure this harness, not the
        # routing. A real harness turn has room to finish.
        "max_tokens": 2048,
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        f"{endpoint}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"] or ""


def ask_retry(model: str, endpoint: str, prompt: str, timeout: float, attempts: int = 3) -> str:
    """A reasoning model can spend its whole budget thinking and answer nothing.

    That is a property of the model, not the routing, so an empty answer gets
    retried rather than counted as a miss.
    """
    last = ""
    for _ in range(attempts):
        try:
            last = ask(model, endpoint, prompt, timeout)
        except Exception as exc:
            last = f"__error__ {exc}"
        if last.strip():
            return last
    return last


def pick_from_reply(reply: str, names: list[str]) -> str:
    """Which skill did it name? Longest match wins so prefixes do not shadow."""
    low = reply.lower()
    best = ""
    for name in names:
        if name.lower() in low and len(name) > len(best):
            best = name
    if best:
        return best
    for line in reply.splitlines():
        line = line.strip().strip("`*-• \t").lower()
        if line in [n.lower() for n in names]:
            return line
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.6-35b")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--json", default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cases = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
    con = builder.connect()
    skills = registry.load_all_skills()
    names = sorted(skills)
    shelf = build_shelf_prompt([skills[n] for n in names])

    rows = []
    t_shelf = t_gate = 0.0
    for case in cases:
        q = case["query"]
        expected = case.get("top1") or (case.get("expect") or [None])[0]
        acceptable = case.get("expect") or ([expected] if expected else [])

        t0 = time.time()
        try:
            reply = ask_retry(args.model, args.endpoint, f"{shelf}\n\nRequest: {q}", args.timeout)
        except Exception as exc:
            reply = f"__error__ {exc}"
        t_shelf += time.time() - t0
        got_shelf = pick_from_reply(reply, names)

        t0 = time.time()
        res = search.search(con, q, limit=3, rerank_enabled="auto")
        t_gate += time.time() - t0
        got_gate = res["results"][0]["skill"] if res["results"] else ""

        rows.append({
            "query": q,
            "expected": expected,
            "acceptable": acceptable,
            "shelf": got_shelf,
            "gateway": got_gate,
            "shelf_ok": bool(expected) and got_shelf == expected,
            "gateway_ok": bool(expected) and got_gate == expected,
            "shelf_top3_ok": bool(acceptable) and got_shelf in acceptable,
            "gateway_top3_ok": bool(acceptable) and got_gate in acceptable,
            "tier": res["tier"],
            "reply": reply[:200],
        })
        if args.verbose and not (rows[-1]["shelf_ok"] and rows[-1]["gateway_ok"]):
            print(f"  {q[:46]:48} expected={expected:20} shelf={got_shelf:20} gateway={got_gate}")

    n = len(cases)
    s1 = sum(r["shelf_ok"] for r in rows)
    g1 = sum(r["gateway_ok"] for r in rows)
    s3 = sum(r["shelf_top3_ok"] for r in rows)
    g3 = sum(r["gateway_top3_ok"] for r in rows)

    print("=" * 74)
    print(f"PICKER COMPARISON   {n} golden queries   model={args.model}")
    print("=" * 74)
    print(f"  shelf   (read {len(names)} skill descriptions)  top1 {s1:>3}/{n} ({100.0*s1/n:5.1f}%)   "
          f"acceptable {s3:>3}/{n}   {t_shelf*1000/n:7.0f} ms/query")
    print(f"  gateway (omnicli BM25 index)    top1 {g1:>3}/{n} ({100.0*g1/n:5.1f}%)   "
          f"acceptable {g3:>3}/{n}   {t_gate*1000/n:7.0f} ms/query")
    print(f"  delta                            top1 {g1-s1:+d}   acceptable {g3-s3:+d}")
    print("=" * 74)

    disagreements = [r for r in rows if r["shelf_ok"] != r["gateway_ok"]]
    if disagreements:
        print(f"\n  {len(disagreements)} case(s) where they differ:")
        for r in disagreements[:12]:
            print(f"    {r['query'][:50]:52} expected={r['expected']:20} "
                  f"shelf={r['shelf'] or '-':20} gateway={r['gateway'] or '-'}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "cases": n, "model": args.model,
            "shelf": {"top1": s1, "acceptable": s3, "ms_per_query": t_shelf * 1000 / n},
            "gateway": {"top1": g1, "acceptable": g3, "ms_per_query": t_gate * 1000 / n},
            "rows": rows,
        }, indent=2))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
