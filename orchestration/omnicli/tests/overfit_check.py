"""Detect alias overfitting against each skill's own documentation.

A multiword alias that cannot be derived from the skill's own description or
SKILL.md body is a query echo: it was copied from a distinctive user query
into the alias set instead of being drawn from the vocabulary the skill
actually documents. This is a HARD pre-push gate leg — it must be able to
fail, and it does not depend on any evaluation set.

Usage:
    python3 tests/overfit_check.py
    OMNICLI_ALIASES_FILE=/tmp/aliases.json python3 tests/overfit_check.py

Exit codes:
    0  no non-derivable multiword aliases (clean)
    1  at least one non-derivable multiword alias (QUERY ECHO / overfitting)
    2  fatal: aliases unreadable, invalid, or skill discovery failed
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from catalog import registry  # noqa: E402

ALIASES = HERE.parent / "catalog" / "aliases.json"
ALIASES_ENV = "OMNICLI_ALIASES_FILE"


def aliases_path() -> Path:
    """The overrides exist for tests; they never skip or loosen the check."""
    override = os.environ.get(ALIASES_ENV)
    return Path(override) if override else ALIASES


def normalise(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").split())


def skill_corpus(skill: str, skills: dict) -> str:
    """The skill's own documentation — description + SKILL.md body, lowercased."""
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


def is_derivable(alias: str, corpus: str) -> bool:
    """True when the alias can be built from the skill's own documentation.

    Either the whole phrase appears verbatim, or every content word (length
    > 3) appears in the docs — the vocabulary may be non-contiguous, e.g.
    "merge conflicts" ~ "automated merge conflict arbitration".
    """
    na = normalise(alias)
    if na and na in corpus:
        return True
    content = [w for w in na.split() if len(w) > 3]
    return len(content) >= 2 and all(w in corpus for w in content)


def main() -> int:
    try:
        aliases = json.loads(aliases_path().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"overfit_check: cannot load aliases: {exc}", file=sys.stderr)
        return 2

    try:
        skills = registry.load_all_skills()
    except Exception as exc:
        print(f"overfit_check: cannot load skills: {exc}", file=sys.stderr)
        return 2

    # Only indexed skills can put an alias into the index. An archived skill's
    # aliases never reach it, so counting them as overfitting is a false
    # positive that hides the real ones.
    indexed = set(skills)
    corpora: dict[str, str] = {}

    derived = []   # multiword alias whose words come from the skill's own docs
    overfit = []   # multiword alias NOT derivable from the skill's own docs
    skipped = []   # aliases belonging to a skill the catalog does not index

    for skill, cfg in aliases.items():
        if skill not in indexed:
            skipped.extend((skill, a) for a in cfg.get("aliases", []))
            continue
        if skill not in corpora:
            corpora[skill] = skill_corpus(skill, skills)
        corpus = corpora[skill]
        for alias in cfg.get("aliases", []):
            words = normalise(alias).split()
            if len(words) < 2:
                # A single domain word ("audio", "canvas", "transcribe") is
                # the skill's own vocabulary, not an answer key. Only
                # multiword phrases can smuggle a distinctive fragment in.
                continue
            if is_derivable(alias, corpus):
                derived.append((skill, alias))
            else:
                overfit.append((skill, alias))

    print(f"aliases checked : {sum(len(c.get('aliases', [])) for c in aliases.values())}")
    if skipped:
        skill_names = sorted({s for s, _ in skipped})
        print(f"not indexed     : {len(skipped)} aliases on {', '.join(skill_names)} "
              f"(sidelined; cannot reach the index)")
    print(f"\nDERIVED from the skill's own docs (legitimate): {len(derived)}")
    for skill, alias in derived:
        print(f"  OK {skill:<22} {alias!r}")
    print(f"\nQUERY ECHOES (non-derivable multiword aliases): {len(overfit)}")
    for skill, alias in overfit:
        print(f"  !! {skill:<22} {alias!r}")
    print()
    return 1 if overfit else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fatal: do not claim a verdict we cannot measure
        print(f"overfit_check: internal error: {exc}", file=sys.stderr)
        sys.exit(2)
