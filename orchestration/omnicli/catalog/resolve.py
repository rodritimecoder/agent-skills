"""Turn an intent into one runnable tool, in process.

`omnicli search` answers *which skill*. `omnicli describe` answers *what are
its inputs*. `omnicli invoke` runs it. Three commands, two context reads — and
the session log shows agents choosing `grep -r` in 85 sessions against 26 for
`omnicli search`, because one hop beats three.

This module performs hops two and three so `omnicli do` can perform all three
in one command. It also moves the two places where a wrong answer is worse
than no answer out of judgement and into code:

* **Skill ambiguity** — if the runner-up scores within ``margin`` of the
  winner, the intent is refused with both candidates named. Measured on 99
  real prompts, margin 1.3 buys 90% precision at 80% coverage.
* **Argument arity** — the contract's required positionals and required flags
  are checked against what was supplied. Missing means a printed contract
  stub and a non-zero exit, never a half-run command.

Everything between those gates is deterministic ranking: BM25+dense over
skills (the tuned default), IDF-weighted token coverage over the chosen
skill's own tools, then descent through sub-commands until a leaf is reached.

A wrong execution costs more than an extra hop, so every refusal here is
cheaper than the thing it prevents.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from typing import Any

from . import argspec, search

# Skills whose runner-up is this close to the winner are refused rather than
# guessed. See SKILL.md: measured coverage/precision on the paraphrase set.
DEFAULT_MARGIN = float(os.environ.get("OMNICLI_DO_MARGIN", "1.3"))

# Sub-command nesting is at most two deep in this catalog; four is a guard
# against a contract cycle, not a design parameter.
MAX_DESCENT = 4

ROOT_KINDS = ("script", "cli", "endpoint")


def margin() -> float:
    return DEFAULT_MARGIN


# --------------------------------------------------------------------------
# contracts
# --------------------------------------------------------------------------

def contract_of(row: Any) -> dict[str, Any]:
    raw = row["contract"]
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def usage_of(contract: dict[str, Any]) -> str:
    return " ".join(str(contract.get("usage") or "").split())


def real_subcommands(contract: dict[str, Any]) -> list[dict[str, str]]:
    """Sub-commands proper, with positionals filtered out.

    The builder writes argparse positionals into the same ``subcommands``
    array as actual sub-parsers, distinguished only by a ``_pos`` suffix on
    the former and by appearing in ``positionals`` on the latter's siblings.
    Mixing them would make ``academic-icm scaffold`` look like a command with
    a sub-command called ``source_md``.
    """
    positional = {str(p) for p in contract.get("positionals") or []}
    out: list[dict[str, str]] = []
    for entry in contract.get("subcommands") or []:
        name = str((entry or {}).get("name") or "")
        if not name or name in positional or name.endswith("_pos"):
            continue
        out.append({"name": name, "summary": str(entry.get("summary") or "")})
    return out


def depth0_choices(usage: str) -> list[str]:
    """Command names in an unbracketed ``{a,b,c}`` — i.e. a *required* choice.

    ``[--format {json,table}]`` is an option's value set and sits inside
    brackets, so the depth check is what keeps it from being mistaken for a
    sub-command.
    """
    found: list[str] = []
    depth = 0
    i = 0
    while i < len(usage):
        ch = usage[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif ch == "{" and depth == 0:
            j = usage.find("}", i)
            if j < 0:
                break
            found += [x.strip() for x in re.split(r"[|,]", usage[i + 1:j]) if x.strip()]
            i = j
        i += 1
    return found


def required_positionals(contract: dict[str, Any]) -> list[str]:
    """Positionals the usage line does not bracket — the ones you must pass."""
    usage = usage_of(contract)
    out = []
    for name in contract.get("positionals") or []:
        name = str(name)
        if re.search(rf"\[\s*<?{re.escape(name)}", usage):
            continue
        out.append(name)
    return out


def required_flags(contract: dict[str, Any]) -> list[str]:
    """Flags at bracket-depth zero in the usage line — argparse's required set."""
    return sorted(argspec._required_flags(usage_of(contract)))


def needs_descent(row: Any, contract: dict[str, Any], children: dict[str, list]) -> bool:
    if row["kind"] == "subcommand":
        return False
    if children.get(row["id"]):
        return True
    if depth0_choices(usage_of(contract)):
        return True
    return bool(real_subcommands(contract))


# --------------------------------------------------------------------------
# text + scoring
# --------------------------------------------------------------------------

