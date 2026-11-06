#!/usr/bin/env python3
"""
review_hub.py — Unified Code Review & Architecture Audit Gateway
Late-binding dispatch engine for 8 core engineering review suites:
Ponytail (YAGNI & Minimal Diff), pstack (Execution Playbooks), Poteto Mode (Domain Modeling),
Thermo-Nuclear (Architectural Limits), Unslop (AI Tell Elimination), TypeScript (Type Discipline),
No-Comments (Comment Constraints), and Verification (Grounded Verification).
Provides Response Projection (--project) and Disk Buffering (--out) to eliminate context bloat.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
if SCRIPT_PATH.parent.name == "scripts":
    REVIEW_HUB_DIR = SCRIPT_PATH.parent.parent
else:
    REVIEW_HUB_DIR = SCRIPT_PATH.parent

SUITES_DIR = REVIEW_HUB_DIR / "suites"


def _skills_root() -> Path:
    """The skills tree this copy lives in: $SKILLS_ROOT, else the nearest
    ancestor directory named 'skills'.

    The gateway searches sibling skills for rubrics, so it must find the tree
    it was actually installed into rather than the one it was written on.
    """
    env = os.environ.get("SKILLS_ROOT")
    if env:
        return Path(env).expanduser()
    for parent in REVIEW_HUB_DIR.parents:
        if parent.name == "skills":
            return parent
    return Path("/run/media/rodri/AI/skills")


SKILLS_DIR = _skills_root()

SUITES = {
    "ponytail": {
        "name": "Ponytail (YAGNI & Minimal Diff)",
        "icon": "📐",
        "lead": "Minimalist Engineering",
        "rubric_path": "ponytail/rubric.md",
        "tags": ["minimal diff", "yagni", "lean code", "simplest solution", "delete bloat", "least code"],
        "description": "The best code is the code never written. Solves the whole problem with the least new code. Deletion beats addition.",
        "related": ["ponytail-review", "ponytail-audit", "ponytail-debt", "ponytail-gain", "ponytail-help"]
    },
    "ponytail-audit": {
        "name": "Ponytail Whole-Repo Audit",
        "icon": "🔍",
        "lead": "Repository Auditor",
        "rubric_path": "ponytail/audit.md",
        "tags": ["audit", "whole repo", "dead code", "bugs", "load breaks"],
        "description": "Quality audit of a whole repo: bugs, security holes, load breaks, risky untested code, and dead code.",
        "related": ["ponytail", "ponytail-review"]
    },
    "ponytail-review": {
        "name": "Ponytail Code Review",
        "icon": "🧐",
        "lead": "Change Reviewer",
        "rubric_path": "ponytail/review.md",
        "tags": ["code review", "review diff", "safety", "tests", "minimal diff"],
        "description": "Quality review of a change: correctness, safety, load resilience, test coverage, and lean diff.",
        "related": ["ponytail", "ponytail-audit"]
    },
    "ponytail-debt": {
        "name": "Ponytail Debt Ledger",
        "icon": "📝",
        "lead": "Technical Debt Auditor",
        "rubric_path": "ponytail/debt.md",
        "tags": ["debt", "shortcuts", "todo", "fixme", "deferred"],
        "description": "Scans for shortcut/ponytail comments and deferred items across the repo as an actionable ledger.",
        "related": ["ponytail"]
    },
    "ponytail-gain": {
        "name": "Ponytail Benchmark & Gain",
        "icon": "📊",
        "lead": "Efficiency Benchmarker",
        "rubric_path": "ponytail/gain.md",
        "tags": ["benchmark", "cost", "speed", "savings"],
        "description": "Measured savings and benchmarks for ponytail methodology.",
        "related": ["ponytail"]
    },
    "ponytail-help": {
        "name": "Ponytail Help & Quick Reference",
        "icon": "❓",
        "lead": "Documentation Lead",
        "rubric_path": "ponytail/help.md",
        "tags": ["help", "reference", "cheatsheet"],
        "description": "Quick reference card for ponytail levels, skills, and commands.",
        "related": ["ponytail"]
    },
    "pstack": {
        "name": "pstack Playbooks",
        "icon": "📚",
        "lead": "Lauren Tan (Cursor / React Core)",
        "rubric_path": "pstack/rubric.md",
        "tags": ["playbooks", "investigation", "hillclimb", "runtime forensics", "shipping", "babysit", "prototype", "rigorous"],
        "description": "23 battle-tested engineering playbooks for deep agent autonomy, systematic triage, and rigorous verification.",
        "related": ["poteto", "verification"]
    },
    "poteto": {
        "name": "Poteto Mode (Domain Modeling)",
        "icon": "🏛️",
        "lead": "Foundational Architecture Discipline",
        "rubric_path": "poteto/rubric.md",
        "tags": ["domain modeling", "state matrix", "foundational thinking", "laziness protocol", "state machine", "type discipline", "verified execution"],
        "description": "Encode the domain into state machines, pre-implementation transition matrices, and types instead of scattered conditionals.",
        "related": ["pstack", "typescript"]
    },
    "thermonuclear": {
        "name": "Thermo-Nuclear Architectural Audit",
        "icon": "⚡",
        "lead": "Harsh Architectural Auditor",
        "rubric_path": "thermonuclear/rubric.md",
        "tags": ["harsh review", "maintainability", "1000 line ceiling", "anti-spaghetti", "structural judo", "architecture audit"],
        "description": "Unusually strict maintainability review. Enforces 1,000-line ceiling, forbids spaghetti conditionals, and seeks structural deletion judo.",
        "related": []
    },
    "unslop": {
        "name": "Unslop Prose (AI Tell Elimination)",
        "icon": "✍️",
        "lead": "Human Voice & Precision Editor",
        "rubric_path": "unslop/rubric.md",
        "tags": ["ai tells", "unslop", "human writing", "no fluff", "active voice", "cut jargon", "anti-bot"],
        "description": "31-rule precision scanner that strips AI tell patterns: superficial -ing, fake ranges, sycophancy, fancy synonyms, and robotic hedging.",
        "related": []
    },
    "verification": {
        "name": "Grounded Verification",
        "icon": "🔬",
        "lead": "Verification & Grounding Lead",
        "rubric_path": "pstack/skills/create-verification-skill/rubric.md",
        "tags": ["verification", "test harness", "requirement traceability", "drive", "doctor", "launch", "evidence", "feature map", "prove it works"],
        "description": "Grounded verification harness with Launch, Doctor, Drive, Evidence, Cleanup, and [REQ-XX] Feature Map.",
        "related": ["create-verification", "maintain-verification", "poteto"]
    },
    "create-verification": {
        "name": "Create Verification Skill",
        "icon": "🔬",
        "lead": "The Grounded Verifier",
        "rubric_path": "pstack/skills/create-verification-skill/rubric.md",
        "tags": ["verification", "test harness", "requirement traceability", "drive", "doctor", "launch", "evidence", "feature map", "prove it works"],
        "description": "Generate a project-local verification skill with Launch, Doctor, Drive, Evidence, Cleanup, and [REQ-XX] Feature Map.",
        "related": ["maintain-verification", "poteto"]
    },
    "maintain-verification": {
        "name": "Maintain Verification Skill",
        "icon": "🧪",
        "lead": "The Drift Hunter",
        "rubric_path": "pstack/skills/maintain-verification-skill/rubric.md",
        "tags": ["verify audit", "drift check", "live pass", "feature map upkeep", "doctor check", "evidence"],
        "description": "Periodic upkeep pass that checks source drift, drives every mapped feature live, verifies health with Doctor, and flags product regressions.",
        "related": ["create-verification", "poteto"]
    },
    "no-comments": {
        "name": "No Comments (Strict Comment Discipline)",
        "icon": "✂️",
        "lead": "Code Clarity Enforcer",
        "rubric_path": "pstack/skills/no-comments/rubric.md",
        "tags": ["clean code", "no comments", "strip ai fluff", "encode constraints", "types over comments"],
        "description": "Eliminate redundant code comments, strip AI commentary, and encode real constraints into types, runtime assertions, or linter rules.",
        "related": ["ponytail", "typescript"]
    },
    "typescript": {
        "name": "TypeScript Best Practices",
        "icon": "🛡️",
        "lead": "Type Discipline Enforcer",
        "rubric_path": "pstack/skills/typescript-best-practices/rubric.md",
        "tags": ["typescript", "ts discipline", "discriminated unions", "branded types", "no as casts", "satisfies", "schemas"],
        "description": "Discriminated unions, branded types, constructive modeling, schemas before guards, zero 'as' casts, and 'satisfies' over 'as'.",
        "related": ["poteto", "no-comments"]
    }
}

CORE_SUITES = ["ponytail", "pstack", "poteto", "thermonuclear", "unslop", "typescript", "no-comments", "verification"]

UNSLOP_PATTERNS = [
    (r"\b(crucial|delve|enduring|enhance|fostering|garner|interplay|intricate|pivotal|showcase|tapestry|testament|underscore|vibrant)\b", "AI Vocabulary Tell"),
    (r"\b(not just [^,\n]+, but)\b", "Not just X, but Y construction"),
    (r"\b(serves as|stands as|boasts|features)\b", "Fancy way to say 'is/has'"),
    (r"\b(in order to)\b", "Wordy filler (use 'to')"),
    (r"\b(due to the fact that)\b", "Wordy filler (use 'because')"),
    (r"\b(it is important to note that|it should be noted that)\b", "Chatbot preamble filler"),
    (r"\b(I hope this helps|Let me know if|Certainly!|Of course!|Found the smoking gun!)\b", "Chatbot conversational artifact"),
    (r"—", "Em dash tell (use period or comma)"),
    (r",\s*(highlighting|ensuring|reflecting|showcasing|fostering)\b", "Superficial -ing participle clause"),
    (r"\b(experts believe|industry reports suggest|some critics argue)\b", "Vague attribution tell"),
    (r"\b(could potentially possibly be argued|it might be suggested that)\b", "Excessive hedging"),
    (r"\b(utilize|utilizing|utilization)\b", "Pompous synonym (use 'use')"),
]


def resolve_suite_file(rel_path: str) -> Path:
    candidates = [
        SUITES_DIR / rel_path,
        SUITES_DIR / f"{rel_path}.md",
        SUITES_DIR / rel_path / "rubric.md",
        SUITES_DIR / "pstack" / "skills" / rel_path / "rubric.md",
        SKILLS_DIR / rel_path / "SKILL.md",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


def normalize_suite_key(key: str) -> str:
    cleaned = key.lower().strip()
    if cleaned in SUITES:
        return cleaned
    compact = cleaned.replace("-", "").replace("_", "")
    for k in SUITES:
        if k.replace("-", "").replace("_", "") == compact:
            return k
    for k in SUITES:
        if k.startswith(cleaned) or k.replace("-", "").startswith(compact):
            return k
    return cleaned


def cmd_list(as_json=False):
    if as_json:
        data = [
            {"id": s_id, "name": info["name"], "lead": info["lead"], "description": info["description"], "tags": info["tags"]}
            for s_id, info in SUITES.items()
        ]
        print(json.dumps(data, indent=2))
        return

    print("\n🔍  [Review Hub] Available Review Suites:\n")
    print(f"{'#':<3} {'Suite':<24} {'Discipline Lead':<30} {'Focus & Philosophy'}")
    print("─" * 84)
    for i, (s_id, info) in enumerate(SUITES.items(), start=1):
        suite_str = f"{info['icon']} {s_id}"
        print(f"{i:<3} {suite_str:<24} {info['lead']:<30} {info['description'][:65]}...")
    print("\n💡 Commands: 'review-hub inspect <suite>' | 'review-hub review [suite] [target]' | 'review-hub all'\n")


def cmd_search(query: str, as_json=False):
    tokens = query.lower().split()
    scored = []
    for s_id, info in SUITES.items():
        score = 0
        haystack = f"{s_id} {info['name']} {info['lead']} {info['description']} {' '.join(info['tags'])}".lower()
        for t in tokens:
            if t in s_id:
                score += 10
            if t in info['name'].lower():
                score += 6
            if t in haystack:
                score += 3
        if score > 0:
            scored.append((score, s_id, info))

    scored.sort(key=lambda x: x[0], reverse=True)
    if as_json:
        results = [
            {"id": s_id, "name": info["name"], "score": score, "description": info["description"], "tags": info["tags"]}
            for score, s_id, info in scored
        ]
        print(json.dumps(results, indent=2))
        return

    if not scored:
        print(f"\n🔍 No review suites matched '{query}'. Run 'review-hub list' to view all available suites.\n")
        return

    print(f"\n🔍 [Review Hub Suite Search] Results for '{query}':\n")
    for score, s_id, info in scored:
        print(f"  • {info['icon']} \033[1m{info['name']}\033[0m (`{s_id}`) — {info['lead']}")
        print(f"    {info['description']}")
        print(f"    Tags: {', '.join(info['tags'][:4])}\n")


def cmd_inspect(suite_id: str):
    s_id = normalize_suite_key(suite_id)
    info = SUITES.get(s_id)
    if not info:
        print(f"❌ Unknown suite '{suite_id}'. Available: {', '.join(SUITES.keys())}")
        sys.exit(1)

    suite_file = resolve_suite_file(info.get("rubric_path", ""))
    if not suite_file.is_file():
        print(f"❌ Rubric file not found: {suite_file}")
        sys.exit(1)

    content = suite_file.read_text(encoding="utf-8")
    print(f"\n📜 [Review Rubric & Guidelines] {info['icon']} {info['name']} ({suite_file})\n")
    print("=" * 80)
    print(content)
    print("=" * 80)


def scan_unslop(text: str):
    findings = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        for pattern, label in UNSLOP_PATTERNS:
            matches = list(re.finditer(pattern, line, re.IGNORECASE))
            for m in matches:
                findings.append({
                    "line": idx,
                    "label": label,
                    "match": m.group(0),
                    "context": line.strip()[:80]
                })
    return findings


def get_git_diff():
    try:
        out = subprocess.check_output(["git", "diff", "HEAD"], stderr=subprocess.DEVNULL, text=True)
        if not out.strip():
            out = subprocess.check_output(["git", "diff"], stderr=subprocess.DEVNULL, text=True)
        return out
    except Exception:
        return ""


def get_git_touched_files():
    try:
        out = subprocess.check_output(["git", "diff", "--name-only", "HEAD"], stderr=subprocess.DEVNULL, text=True)
        files = [f.strip() for f in out.splitlines() if f.strip() and Path(f.strip()).is_file()]
        if not files:
            out2 = subprocess.check_output(["git", "diff", "--name-only"], stderr=subprocess.DEVNULL, text=True)
            files = [f.strip() for f in out2.splitlines() if f.strip() and Path(f.strip()).is_file()]
        return files
    except Exception:
        return []


def evaluate_suite(suite_id: str, target: str = None) -> dict:
    s_id = normalize_suite_key(suite_id)
    info = SUITES.get(s_id)
    if not info:
        return {"error": f"Unknown review suite '{suite_id}'"}

    target_text = ""
    is_git_diff = False
    target_desc = ""

    if target and Path(target).is_file():
        target_desc = f"File: {target}"
        target_text = Path(target).read_text(encoding="utf-8", errors="replace")
    elif target and Path(target).is_dir():
        target_desc = f"Directory: {target}"
    else:
        diff = get_git_diff()
        if diff:
            target_desc = "Current Git Diff (staged + unstaged)"
            target_text = diff
            is_git_diff = True
        else:
            target_desc = "Workspace Codebase"

    checks = []
    status = "OK"

    if s_id == "thermonuclear":
        touched = get_git_touched_files() if is_git_diff else ([target] if target and Path(target).is_file() else [])
        if touched:
            for tf in touched:
                try:
                    lines = len(Path(tf).read_text(encoding="utf-8", errors="replace").splitlines())
                    if lines > 1000:
                        checks.append(f"❌ VIOLATION: {tf} is {lines} lines (>1,000 ceiling)")
                        status = "VIOLATION"
                    else:
                        checks.append(f"✅ OK: {tf} is {lines} lines (<1,000 lines)")
                except Exception:
                    pass
        else:
            checks.append("• Clean working tree or no diff for file size audit.")

    elif s_id in ["ponytail", "ponytail-review"]:
        if target_text and is_git_diff:
            added = sum(1 for line in target_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
            deleted = sum(1 for line in target_text.splitlines() if line.startswith("-") and not line.startswith("---"))
            checks.append(f"• Diff Volume: +{added} / -{deleted} (Net: {added - deleted:+d} lines)")
            if added > 150:
                checks.append("⚠️  Caution: Large addition (>150 lines). Can this be solved with less new code?")
                status = "WARNING"
            else:
                checks.append("✅ Diff volume is compact and minimal.")
        else:
            checks.append("• Clean working tree or no diff to calculate delta.")

    elif s_id in ["ponytail-debt", "debt"]:
        debt_items = []
        try:
            res = subprocess.run(["git", "grep", "-En", r"(//|#)\s*(shortcut|ponytail|TODO|FIXME):"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                debt_items = res.stdout.strip().splitlines()
        except Exception:
            pass
        if debt_items:
            checks.append(f"📝 Found {len(debt_items)} recorded shortcut/debt item(s):")
            for item in debt_items[:8]:
                checks.append(f"   {item.strip()}")
            if len(debt_items) > 8:
                checks.append(f"   ... and {len(debt_items) - 8} more.")
        else:
            checks.append("✅ Zero unresolved shortcut: or ponytail: comments found in repository.")

    elif s_id in ["ponytail-audit", "audit"]:
        checks.append("1. Bug & Vulnerability Scan: Search for unchecked inputs, loose type casts, and state leaks.")
        checks.append("2. Dead Code Removal: Identify orphaned files, uncalled functions, and dead dependencies.")
        checks.append("3. Real Load Resilience: Verify timeouts, failure handling, and retry bounds.")

    elif s_id == "unslop":
        findings = scan_unslop(target_text) if target_text else []
        if findings:
            checks.append(f"⚠️  Found {len(findings)} potential AI tell pattern(s):")
            for f in findings[:6]:
                checks.append(f"   [Line {f['line']}] {f['label']}: \"{f['match']}\"")
            status = "WARNING"
        else:
            checks.append("✅ Clean! Zero obvious AI tell words detected.")

    elif s_id in ["pstack", "poteto"]:
        checks.append("1. Model the Domain: States as explicit unions/state machines instead of loose flags.")
        checks.append("2. Laziness Protocol: Deletion beats addition; verify every line is strictly necessary.")
        checks.append("3. Grounded Artifacts: Never trust assumptions; verify with real command execution.")

    elif "typescript" in s_id or s_id == "ts":
        touched = get_git_touched_files() if is_git_diff else ([target] if target and Path(target).is_file() else [])
        ts_files = [f for f in touched if f.endswith((".ts", ".tsx"))]
        if ts_files:
            any_count = 0
            as_count = 0
            for tf in ts_files:
                try:
                    content = Path(tf).read_text(encoding="utf-8", errors="replace")
                    any_count += len(re.findall(r":\s*any\b", content))
                    as_count += len(re.findall(r"\bas\s+[A-Z]", content))
                except Exception:
                    pass
            checks.append(f"• Scanned {len(ts_files)} TypeScript file(s)")
            if any_count > 0:
                checks.append(f"⚠️ Found {any_count} loose 'any' annotations. (Prefer 'unknown' or domain types)")
                status = "WARNING"
            if as_count > 0:
                checks.append(f"⚠️ Found {as_count} unvalidated 'as' casts. (Prefer 'satisfies' or type guards)")
                status = "WARNING"
            if any_count == 0 and as_count == 0:
                checks.append("✅ Zero unvalidated 'any' or risky 'as' casts detected.")
        else:
            checks.append("• No modified .ts/.tsx files found to scan.")

    elif "nocomments" in s_id or "no-comments" in s_id:
        touched = get_git_touched_files() if is_git_diff else ([target] if target and Path(target).is_file() else [])
        code_files = [f for f in touched if not f.endswith((".md", ".txt", ".json", ".yaml", ".yml"))]
        if code_files:
            for cf in code_files[:5]:
                try:
                    lines = Path(cf).read_text(encoding="utf-8", errors="replace").splitlines()
                    comment_lines = sum(1 for l in lines if re.match(r"^\s*(//|#|/\*|\*)", l))
                    ratio = (comment_lines / len(lines) * 100) if lines else 0
                    if ratio > 25:
                        checks.append(f"⚠️ {cf}: {comment_lines}/{len(lines)} lines are comments ({ratio:.1f}%). Strip trivial comments.")
                        status = "WARNING"
                    else:
                        checks.append(f"✅ {cf}: comment ratio clean ({ratio:.1f}%)")
                except Exception:
                    pass
        else:
            checks.append("• No modified code files found to audit comments.")

    elif "verification" in s_id or "verify" in s_id:
        checks.append("1. Launch: Start the real service, CLI, or test harness from a clean state.")
        checks.append("2. Doctor: Run a read-only health check before driving actions.")
        checks.append("3. Drive: Programmatically exercise real user paths (CLI/curl/CDP).")
        checks.append("4. Evidence: Capture exit codes, logs, and artifacts that survive teardown.")
        checks.append("5. Cleanup: Terminate child processes cleanly without stranding ports.")

    suite_file = resolve_suite_file(info.get("rubric_path", ""))
    return {
        "suite_id": s_id,
        "name": info["name"],
        "icon": info["icon"],
        "lead": info["lead"],
        "description": info["description"],
        "target_desc": target_desc,
        "status": status,
        "checks": checks,
        "rubric_file": str(suite_file),
    }


def output_results(data: dict, out_path: str = None, project_fields: str = None, as_json: bool = False, title: str = None):
    if project_fields and isinstance(data, dict):
        fields = [f.strip() for f in project_fields.split(",")]
        if "suite_id" in data:
            data = {k: v for k, v in data.items() if k in fields}
        else:
            # Multi-suite dictionary
            data = {s_k: {k: v for k, v in s_v.items() if k in fields} for s_k, s_v in data.items()}

    if as_json or project_fields or out_path:
        full_json = json.dumps(data, indent=2)
        if out_path:
            Path(out_path).write_text(full_json, encoding="utf-8")
            print(f"[Review Complete. Output buffered to {out_path}]")
        else:
            print(full_json)
        return

    if "suite_id" in data:
        # Single suite print
        print(f"\n🔍 \033[1m[Review Run]\033[0m {data['icon']} \033[1m{data['name']}\033[0m")
        print(f"   👤 Lead: {data['lead']}")
        print(f"   🎯 Focus: {data['description']}")
        print(f"   🔍 Target: {data['target_desc']}")
        print(f"   📊 Status: \033[1m{data['status']}\033[0m")
        print("─" * 70)
        for check in data.get("checks", []):
            print(f"   {check}")
        print(f"\n📋 [Rubric Available in {data.get('rubric_file', '')}]")
    else:
        # Multi-suite print
        header = title or "Full Review Suite Run"
        print(f"\n📊 \033[1m[{header}]\033[0m\n" + "=" * 70)
        for s_k, res in data.items():
            print(f"\n{res.get('icon', '•')} {res.get('name', s_k)}: {res.get('status', 'OK')}")
            for check in res.get("checks", []):
                bullet = "" if (check.startswith("•") or check.startswith("⚠️") or check.startswith("✅") or check.startswith("❌") or check.startswith("📝") or (len(check) > 2 and check[0].isdigit() and check[1] == ".")) else "• "
                print(f"   {bullet}{check}")


def cmd_all(target: str = None, out_path: str = None, project_fields: str = None, as_json: bool = False):
    results = {}
    for s_k in CORE_SUITES:
        results[s_k] = evaluate_suite(s_k, target)
    output_results(results, out_path, project_fields, as_json, title="Review Across All Core Suites")


def cmd_review(suite_id: str = None, target: str = None, out_path: str = None, project_fields: str = None, as_json: bool = False):
    # Handle default suite
    if not suite_id or suite_id == "all":
        cmd_all(target=target, out_path=out_path, project_fields=project_fields, as_json=as_json)
        return

    # Check if suite_id is actually a file or directory path
    if Path(suite_id).exists() and not normalize_suite_key(suite_id) in SUITES:
        target = suite_id
        suite_id = "ponytail"

    res = evaluate_suite(suite_id, target)
    output_results(res, out_path, project_fields, as_json)


def cmd_audit(suite_id: str = None, target: str = None, out_path: str = None, project_fields: str = None, as_json: bool = False):
    if not suite_id:
        suite_id = "ponytail-audit"
    elif suite_id in ["thermo", "thermonuclear"]:
        suite_id = "thermonuclear"
    elif suite_id in ["debt", "ledger"]:
        suite_id = "ponytail-debt"

    res = evaluate_suite(suite_id, target)
    output_results(res, out_path, project_fields, as_json)


def main():
    parser = argparse.ArgumentParser(
        prog="review-hub",
        description="Unified Code Review & Architecture Audit Gateway"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # list / suites
    p_list = sub.add_parser("list", help="List available review suites")
    p_list.add_argument("--json", action="store_true", help="Output suite list as JSON")

    p_suites = sub.add_parser("suites", help="Alias for list")
    p_suites.add_argument("--json", action="store_true", help="Output suite list as JSON")

    # search
    p_search = sub.add_parser("search", help="Search review suites by intent or keyword")
    p_search.add_argument("query", help="Intent query (e.g. 'harsh audit', 'minimal diff', 'unslop')")
    p_search.add_argument("--json", action="store_true", help="Output results as JSON")

    # inspect
    p_inspect = sub.add_parser("inspect", help="Read full rubric and guidelines for a suite")
    p_inspect.add_argument("suite", help="Suite identifier (e.g. ponytail, pstack, poteto, thermonuclear, unslop, typescript, no-comments, verification)")

    # review
    p_review = sub.add_parser("review", help="Review diff or target against a specific review suite")
    p_review.add_argument("suite", nargs="?", default="ponytail", help="Review suite (default: ponytail; or 'all')")
    p_review.add_argument("target", nargs="?", default=None, help="Optional file or directory target")
    p_review.add_argument("--out", default=None, help="Buffer raw review output to disk file")
    p_review.add_argument("--project", default=None, help="Comma-separated fields to project (e.g. 'status,checks')")
    p_review.add_argument("--json", action="store_true", help="Output results as JSON")

    # audit
    p_audit = sub.add_parser("audit", help="Run architectural, technical debt, or repo-wide audit")
    p_audit.add_argument("suite", nargs="?", default="ponytail-audit", help="Audit suite (ponytail-audit, thermonuclear, ponytail-debt; default: ponytail-audit)")
    p_audit.add_argument("target", nargs="?", default=None, help="Optional file or directory target")
    p_audit.add_argument("--out", default=None, help="Buffer raw audit output to disk file")
    p_audit.add_argument("--project", default=None, help="Comma-separated fields to project (e.g. 'status,checks')")
    p_audit.add_argument("--json", action="store_true", help="Output results as JSON")

    # all
    p_all = sub.add_parser("all", help="Run all core review suites sequentially")
    p_all.add_argument("target", nargs="?", default=None, help="Optional file or directory target")
    p_all.add_argument("--out", default=None, help="Buffer output to disk file")
    p_all.add_argument("--project", default=None, help="Comma-separated fields to project (e.g. 'status,checks')")
    p_all.add_argument("--json", action="store_true", help="Output results as JSON")

    # backward-compatibility fallbacks
    p_order = sub.add_parser("order", help="Deprecated alias for review")
    p_order.add_argument("suite", nargs="?", default="ponytail", help="Review suite")
    p_order.add_argument("target", nargs="?", default=None, help="Optional target")
    p_order.add_argument("--out", default=None, help="Buffer output")
    p_order.add_argument("--project", default=None, help="Project fields")
    p_order.add_argument("--json", action="store_true", help="JSON output")

    p_menu = sub.add_parser("menu", help="Deprecated alias for list")
    p_menu.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()

    if args.action in ["list", "suites", "menu"]:
        cmd_list(as_json=getattr(args, "json", False))
    elif args.action == "search":
        cmd_search(args.query, as_json=args.json)
    elif args.action == "inspect":
        cmd_inspect(args.suite)
    elif args.action in ["review", "order"]:
        cmd_review(args.suite, args.target, out_path=args.out, project_fields=args.project, as_json=args.json)
    elif args.action == "audit":
        cmd_audit(args.suite, args.target, out_path=args.out, project_fields=args.project, as_json=args.json)
    elif args.action == "all":
        cmd_all(args.target, out_path=args.out, project_fields=args.project, as_json=args.json)


if __name__ == "__main__":
    main()
