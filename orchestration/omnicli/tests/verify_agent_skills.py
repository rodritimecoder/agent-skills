#!/usr/bin/env python3
"""Lint skills against the Agent Skills spec and omnicli best practices.

Validates frontmatter constraints (`name`, `description`, `compatibility`),
description framing guidance, progressive-disclosure size, and executable
script readiness (`--help`, non-interactive errors, `--json`).

Exit codes: 0 clean, 2 violations found, 1 fatal.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
sys.path.insert(0, str(SKILL_ROOT))

from catalog import registry, skilldoc  # noqa: E402

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PASSIVE_START_RE = re.compile(
    r"^(?:this skill|the skill|a tool|this tool|provides|implements)\b",
    re.IGNORECASE,
)
IMPERATIVE_TRIGGER_RE = re.compile(
    r"\b(?:use (?:this skill )?when|must use|invoke when|trigger when|run when)\b",
    re.IGNORECASE,
)
PY_INPUT_RE = re.compile(r"(?<![.\w])input\s*\(")
JS_READLINE_RE = re.compile(r"readline\.createInterface\s*\(")
JSON_HINT_RE = re.compile(r"--(?:as-json|json|omni-schema)\b")

MAX_NAME_LEN = 64
MAX_DESC_LEN = 1024
MIN_DESC_LEN = 40
MAX_COMPAT_LEN = 500
MAX_BODY_TOKENS = 5000
MAX_BODY_LINES = 500


def _normalize_scalar_field(raw: str) -> str:
    """Normalize a parsed frontmatter scalar or folded block."""
    text = (raw or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    if lines[0].strip() in (">", "|", ">-", "|-", ">+", "|+"):
        lines = lines[1:]
    joined = " ".join(ln.strip() for ln in lines if ln.strip())
    return joined.strip().strip("\"'")


def _load_skills(skills_dir: Path | None, include_sidelined: bool) -> dict[str, dict[str, Any]]:
    if skills_dir is None:
        return registry.load_all_skills(include_sidelined=include_sidelined)
    skills: dict[str, dict[str, Any]] = {}
    for item, status in registry._iter_skill_dirs(skills_dir, include_sidelined):
        md = item / "SKILL.md"
        try:
            content = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name, desc = registry.parse_frontmatter(content)
        key = name or item.name
        skills[key] = {
            "name": name or item.name,
            "dir_name": item.name,
            "path": str(item),
            "md_path": str(md),
            "description": desc,
            "status": status,
        }
    return skills


def _cli_scripts(skill_dir: Path) -> list[Path]:
    out: list[Path] = []
    for path in registry._iter_scripts(skill_dir):
        try:
            rel_parts = path.relative_to(skill_dir).parts
        except ValueError:
            rel_parts = ()
        if "hooks" in rel_parts:
            continue
        if registry._is_cli_entry(path):
            out.append(path)
    return out


def _calls_python_input(src: str) -> bool:
    """True when Python source actually invokes builtin ``input(...)``."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return bool(PY_INPUT_RE.search(src))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "input":
            return True
    return False