def entry_text(row: Any, contract: dict[str, Any]) -> str:
    parts = [str(row["summary"] or ""), usage_of(contract)]
    for sub in real_subcommands(contract):
        parts.append(sub["name"])
        parts.append(sub["summary"])
    for flag in contract.get("flags") or []:
        if isinstance(flag, str):
            parts.append(flag)
    leaf = str(row["id"]).split("/")[-1].split(":")[-1]
    parts.append(leaf.replace("_", " "))
    return " ".join(p for p in parts if p)


def _suffix_variants(token: str) -> set[str]:
    """Fold the English inflections that made `grade` miss `grades`.

    The catalog's tokenizer is deliberately stemless — FTS5 and the tuned
    search ranking are both measured against it, so changing it would move a
    baseline that is not part of this experiment. Tier-2 has no such
    dependency: it matches an intent against ~10 entries inside one skill, and
    there exact matching lost the sub-command on several golden cases
    (`grade` vs `grades`, `announcement` vs `announcements`,
    `recorded` vs `recording`).

    Every applicable ending is added, not just the first: `grades` must yield
    both `grad` (drop `es`) *and* `grade` (drop `s`), because only the second
    one is what `grade` looks like. Taking a single strip silently missed.

    Conservative on purpose: only the endings below, only when at least three
    characters survive, and the same function runs on both sides of every
    comparison, so a fold can never create a match the raw tokens did not
    already support in the same direction.
    """
    out: set[str] = {token}
    if len(token) <= 3:
        return out
    for ending, repl in (("ations", "ate"), ("ing", ""), ("ed", ""),
                         ("ies", "y"), ("es", ""), ("s", "")):
        if token.endswith(ending) and len(token) - len(ending) >= 3:
            out.add(token[:-len(ending)] + repl)
    return out


def _tokenize(text: str) -> set[str]:
    out: set[str] = set()
    for token in search.tokenize(text):
        out |= _suffix_variants(token)
    return out


def _idf(texts: list[str]) -> dict[str, float]:
    n = len(texts) or 1
    df: dict[str, int] = {}
    for text in texts:
        for token in _tokenize(text):
            df[token] = df.get(token, 0) + 1
    return {t: math.log((n + 1) / (d + 1)) + 1.0 for t, d in df.items()}


def _score(tokens: list[str], text: str, idf: dict[str, float]) -> float:
    """Coverage of the intent by the entry's text, weighted by rarity.

    Normalising by the whole intent (not just the matched part) is what stops
    a one-word coincidence from beating an entry that explains the request.
    Unmatched tokens still cost you, which is why a generic skill description
    cannot outscore a sub-command that names the actual verb.
    """
    if not tokens:
        return 0.0
    present = _tokenize(text)
    matched = [t for t in tokens if t in present]
    if not matched:
        return 0.0
    denom = sum(idf.get(t, 1.0) for t in tokens)
    return sum(idf.get(t, 1.0) for t in matched) / denom


# --------------------------------------------------------------------------
# refusal payloads
# --------------------------------------------------------------------------

def _stub(row: Any, contract: dict[str, Any], missing: list[str]) -> str:
    usage = usage_of(contract) or "(no usage recorded)"
    lines = [
        f"❌ omnicli do: {row['id']} needs arguments.",
        f"   usage    : {usage}",
        f"   missing  : {', '.join(missing)}",
        f"   supply   : omnicli do \"<intent>\" -- {' '.join('<' + m + '>' for m in missing)}",
        f"   contract : omnicli describe {row['id']}",
    ]
    return "\n".join(lines)


def _ambiguous(level: str, candidates: list[tuple[str, float]],
               extra: str = "") -> dict[str, Any]:
    """A structured refusal, not a formatted string.

    Returning pre-rendered text here meant the caller printed its own header
    around a message that already had one, so a tier-2 refusal came out as
    ``ambiguous (tool) — refusing to guess`` followed by a second
    ``❌ omnicli do: ambiguous sub-command — refusing to guess``. The level and
    the candidate list belong to the caller, which owns the format.
    """
    return {
        "level": level,
        "reason": extra or f"ambiguous {level}",
        "candidates": [{"name": name, "score": round(score, 3)}
                       for name, score in candidates],
    }


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------

