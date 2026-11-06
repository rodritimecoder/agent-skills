#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

def _find_jev_scripts() -> Optional[Path]:
    """Locate the jev-decision skill's engine, in the repo or a flat harness."""
    here = Path(__file__).resolve()
    roots = [Path("/run/media/rodri/AI/skills"), *here.parents]
    roots += [Path.home() / d for d in (
        ".config/opencode/skills", ".gemini/config/skills", ".pi/agent/skills",
    )]
    for root in roots:
        for cand in (root / "jev-decision" / "scripts", root / "glitch-cat" / "jev-decision" / "scripts"):
            if (cand / "jev_engine.py").is_file():
                return cand
    return None


JEV_SCRIPTS = _find_jev_scripts()
if JEV_SCRIPTS and str(JEV_SCRIPTS) not in sys.path:
    sys.path.append(str(JEV_SCRIPTS))

CONFIG_DIR = Path.home() / ".config" / "eval-router"
WEIGHTS_FILE = CONFIG_DIR / "weights.json"

TIER_CRITERIA = {
    "easy": "Simple formatting, typos, quick syntax lookups, single regex, basic shell commands, trivial edits",
    "moderate": "Standard functions, single-file bugfixes, docstrings, unit tests, script modifications",
    "hard": "Complex multi-file architecture, distributed systems, concurrency, cryptography, deep refactoring, critical security"
}

HEURISTIC_RULES: List[Tuple[re.Pattern, str, float]] = [
    (re.compile(r"\b(typo|fix typo|spelling|readme|format json|indent|lint|rename variable)\b", re.I), "easy", 0.90),
    (re.compile(r"\b(what is|how do i run|curl command|simple script|echo|boilerplate)\b", re.I), "easy", 0.85),
    (re.compile(r"\b(distributed|concurrency|mutex|deadlock|raft|paxos|byzantine|memory leak|kernel|driver)\b", re.I), "hard", 0.95),
    (re.compile(r"\b(architect|refactor entire|redesign|zero-day|exploit|cryptograph|formal verification)\b", re.I), "hard", 0.92),
    (re.compile(r"\b(unit test|add test|write function|parse|scrape|endpoint|handler|query|regex)\b", re.I), "moderate", 0.75),
]

def _heuristic_classify(prompt: str) -> Dict[str, Any]:
    for pattern, tier, conf in HEURISTIC_RULES:
        if pattern.search(prompt):
            p = {"easy": 0.05, "moderate": 0.05, "hard": 0.05}
            p[tier] = conf
            rem = (1.0 - conf) / 2.0
            for k in p:
                if k != tier:
                    p[k] = rem
            return {
                "tier": tier,
                "confidence": round(conf, 4),
                "probabilities": {k: round(v, 4) for k, v in p.items()},
                "source": "heuristic",
                "reasoning": f"Matched heuristic rule for '{tier}'"
            }

    word_count = len(prompt.split())
    if word_count < 10:
        return {
            "tier": "easy",
            "confidence": 0.65,
            "probabilities": {"easy": 0.70, "moderate": 0.20, "hard": 0.10},
            "source": "heuristic",
            "reasoning": "Short prompt heuristic (<10 words)"
        }
    elif word_count > 120:
        return {
            "tier": "hard",
            "confidence": 0.70,
            "probabilities": {"easy": 0.05, "moderate": 0.25, "hard": 0.70},
            "source": "heuristic",
            "reasoning": "Extensive complex prompt heuristic (>120 words)"
        }

    return {
        "tier": "moderate",
        "confidence": 0.50,
        "probabilities": {"easy": 0.25, "moderate": 0.55, "hard": 0.20},
        "source": "heuristic",
        "reasoning": "Default moderate complexity baseline"
    }

def _learned_classify(prompt: str, weights: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tokens = re.findall(r"\b[a-zA-Z0-9_\-\.]{2,}\b", prompt.lower())
    if not tokens:
        return None

    scores = {"easy": 0.0, "moderate": 0.0, "hard": 0.0}
    feat_weights = weights.get("features", {})
    biases = weights.get("biases", {"easy": 0.0, "moderate": 0.0, "hard": 0.0})

    for k in scores:
        scores[k] = biases.get(k, 0.0)

    matched = 0
    for t in tokens:
        if t in feat_weights:
            matched += 1
            for k in scores:
                scores[k] += feat_weights[t].get(k, 0.0)

    if matched == 0:
        return None

    max_val = max(scores.values())
    exp_scores = {k: math.exp(v - max_val) for k, v in scores.items()}
    total = sum(exp_scores.values())
    probs = {k: v / total for k, v in exp_scores.items()}

    best_tier = max(probs, key=lambda k: probs[k])
    p_max = probs[best_tier]
    h = -sum(p * math.log2(p) for p in probs.values() if p > 0)
    conf = max(0.0, 1.0 - (h / math.log2(3)))

    return {
        "tier": best_tier,
        "confidence": round(conf, 4),
        "probabilities": {k: round(v, 4) for k, v in probs.items()},
        "source": "learned_weights",
        "reasoning": f"Pure-Python TF-IDF model matched {matched} features"
    }

def classify(prompt: str, port: int = 8083, min_conf: float = 0.45) -> Dict[str, Any]:
    if WEIGHTS_FILE.is_file():
        try:
            with open(WEIGHTS_FILE) as f:
                w = json.load(f)
            learned = _learned_classify(prompt, w)
            if learned and learned["confidence"] >= min_conf:
                return learned
        except Exception:
            pass

    try:
        from jev_engine import JevEngine  # type: ignore
        question = (
            "Which task complexity tier does this engineering/coding request belong to? "
            + " ".join(f"{tier}: {desc}." for tier, desc in TIER_CRITERIA.items())
        )
        res = JevEngine(port=port, timeout=3.0).decide_choice(
            prompt, question, list(TIER_CRITERIA.keys())
        )
        tier = res["selection"]
        conf = float(res.get("confidence", 0.0))
        probs = res.get("probabilities", {})

        if conf < min_conf:
            h_res = _heuristic_classify(prompt)
            if h_res["confidence"] > conf:
                return h_res

        return {
            "tier": tier,
            "confidence": round(conf, 4),
            "probabilities": {k: round(float(v), 4) for k, v in probs.items()},
            "source": res.get("source", "h2o_lightning_4b_systemone"),
            "reasoning": f"Calibrated Jev decision (confidence {conf:.2f})"
        }
    except Exception as e:
        res = _heuristic_classify(prompt)
        res["reasoning"] += f" (h2o-lightning-4b unavailable: {e})"
        return res
