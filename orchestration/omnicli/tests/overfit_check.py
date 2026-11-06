"""Detect alias overfitting.

An alias that is a verbatim echo of a golden-eval query makes the evaluation
meaningless: the router is being handed the answer key. This script finds
every alias that overlaps an eval query, so the alias set can be reduced to
*natural domain synonyms* — the words a user would actually type — and the
reported accuracy can be trusted.

Usage:
    python3 tests/overfit_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from catalog import builder  # noqa: E402

GOLDEN = HERE / "golden_eval.json"
ALIASES = HERE.parent / "catalog" / "aliases.json"


def normalise(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").split())


def skill_corpus(skill: str) -> str:
    """The skill's own documentation, lowercased."""
    from catalog import registry
    skills = registry.load_all_skills()
    s = skills.get(skill)
    if not s:
        return ""
    parts = [s.get("description", "")]
    md = s.get("md_path")
    if md:
        try:
            parts.append(Path(md).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return normalise(" ".join(parts))


def main() -> None:
    from catalog import registry

    cases = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
    aliases = json.loads(ALIASES.read_text(encoding="utf-8"))
    # Only indexed skills can hand out an answer key. An archived skill's
    # aliases never reach the FTS table, so counting them as overfitting is a
    # false positive that hides the real ones.
    indexed = set(registry.load_all_skills())

    queries = [(c["query"], normalise(c["query"])) for c in cases]
    corpora: dict[str, str] = {}

    derived = []   # echo of a query, but the words come from the skill's own docs
    overfit = []   # echo of a query, and NOT derivable from the skill's docs
    skipped = []   # aliases belonging to a skill the catalog does not index

    for skill, cfg in aliases.items():
        if skill not in indexed:
            skipped.extend((skill, a) for a in cfg.get("aliases", []))
            continue
        if skill not in corpora:
            corpora[skill] = skill_corpus(skill)
        corpus = corpora[skill]
        for alias in cfg.get("aliases", []):
            na = normalise(alias)
            words = na.split()
            if len(words) < 2:
                # A single domain word ("audio", "canvas", "transcribe") is
                # the skill's own vocabulary, not an answer key. Only
                # multi-word phrases can smuggle a distinctive query
                # fragment into the index.
                continue
            for raw_q, nq in queries:
                echo = na and (na in nq or nq in na)
                if not echo:
                    for i in range(len(words) - 4):
                        if " ".join(words[i:i + 5]) in nq:
                            echo = True
                            break
                if not echo:
                    continue
                # A two-word alias that happens to appear in a query is not
                # an answer key: "force push", "rm rf", "drop table" and
                # "out loud" are all legitimate domain terms. Containment
                # only counts from three words up; shorter overlaps are
                # left to the 5-gram check, which needs five.
                if len(words) < 3 and na in nq:
                    continue
                # Derivable? Either the alias phrase appears verbatim in the
                # skill's own documentation, or at least two of its content
                # words do (the vocabulary may be non-contiguous, e.g.
                # "merge conflicts" ~ "automated merge conflict arbitration").
                content = [w for w in words if len(w) > 3]
                if na and na in corpus:
                    derived.append((skill, alias, raw_q))
                elif len(content) >= 2 and all(w in corpus for w in content):
                    derived.append((skill, alias, raw_q))
                else:
                    overfit.append((skill, alias, raw_q))
                break

    print(f"aliases checked : {sum(len(c.get('aliases', [])) for c in aliases.values())}")
    print(f"eval queries    : {len(cases)}")
    if skipped:
        skills = sorted({s for s, _ in skipped})
        print(f"not indexed     : {len(skipped)} aliases on {', '.join(skills)} "
              f"(sidelined; cannot echo an answer key)")
    print(f"\nDERIVED from the skill's own docs (legitimate): {len(derived)}")
    for skill, alias, q in derived:
        print(f"  ✅ {skill:<22} {alias!r}")
    print(f"\nQUERY ECHOES (overfitting — the answer key): {len(overfit)}")
    for skill, alias, q in overfit:
        print(f"  ⚠️  {skill:<22} alias={alias!r}")
        print(f"      echo of: {q!r}")
    print()
    return 0 if not overfit else 1


if __name__ == "__main__":
    sys.exit(main())
