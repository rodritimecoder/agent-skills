#!/usr/bin/env python3
"""Description audit: the worklist for rewriting ``SKILL.md`` trigger text.

The ``description`` field is the only routing signal a client reads before it
decides to load a skill, so a description that is accurate but written in the
catalog's vocabulary ("Glitch Cat Club; Reel Dfhog8VtWDx") routes worse than one
written in the operator's ("why did the deskforge one break"). That gap is
measured, not guessed: the golden set shares the catalog's vocabulary and sits
at 57/61 top-1, while the paraphrase set — real prompts harvested from session
logs — sits at 21/39. Every paraphrase miss is evidence of a word the
description should have carried and does not.

This tool turns those misses into a per-skill worklist:

* **held-out split** — the paraphrase set is split 60/40 by a stable hash of the
  query. Rewrites are steered by *train* failures only. Validation is scored
  afterwards, so a description that merely learned its own eval set is visible
  as a train-gain / validation-flat.
* **unrouted vocabulary** — tokens from *failing train* queries that appear in
  neither the description, the skill name, nor the curated aliases. That is the
  concrete list of words a rewrite should cover, rather than a guess.
* **provenance waste** — characters spent on reel ids and brand names nobody
  types, inside a 1024-char field.
* **gaps the spec cares about** — description under/over length, missing
  imperative trigger, and no curated alias entry at all (39 of 62 skills have
  one).

Usage:
    python3 tests/desc_audit.py                 # human worklist, grouped by folder
    python3 tests/desc_audit.py --json          # machine readable
    python3 tests/desc_audit.py --folder=academic
    python3 tests/desc_audit.py --strict        # exit 2 when a skill is unsettled

Exit codes: 0 clean, 2 findings under --strict, 1 fatal.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
sys.path.insert(0, str(SKILL_ROOT))

from catalog import aliases as aliaslib, builder, registry, search  # noqa: E402

MIN_DESC_LEN = 40
MAX_DESC_LEN = 1024

# A description is an instruction to act, not a summary of a package.
TRIGGER_RE = re.compile(
    r"\b(?:use (?:this skill )?when|use for|must use|invoke when|trigger when|"
    r"run when|reach for|use it when|use this whenever)\b",
    re.IGNORECASE,
)
# Provenance that belongs in git history or a README, not the routing field.
PROVENANCE_RE = re.compile(r"\bReel\s+[A-Za-z0-9_-]{6,}\b|\bGlitch Cat Club\b")

WORD_RE = re.compile(r"[a-z0-9][a-z0-9+._/-]*")

TRAIN_BUCKETS = 3  # out of 5: ~60% train, ~40% held out


def split_of(query: str) -> str:
    """Stable train/validation assignment for an eval query.

    Hashed rather than shuffled so the split survives edits to the eval sets:
    a case keeps its bucket when a new case is inserted above it. The point is
    that a description cannot be tuned against the validation half by accident.
    """
    digest = hashlib.md5(query.strip().lower().encode("utf-8")).digest()
    return "train" if digest[0] % 5 < TRAIN_BUCKETS else "validation"


def _words(text: str) -> set[str]:
    return set(WORD_RE.findall((text or "").lower()))


def _load_cases(name: str) -> list[dict]:
    path = HERE / f"{name}_eval.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("cases", [])


def _folder_of(skill_path: str) -> str:
    """The grouping directory a skill lives in, for dispatch."""
    root = registry.resolve_skills_dir()
    try:
        rel = Path(skill_path).resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return "."
    return rel.parent.name if rel.parent.name else "."


def audit(fusion: str = "never", rerank: str = "never") -> dict:
    skills = registry.load_all_skills()
    alias_cfg = aliaslib.load()
    con = builder.connect()
    builder.ensure_built(con, progress=False)

    golden = [dict(c, _set="golden") for c in _load_cases("golden")]
    para = [dict(c, _set="paraphrase", _split=split_of(c["query"])) for c in _load_cases("paraphrase")]
    cases = golden + para

    # Score every case once; retrieval is the expensive part.
    for case in cases:
        res = search.search(con, case["query"], limit=3,
                            rerank_enabled=rerank, fusion=fusion)
        ids = [r["skill"] for r in res["results"]]
        case["_top3"] = ids
        expected = case.get("top1") or (case.get("expect") or [None])[0]
        case["_expected"] = expected
        case["_pass"] = bool(ids) and expected in ids[:1]

    by_skill: dict[str, list[dict]] = {}
    for case in cases:
        by_skill.setdefault(case["_expected"], []).append(case)

    rows = []
    for name, spec in sorted(skills.items()):
        if spec.get("status") != "active":
            continue
        desc = spec.get("description") or ""
        aliases = list(alias_cfg.get(name, {}).get("aliases", []))
        own = by_skill.get(name, [])

        failing_train = [c for c in own
                         if not c["_pass"] and c.get("_split", "train") == "train"]
        failing_val = [c for c in own
                       if not c["_pass"] and c.get("_split") == "validation"]

        covered = _words(" ".join([desc, name, " ".join(aliases)]))
        unrouted: list[str] = []
        for case in failing_train:
            for token in sorted(_words(case["query"])):
                if token in covered or len(token) < 3 or token in search.STOPWORDS:
                    continue
                if token not in unrouted:
                    unrouted.append(token)

        provenance = PROVENANCE_RE.findall(desc)
        has_trigger = bool(TRIGGER_RE.search(desc))

        problems = []
        if not desc:
            problems.append("description-missing")
        elif len(desc) < MIN_DESC_LEN:
            problems.append("description-thin")
        elif len(desc) > MAX_DESC_LEN:
            problems.append("description-over-limit")
        if desc and not has_trigger:
            problems.append("no-imperative-trigger")
        if not aliases:
            problems.append("no-aliases")
        if failing_train:
            problems.append(f"misroutes x{len(failing_train)}")
        if provenance:
            problems.append("provenance-in-description")

        rows.append({
            "skill": name,
            "folder": _folder_of(spec["path"]),
            "path": spec["md_path"],
            "desc_len": len(desc),
            "description": desc,
            "has_trigger": has_trigger,
            "provenance": provenance,
            "aliases": len(aliases),
            "golden": sum(1 for c in own if c["_set"] == "golden"),
            "golden_pass": sum(1 for c in own if c["_set"] == "golden" and c["_pass"]),
            "train_fail": len(failing_train),
            "val_fail": len(failing_val),
            "unrouted": unrouted[:12],
            "problems": problems,
            "failing": [
                {"query": c["query"], "got": (c["_top3"] or [None])[0], "split": c.get("_split")}
                for c in failing_train + failing_val
            ],
        })

    totals = {
        "skills": len(rows),
        "clean": sum(1 for r in rows if not r["problems"]),
        "misrouting": sum(1 for r in rows if r["train_fail"]),
        "no_trigger": sum(1 for r in rows if "no-imperative-trigger" in r["problems"]),
        "no_aliases": sum(1 for r in rows if "no-aliases" in r["problems"]),
        "provenance": sum(1 for r in rows if r["provenance"]),
        "over_limit": sum(1 for r in rows if "description-over-limit" in r["problems"]),
        "train_cases": sum(1 for c in cases if c.get("_split") == "train"),
        "val_cases": sum(1 for c in cases if c.get("_split") == "validation"),
    }
    return {"totals": totals, "rows": rows}


def worklist(report: dict) -> str:
    """Render the report as the brief handed to one writer per folder."""
    out: list[str] = []
    folders: dict[str, list[dict]] = {}
    for row in report["rows"]:
        folders.setdefault(row["folder"], []).append(row)

    for folder, rows in sorted(folders.items()):
        dirty = [r for r in rows if r["problems"]]
        if not dirty:
            continue
        out.append(f"## {folder}  ({len(dirty)}/{len(rows)} skills need work)")
        for row in dirty:
            out.append(f"\n### {row['skill']}   [{' '.join(row['problems'])}]")
            out.append(f"desc {row['desc_len']}ch · aliases {row['aliases']} · "
                       f"golden {row['golden_pass']}/{row['golden']} · "
                       f"train-fail {row['train_fail']} · val-fail {row['val_fail']}")
            for item in row["failing"]:
                if item["split"] == "train":
                    out.append(f"  train  ✗ \"{item['query']}\" -> {item['got']}")
            if row["unrouted"]:
                out.append(f"  words nothing routes on: {', '.join(row['unrouted'])}")
        out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    strict = "--strict" in argv
    folder = next((a.split("=", 1)[1] for a in argv if a.startswith("--folder=")), None)
    fusion = next((a.split("=", 1)[1] for a in argv if a.startswith("--fusion=")), "never")
    rerank = next((a.split("=", 1)[1] for a in argv if a.startswith("--rerank=")), "never")

    report = audit(fusion=fusion, rerank=rerank)
    if folder:
        report["rows"] = [r for r in report["rows"] if r["folder"] == folder]
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        t = report["totals"]
        print(f"DESCRIPTION AUDIT   {t['skills']} active skills   "
              f"train {t['train_cases']} / validation {t['val_cases']} cases")
        print(f"  clean {t['clean']}   misrouting {t['misrouting']}   "
              f"no-trigger {t['no_trigger']}   no-aliases {t['no_aliases']}   "
              f"provenance {t['provenance']}   over-limit {t['over_limit']}\n")
        print(worklist(report))
    dirty = any(r["problems"] for r in report["rows"])
    return 2 if (strict and dirty) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
