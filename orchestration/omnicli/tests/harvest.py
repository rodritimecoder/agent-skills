#!/usr/bin/env python3
"""Harvest a fresh held-out routing set from this machine's session log.

The ``paraphrase`` set is the honest referee for description work, and it stops
being honest the moment a description was tuned against it. This tool builds its
successor from prompts the operator actually typed, labelled by what the session
actually reached for — so the next round of rewrites is judged on prompts no
description has seen.

Labelling rule: within the assistant turns that follow the prompt, collect every
skill name that appears in a shell command or Code Mode plan, and keep the case
only when **exactly one** skill was named. Two skills in one turn means the label
is a guess, and a guessed label is worse than no case. Prompts that overlap an
existing eval case (token Jaccard above the threshold) are dropped, so the set
cannot inherit the answer key it is meant to check.

Usage:
    python3 tests/harvest.py                        # last 60 days, write the set
    python3 tests/harvest.py --days=120 --min=8
    python3 tests/harvest.py --dry-run              # report, write nothing
    python3 tests/harvest.py --out=tests/fresh_eval.json

Exit codes: 0 wrote or reported, 1 fatal.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
sys.path.insert(0, str(SKILL_ROOT))

from catalog import registry, search  # noqa: E402

DEFAULT_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
OUT = HERE / "fresh_eval.json"

MIN_CHARS = 15
MAX_CHARS = 320
WINDOW = 12          # assistant messages examined after the prompt
JACCARD_MAX = 0.6    # overlap with an existing case

# A prompt that is only an acknowledgement teaches nothing about routing.
ACK_RE = re.compile(
    r"^(?:yes|yeah|yep|no|nope|ok|okay|sure|thanks|ty|go|continue|carry on|do it|"
    r"proceed|next|keep going|nice|cool|perfect|lgtm|sounds good|yeah sure)[.!? ]*$",
    re.IGNORECASE,
)
# A reply that leans on the previous turn is not a routing query: nobody can
# route "yeah strip those references" without the transcript. The set is meant
# to measure what a description can do, so these are dropped rather than
# counted as permanent failures.
CONTINUATION_RE = re.compile(
    r"^(?:and|but|so|then|also|now|yeah|yep|nope|wait|hmm|idk|why|how about|"
    r"what about|ok|okay|sure|next|thoughts)\b",
    re.IGNORECASE,
)
SLASH_RE = re.compile(r"^/\S")
FENCE_RE = re.compile(r"```")
# Prompts written *to* an agent about its own tools ("use the read tool on
# SKILL.md and report exactly what each call returned") are harness probes, not
# operator intents, and they label the gateway rather than a skill.
HARNESS_RE = re.compile(
    r"\b(?:use the (?:read|write|edit|shell|execute) tool|call the \w+ tool|"
    r"report exactly|report what each|using the \w+ tool)\b",
    re.IGNORECASE,
)

# A prompt earns its place when it carries at least one *distinctive* term the
# labelled skill actually documents — a word that few other skills use. That is
# the whole substance of routing: "port 8083", "zoom", "cornell". A prompt with
# no such term is a continuation wearing a question mark.
DF_MAX = 6


def doc_tokens(spec: dict) -> set[str]:
    text = [spec.get("description") or ""]
    md = spec.get("md_path")
    if md:
        try:
            text.append(Path(md).read_text(encoding="utf-8", errors="replace")[:4000])
        except OSError:
            pass
    return token_set(" ".join(text))


def token_set(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9][a-z0-9+._/-]*", text.lower()) if len(t) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def skill_patterns() -> dict[str, re.Pattern]:
    """Match a skill where a session would *reach* for it: in command position.

    Two guards, both learned from a noisy first pass. Virtual umbrella skills
    (``local``) are skipped: their name is an English word that appears in every
    ``~/.local/bin`` path, and they have no document to route to. And a name only
    counts when it starts a command — after whitespace, a pipe, ``;``, ``&&``, a
    slash, or at the start of the text — because ``memory`` inside "memory cap"
    is prose, while ``memory search`` is an invocation. Hyphens and spaces are
    interchangeable, since people type "zoom recorder".
    """
    patterns: dict[str, re.Pattern] = {}
    for name, spec in registry.load_all_skills().items():
        if spec.get("status") != "active" or not spec.get("md_path"):
            continue
        forms = {name, name.replace("-", " ")}
        shim = spec.get("cli") or ""
        if shim:
            forms.add(Path(shim).name)
        body = "|".join(re.escape(f).replace(r"\ ", r"[\s-]") for f in sorted(forms))
        patterns[name] = re.compile(
            rf"(?:^|[\s/|;&(`\[])(?:{body})(?=\s|$|/|[\"'`])", re.IGNORECASE
        )
    return patterns


def tool_text(msg_type: str, data: dict) -> str:
    """The text a tool call carries, for skill-name matching."""
    out: list[str] = []
    for part in data.get("content") or []:
        if part.get("type") != "tool":
            continue
        state = part.get("state") or {}
        inp = state.get("input") or {}
        for value in inp.values():
            if isinstance(value, str):
                out.append(value)
        if isinstance(part.get("name"), str):
            out.append(part["name"])
    return "\n".join(out)


def main(argv: list[str]) -> int:
    days = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--days=")), "60"))
    min_cases = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--min=")), "8"))
    out_path = Path(next((a.split("=", 1)[1] for a in argv if a.startswith("--out=")), str(OUT)))
    dry = "--dry-run" in argv
    db = Path(os.environ.get("OPENCODE_DB", DEFAULT_DB))
    if not db.is_file():
        print(f"fatal: session db not found: {db}", file=sys.stderr)
        return 1

    cutoff = int((time.time() - days * 86400) * 1000)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sessions = con.execute(
        "SELECT DISTINCT session_id FROM session_message WHERE time_created >= ?", (cutoff,)
    ).fetchall()

    patterns = skill_patterns()
    docs = {n: doc_tokens(s) for n, s in registry.load_all_skills().items()
            if s.get("status") == "active"}
    df: dict[str, int] = {}
    for toks in docs.values():
        for t in toks:
            df[t] = df.get(t, 0) + 1
    existing = []
    for name in ("golden", "paraphrase"):
        p = HERE / f"{name}_eval.json"
        if p.is_file():
            existing += [token_set(c["query"])
                         for c in json.loads(p.read_text(encoding="utf-8")).get("cases", [])]

    cases: list[dict] = []
    rejected = {"ack": 0, "continuation": 0, "shape": 0, "ambiguous": 0,
                "unlabelled": 0, "no-distinctive-term": 0, "duplicate": 0}
    for row in sessions:
        msgs = con.execute(
            "SELECT type, data FROM session_message WHERE session_id = ? ORDER BY seq",
            (row["session_id"],),
        ).fetchall()
        for idx, m in enumerate(msgs):
            if m["type"] != "user":
                continue
            try:
                data = json.loads(m["data"])
            except json.JSONDecodeError:
                continue
            text = (data.get("text") or "").strip()
            if not text:
                continue
            if ACK_RE.match(text):
                rejected["ack"] += 1
                continue
            if CONTINUATION_RE.match(text):
                rejected["continuation"] += 1
                continue
            if (not MIN_CHARS <= len(text) <= MAX_CHARS or SLASH_RE.match(text)
                    or FENCE_RE.search(text) or "\n" in text or HARNESS_RE.search(text)):
                rejected["shape"] += 1
                continue

            hits: set[str] = set()
            for nxt in msgs[idx + 1: idx + 1 + WINDOW]:
                if nxt["type"] != "assistant":
                    continue
                try:
                    body = json.loads(nxt["data"])
                except json.JSONDecodeError:
                    continue
                window_text = tool_text(nxt["type"], body)
                if not window_text:
                    continue
                for name, pat in patterns.items():
                    if pat.search(window_text):
                        hits.add(name)
            if not hits:
                rejected["unlabelled"] += 1
                continue
            if len(hits) > 1:
                rejected["ambiguous"] += 1
                continue
            skill = next(iter(hits))

            toks = token_set(text)
            distinctive = {
                t for t in toks
                if len(t) >= 4 and t not in search.STOPWORDS
                and df.get(t, 0) <= DF_MAX and t in docs.get(skill, set())
            }
            if not distinctive:
                rejected["no-distinctive-term"] += 1
                continue
            if any(jaccard(toks, prev) >= JACCARD_MAX for prev in existing):
                rejected["duplicate"] += 1
                continue

            cases.append({"query": text, "top1": skill, "expect": [skill],
                          "kind": "harvested-fresh",
                          "evidence": sorted(distinctive)[:4]})

    # One case per (skill, query); identical prompts teach the same lesson twice.
    seen: set[tuple[str, str]] = set()
    unique = []
    for c in cases:
        key = (c["top1"], c["query"].lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)

    per_skill: dict[str, int] = {}
    for c in unique:
        per_skill[c["top1"]] = per_skill.get(c["top1"], 0) + 1

    print(f"fresh harvest  {days}d  {len(sessions)} sessions  ->  {len(unique)} cases")
    print(f"  rejected: {rejected}")
    print(f"  skills covered: {len(per_skill)}")
    for name, n in sorted(per_skill.items(), key=lambda kv: -kv[1])[:15]:
        print(f"    {n:>3}  {name}")

    if dry:
        return 0
    if len(unique) < min_cases:
        print(f"fatal: only {len(unique)} cases, need {min_cases} "
              f"(widen --days or lower --min)", file=sys.stderr)
        return 1

    payload = {"name": "fresh", "banked_at": time.strftime("%Y-%m-%d"), "cases": unique}
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}  ({len(unique)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
