#!/usr/bin/env python3
"""SDP_ROUTER adapter: route holdout prompts with the real skills catalog.

Protocol (blind holdout contract)::

    python3 tests/sdp_router_adapter.py --mode full|brief|l05 --cases PATH
    -> {"mode": ..., "predictions":[{"id":..., "pred_skill":...}],
        "bytes": N, "tokens": N, "turns": N}

``full`` exposes each skill's name, domain, full description, aliases and tags
to the (deterministic, inference-free) scorer. ``brief`` and ``l05`` expose
only the compact card the real ``lsSkills({brief:true})`` window returns:
``{name, domain, trigger}``. The reported ``bytes`` is the serialized size of
that discovery payload, so brief is measurably smaller than full. A single
discovery turn serves every case; there is no per-batch judging.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from catalog import registry  # noqa: E402

MODES = ("full", "brief", "l05")
NONE_LABEL = "__NONE__"
TRIGGER_MAX = 120

STOPWORDS = frozenset("""
    a an the and or but if then than to of in on at by for with from into about
    i me my we you your it its this that these those is are was were be been
    being do does did doing have has had having can could would should will
    shall may might must not no nor as so too very just also please help want
    need needs get got make makes use using used via per out up down over under
    some any all one two more most other another each own same
""".split())
SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)")
WHEN_RE = re.compile(r"\buse (?:this skill )?when\b", re.IGNORECASE)
WHEN_USER_RE = re.compile(r"\bwhen the user\b", re.IGNORECASE)


def derive_trigger(description: str) -> str:
    """One-line, <=120-char summary: first when-to-use sentence, else first."""
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


def load_aliases() -> dict[str, dict[str, list[str]]]:
    path = ROOT / "catalog" / "aliases.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def build_catalog(mode: str) -> tuple[list[dict[str, Any]], int]:
    """Return (records, payload_bytes) for the requested discovery mode."""
    skills = registry.load_all_skills(include_sidelined=False)
    aliases = load_aliases()
    records: list[dict[str, Any]] = []
    for name in sorted(skills):
        spec = skills[name]
        domain = domain_of(spec)
        description = spec.get("description") or ""
        if mode == "full":
            extra = aliases.get(name, {})
            text = " ".join([
                name, domain, description,
                " ".join(extra.get("aliases", [])),
                " ".join(extra.get("tags", [])),
            ])
            records.append({"name": name, "domain": domain,
                            "description": description, "text": text})
        else:
            trigger = derive_trigger(description)
            records.append({"name": name, "domain": domain,
                            "trigger": trigger, "text": " ".join([name, domain, trigger])})
    payload_bytes = len(json.dumps(records, ensure_ascii=False).encode("utf-8"))
    return records, payload_bytes


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


def make_idf(records: list[dict[str, Any]]) -> dict[str, float]:
    import math
    n = len(records) or 1
    df: dict[str, int] = {}
    for rec in records:
        for tok in set(tokenize(rec["text"])):
            df[tok] = df.get(tok, 0) + 1
    return {tok: math.log((n + 1) / (cnt + 1)) + 1.0 for tok, cnt in df.items()}


def score(prompt: str, rec: dict[str, Any], idf: dict[str, float]) -> float:
    q_tokens = tokenize(prompt)
    if not q_tokens:
        return 0.0
    d_tokens = tokenize(rec["text"])
    if not d_tokens:
        return 0.0
    d_set = set(d_tokens)
    matched = sum(idf.get(tok, 1.0) for tok in set(q_tokens) if tok in d_set)
    # Normalize by prompt size and by a mild doc-size penalty so a sprawling
    # description cannot win by mere length.
    return matched / (len(set(q_tokens)) * (1.0 + 0.02 * len(d_tokens)))


def route(cases: list[dict[str, Any]], records: list[dict[str, Any]],
          threshold: float = 0.06) -> list[dict[str, str]]:
    idf = make_idf(records)
    predictions = []
    for case in cases:
        cid = str(case.get("id", ""))
        prompt = case.get("prompt", "")
        best_name = NONE_LABEL
        best_score = threshold
        for rec in records:
            s = score(prompt, rec, idf)
            if s > best_score:
                best_score = s
                best_name = rec["name"]
        predictions.append({"id": cid, "pred_skill": best_name})
    return predictions


def resolve_cases(path: str) -> Path:
    """Resolve a cases path, falling back to the canonical checkout.

    Worktrees carry the adapter source but not the untracked ``.kem-loop``
    holdout fixtures, so a relative path from an isolated worktree may miss.
    The canonical skills tree is the single source of truth for those fixtures.
    """
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    canonical = registry.REPO_ROOT / ".kem-loop" / "skill-discovery-plumbing" / "holdouts" / "cases.json"
    try:
        from catalog import exec_runner
        root = exec_runner._canonical_skills_root()
        if root is not None:
            canonical = root / ".kem-loop" / "skill-discovery-plumbing" / "holdouts" / "cases.json"
    except (ImportError, AttributeError):
        pass
    if canonical.is_file():
        return canonical
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SDP_ROUTER adapter")
    parser.add_argument("--mode", default="brief", choices=MODES)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--threshold", type=float, default=0.06)
    args = parser.parse_args(argv)

    try:
        payload = json.loads(resolve_cases(args.cases).read_text(encoding="utf-8"))
        cases = payload.get("cases", []) if isinstance(payload, dict) else payload
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": "BAD_CASES", "detail": str(exc)}))
        return 2

    records, payload_bytes = build_catalog(args.mode)
    predictions = route(cases, records, args.threshold)
    result = {
        "mode": args.mode,
        "predictions": predictions,
        "bytes": payload_bytes,
        "tokens": round(payload_bytes / 4),
        "turns": 1,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