def check_skill(skill: dict[str, Any]) -> list[dict[str, str]]:
    """Return Agent Skills spec and best-practice findings for one skill."""
    findings: list[dict[str, str]] = []
    md_path_raw = skill.get("md_path")
    if not md_path_raw:
        return findings
    md_path = Path(md_path_raw)
    skill_dir = Path(skill.get("path") or md_path.parent)
    dir_name = skill.get("dir_name") or skill_dir.name
    label = skill.get("name") or dir_name

    try:
        content = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        findings.append({
            "severity": "error", "rule": "skill-unreadable", "skill": label,
            "path": str(md_path), "detail": f"cannot read SKILL.md: {exc}",
        })
        return findings

    raw_fm = skilldoc.parse_frontmatter(content)
    parsed_name, desc = registry.parse_frontmatter(content)
    fm_name = _normalize_scalar_field(raw_fm.get("name", "")) or parsed_name
    label = fm_name or dir_name

    def add(severity: str, rule: str, detail: str, path: Path = md_path) -> None:
        findings.append({
            "severity": severity, "rule": rule, "skill": label,
            "path": str(path), "detail": detail,
        })

    # --- Spec errors -----------------------------------------------------
    if not fm_name:
        add("error", "name-missing", "frontmatter `name` is missing or empty")
    else:
        if len(fm_name) > MAX_NAME_LEN or not NAME_RE.match(fm_name):
            add("error", "name-format",
                f"name {fm_name!r} must be 1-{MAX_NAME_LEN} chars matching [a-z0-9-] with no leading/trailing/consecutive '-'")
        if fm_name != dir_name:
            add("error", "name-mismatch",
                f"frontmatter name {fm_name!r} does not match directory {dir_name!r}")

    if not desc:
        add("error", "description-missing", "frontmatter `description` is missing or empty")
    elif len(desc) > MAX_DESC_LEN:
        add("error", "description-length",
            f"description is {len(desc)} chars (spec limit: {MAX_DESC_LEN})")

    compat = _normalize_scalar_field(raw_fm.get("compatibility", ""))
    if len(compat) > MAX_COMPAT_LEN:
        add("error", "compatibility-length",
            f"compatibility is {len(compat)} chars (spec limit: {MAX_COMPAT_LEN})")

    # --- Best-practice warnings ------------------------------------------
    if desc:
        if len(desc) < MIN_DESC_LEN:
            add("warning", "description-too-short",
                f"description is only {len(desc)} chars; describe what it does and when to use it")
        if PASSIVE_START_RE.match(desc) and not IMPERATIVE_TRIGGER_RE.search(desc):
            add("warning", "description-passive",
                "description uses passive framing without an imperative trigger (e.g. 'Use this skill when...')")

    body = re.sub(r"\A---\s*\n.*?\n---\s*\n?", "", content, flags=re.DOTALL)
    body_lines = len(body.splitlines())
    body_tokens = skilldoc.estimate_tokens(body)
    if body_tokens > MAX_BODY_TOKENS or body_lines > MAX_BODY_LINES:
        add("warning", "body-too-large",
            f"SKILL.md body is {body_lines} lines (~{body_tokens} tokens); consider moving detail to references/")

    # --- Script readiness ------------------------------------------------
    cli_scripts = _cli_scripts(skill_dir)
    if cli_scripts:
        help_scripts: list[Path] = []
        any_json = False
        for script in cli_scripts:
            try:
                src = script.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if registry._mentions_help(script):
                help_scripts.append(script)
            else:
                add("warning", "script-no-help",
                    f"CLI script {script.name} lacks --help handling", path=script)
            if JSON_HINT_RE.search(src):
                any_json = True
            if script.suffix == ".py" and _calls_python_input(src):
                add("warning", "script-interactive",
                    f"CLI script {script.name} calls interactive input(); prefer CLI flags/args",
                    path=script)
            elif script.suffix in (".js", ".mjs") and JS_READLINE_RE.search(src):
                add("warning", "script-interactive",
                    f"CLI script {script.name} uses readline.createInterface; prefer CLI flags/args",
                    path=script)
        if help_scripts and not any_json:
            add("warning", "script-no-json",
                "CLI script(s) expose --help but none mention --json, --as-json, or --omni-schema",
                path=help_scripts[0])

    return findings


def run_checks(
    *,
    skill: str | None = None,
    skills_dir: Path | None = None,
    include_sidelined: bool = False,
) -> tuple[list[dict[str, str]], int, str | None]:
    """Run checks and return ``(findings, checked_count, fatal_error)``."""
    if skills_dir is not None and not skills_dir.is_dir():
        return [], 0, f"fatal: skills directory not found: {skills_dir}"
    loaded = _load_skills(skills_dir, include_sidelined=include_sidelined)
    targets = [s for s in loaded.values() if s.get("md_path")]
    if skill:
        targets = [s for s in targets if s.get("name") == skill or s.get("dir_name") == skill]
        if not targets:
            return [], 0, f"fatal: unknown skill {skill!r}"
    targets.sort(key=lambda s: (s.get("name") or s.get("dir_name") or ""))

    findings: list[dict[str, str]] = []
    for s in targets:
        findings.extend(check_skill(s))
    return findings, len(targets), None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Validate skills against the Agent Skills spec and omnicli script guidelines."
    )
    p.add_argument("--skill", metavar="SKILL", help="Check only this skill (name or directory)")
    p.add_argument("--skills-dir", metavar="PATH", help="Override canonical skills directory")
    p.add_argument("--all", action="store_true", help="Include sidelined/archived skills")
    p.add_argument("--strict", action="store_true", help="Treat warnings as failures (exit 2)")
    p.add_argument("--json", action="store_true", help="Emit findings as JSON")
    return p


def main() -> int:
    args = build_parser().parse_args()
    skills_dir = Path(args.skills_dir).resolve() if args.skills_dir else None
    findings, checked, fatal = run_checks(
        skill=args.skill,
        skills_dir=skills_dir,
        include_sidelined=args.all,
    )
    if fatal:
        sys.stderr.write(f"{fatal}\n")
        return 1

    errors = sum(1 for f in findings if f["severity"] == "error")
    warnings = sum(1 for f in findings if f["severity"] == "warning")
    failed = errors > 0 or (args.strict and warnings > 0)

    if args.json:
        print(json.dumps({
            "clean": not failed,
            "checked": checked,
            "errors": errors,
            "warnings": warnings,
            "findings": findings,
        }, indent=2))
    else:
        if not findings:
            print(f"✅ clean — {checked} skill(s) checked")
        else:
            mark = "❌" if failed else "⚠️ "
            print(f"{mark} {errors} error(s), {warnings} warning(s) across {checked} skill(s)")
            width = max(len(f["skill"]) for f in findings)
            for f in findings:
                tag = "ERR " if f["severity"] == "error" else "WARN"
                print(f"  {tag} {f['skill']:<{width}}  {f['rule']:<22} {f['detail']}")
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