def _load(con: sqlite3.Connection, skill: str) -> tuple[list[Any], dict[str, list]]:
    rows = con.execute(
        "SELECT id, skill, kind, parent, summary, contract, argv, enabled FROM tools "
        "WHERE skill = ? AND enabled = 1 AND kind IN "
        "('script', 'cli', 'endpoint', 'subcommand') ORDER BY id",
        (skill,),
    ).fetchall()
    children: dict[str, list] = {}
    for row in rows:
        if row["parent"]:
            children.setdefault(row["parent"], []).append(row)
    return rows, children


def _rank(entries: list[dict[str, Any]], tokens: list[str],
          idf: dict[str, float]) -> list[tuple[dict[str, Any], float]]:
    scored = [(e, _score(tokens, e["text"], idf)) for e in entries]
    scored.sort(key=lambda pair: (-pair[1], pair[0]["id"]))
    return scored


def _pseudo_children(row: Any, contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Sub-commands the contract names but the catalog has no row for."""
    argv = _argv_of(row)
    out = []
    for sub in real_subcommands(contract):
        cid = f"{row['id']}:{sub['name']}"
        out.append({
            "id": cid,
            "kind": "pseudo",
            "parent": row["id"],
            "summary": sub["summary"],
            "contract": {},
            "argv": [str(a) for a in argv] + [sub["name"]],
            "text": f"{sub['name']} {sub['summary']}",
        })
    return out


def _argv_of(row: Any) -> list[str]:
    """argv as a list, whether the row came from SQLite or from an entry dict.

    ``_load`` hands back database rows where ``argv`` is still JSON text;
    ``_rank``/``_pseudo_children`` hand back dicts where it has already been
    parsed. Reading one with the other's accessor raises on perfectly good
    input, so the coercion lives here instead of at each call site.
    """
    raw = row["argv"] if not isinstance(row, dict) else row.get("argv")
    if isinstance(raw, list):
        return [str(a) for a in raw]
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(a) for a in parsed] if isinstance(parsed, list) else []


def _real_row_for(con: sqlite3.Connection, skill: str, pseudo_id: str) -> Any:
    """The real catalog row a pseudo child stands in for.

    45 of 51 skills expose two entry points for the same commands — a ``cli``
    wrapper and the script itself — and only one of them carries child rows.
    Descending through the other produced a pseudo child with an empty
    contract, which ``check_args`` then read as "requires nothing": 247 of 255
    such descents would have skipped the arity gate entirely.

    Matched by leaf name within the skill, because the ids differ only by
    which root they hang off (``ocr/cli:read`` vs ``ocr/ocr:read``).
    """
    exact = con.execute(
        "SELECT * FROM tools WHERE id = ? AND enabled = 1", (pseudo_id,)).fetchone()
    if exact is not None:
        return exact
    leaf = pseudo_id.rsplit(":", 1)[-1]
    rows = con.execute(
        "SELECT * FROM tools WHERE skill = ? AND enabled = 1 "
        "AND kind = 'subcommand' AND id LIKE ?",
        (skill, f"%:{leaf}"),
    ).fetchall()
    for row in rows:
        if str(row["id"]).rsplit(":", 1)[-1] == leaf:
            return row
    return None


def _descend(con: sqlite3.Connection, row: Any, contract: dict[str, Any],
             children: dict[str, list], tokens: list[str],
             idf: dict[str, float]
             ) -> tuple[Any, dict[str, Any], list[str], dict[str, Any] | None]:
    """Walk down to a leaf. Returns (row, contract, argv, refusal).

    ``refusal`` is None when a leaf was reached, otherwise the structured
    refusal from ``_ambiguous`` — never a pre-formatted message.
    """
    path: list[str] = []
    for _ in range(MAX_DESCENT):
        if not needs_descent(row, contract, children):
            return row, contract, _argv_of(row), None

        kids = children.get(row["id"])
        if kids:
            entries = [{
                "id": k["id"], "kind": k["kind"], "summary": k["summary"],
                "contract": contract_of(k),
                "argv": _argv_of(k),
                "text": entry_text(k, contract_of(k)),
            } for k in kids]
        else:
            entries = _pseudo_children(row, contract)

        if not entries:
            # A required choice the contract never spelled out: refuse with the
            # usage line, which is the only thing that can name it.
            return row, contract, _argv_of(row), _ambiguous(
                "sub-command",
                [(row["id"], 0.0)],
                f"usage: {usage_of(contract)}",
            )

        ranked = _rank(entries, tokens, idf)
        best, best_score = ranked[0]
        if len(ranked) > 1 and best_score <= 0.0:
            return row, contract, _argv_of(row), _ambiguous(
                "sub-command",
                [(e["id"], s) for e, s in ranked[:4]],
                "no candidate shares a term with the intent",
            )

        path.append(best["id"])
        if best["kind"] == "pseudo":
            real = _real_row_for(con, row["skill"], best["id"])
            if real is None:
                return best, best["contract"], best["argv"], None
            row, contract = real, contract_of(real)
        else:
            row, contract = best, best["contract"]

    return row, contract, _argv_of(row), _ambiguous(
        "sub-command", [(row["id"], 0.0)], "descent did not terminate")


# --------------------------------------------------------------------------
# argument arity
# --------------------------------------------------------------------------

def _flag_kinds(contract: dict[str, Any]) -> tuple[set[str], set[str]]:
    """(value-taking flags, boolean flags) recovered from the help text."""
    value: set[str] = set()
    boolean: set[str] = set()
    try:
        params = argspec.parse_flags(contract)
    except Exception:  # a malformed help block must not break resolution
        params = []
    for p in params:
        if not p.flag:
            continue
        (boolean if p.kind == "bool" else value).add(p.flag)
    return value, boolean


def split_supplied(contract: dict[str, Any], argv: list[str]) -> tuple[list[str], set[str]]:
    """Split supplied args into (positional values, flags present).

    An unclassifiable flag is assumed to take the next token. Guessing the
    other way would over-count positionals and let an under-supplied command
    look complete — a false pass is the expensive direction here.
    """
    value_flags, bool_flags = _flag_kinds(contract)
    positionals: list[str] = []
    flags: set[str] = set()
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            positionals.extend(argv[i + 1:])
            break
        if arg.startswith("-") and arg != "-":
            name = arg.split("=", 1)[0]
            flags.add(name)
            if "=" in name or name in bool_flags:
                i += 1
                continue
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                if name in value_flags or name not in bool_flags:
                    i += 2
                    continue
            i += 1
            continue
        positionals.append(arg)
        i += 1
    return positionals, flags


def check_args(contract: dict[str, Any], supplied_argv: list[str]) -> list[str]:
    """Everything the contract requires that the supplied argv does not provide."""
    positionals, flags = split_supplied(contract, supplied_argv)
    missing: list[str] = []
    need = required_positionals(contract)
    if len(positionals) < len(need):
        missing.extend(need[len(positionals):])
    for flag in required_flags(contract):
        if not any(f == flag or f.startswith(flag + "=") for f in flags):
            missing.append(flag)
    return missing


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------

def resolve(con: sqlite3.Connection, intent: str, *,
            skill_hint: str | None = None,
            tool_hint: str | None = None,
            limit: int = 3,
            do_margin: float | None = None) -> dict[str, Any]:
    """Resolve ``intent`` to one runnable tool, or explain the refusal.

    Returns a dict with ``status`` in {``ok``, ``no_match``, ``ambiguous``,
    ``missing_args``, ``no_tool``} plus ``skill``, ``tool``, ``argv``,
    ``missing`` and ``candidates`` as applicable.
    """
    tokens = search.tokenize(intent)
    if not tokens and not (skill_hint or tool_hint):
        return {"status": "no_match", "reason": "intent is only stopwords",
                "candidates": []}

    # --- explicit tool hint: it names the skill, so tier-1 is skipped ---
    # An operator who writes `--tool ocr/ocr:read` has already made the choice
    # tier-1 exists to make. Running the skill margin over it anyway made the
    # hint untestable: a vague intent refused at tier-1 before the hint was
    # ever looked at, so `--tool no/such/tool` reported "ambiguous" instead of
    # "not found". Checked first, and it settles which skill applies.
    if tool_hint:
        row = con.execute(
            "SELECT id, skill, kind, parent, summary, contract, argv, enabled FROM tools "
            "WHERE id = ? AND enabled = 1", (tool_hint,)).fetchone()
        if row is None:
            return {"status": "no_tool", "skill": skill_hint,
                    "reason": f"tool {tool_hint!r} not found or disabled",
                    "candidates": []}
        if skill_hint and row["skill"] != skill_hint:
            return {"status": "no_tool", "skill": skill_hint,
                    "reason": (f"tool {tool_hint!r} belongs to {row['skill']!r}, "
                               f"not {skill_hint!r}"),
                    "candidates": []}
        skill = row["skill"]
        contract = contract_of(row)
        argv = _argv_of(row)
        rows, children = _load(con, skill)
        # Descend: the hint may name a wrapper rather than the leaf.
        row, contract, argv, refusal = _descend(
            con, row, contract, children, tokens, _idf(
                [entry_text(r, contract_of(r)) for r in rows]))
        if refusal:
            return {"status": "ambiguous", "skill": skill,
                    "reason": refusal["reason"],
                    "candidates": refusal["candidates"],
                    "level": refusal["level"]}
        missing = check_args(contract, [])
        if missing:
            return {"status": "missing_args", "skill": skill, "tool": row["id"],
                    "missing": missing, "contract": contract, "argv": argv,
                    "candidates": []}
        return {"status": "ok", "skill": skill, "tool": row["id"],
                "argv": argv, "contract": contract, "path": [],
                "candidates": []}

    # --- tier 1: skill ------------------------------------------------
    if skill_hint:
        skill = skill_hint
        results: list[dict[str, Any]] = []
    else:
        # never/never, deliberately. The skill margin (1.3) was calibrated on
        # this configuration, and measured against auto/auto it is strictly
        # worse here: golden top1 57 vs 56, top3 61 vs 58; paraphrase top3
        # 32 vs 31. Re-ranking would also break the threshold it is judged by.
        found = search.search(con, intent, limit=limit,
                              rerank_enabled="never", fusion="never")
        results = list(found.get("results") or [])
        if not results:
            return {"status": "no_match",
                    "reason": str(found.get("note") or "no skill matched"),
                    "candidates": []}
        top = results[0]
        skill = str(top["skill"]).split("/")[0]
        threshold = margin() if do_margin is None else do_margin
        if len(results) > 1 and threshold > 0:
            second = results[1]["score"]
            ratio = top["score"] / second if second > 0 else math.inf
            if ratio < threshold:
                return {
                    "status": "ambiguous",
                    "level": "skill",
                    "reason": f"top-2 ratio {ratio:.2f} < {threshold}",
                    "skill": skill,
                    "candidates": [
                        {"name": str(r["skill"]).split("/")[0],
                         "score": round(float(r["score"]), 3)}
                        for r in results[:3]
                    ],
                }

    # --- tier 2: tool -------------------------------------------------
    rows, children = _load(con, skill)
    roots = [r for r in rows if r["kind"] in ROOT_KINDS]
    if not roots:
        return {"status": "no_tool", "skill": skill,
                "reason": "skill exposes no runnable tool",
                "candidates": []}

    all_text = [entry_text(r, contract_of(r)) for r in rows]
    idf = _idf(all_text)

    root_entries = [{
        "id": r["id"], "kind": r["kind"], "summary": r["summary"],
        "contract": contract_of(r),
        "argv": _argv_of(r),
        "text": entry_text(r, contract_of(r)),
    } for r in roots]
    ranked = _rank(root_entries, tokens, idf)
    best, best_score = ranked[0]
    if best_score <= 0.0 and len(ranked) > 1:
        return {"status": "ambiguous", "level": "tool", "skill": skill,
                "reason": "no tool shares a term with the intent",
                "candidates": [{"name": e["id"], "score": round(s, 3)}
                               for e, s in ranked[:4]]}

    row = con.execute(
        "SELECT id, skill, kind, parent, summary, contract, argv, enabled FROM tools "
        "WHERE id = ? AND enabled = 1", (best["id"],)).fetchone()
    contract = contract_of(row)
    row, contract, argv, refusal = _descend(
        con, row, contract, children, tokens, idf)
    if refusal:
        return {"status": "ambiguous", "skill": skill,
                "reason": refusal["reason"],
                "candidates": refusal["candidates"],
                "level": refusal["level"]}

    # --- tier 3: arity ------------------------------------------------
    missing = check_args(contract, [])
    if missing:
        return {"status": "missing_args", "skill": skill, "tool": row["id"],
                "missing": missing, "contract": contract, "argv": argv,
                "candidates": []}

    return {"status": "ok", "skill": skill, "tool": row["id"], "argv": argv,
            "contract": contract, "path": [], "candidates": []}


def stub_for(decision: dict[str, Any]) -> str:
    """The printable refusal for a ``missing_args`` decision."""
    row = {"id": decision["tool"]}
    return _stub(row, decision.get("contract") or {}, decision.get("missing") or [])
