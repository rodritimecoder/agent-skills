#!/usr/bin/env python3
"""SDP_EVAL adapter: score a catalog JSON against holdout cases.

Protocol (blind holdout contract)::

    python3 tests/sdp_eval_adapter.py --describe-catalog
    -> {"skills":[{"name","description","domain","trigger"}, ...]}

    python3 tests/sdp_eval_adapter.py --catalog PATH --cases PATH
    -> {"accuracy": 0.0 .. 1.0}

The scorer is a deterministic token-overlap model — no inference, no network.
It is deliberately sensitive to description quality: a jargon-only summary
stops matching the implicit-vocabulary prompts and a colliding summary splits
the vote with its sibling, so accuracy measurably degrades.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from catalog import registry  # noqa: E402

NONE_LABEL = "__NONE__"
TRIGGER_MAX = 120
SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)")
WHEN_RE = re.compile(r"\buse (?:this skill )?when\b", re.IGNORECASE)
WHEN_USER_RE = re.compile(r"\bwhen the user\b", re.IGNORECASE)
STOPWORDS = frozenset("""
    a an the and or but if then than to of in on at by for with from into about
    i me my we you your it its this that these those is are was were be been
    being do does did doing have has had having can could would should will
    shall may might must not no nor as so too very just also please help want
    need needs get got make makes use using used via per out up down over under
    some any all one two more most other another each own same
""".split())


def derive_trigger(description: str) -> str:
    text = " ".join(str(description or "").split())
    if not text:
        return ""
    sentences = SENTENCE_RE.findall(text) or [text]
    line = next((s for s in sentences if WHEN_RE.search(s)),
                next((s for s in sentences if WHEN_USER_RE.search(s)), sentences[0]))
    line = " ".join(line.split())
    if len(line) <= TRIGGER_MAX:
        return line
    cut = line[:TRIGGER_MAX - 1].rstrip()
    last_space = cut.rfind(" ")
    return (cut[:last_space] if last_space > 0 else cut) + "…"


def domain_of(spec: dict[str, Any]) -> str:
    raw = spec.get("path")
    if not raw:
        return "root"
    try:
        rel = Path(raw).resolve().relative_to(registry.resolve_skills_dir().resolve())
        parts = rel.parts
    except (ValueError, OSError):
        return "root"
    return parts[0] if len(parts) > 1 else "root"


def describe_catalog() -> dict[str, Any]:
    skills = registry.load_all_skills(include_sidelined=False)
    entries = []
    for name in sorted(skills):
        spec = skills[name]
        description = spec.get("description") or ""
        entries.append({
            "name": name,
            "description": description,
            "domain": domain_of(spec),
            "trigger": derive_trigger(description),
        })
    return {"skills": entries}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[a-z0-9]+", str(text or "").lower()):
        if raw in STOPWORDS or len(raw) < 3:
            continue
        stem = raw
        for suffix in ("ing", "ed", "es", "s"):
            if len(stem) > len(suffix) + 2 and stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        tokens.append(stem)
    return tokens


def normalize_catalog(value: Any) -> list[dict[str, Any]]:
    """Accept the describe-catalog shape, a bare list, or a name->text map."""
    if isinstance(value, dict):
        if isinstance(value.get("skills"), list):
            value = value["skills"]
        else:
            value = [{"name": k, "description": v if isinstance(v, str) else str(v)}
                     for k, v in value.items()]
    if not isinstance(value, list):
        return []
    entries = []
    for item in value:
        if isinstance(item, str):
            item = {"name": item, "description": item}
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        if not name:
            continue
        description = str(item.get("description") or "")
        trigger = str(item.get("trigger") or "")
        domain = str(item.get("domain") or "")
        text = " ".join([name, domain, trigger, description])
        entries.append({"name": name, "text": text})
    return entries


def score(prompt: str, entry: dict[str, Any], idf: dict[str, float]) -> float:
    q = set(tokenize(prompt))
    if not q:
        return 0.0
    d = set(tokenize(entry["text"]))
    if not d:
        return 0.0
    matched = sum(idf.get(tok, 1.0) for tok in q if tok in d)
    return matched / (len(q) * (1.0 + 0.02 * len(d)))


def evaluate(catalog: list[dict[str, Any]], cases: list[dict[str, Any]],
             threshold: float = 0.06) -> float:
    n = len(catalog) or 1
    df: dict[str, int] = {}
    for entry in catalog:
        for tok in set(tokenize(entry["text"])):
            df[tok] = df.get(tok, 0) + 1
    idf = {tok: math.log((n + 1) / (cnt + 1)) + 1.0 for tok, cnt in df.items()}

    correct = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        expected = NONE_LABEL if case.get("expected_none") else str(case.get("expected_skill", ""))
        prompt = case.get("prompt", "")
        best_name = NONE_LABEL
        best_score = threshold
        for entry in catalog:
            s = score(prompt, entry, idf)
            if s > best_score:
                best_score = s
                best_name = entry["name"]
        if best_name == expected:
            correct += 1
    return correct / len(cases) if cases else 0.0


def resolve_cases(path: Path) -> Path:
    """Resolve a cases path, falling back to the canonical checkout."""
    if path.is_file():
        return path
    canonical = registry.REPO_ROOT / ".kem-loop" / "skill-discovery-plumbing" / "holdouts" / "cases.json"
    try:
        from catalog import exec_runner
        root = exec_runner._canonical_skills_root()
        if root is not None:
            canonical = root / ".kem-loop" / "skill-discovery-plumbing" / "holdouts" / "cases.json"
    except (ImportError, AttributeError):
        pass
    return canonical if canonical.is_file() else path


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(resolve_cases(path).read_text(encoding="utf-8"))
    cases = payload.get("cases", []) if isinstance(payload, dict) else payload
    return cases if isinstance(cases, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SDP_EVAL adapter")
    parser.add_argument("--describe-catalog", action="store_true")
    parser.add_argument("--catalog")
    parser.add_argument("--cases")
    parser.add_argument("--threshold", type=float, default=0.06)
    args = parser.parse_args(argv)

    if args.describe_catalog:
        print(json.dumps(describe_catalog(), ensure_ascii=False))
        return 0
    if not args.catalog or not args.cases:
        print(json.dumps({"error": "CATALOG_AND_CASES_REQUIRED"}))
        return 2
    try:
        catalog_value = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
        cases = load_cases(Path(args.cases))
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": "BAD_INPUT", "detail": str(exc)}))
        return 2
    catalog = normalize_catalog(catalog_value)
    accuracy = evaluate(catalog, cases, args.threshold)
    print(json.dumps({"accuracy": round(accuracy, 6)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
