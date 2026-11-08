#!/usr/bin/env python3
"""Gate a skill's CLI against the Code-Mode contract.

The gate exists so a slice can be handed to a cheap builder and judged by an
assertion instead of a reading of the diff. It reads the catalog's extracted
contracts (no network, no model) and reports the rules a skill breaks.

Static mode (default) answers: would a Code-Mode binding be typed correctly,
and does the skill expose the structured-output surface its tier promises?
Live mode (``--cases``) runs named invocations and asserts the stdout and exit
code contract.

Exit codes: 0 clean, 2 violations found, 1 fatal.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
sys.path.insert(0, str(SKILL_ROOT))

from catalog import argspec  # noqa: E402

DEFAULT_CONFIG = HERE / "code_mode_gate.json"
DEFAULT_DB = Path(
    os.environ.get("OMNICLI_DB")
    or (Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "omnicli" / "catalog.db")
)

NUMBERISH = re.compile(
    r"^(limit|count|num|number|offset|page|pages|port|timeout|threshold|score|ratio|"
    r"alpha|temperature|worker|workers|job|jobs|retry|retries|max|min|tokens|top-k|"
    r"top-p|depth|width|height|scale|fps|seed|budget|bytes|lines|rows|turns|attempts|"
    r"iterations|interval|delay|concurrency|cores|cpus|memory)$"
)

JSON_FLAGS = {"--json", "--as-json"}
PROJECTION_FLAGS = {"--fields", "--project", "--select", "--columns", "--table", "--outline"}


def log(msg: str) -> None:
    sys.stderr.write(f"{msg}\n")
    sys.stderr.flush()


def last_segment(flag: str) -> str:
    return flag.lstrip("-").split("-")[-1].lower()


def load_config(path: Path) -> dict:
    if not path.is_file():
        return {"allow_str": {}, "tiers": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def tool_rows(db: Path, skills: set[str] | None) -> list[dict]:
    import sqlite3

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("select id, skill, kind, contract, enabled from tools order by id")]
    con.close()
    if skills is not None:
        rows = [r for r in rows if r["skill"] in skills]
    return rows


def skill_set(cfg: dict, tier: str, only: str | None) -> set[str] | None:
    if only:
        return {only}
    if tier in ("all", "b1"):
        return None
    names = set(cfg.get("tiers", {}).get(tier) or [])
    return names or None


def check_typing(rows: list[dict], allow: dict[str, str]) -> list[dict]:
    found = []
    for row in rows:
        contract = json.loads(row["contract"] or "{}")
        try:
            params = argspec.parse_flags(contract)
        except Exception as exc:  # a contract the parser cannot read is a finding
            found.append({"rule": "typing", "skill": row["skill"], "tool": row["id"],
                          "flag": "-", "detail": f"contract unreadable: {exc}"})
            continue
        for p in params:
            if p.kind != "str":
                continue
            name = p.flag.lstrip("-").lower()
            if not (NUMBERISH.match(last_segment(p.flag)) or NUMBERISH.match(name)):
                continue
            if p.flag in allow or f"{row['id']}|{p.flag}" in allow:
                continue
            found.append({
                "rule": "typing", "skill": row["skill"], "tool": row["id"], "flag": p.flag,
                "detail": f"numeric-named flag binds as str (add metavar=PORT/N/SCORE or allow it)",
            })
    return found


def check_output(rows: list[dict], cfg: dict, tier: str) -> list[dict]:
    found = []
    by_skill: dict[str, set[str]] = {}
    for row in rows:
        contract = json.loads(row["contract"] or "{}")
        by_skill.setdefault(row["skill"], set()).update(contract.get("flags") or [])
    targets = {
        "b2a": (JSON_FLAGS, "no --json: a Code-Mode call must be able to parse the result"),
        "b2b": (PROJECTION_FLAGS, "no --fields/--project: list output is unbounded"),
    }
    wanted = {t: spec for t, spec in targets.items() if tier in (t, "all")}
    deferred = cfg.get("deferred") or {}
    for skill, flags in sorted(by_skill.items()):
        if skill in deferred:
            continue
        for name, (accept, detail) in wanted.items():
            if skill not in (cfg.get("tiers", {}).get(name) or []):
                continue
            if not (flags & accept):
                found.append({"rule": name, "skill": skill, "tool": "-", "flag": ",".join(sorted(accept)),
                              "detail": detail})
    return found


def check_declared_types(db: Path, skills: set[str] | None) -> list[dict]:
    """Flag add_argument(type=int) paired with a metavar that binds a float.

    The catalog contract is text: it carries the metavar but not argparse's
    ``type=``. So a flag can declare ``type=int`` and still bind as ``float``
    when its metavar is ``TIMEOUT`` or ``SECONDS`` — ``--interval TIMEOUT``
    says int to argparse and float to every generated plan. Only the source
    can answer this, so this check reads it.
    """
    import sqlite3

    import ast

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("select name, path from skills")]
    con.close()
    if skills is not None:
        rows = [r for r in rows if r["name"] in skills]

    found = []
    for skill in rows:
        root = Path(skill["path"] or "")
        if not root.is_absolute() or not root.is_dir():
            continue
        candidates = list(root.glob("*.py"))
        scripts = root / "scripts"
        if scripts.is_dir():
            candidates += list(scripts.rglob("*.py"))
        for file in sorted(candidates):
            if any(part in {"__pycache__", "tests", "modules", ".venv"} for part in file.parts):
                continue
            try:
                tree = ast.parse(file.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument"):
                    continue
                kw = {k.arg: k.value for k in node.keywords if k.arg}
                declared, metavar = kw.get("type"), kw.get("metavar")
                if not (isinstance(declared, ast.Name) and declared.id in ("int", "float")):
                    continue
                if not (isinstance(metavar, ast.Constant) and isinstance(metavar.value, str)):
                    continue
                hints = argspec.INT_HINTS if declared.id == "int" else argspec.FLOAT_HINTS
                if metavar.value.upper() in hints:
                    continue
                binds = "float" if metavar.value.upper() in argspec.FLOAT_HINTS else (
                    "int" if metavar.value.upper() in argspec.INT_HINTS else "str")
                flags = [a.value for a in node.args if isinstance(a, ast.Constant) and str(a.value).startswith("-")]
                found.append({
                    "rule": "declared", "skill": skill["name"], "tool": f"{file.relative_to(root)}:{node.lineno}",
                    "flag": ",".join(flags) or "?",
                    "detail": f"argparse declares {declared.id} but metavar {metavar.value} binds {binds}",
                })
    return found


def deferred_notes(cfg: dict, rows: list[dict]) -> list[dict]:
    """Skills whose tier work is postponed, reported but never counted.

    Deferring is a decision, so it is recorded with a reason in the config
    rather than by deleting the skill from the tier list — deleting it would
    make the gate green by forgetting.
    """
    deferred = cfg.get("deferred") or {}
    present = {r["skill"] for r in rows}
    return [{"skill": s, "detail": reason} for s, reason in sorted(deferred.items()) if s in present]


CASE_MAX_BYTES = 500_000


def run_cases(cases_path: Path, timeout: int) -> list[dict]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    binary = os.environ.get("OMNICLI_BIN") or shutil.which("omnicli") or "omnicli"
    found = []
    for case in cases:
        # The gateway elides stdout above --omni-max-bytes and appends a marker,
        # which is correct for a model's context and fatal for json.loads. A
        # case that asserts JSON asks for the whole payload.
        argv = [binary, "invoke", case["tool"], "--omni-max-bytes", str(CASE_MAX_BYTES),
                *[str(a) for a in case.get("argv", [])]]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            found.append({"rule": "live", "skill": case["tool"].split("/")[0], "tool": case["tool"],
                          "flag": "-", "detail": f"timed out after {timeout}s"})
            continue
        want_exit = case.get("expect_exit")
        if want_exit is not None and proc.returncode != int(want_exit):
            found.append({"rule": "live", "skill": case["tool"].split("/")[0], "tool": case["tool"],
                          "flag": "-", "detail": f"exit {proc.returncode}, expected {want_exit}: "
                                                 f"{(proc.stderr or proc.stdout).strip()[:160]}"})
            continue
        if want_exit not in (None, 0) and proc.stdout.strip():
            found.append({"rule": "live", "skill": case["tool"].split("/")[0], "tool": case["tool"],
                          "flag": "-", "detail": "failure wrote to stdout (rule 3: silent exit)"})
        if case.get("expect_json"):
            try:
                json.loads(proc.stdout)
            except ValueError as exc:
                found.append({"rule": "live", "skill": case["tool"].split("/")[0], "tool": case["tool"],
                              "flag": "--json", "detail": f"stdout is not JSON: {exc}"})
    return found


def render_text(violations: list[dict], scoped: int) -> None:
    if not violations:
        print(f"✅ clean — {scoped} tools checked")
        return
    print(f"❌ {len(violations)} violation(s) across {scoped} tools")
    width = max(len(v["skill"]) for v in violations)
    for v in violations:
        print(f"  {v['rule']:5} {v['skill']:<{width}}  {v['flag']:<18} {v['detail']}")
        print(f"        {v['tool']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Assert the Code-Mode rules for one skill, one tier, or the whole catalog.")
    p.add_argument("--skill", metavar="SKILL", help="Only this skill")
    p.add_argument("--tier", choices=["all", "b1", "b2a", "b2b"], default="all",
                   help="Only skills in this tier of the gate config (default: all)")
    p.add_argument("--db", metavar="PATH", default=str(DEFAULT_DB), help="Catalog database")
    p.add_argument("--config", metavar="PATH", default=str(DEFAULT_CONFIG), help="Allowlist + tier map")
    p.add_argument("--cases", metavar="PATH", help="Run a live invocation manifest as well")
    p.add_argument("--timeout", type=int, metavar="N", default=60)
    p.add_argument("--json", action="store_true", help="Emit the findings as JSON")
    return p


def main() -> int:
    args = build_parser().parse_args()
    db = Path(args.db)
    if not db.is_file():
        log(f"fatal: no catalog at {db} (run `omnicli index`)")
        return 1
    cfg = load_config(Path(args.config))
    skills = skill_set(cfg, args.tier, args.skill)
    if skills is not None and not skills:
        log(f"fatal: tier {args.tier} is empty in {args.config}")
        return 1
    rows = tool_rows(db, skills)
    violations = check_typing(rows, cfg.get("allow_str") or {})
    violations += check_output(rows, cfg, args.tier)
    if args.tier in ("all", "b1"):
        violations += check_declared_types(db, skills)
    if args.cases:
        violations += run_cases(Path(args.cases), args.timeout)
    deferred = deferred_notes(cfg, rows)

    if args.json:
        print(json.dumps({"clean": not violations, "checked": len(rows),
                          "violations": violations, "deferred": deferred}, indent=2))
    else:
        render_text(violations, len(rows))
        for d in deferred:
            print(f"  ⏸ deferred {d['skill']}: {d['detail']}")
    return 0 if not violations else 2


if __name__ == "__main__":
    sys.exit(main())
