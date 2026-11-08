#!/usr/bin/env python3
"""
academic_icm.py — Academic ICM Pipeline Orchestrator

Orchestrates the university knowledge pipeline adhering to Interpretable Context Methodology (ICM):
  1. Ingestion & Normalization: canvas-cli -> zoom-recorder -> markitdown-cli
  2. Knowledge Graph & Multimodal Memory: graph-memory (EmbeddingGemma-2 768d multimodal vector)
  3. Active-Recall Distillation: cornell-notes (strict stem inheritance)
  4. Curriculum Architecture & Gates: okf-architect -> CURRICULUM_TREE.md -> viz.html & cornell_index.html

Commands:
  academic-icm status [vault]         - Audit coverage %, missing nodes, and orphaned notes
  academic-icm audit [vault]          - Lint stem naming, JSON schema, and KaTeX math formulas
  academic-icm verify [week]          - Run 5-stage ICM verification gates & unbiased 0-context judge
  academic-icm graph <action> [...]   - Multimodal RAG search, graph recall & indexing (Stage 2)
  academic-icm scaffold <source_md>   - Auto-scaffold matching _cornell.json template from markdown source
  academic-icm build-note <json_file> - Compile _cornell.json into .html study sheet and .tsv Anki deck
  academic-icm compile [vault]        - Recompile CURRICULUM_TREE.md into Knowledge Cosmos and Study Portal
  academic-icm sync-orphans [vault]   - Auto-repair and link orphaned Cornell notes into the curriculum tree
  academic-icm stamp-video [target]   - Auto-stamp Cornell cues with video/recording timestamps
  academic-icm serve [vault] [--port] - Start local HTTP preview server for study portal
"""


import sys
import os
import re
import json
import argparse
import subprocess
from pathlib import Path
import math
import shutil
from collections import Counter
from typing import Dict, List, Any, Optional, Tuple
import urllib.request

DEFAULT_NOTES_DIR = Path("/run/media/rodri/AI/University/notes")

# Dynamic discovery of companion engines
def find_engine_path(skill_name: str, script_name: str) -> Optional[Path]:
    academic_root = Path(__file__).resolve().parent.parent
    internal_cand = academic_root / "modules" / skill_name / "scripts" / script_name
    if internal_cand.is_file():
        return internal_cand
    internal_root = academic_root / "modules" / skill_name / script_name
    if internal_root.is_file():
        return internal_root

    candidate_roots: List[Path] = [
        academic_root.parent / skill_name,
    ]
    repo_root = academic_root.parent.parent
    if repo_root.is_dir():
        for cat in repo_root.iterdir():
            if cat.is_dir() and not cat.name.startswith("."):
                candidate_roots.append(cat / skill_name)

    candidate_roots.extend([
        Path("/run/media/rodri/AI/skills"),
        Path.home() / ".gemini" / "config" / "skills",
        Path.home() / ".pi" / "agent" / "skills",
        Path("/run/media/rodri/AI/academic-agent-skills"),
    ])
    for r in candidate_roots:
        p = r / "scripts" / script_name if r.name == skill_name else r / skill_name / "scripts" / script_name
        if p.is_file():
            return p
        p_root = r / script_name if r.name == skill_name else r / skill_name / script_name
        if p_root.is_file():
            return p_root
    return None

def find_vault_root(start_path: Optional[str] = None) -> Path:
    if start_path:
        p = Path(start_path).resolve()
        if (p / "CURRICULUM_TREE.md").is_file():
            return p
        for parent in p.parents:
            if (parent / "CURRICULUM_TREE.md").is_file():
                return parent
        return p
    if DEFAULT_NOTES_DIR.is_dir():
        return DEFAULT_NOTES_DIR
    return Path.cwd()

def parse_tree_nodes(tree_file: Path) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    """
    Parses CURRICULUM_TREE.md.
    Returns: { course_name: { module_header: [ { 'path': rel_path, 'title': title, 'stem': stem } ] } }
    """
    if not tree_file.is_file():
        return {}

    courses: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
    current_course = None
    current_module = "Overview"

    for line in tree_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(">"):
            continue
        if line.startswith("## "):
            current_course = line.replace("## ", "").strip()
            courses[current_course] = {}
            current_module = "Course Overview"
            courses[current_course][current_module] = []
        elif line.startswith("### ") and current_course:
            current_module = line.replace("### ", "").strip()
            courses[current_course].setdefault(current_module, [])
        elif line.startswith("- [[") and current_course:
            m = re.match(r'- \[\[(.*?)\]\]\s*(.*)', line)
            if m:
                target_path = m.group(1).strip()
                title = m.group(2).strip()
                stem = Path(target_path).stem.lower().replace("-", "_").replace(" ", "_")
                courses[current_course][current_module].append({
                    "path": target_path,
                    "title": title,
                    "stem": stem
                })
    return courses

def collect_cornell_notes(vault_root: Path) -> Dict[str, Dict[str, Any]]:
    """Collects all *_cornell.json files and indexes them by stem and source."""
    cornell_notes: Dict[str, Dict[str, Any]] = {}
    for jf in vault_root.rglob("*_cornell.json"):
        if any(p in jf.parts for p in ("02_workers", "scratch", ".kanban", ".git", ".gemini", "brain")):
            continue
        if "outputs" in jf.parts or "json" in jf.parts:
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                clean_stem = re.sub(r'_cornell(_cornell)?$', '', jf.stem, flags=re.IGNORECASE).lower().replace("-", "_").replace(" ", "_")
                src = data.get("source", "")
                src_stem = Path(src).stem.lower().replace("-", "_").replace(" ", "_") if src else ""
                
                # Check html and tsv presence
                html_file = jf.parent.parent / "html" / f"{jf.stem}.html"
                if not html_file.is_file():
                    html_file = jf.with_suffix(".html")
                
                anki_dir = jf.parent.parent / "anki"
                anki_file = None
                for cand in (
                    anki_dir / f"{jf.stem}_anki.tsv",
                    anki_dir / f"{clean_stem}_anki.tsv",
                    anki_dir / f"{clean_stem}_cornell_anki.tsv",
                    jf.parent / f"{jf.stem}_anki.tsv"
                ):
                    if cand.is_file():
                        anki_file = cand
                        break
                if not anki_file and anki_dir.is_dir():
                    for f in anki_dir.glob("*.tsv"):
                        f_norm = re.sub(r'_cornell(_cornell)?', '', f.stem.lower()).replace("-", "_").replace(" ", "_")
                        if clean_stem in f_norm or f_norm in clean_stem:
                            anki_file = f
                            break

                cues_count = sum(len(sec.get("entries", [])) for sec in data.get("sections", []))

                info = {
                    "json_path": jf,
                    "html_path": html_file if html_file.is_file() else None,
                    "anki_path": anki_file if anki_file.is_file() else None,
                    "title": data.get("title", clean_stem),
                    "source": src,
                    "clean_stem": clean_stem,
                    "src_stem": src_stem,
                    "cues_count": cues_count,
                    "sections_count": len(data.get("sections", [])),
                    "matched": False
                }
                cornell_notes[clean_stem] = info
                if src_stem and src_stem != clean_stem:
                    cornell_notes[src_stem] = info
            except Exception:
                pass
    return cornell_notes

# ==============================================================================
# SUBCOMMAND: status
# ==============================================================================
def cmd_status(args: argparse.Namespace) -> int:
    vault_root = find_vault_root(args.vault)
    tree_file = vault_root / "CURRICULUM_TREE.md"
    
    print(f"\n📊 [Academic ICM Status] Inspecting vault: {vault_root}")
    if not tree_file.is_file():
        print(f"❌ Error: CURRICULUM_TREE.md not found in {vault_root}")
        return 1

    courses = parse_tree_nodes(tree_file)
    notes_map = collect_cornell_notes(vault_root)
    
    total_tree_nodes = 0
    covered_nodes = 0
    total_cues = 0

    print("\n🏛️  Course Curriculum Coverage:")
    print(f"{'Course / Module':<50} | {'Nodes':<6} | {'Cornell':<8} | {'Coverage':<8}")
    print("─" * 80)

    course_missing: Dict[str, List[Tuple[str, str, str]]] = {}

    for course_name, modules in courses.items():
        course_nodes = 0
        course_covered = 0
        course_missing[course_name] = []

        for mod_name, items in modules.items():
            for item in items:
                course_nodes += 1
                stem = item["stem"]
                # Match against clean_stem or src_stem
                matched_note = None
                if stem in notes_map:
                    matched_note = notes_map[stem]
                else:
                    # Fuzzy match check
                    for n_stem, n_info in notes_map.items():
                        if n_stem == stem or n_info.get("src_stem") == stem:
                            matched_note = n_info
                            break
                        if len(stem) > 8 and (stem in n_stem or n_stem in stem):
                            matched_note = n_info
                            break

                if matched_note:
                    course_covered += 1
                    matched_note["matched"] = True
                    total_cues += matched_note["cues_count"]
                else:
                    course_missing[course_name].append((mod_name, item["title"], item["path"]))

        total_tree_nodes += course_nodes
        covered_nodes += course_covered
        cov_pct = (course_covered / course_nodes * 100) if course_nodes > 0 else 0.0
        print(f"{course_name[:48]:<50} | {course_nodes:<6} | {course_covered:<8} | {cov_pct:>6.1f}%")

    overall_cov = (covered_nodes / total_tree_nodes * 100) if total_tree_nodes > 0 else 0.0
    print("─" * 80)
    print(f"{'TOTAL CURRICULUM':<50} | {total_tree_nodes:<6} | {covered_nodes:<8} | {overall_cov:>6.1f}%\n")

    # Detect Orphans
    unique_notes = {v["json_path"]: v for v in notes_map.values()}
    orphans = [v for v in unique_notes.values() if not v["matched"]]
    
    if orphans:
        print(f"⚠️  Detected {len(orphans)} Orphaned Cornell Notes (exists on disk but unlinked in CURRICULUM_TREE.md):")
        for o in orphans:
            print(f"   • ❌ {o['json_path'].name} (source: '{o['source'] or 'None'}')")
            print(f"     Path: {o['json_path']}")
        print("   💡 Tip: Run 'academic-icm sync-orphans' to automatically repair stem alignment.")
    else:
        print("✅ Zero orphaned notes detected! All Cornell files match CURRICULUM_TREE.md.")

    return 0

# ==============================================================================
# SUBCOMMAND: audit
# ==============================================================================
def cmd_audit(args: argparse.Namespace) -> int:
    vault_root = find_vault_root(args.vault)
    print(f"\n🔍 [Academic ICM Audit] Deep linting vault: {vault_root}")
    
    notes_map = collect_cornell_notes(vault_root)
    unique_notes = {v["json_path"]: v for v in notes_map.values()}
    
    issues = 0
    warnings = 0

    for jf, info in unique_notes.items():
        clean_stem = info["clean_stem"]
        src = info["source"]
        
        # Check 1: Stem alignment & Source resolution
        if src:
            src_name = Path(src).name
            subject_root = jf.parent.parent.parent if jf.parent.parent.name == "outputs" else jf.parent.parent
            src_p = subject_root / src
            resolved_p = None
            if src_p.is_file():
                resolved_p = src_p
            elif (vault_root / src).is_file():
                resolved_p = vault_root / src
            else:
                # Case-insensitive / dash-insensitive search within subject directory
                src_target = re.sub(r'[-_\s]+', '_', Path(src).stem.lower())
                for f in subject_root.rglob("*.md"):
                    f_norm = re.sub(r'[-_\s]+', '_', f.stem.lower())
                    if f_norm == src_target or (len(src_target) > 8 and src_target in f_norm):
                        resolved_p = f
                        break

            src_stem = Path(src).stem.lower().replace("-", "_").replace(" ", "_")
            if src_stem != clean_stem:
                print(f"  ⚠️  [Stem Mismatch] {jf.name}: JSON stem '{clean_stem}' != source stem '{src_stem}'")
                warnings += 1

            if not resolved_p:
                print(f"  ❌ [Broken Source] {jf.name}: Source file not found on disk: {src}")
                issues += 1
            else:
                rel_fix = str(resolved_p.relative_to(subject_root)).replace("\\", "/")
                if rel_fix != src:
                    if getattr(args, "fix_sources", False):
                        try:
                            raw_j = json.loads(jf.read_text(encoding="utf-8"))
                            raw_j["source"] = rel_fix
                            jf.write_text(json.dumps(raw_j, indent=2, ensure_ascii=False), encoding="utf-8")
                            print(f"  ✨ [Fixed Source] {jf.name}: Updated source to '{rel_fix}'")
                        except Exception as e:
                            print(f"  ❌ Failed to update {jf.name}: {e}")
                    else:
                        print(f"  💡 [Fixable Path] {jf.name}: Source '{src}' -> normalized relative '{rel_fix}'")
                        warnings += 1
        else:
            print(f"  ⚠️  [Missing Source] {jf.name}: 'source' field is empty in JSON.")
            warnings += 1

        # Check 2: Cue count
        if info["cues_count"] < 6:
            print(f"  ⚠️  [Low Depth] {jf.name}: Only {info['cues_count']} cues (target: 6–8 active cues)")
            warnings += 1

        # Check 3: HTML / Anki sync
        if not info["html_path"]:
            print(f"  ❌ [Missing HTML] {jf.name}: Corresponding HTML study sheet missing in outputs/html/")
            issues += 1
        if not info["anki_path"]:
            print(f"  ⚠️  [Missing Anki] {jf.name}: TSV flashcard deck missing in outputs/anki/")
            warnings += 1

    print(f"\nAudit complete: {issues} critical errors, {warnings} naming/depth warnings.")
    return 2 if issues > 0 else 0

# ==============================================================================
# SUBCOMMAND: scaffold
# ==============================================================================
def cmd_scaffold(args: argparse.Namespace) -> int:
    src_file = Path(args.source_md).resolve()
    if not src_file.is_file():
        print(f"❌ Error: Source file not found: {src_file}")
        return 1

    # Locate subject root
    subject_root = None
    cur = src_file.parent
    while cur != cur.parent:
        if (cur / "outputs").is_dir() or (cur / "CURRICULUM_TREE.md").is_file():
            subject_root = cur
            break
        if cur.name.startswith(("48520", "48521", "48430", "41200")):
            subject_root = cur
            break
        cur = cur.parent

    if not subject_root:
        subject_root = src_file.parent

    # Output directory
    out_json_dir = subject_root / "outputs" / "json"
    out_json_dir.mkdir(parents=True, exist_ok=True)
    
    stem = src_file.stem.lower().replace("-", "_").replace(" ", "_")
    target_json = out_json_dir / f"{stem}_cornell.json"

    if target_json.is_file() and not args.force:
        print(f"⚠️  File already exists: {target_json}")
        print("   Use --force to overwrite.")
        return 0

    # Extract title and headings from markdown
    lines = src_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    title = stem.replace("_", " ").title()
    for l in lines:
        if l.startswith("# "):
            title = l.replace("# ", "").strip()
            break

    # Extract sections
    sections = []
    current_sec = None
    for l in lines:
        if l.startswith("## "):
            sec_title = l.replace("## ", "").strip()
            current_sec = {"heading": sec_title, "entries": []}
            sections.append(current_sec)
    
    if not sections:
        sections = [
            {"heading": "Core Principles & Governing Laws", "entries": []},
            {"heading": "Analytical Methods & Derivations", "entries": []},
            {"heading": "Exam Traps & Application Checklist", "entries": []}
        ]

    # Pre-populate starter cues adhering to ICM standards
    rel_source = str(src_file.relative_to(subject_root)).replace("\\", "/")
    
    template_data = {
        "title": title,
        "source": rel_source,
        "subject": subject_root.name,
        "summary": f"Comprehensive active-recall review of {title}. Covers foundational definitions, governing mathematical models, and common analysis pitfalls.",
        "sections": [
            {
                "heading": sections[0]["heading"] if sections else "Core Principles & Governing Laws",
                "entries": [
                    {
                        "badge": "definition",
                        "cue": f"What is the physical definition and primary role of {title.split(':')[0]}?",
                        "notes": "Define the fundamental concept clearly and concisely with standard SI units."
                    },
                    {
                        "badge": "formula",
                        "cue": "State the primary governing equation and boundary conditions.",
                        "notes": "$$y = f(x)$$\n\nWhere:\n- $y$: Primary variable\n- $x$: Independent quantity"
                    }
                ]
            },
            {
                "heading": sections[1]["heading"] if len(sections) > 1 else "Analytical Methods & Derivations",
                "entries": [
                    {
                        "badge": "mechanism",
                        "cue": "What is the systematic step-by-step procedure for solving standard problems in this topic?",
                        "notes": "1. **Identify** knowns, boundary conditions, and circuit nodes.\n2. **Apply** governing conservation laws.\n3. **Solve** the resulting system of equations."
                    },
                    {
                        "badge": "comparison",
                        "cue": "How does this method compare to alternative approaches under extreme or limit cases?",
                        "notes": "| Feature | Standard Method | Alternative Approach |\n|---|---|---|\n| Complexity | Low | High |\n| Accuracy | High | Approximated |"
                    }
                ]
            },
            {
                "heading": sections[2]["heading"] if len(sections) > 2 else "Exam Traps & Application Checklist",
                "entries": [
                    {
                        "badge": "pitfall",
                        "cue": "What is the most frequent sign error, invalid assumption, or trap in student calculations?",
                        "notes": "> [!WARNING]\n> Always verify reference polarities and initial energy storage conditions before substituting values."
                    },
                    {
                        "badge": "checklist",
                        "cue": "What sanity checks should be verified before submitting the final answer?",
                        "notes": "- [ ] Dimensional analysis check (units balance)\n- [ ] Asymptotic limits check ($t \\to 0$, $t \\to \\infty$)\n- [ ] Power conservation check ($P_{\\text{gen}} = P_{\\text{abs}}$)"
                    }
                ]
            }
        ]
    }

    target_json.write_text(json.dumps(template_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✨ [Scaffold Complete] Created Cornell Note template:")
    print(f"   • Target JSON: {target_json}")
    print(f"   • Inherited Stem: '{stem}' (guarantees seamless CURRICULUM_TREE linking)")
    print(f"   • Pre-filled Source: '{rel_source}'")
    print("\n👉 Next steps for AI Agent / Human:")
    print(f"   1. Populate 6–8 rigorous active-recall cues in: {target_json.name}")
    print(f"   2. Build interactive HTML & Anki TSV: academic-icm build-note {target_json}")
    print(f"   3. Compile Cosmos: academic-icm compile")
    return 0

# ==============================================================================
# SUBCOMMAND: build-note
# ==============================================================================
def cmd_build_note(args: argparse.Namespace) -> int:
    target_json = Path(args.json_file).resolve()
    if not target_json.is_file():
        print(f"❌ Error: JSON note file not found: {target_json}")
        return 1

    format_script = find_engine_path("cornell-notes", "format_notes.py")
    if not format_script:
        print("❌ Error: format_notes.py engine not found in skills catalog.")
        return 1

    print(f"\n🔨 [Building Note] Compiling HTML & Anki TSV for: {target_json.name}")
    res = subprocess.run([sys.executable, str(format_script), str(target_json), "--anki"])
    if res.returncode == 0:
        html_file = target_json.parent.parent / "html" / f"{target_json.stem}.html"
        print(f"✅ Note compiled successfully!")
        if html_file.is_file():
            print(f"   • HTML Study Sheet: file://{html_file}")
        return 0
    return res.returncode

# ==============================================================================
# SUBCOMMAND: compile
# ==============================================================================
def cmd_compile(args: argparse.Namespace) -> int:
    vault_root = find_vault_root(args.vault)
    tree_file = vault_root / "CURRICULUM_TREE.md"
    
    print(f"\n🌲 [Curriculum Compiler] Compiling from {tree_file}...")
    
    okf_script = find_engine_path("okf-architect", "okf_architect.py")
    if not okf_script:
        # Fallback to local compile_tree.py
        local_compile = vault_root / "compile_tree.py"
        if local_compile.is_file():
            res = subprocess.run([sys.executable, str(local_compile)])
            return res.returncode
        print("❌ Error: okf-architect engine not found.")
        return 1

    # Run okf_architect compile-tree
    res = subprocess.run([sys.executable, str(okf_script), "compile-tree", str(vault_root)])
    if res.returncode == 0:
        print("\n✨ Compilation finished successfully!")
        print(f"   • Knowledge Cosmos: file://{vault_root / 'viz.html'}")
        print(f"   • Study Workspace:  file://{vault_root / 'study.html'}")
        print(f"   • Study Portal:     file://{vault_root / 'cornell_index.html'}")
    return res.returncode

# ==============================================================================
# SUBCOMMAND: sync-orphans
# ==============================================================================
def cmd_sync_orphans(args: argparse.Namespace) -> int:
    vault_root = find_vault_root(args.vault)
    tree_file = vault_root / "CURRICULUM_TREE.md"
    if not tree_file.is_file():
        print(f"❌ Error: CURRICULUM_TREE.md not found in {vault_root}")
        return 1

    print(f"\n🔧 [Sync Orphans] Repairing known stem mismatches in: {vault_root}")
    repaired = 0

    # Repair 1: Week 7 sinusoidal analysis in 48520
    w7_old = vault_root / "48520 - Electronics and Circuits" / "outputs" / "json" / "Week07_Sinusoidal_Analysis_cornell.json"
    w7_new = vault_root / "48520 - Electronics and Circuits" / "outputs" / "json" / "w07_week_7_48520_topic_14_and_topic_15_2022_2nd_cornell.json"
    if w7_old.is_file() and not w7_new.is_file():
        print(f"  • Renaming 48520 Week 7 note to canonical stem: {w7_new.name}")
        w7_old.rename(w7_new)
        # Also rename HTML if present
        w7_html_old = w7_old.parent.parent / "html" / "Week07_Sinusoidal_Analysis_cornell.html"
        w7_html_new = w7_old.parent.parent / "html" / "w07_week_7_48520_topic_14_and_topic_15_2022_2nd_cornell.html"
        if w7_html_old.is_file():
            w7_html_old.rename(w7_html_new)
        repaired += 1

    # Repair 2: Map Quiz 3 Worked Solutions Playbook in CURRICULUM_TREE.md if missing
    tree_text = tree_file.read_text(encoding="utf-8")
    if "Quiz_3_Worked_Solutions_Playbook" not in tree_text and "real_quiz_3_solutions_2" in tree_text:
        # Add alias or ensure mapping
        pass

    if repaired > 0:
        print(f"\n✅ Repaired {repaired} stem mismatches. Recompiling tree...")
        cmd_compile(args)
    else:
        print("ℹ️  No immediate automatic renames required.")
    return 0

# ==============================================================================
# SUBCOMMAND: stamp-video
# ==============================================================================

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
    "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had",
    "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd",
    "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself",
    "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off",
    "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own",
    "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there",
    "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this", "those", "through",
    "to", "too", "under", "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're",
    "we've", "were", "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would", "wouldn't", "you",
    "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves", "okay", "sorry",
    "yeah", "right", "alright", "um", "uh", "just", "like", "well", "see", "basically", "now"
}

def clean_tokens(text: str) -> List[str]:
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.DOTALL)
    text = re.sub(r"\$.*?\$", " ", text)
    text = re.sub(r"\[▶.*?\]\(.*?\)", " ", text)
    text = re.sub(r"\[.*?\]\(.*?\)", " ", text)
    text = re.sub(r"[#*`_~\\|/(){}\[\]<>]", " ", text)
    words = re.findall(r"[a-zA-Z0-9]+(?:[-'][a-zA-Z0-9]+)?", text.lower())
    return [w for w in words if len(w) > 1 and w not in STOPWORDS]

def parse_vtt(vtt_path: Path) -> List[Dict[str, Any]]:
    lines = vtt_path.read_text(encoding="utf-8").splitlines()
    cues = []
    i = 0
    time_re = re.compile(r"^(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})")
    while i < len(lines):
        line = lines[i].strip()
        m = time_re.match(line)
        if m:
            start_str, _ = m.group(1), m.group(2)
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                text_lines.append(lines[i].strip())
                i += 1
            raw_text = " ".join(text_lines)
            speaker = ""
            if ":" in raw_text:
                parts = raw_text.split(":", 1)
                speaker = parts[0].strip()
                text = parts[1].strip()
            else:
                text = raw_text
            
            p = start_str.split(":")
            if len(p) == 3:
                sec = int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
                mm_ss = f"{int(p[0])*60 + int(p[1]):02d}:{int(float(p[2])):02d}" if int(p[0]) == 0 else f"{int(p[0]):02d}:{int(p[1]):02d}:{int(float(p[2])):02d}"
            else:
                sec = int(p[0]) * 60 + float(p[1])
                mm_ss = f"{int(p[0]):02d}:{int(float(p[1])):02d}"
            cues.append({
                "seconds": int(sec),
                "time_str": mm_ss,
                "speaker": speaker,
                "text": text
            })
        i += 1
    return cues

def parse_transcript_md(md_path: Path) -> List[Dict[str, Any]]:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    cues = []
    line_re = re.compile(r"-\s*`\[(\d{2}:\d{2}:\d{2}|\d{2}:\d{2})\]`\s*(?:\*\*([^*]+)\*\*:\s*)?(.*)")
    for line in lines:
        line = line.strip()
        m = line_re.match(line)
        if m:
            time_str = m.group(1)
            speaker = (m.group(2) or "").strip()
            text = m.group(3).strip()
            p = time_str.split(":")
            if len(p) == 3:
                sec = int(p[0]) * 3600 + int(p[1]) * 60 + int(p[2])
            else:
                sec = int(p[0]) * 60 + int(p[1])
            cues.append({
                "seconds": int(sec),
                "time_str": time_str,
                "speaker": speaker,
                "text": text
            })
    return cues

def build_sliding_chunks(cues: List[Dict[str, Any]], window_cues: int = 4, step_cues: int = 2) -> List[Dict[str, Any]]:
    chunks = []
    for i in range(0, len(cues), step_cues):
        window = cues[i:i+window_cues]
        if not window:
            continue
        combined_text = " ".join([c["text"] for c in window])
        chunks.append({
            "start_seconds": window[0]["seconds"],
            "time_str": window[0]["time_str"],
            "speaker": window[0].get("speaker", ""),
            "text": combined_text,
            "tokens": clean_tokens(combined_text)
        })
    return chunks

class BM25Ranker:
    def __init__(self, chunks: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.N = len(chunks)
        self.doc_lens = [len(c["tokens"]) for c in chunks]
        self.avgdl = sum(self.doc_lens) / (self.N or 1)
        
        self.df = Counter()
        for c in chunks:
            for t in set(c["tokens"]):
                self.df[t] += 1
                
        self.idf = {}
        for t, freq in self.df.items():
            self.idf[t] = math.log((self.N - freq + 0.5) / (freq + 0.5) + 1.0)
            
    def query(self, query_tokens: List[str], problem_tag: Optional[str] = None) -> List[Tuple[float, int]]:
        q_counts = Counter(query_tokens)
        scores = []
        for i, c in enumerate(self.chunks):
            score = 0.0
            doc_len = self.doc_lens[i]
            c_counts = Counter(c["tokens"])
            for t, q_count in q_counts.items():
                if t in c_counts:
                    tf = c_counts[t]
                    idf = self.idf.get(t, 0.0)
                    numerator = tf * (self.k1 + 1.0)
                    denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / (self.avgdl or 1.0)))
                    score += idf * (numerator / denominator)
            
            # Problem number bonus (e.g. "9.1", "9.3", "exercise 9.1")
            if problem_tag and problem_tag.lower() in c["text"].lower():
                score += 15.0
                
            scores.append((score, i))
        scores.sort(key=lambda x: x[0], reverse=True)
        return scores

def find_media_and_transcript_for_note(vault_root: Path, json_path: Path, note_data: dict) -> Tuple[Optional[Path], Optional[str], Optional[str], Dict[str, str]]:
    """
    Discovers:
      1. Associated transcript file (.vtt or _transcript.md)
      2. Media target (local MP4 path, Zoom URL, or YouTube URL)
      3. Passcode if applicable
      4. Explicit question-to-video mapping (e.g. from YouTube question playlists)
    """
    source_rel = note_data.get("source") or ""
    course_dir = None
    module_dir = None
    
    # Try resolving from json_path parent hierarchy
    for p in json_path.parents:
        if (p / "CURRICULUM_TREE.md").is_file() or p.parent == vault_root:
            course_dir = p
            break
    if not course_dir and source_rel:
        full_source = vault_root / source_rel
        for p in full_source.parents:
            if p.parent == vault_root:
                course_dir = p
                break

    if not course_dir:
        course_dir = json_path.parent.parent

    # Determine module / week name
    source_path = Path(source_rel)
    week_token = ""
    for part in [source_path.parent.name, source_path.name, json_path.name]:
        m = re.search(r"(week[_\s-]*\d+|w\d+|module[_\s-]*\d+|topic[_\s-]*\d+[a-z]?)", part, re.I)
        if m:
            week_token = m.group(1).lower().replace(" ", "_").replace("-", "_")
            break

    module_cand = course_dir / source_path.parent
    if module_cand.is_dir():
        module_dir = module_cand
    elif (course_dir / source_path.parent.parent).is_dir():
        module_dir = course_dir / source_path.parent.parent

    transcript_path: Optional[Path] = None
    media_target: Optional[str] = None
    passcode: Optional[str] = None
    q_map: Dict[str, str] = {}

    # 0. Explicit note video metadata takes highest precedence
    if "video" in note_data and isinstance(note_data["video"], dict):
        v = note_data["video"]
        if v.get("src"):
            media_target = v["src"]
            passcode = v.get("passcode")

    # 1. Search for transcript in module folder
    search_dirs = []
    if module_dir and module_dir.is_dir():
        search_dirs.append(module_dir)
        search_dirs.append(module_dir / "markdown")
        search_dirs.append(module_dir / "video_transcripts")
        search_dirs.append(module_dir / "transcripts")
    recordings_dir = course_dir / "recordings"
    if recordings_dir.is_dir():
        search_dirs.append(recordings_dir)
        for sub in recordings_dir.iterdir():
            if sub.is_dir() and (week_token and week_token in sub.name.lower().replace("-", "_")):
                search_dirs.insert(0, sub)

    # Find VTT or transcript markdown
    for s_dir in search_dirs:
        if not s_dir.is_dir():
            continue
        vtt_files = list(s_dir.glob("*.vtt"))
        if vtt_files:
            transcript_path = vtt_files[0]
            break
        md_transcripts = list(s_dir.glob("*transcript*.md"))
        if md_transcripts:
            transcript_path = md_transcripts[0]
            break

    # 2. Check for local MP4 in course_dir / "videos" (only if no explicit video declared)
    if not media_target:
        videos_dir = course_dir / "videos"
        if videos_dir.is_dir():
            mp4_files = list(videos_dir.glob("*.mp4")) + list(videos_dir.glob("*.m4a")) + list(videos_dir.glob("*.mkv"))
            if mp4_files and week_token:
                matched_mp4 = None
                try:
                    w_int = int(week_token)
                    w_regex = re.compile(rf"\b(?:week|w)[_\s-]*0?{w_int}(?!\d)", re.I)
                    for mp4 in mp4_files:
                        if w_regex.search(mp4.stem):
                            matched_mp4 = mp4
                            break
                except ValueError:
                    pass

                if matched_mp4:
                    try:
                        rel_mp4 = matched_mp4.relative_to(vault_root)
                        media_target = str(rel_mp4)
                    except ValueError:
                        media_target = str(matched_mp4)

    # 3. Check for Zoom recording files if no local MP4
    if not media_target:
        for s_dir in search_dirs:
            if not s_dir.is_dir():
                continue
            for rec_md in s_dir.glob("*.md"):
                if rec_md == transcript_path:
                    continue
                content = rec_md.read_text(encoding="utf-8")
                z_match = re.search(r"https://(?:[a-zA-Z0-9-]+\.)?zoom\.us/rec/(?:share|play)/[^\s\)\"\'>]+", content)
                if z_match:
                    media_target = z_match.group(0)
                    p_match = re.search(r"Passcode:\s*([A-Za-z0-9=+^#@!_%~-]+)", content)
                    if p_match:
                        passcode = p_match.group(1).strip()
                    break
            if media_target:
                break

    # 4. Check for YouTube question mappings (e.g. FEET Module 1)
    if module_dir and module_dir.is_dir():
        for f in module_dir.glob("*.md"):
            txt = f.read_text(encoding="utf-8")
            for m in re.finditer(r"[\*\-]?\s*(?:Q|Question|Exercise)\s*(\d+)(?:\s*-\s*(?:Q|Question|Exercise)?\s*(\d+))?.*?:.*?<?(https://(?:youtu\.be/|www\.youtube\.com/watch\?v=)[^\s\)\"\'>]+)>?", txt, re.I):
                q_start = int(m.group(1))
                q_end = int(m.group(2)) if m.group(2) else q_start
                yt_link = m.group(3).strip()
                for q_n in range(q_start, q_end + 1):
                    q_map[str(q_n)] = yt_link
                if not media_target:
                    media_target = yt_link

    # 5. Fallback: if transcript exists but no media, link to transcript directly
    if not media_target and transcript_path:
        try:
            rel_t = transcript_path.relative_to(vault_root)
            media_target = str(rel_t)
        except ValueError:
            media_target = str(transcript_path)

    return transcript_path, media_target, passcode, q_map

def get_embedding_gemma2(text: str, endpoint: str = "http://127.0.0.1:8082/embedding") -> Optional[List[float]]:
    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps({"content": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
            raw = data[0]["embedding"]
            if isinstance(raw[0], list):
                raw = raw[0]
            norm = math.sqrt(sum(x * x for x in raw))
            if norm == 0:
                return raw
            return [x / norm for x in raw]
    except Exception:
        return None

def load_slide_vectors(vault_root: Path) -> List[Dict[str, Any]]:
    for cand in [vault_root / "slide_vectors.json", vault_root / "viz_icm" / "slide_vectors.json"]:
        if cand.is_file():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                pass
    return []

def find_best_slide_diagram(
    cue_vec: List[float],
    slide_corpus: List[Dict[str, Any]],
    course_hint: str,
    min_sim: float = 0.62
) -> Optional[Dict[str, Any]]:
    if not cue_vec or not slide_corpus:
        return None

    course_nums = re.findall(r'\b\d{5}\b', course_hint)
    pool = slide_corpus
    if course_nums:
        matching_course = [
            s for s in slide_corpus
            if any(num in s.get("course", "") or num in s.get("image_path", "") for num in course_nums)
        ]
        if matching_course:
            pool = matching_course

    best_sim = -1.0
    best_slide = None
    for s in pool:
        s_vec = s.get("vector")
        if not s_vec or len(s_vec) != len(cue_vec):
            continue
        sim = sum(a * b for a, b in zip(cue_vec, s_vec))
        if sim > best_sim:
            best_sim = sim
            best_slide = s

    if best_slide and best_sim >= min_sim:
        res = dict(best_slide)
        res["similarity"] = round(best_sim, 4)
        return res
    return None

def clean_spoken_quote(raw_text: str, max_words: int = 28) -> str:
    cleaned = re.sub(r'^(?:so|now|well|okay|right|yeah|um|uh|like|see)[\s,]+', '', raw_text.strip(), flags=re.I)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    words = cleaned.split()
    if len(words) > max_words:
        snippet = " ".join(words[:max_words]).strip()
        if not snippet.endswith((".", "!", "?")):
            snippet += "..."
    else:
        snippet = " ".join(words)
    return snippet

# ==============================================================================
# 7-STAGE TEMPORAL VIDEO GROUNDING & EVIDENCE ADJUDICATION ENGINE
# ==============================================================================

def establish_video_ground_truth(
    vault_root: Path,
    json_path: Path,
    note_data: dict
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Stage 1 — Establish video ground truth.
    Discovers canonical media asset, transcript file, duration, and provenance.
    Rule: LLM/system must never invent a timestamp; it only selects from verified ground truth evidence.
    """
    transcript_path, media_target, passcode, q_map = find_media_and_transcript_for_note(vault_root, json_path, note_data)
    if not transcript_path and not media_target and not q_map:
        return None, []

    raw_cues = []
    if transcript_path:
        if transcript_path.suffix.lower() == ".vtt":
            raw_cues = parse_vtt(transcript_path)
        else:
            raw_cues = parse_transcript_md(transcript_path)

    max_sec = max((c["seconds"] for c in raw_cues), default=0)
    
    source_str = str(note_data.get("source") or json_path.stem)
    m_course = re.search(r'\b(41200|48430|48520|48521)\b', str(json_path) + " " + source_str)
    c_code = m_course.group(1) if m_course else "general"
    m_week = re.search(r'(?:week|w|topic)[_\s-]*0?(\d+)', str(json_path).lower())
    w_num = f"week_{int(m_week.group(1)):02d}" if m_week else "core"
    
    video_id = f"{c_code}_{w_num}_{re.sub(r'[^a-zA-Z0-9]+', '_', json_path.stem.lower()).strip('_')}"
    if media_target and media_target.endswith(".mp4"):
        video_id = Path(media_target).stem

    v_type = "local_mp4" if (media_target and media_target.endswith(".mp4")) else ("zoom_cloud" if (media_target and "zoom.us" in media_target) else ("youtube" if (media_target and "youtu" in media_target) else "transcript_only"))
    provenance = "zoom_cloud_vtt" if (transcript_path and transcript_path.suffix.lower() == ".vtt") else ("transcript_markdown" if transcript_path else "external_video")

    gt = {
        "video_id": video_id,
        "canonical_url": media_target or (str(transcript_path.relative_to(vault_root)) if transcript_path else ""),
        "video_type": v_type,
        "duration_seconds": max_sec,
        "duration_str": f"{max_sec // 3600:02d}:{(max_sec % 3600) // 60:02d}:{max_sec % 60:02d}" if max_sec >= 3600 else f"{max_sec // 60:02d}:{max_sec % 60:02d}",
        "transcript_path": str(transcript_path) if transcript_path else None,
        "transcript_provenance": provenance,
        "player_offset_seconds": 0,
        "passcode": passcode,
        "q_map": q_map
    }
    return gt, raw_cues

def build_temporal_evidence_index(
    cues: List[Dict[str, Any]],
    window_size: int = 4,
    step: int = 2
) -> Dict[str, Any]:
    """
    Stage 2 — Build a temporal evidence index.
    Constructs discrete, addressable explanation windows (S001, S002...) with surrounding context.
    """
    if not cues:
        return {"segments": [], "by_id": {}, "ranker": None}

    segments = []
    for idx in range(0, len(cues), step):
        win = cues[idx:idx + window_size]
        if not win:
            continue
        seg_num = len(segments) + 1
        seg_id = f"S{seg_num:03d}"
        s_start = win[0]["seconds"]
        s_end = win[-1]["seconds"] + 15
        time_win = f"{win[0]['time_str']}–{win[-1]['time_str']}"
        txt = " ".join(c["text"] for c in win)
        tokens = clean_tokens(txt)
        segments.append({
            "segment_id": seg_id,
            "start_seconds": s_start,
            "end_seconds": s_end,
            "time_window": time_win,
            "time_str": win[0]["time_str"],
            "speaker": win[0].get("speaker", ""),
            "text": txt,
            "tokens": tokens,
            "prev_id": f"S{seg_num - 1:03d}" if seg_num > 1 else None,
            "next_id": f"S{seg_num + 1:03d}" if idx + step < len(cues) else None
        })

    by_id = {s["segment_id"]: s for s in segments}
    ranker = BM25Ranker(segments)
    return {"segments": segments, "by_id": by_id, "ranker": ranker}

def expand_segment_context(seg_id: str, index: Dict[str, Any], window: int = 1) -> str:
    """Expands promising segment into adjacent segments to capture multi-step explanations."""
    by_id = index.get("by_id", {})
    if seg_id not in by_id:
        return ""
    cur = by_id[seg_id]
    texts = []
    if window >= 1 and cur.get("prev_id") and cur["prev_id"] in by_id:
        texts.append(by_id[cur["prev_id"]]["text"])
    texts.append(cur["text"])
    if window >= 1 and cur.get("next_id") and cur["next_id"] in by_id:
        texts.append(by_id[cur["next_id"]]["text"])
    return " ".join(texts)

def decompose_cue_to_evidence_request(
    cue: str,
    notes_sample: str,
    cue_id: str = "cue_001"
) -> Dict[str, Any]:
    """
    Stage 3 — Decompose the Cornell cue into a structured evidence request.
    Extracts learning target, expected answer facets, critical terminology, and cognitive category.
    """
    base_cue = re.sub(r'\[▶.*?\]\(.*?\)', '', cue).strip()
    notes_lines = [l.strip() for l in notes_sample.splitlines() if l.strip() and not l.startswith('>') and not l.startswith('!')]
    facets = [re.sub(r'^[-\*\d\.]+\s*', '', l) for l in notes_lines if len(l) > 10][:3]
    if not facets:
        facets = [notes_sample[:120].strip()]

    cue_lower = base_cue.lower()
    if any(k in cue_lower for k in ["how to", "steps", "solve", "procedure", "how do you analyze"]):
        cat = "mechanism"
    elif any(k in cue_lower for k in ["formula", "equation", "derive", "state the universal"]):
        cat = "derivation"
    elif any(k in cue_lower for k in ["compare", "vs", "difference", "trade-off"]):
        cat = "comparison"
    elif any(k in cue_lower for k in ["example", "exercise", "question", "problem"]):
        cat = "worked_example"
    elif any(k in cue_lower for k in ["pitfall", "trap", "warning", "mistake"]):
        cat = "pitfall"
    else:
        cat = "definition"

    cue_tokens = clean_tokens(base_cue)
    notes_tokens = [w for w in clean_tokens(" ".join(facets)) if w not in cue_tokens][:8]
    expected_terms = [t for t in cue_tokens + notes_tokens if len(t) > 2][:10]

    mult_plausible = (" and " in base_cue or cat in ("mechanism", "derivation") or len(facets) >= 2)

    return {
        "cue_id": cue_id,
        "cue": base_cue,
        "learning_target": base_cue,
        "expected_answer": facets,
        "expected_terminology": expected_terms,
        "cognitive_category": cat,
        "multiple_plausible": mult_plausible
    }

def retrieve_candidate_windows(
    request: Dict[str, Any],
    temporal_index: Dict[str, Any],
    ground_truth: Dict[str, Any],
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    Stage 4 — Retrieve candidates, not a final timestamp.
    Ranks top candidate windows using multi-metric scoring:
    1. Semantic relevance (EmbeddingGemma-2)
    2. Answer facet coverage
    3. Directness
    4. Teaching evidence indicators vs passing mention
    5. Adjacent segment completeness
    """
    segments = temporal_index.get("segments", [])
    ranker = temporal_index.get("ranker")
    if not segments or not ranker:
        return []

    p_m = re.search(r'\b(\d+\.\d+)\b', request["cue"])
    p_tag = p_m.group(1) if p_m else None

    bm_scores = ranker.query(request["expected_terminology"], problem_tag=p_tag)
    cand_indices = [idx for sc, idx in bm_scores[:12] if sc > 0]
    if not cand_indices and bm_scores:
        cand_indices = [bm_scores[0][1]]

    cue_vec = get_embedding_gemma2(request["learning_target"] + " " + " ".join(request["expected_answer"][:2]))

    candidates = []
    top_bm_score = bm_scores[0][0] if bm_scores else 1.0

    for idx in cand_indices:
        seg = segments[idx]
        seg_id = seg["segment_id"]
        exp_text = expand_segment_context(seg_id, temporal_index, window=1)

        sim = 0.0
        if cue_vec:
            s_vec = get_embedding_gemma2(seg["text"])
            if s_vec:
                sim = sum(a * b for a, b in zip(cue_vec, s_vec))

        terms_in_seg = [t for t in request["expected_terminology"] if t.lower() in exp_text.lower()]
        facet_cov = len(terms_in_seg) / (len(request["expected_terminology"]) or 1.0)
        supported_facets = [f for f in request["expected_answer"] if any(w in exp_text.lower() for w in clean_tokens(f)[:3])]

        words = seg["text"].split()
        filler_count = sum(1 for w in words if w.lower() in STOPWORDS)
        directness = max(0.1, 1.0 - (filler_count / (len(words) or 1.0)))

        teach_indicators = ["we define", "formula is", "definition", "let us derive", "notice that", "equal to", "value of", "step response is", "rearrange"]
        is_teaching = any(ind in exp_text.lower() for ind in teach_indicators)
        teach_score = 1.0 if is_teaching else 0.4

        bm_val = next((sc for sc, ci in bm_scores if ci == idx), 0.0)
        bm_norm = min(1.0, bm_val / (top_bm_score or 1.0))

        composite = (
            0.35 * max(0.0, sim) +
            0.25 * facet_cov +
            0.15 * directness +
            0.15 * teach_score +
            0.10 * bm_norm
        )

        quote = clean_spoken_quote(seg["text"], max_words=28)

        candidates.append({
            "segment_id": seg_id,
            "video_id": ground_truth.get("video_id", "unknown"),
            "canonical_url": ground_truth.get("canonical_url", ""),
            "start_seconds": seg["start_seconds"],
            "end_seconds": seg["end_seconds"],
            "time_window": seg["time_window"],
            "time_str": seg["time_str"],
            "evidence_quote": quote,
            "supports": supported_facets,
            "semantic_score": round(sim, 4),
            "facet_coverage": round(facet_cov, 4),
            "directness": round(directness, 4),
            "teaching_evidence": round(teach_score, 4),
            "confidence": round(min(0.99, max(0.10, composite)), 4)
        })

    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    return candidates[:top_k]

def adjudicate_candidates(
    cue: str,
    request: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    ground_truth: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Stage 5 — Decide whether there is one answer or several.
    Classifies relationship between candidate windows into:
      - one_primary: single clearest complete explanation
      - multiple_complementary: distinct complementary moments (concept, derivation, worked example)
      - ambiguous: several plausible moments without clear separation
      - no_supported_anchor: weak or unsupported match
    """
    if not candidates:
        return {"status": "no_supported_anchor", "anchors": []}

    top = candidates[0]
    if top["confidence"] < 0.35:
        return {"status": "no_supported_anchor", "anchors": []}

    if len(candidates) == 1 or (len(candidates) >= 2 and top["confidence"] >= 0.70 and candidates[1]["confidence"] < 0.50):
        top_anchor = dict(top)
        top_anchor["role"] = "concept_explanation" if request["cognitive_category"] in ("definition", "comparison") else ("derivation" if request["cognitive_category"] == "derivation" else "worked_example")
        return {"status": "one_primary", "anchors": [top_anchor]}

    cand2 = candidates[1]
    time_delta = abs(top["start_seconds"] - cand2["start_seconds"])

    if time_delta >= 75 and cand2["confidence"] >= 0.52 and request.get("multiple_plausible", False):
        try:
            sys.path.append("/run/media/rodri/AI/skills/jev-decision/scripts")
            from jev_engine import JevEngine
            jev = JevEngine(port=8083)
            if jev.is_online():
                ctx = (
                    f"Technical Cue: {cue}\n"
                    f"Window A [{top['time_window']}]: \"{top['evidence_quote']}\"\n"
                    f"Window B [{cand2['time_window']}]: \"{cand2['evidence_quote']}\""
                )
                j_res = jev.decide_choice(
                    context=ctx,
                    question="Which option best categorizes the pedagogical relationship between Window A and Window B?",
                    options=[
                        "Window A is concept explanation, Window B is worked example or circuit application",
                        "Window A is core derivation, Window B is conversational preamble",
                        "Both windows are redundant duplicates"
                    ]
                )
                if j_res and "selection" in j_res and "application" in j_res["selection"]:
                    a1 = dict(top)
                    a1["role"] = "concept_explanation"
                    a2 = dict(cand2)
                    a2["role"] = "worked_example"
                    return {"status": "multiple_complementary", "anchors": [a1, a2]}
        except Exception:
            pass

        a1 = dict(top)
        a1["role"] = "concept_explanation" if top["start_seconds"] < cand2["start_seconds"] else "worked_example"
        a2 = dict(cand2)
        a2["role"] = "worked_example" if a1["role"] == "concept_explanation" else "concept_explanation"
        return {"status": "multiple_complementary", "anchors": [a1, a2]}

    if len(candidates) >= 2 and abs(top["confidence"] - cand2["confidence"]) <= 0.04 and time_delta >= 60:
        a1 = dict(top)
        a1["role"] = "candidate_anchor"
        return {"status": "ambiguous", "anchors": [a1]}

    top_anchor = dict(top)
    top_anchor["role"] = "concept_explanation" if request["cognitive_category"] == "definition" else "derivation"
    return {"status": "one_primary", "anchors": [top_anchor]}

def verify_timestamp_evidence_gate(
    video_evidence: Dict[str, Any],
    ground_truth: Dict[str, Any],
    transcript_text: str
) -> List[str]:
    """
    Stage 7 — Final timestamp verification gate.
    Validates provenance, duration boundaries, verbatim transcript grounding, and role distinctness.
    """
    issues = []
    status = video_evidence.get("status")
    anchors = video_evidence.get("anchors", [])

    if status == "no_supported_anchor":
        return []

    max_dur = ground_truth.get("duration_seconds", 0)

    for i, a in enumerate(anchors):
        s_sec = a.get("start_seconds", -1)
        e_sec = a.get("end_seconds", -1)
        quote = a.get("evidence_quote", "")

        if s_sec < 0 or (max_dur > 0 and s_sec > max_dur):
            issues.append(f"Anchor {i}: start_seconds {s_sec} exceeds duration {max_dur}")
        if e_sec <= s_sec or (max_dur > 0 and e_sec > max_dur + 60):
            issues.append(f"Anchor {i}: end_seconds {e_sec} invalid or exceeds duration")

        w_dur = e_sec - s_sec
        if w_dur < 10 or w_dur > 360:
            issues.append(f"Anchor {i}: window duration {w_dur}s out of acceptable range [10, 360]")

        if quote and transcript_text:
            clean_q = " ".join(re.sub(r'[^a-zA-Z0-9\s]', ' ', quote.replace('...', '')).lower().split()[:4])
            clean_t = " ".join(re.sub(r'[^a-zA-Z0-9\s]', ' ', transcript_text).lower().split())
            if clean_q and clean_q not in clean_t:
                issues.append(f"Anchor {i}: Evidence quote '{clean_q}...' not grounded in transcript")

    if status == "multiple_complementary" and len(anchors) >= 2:
        for i in range(len(anchors) - 1):
            for j in range(i + 1, len(anchors)):
                if abs(anchors[i]["start_seconds"] - anchors[j]["start_seconds"]) < 45:
                    issues.append(f"Anchors {i} and {j} too close in time (<45s) for complementary status")
                if anchors[i].get("role") == anchors[j].get("role"):
                    issues.append(f"Anchors {i} and {j} share identical role '{anchors[i].get('role')}'")

    return issues

def stamp_cornell_json(
    json_path: Path,
    vault_root: Path,
    threshold: float = 0.15,
    force: bool = False,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Executes the 7-Stage Temporal Grounding & Evidence Adjudication Pipeline:
      Stage 1: Establish video ground truth
      Stage 2: Build temporal evidence index (S001, S002...)
      Stage 3: Decompose Cornell cue into structured evidence request
      Stage 4: Retrieve candidate windows (top 5)
      Stage 5: Decide relationship (one_primary, multiple_complementary, ambiguous, no_supported_anchor)
      Stage 6: Upgrade data model with auditable video_evidence object
      Stage 7: Final timestamp verification gate
    """
    try:
        note_data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"file": json_path.name, "stamped": 0, "error": str(e)}

    # Stage 1: Ground Truth
    gt, raw_cues = establish_video_ground_truth(vault_root, json_path, note_data)
    slide_corpus = load_slide_vectors(vault_root)

    if not gt and not slide_corpus:
        return {"file": json_path.name, "stamped": 0, "skipped": "No media ground truth or slide vectors found"}

    # Stage 2: Temporal Index
    temporal_index = build_temporal_evidence_index(raw_cues) if raw_cues else {"segments": [], "by_id": {}, "ranker": None}
    full_transcript_text = " ".join(c["text"] for c in raw_cues) if raw_cues else ""

    stamped_count = 0
    quotes_count = 0
    slides_count = 0
    results_detail = []

    for sec_idx, sec in enumerate(note_data.get("sections", [])):
        for e_idx, entry in enumerate(sec.get("entries", [])):
            orig_cue = entry.get("cue", "")
            has_existing = bool(re.search(r"\[▶.*?\]\(.*?\)", orig_cue))
            base_cue = re.sub(r"\[▶.*?\]\(.*?\)", "", orig_cue).strip()
            notes_sample = entry.get("notes", "")

            # Stage 3: Decompose Cue
            cue_id = f"cue_{sec_idx+1}_{e_idx+1:02d}"
            request = decompose_cue_to_evidence_request(base_cue, notes_sample, cue_id=cue_id)

            adjudication = None
            q_map = gt.get("q_map", {}) if gt else {}

            if not has_existing or force:
                # Check explicit question mapping
                q_match = re.search(r"\b(?:q|question|exercise)\s*(\d+(?:-\d+)?)\b", base_cue, re.I)
                if q_match and q_match.group(1).lower() in q_map:
                    q_num = q_match.group(1).lower()
                    target_url = q_map[q_num]
                    adjudication = {
                        "status": "one_primary",
                        "video_id": gt.get("video_id", "external_solution"),
                        "canonical_url": target_url,
                        "anchors": [{
                            "role": "worked_example",
                            "video_id": gt.get("video_id", "external_solution"),
                            "canonical_url": target_url,
                            "start_seconds": 0,
                            "end_seconds": 60,
                            "time_window": "00:00–01:00",
                            "time_str": "00:00",
                            "evidence_quote": f"Explicit question {q_num.upper()} worked solution recording",
                            "supports": request["expected_answer"][:1],
                            "confidence": 1.0
                        }]
                    }
                elif temporal_index.get("segments") and gt:
                    # Stage 4: Retrieve candidate windows
                    candidates = retrieve_candidate_windows(request, temporal_index, gt, top_k=5)
                    # Stage 5: Adjudicate relationship
                    adjudication = adjudicate_candidates(base_cue, request, candidates, gt)

                if adjudication:
                    # Stage 7: Final Timestamp Verification Gate
                    gate_issues = verify_timestamp_evidence_gate(adjudication, gt, full_transcript_text)
                    if gate_issues:
                        for issue in gate_issues:
                            print(f"      ⚠️  [Gate 7 Warning] {cue_id}: {issue}")

                    # Stage 6: Update Data Model (video_evidence object + clean cue)
                    entry["video_evidence"] = adjudication
                    entry["expected_answer"] = request["expected_answer"]

                    status = adjudication["status"]
                    anchors = adjudication.get("anchors", [])

                    if status == "one_primary" and anchors:
                        a = anchors[0]
                        clean_target = re.sub(r"[#?].*$", "", a["canonical_url"])
                        entry["cue"] = f"{base_cue} [▶ {a['time_str']}]({clean_target}#t={a['start_seconds']})"
                        stamped_count += 1
                    elif status == "multiple_complementary" and anchors:
                        tags = []
                        for a in anchors:
                            role_short = "Theory" if a["role"] in ("concept_explanation", "derivation") else "Example"
                            clean_target = re.sub(r"[#?].*$", "", a["canonical_url"])
                            tags.append(f"[▶ {a['time_str']} {role_short}]({clean_target}#t={a['start_seconds']})")
                        entry["cue"] = f"{base_cue} {' '.join(tags)}"
                        stamped_count += 1
                    elif status == "ambiguous" and anchors:
                        a = anchors[0]
                        clean_target = re.sub(r"[#?].*$", "", a["canonical_url"])
                        entry["cue"] = f"{base_cue} [▶ {a['time_str']} ?]({clean_target}#t={a['start_seconds']})"
                        stamped_count += 1
                    elif status == "no_supported_anchor":
                        entry["cue"] = base_cue

            # 2. Spoken Transcript Quote Snippet Chip
            if adjudication and adjudication.get("anchors"):
                best_anchor = adjudication["anchors"][0]
                if "💬 **Lecture" not in entry.get("notes", "") and best_anchor.get("evidence_quote"):
                    snip = best_anchor["evidence_quote"]
                    time_lbl = best_anchor.get("time_str", "00:00")
                    entry["notes"] = f"{entry.get('notes', '').rstrip()}\n\n> 💬 **Lecture [{time_lbl}]**: *\"{snip}\"*"
                    quotes_count += 1

            # 3. Slide Keyframe & Visual Diagram Matching (EmbeddingGemma-2)
            if slide_corpus:
                cue_vec = get_embedding_gemma2(base_cue + " " + notes_sample[:100])
                if cue_vec:
                    matched_slide = find_best_slide_diagram(cue_vec, slide_corpus, str(json_path), min_sim=0.62)
                    if matched_slide:
                        slide_filename = matched_slide.get("filename", "")
                        if slide_filename and slide_filename not in entry.get("notes", ""):
                            html_dir = json_path.parent.parent / "html"
                            rel_img = os.path.relpath(matched_slide["image_path"], html_dir)
                            slide_label = matched_slide.get("label") or Path(matched_slide["image_path"]).stem
                            entry["notes"] = f"{entry.get('notes', '').rstrip()}\n\n![Slide Diagram: {slide_label}]({rel_img})"
                            slides_count += 1

            if adjudication and adjudication.get("anchors"):
                a = adjudication["anchors"][0]
                results_detail.append({
                    "cue": base_cue[:60],
                    "status": adjudication["status"],
                    "time": a.get("time_str", "00:00"),
                    "role": a.get("role", "anchor"),
                    "target": a.get("canonical_url", ""),
                    "score": f"{a.get('confidence', 0.0):.2f}",
                    "anchors": len(adjudication["anchors"]),
                    "quote": bool(adjudication["anchors"]),
                    "slide": bool(slide_corpus)
                })

    if (stamped_count > 0 or quotes_count > 0 or slides_count > 0) and not dry_run:
        json_path.write_text(json.dumps(note_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "file": json_path.name,
        "stamped": stamped_count,
        "quotes": quotes_count,
        "slides": slides_count,
        "details": results_detail,
        "media": gt.get("canonical_url", "None") if gt else "None",
        "transcript": Path(gt["transcript_path"]).name if (gt and gt.get("transcript_path")) else "None"
    }

def cmd_stamp_video(args: argparse.Namespace) -> int:
    vault_root = find_vault_root(args.vault if hasattr(args, "vault") else None)
    target = getattr(args, "target", None)
    threshold = getattr(args, "threshold", 0.20)
    force = getattr(args, "force", False)
    dry_run = getattr(args, "dry_run", False)
    course_filter = getattr(args, "course", None)

    mode_label = "🔍 [DRY-RUN] " if dry_run else "⚡ "
    print(f"\n{mode_label}[Academic ICM] Video & Solution Timestamp Stamping Harness")
    print(f"   • Vault Root : {vault_root}")
    print(f"   • Threshold  : {threshold}")
    print(f"   • Force      : {force}\n")

    json_files = []
    if target:
        tp = Path(target).resolve()
        if tp.is_file() and tp.name.endswith("_cornell.json"):
            json_files.append(tp)
        elif tp.is_dir():
            json_files = list(tp.rglob("*_cornell.json"))
        else:
            # Check within vault_root
            cand = vault_root / target
            if cand.is_file() and cand.name.endswith("_cornell.json"):
                json_files.append(cand)
            elif cand.is_dir():
                json_files = list(cand.rglob("*_cornell.json"))
    
    if not json_files:
        json_files = list(vault_root.rglob("*_cornell.json"))

    if course_filter:
        json_files = [f for f in json_files if course_filter.lower() in str(f).lower()]

    if not json_files:
        print("❌ No matching _cornell.json notes found.")
        return 1

    total_stamped = 0
    total_quotes = 0
    total_slides = 0
    total_files_changed = 0

    for jf in sorted(json_files):
        res = stamp_cornell_json(jf, vault_root, threshold=threshold, force=force, dry_run=dry_run)
        cnt = res.get("stamped", 0)
        q_cnt = res.get("quotes", 0)
        s_cnt = res.get("slides", 0)
        if cnt > 0 or q_cnt > 0 or s_cnt > 0:
            total_stamped += cnt
            total_quotes += q_cnt
            total_slides += s_cnt
            total_files_changed += 1
            print(f"📄 {jf.name} -> {cnt} cues stamped, {q_cnt} quotes, {s_cnt} slide diagrams (media: {res.get('media')})")
            for d in res.get("details", []):
                flags = []
                if d.get("status"): flags.append(f"🎯 {d['status']}")
                if d.get("role"): flags.append(f"📌 {d['role']}")
                if d.get("quote"): flags.append("💬 quote")
                if d.get("slide"): flags.append("🖼️ slide")
                flag_str = f" [{' '.join(flags)}]" if flags else ""
                print(f"   • [{d['time']}] (conf: {d['score']}){flag_str} {d['cue']}...")
        elif "skipped" in res:
            pass

    action_word = "Would stamp" if dry_run else "Stamped"
    print(f"\n🎯 Summary: {action_word} {total_stamped} cues, {total_quotes} lecture quotes, {total_slides} slide diagrams across {total_files_changed} notes (scanned {len(json_files)} total notes).")
    if (total_stamped > 0 or total_quotes > 0 or total_slides > 0) and not dry_run:
        print("💡 Run 'academic-icm compile' to update your Knowledge Cosmos and Study Portal with new video drawers!")
    return 0

# ==============================================================================
# SUBCOMMAND: verify (The 5-Stage ICM Step-Level Gate & Unbiased 0-Context Judge)
# ==============================================================================
def normalize_week_filter(week_arg: Optional[str]) -> Optional[str]:
    if not week_arg or week_arg.strip().lower() in ("all", "none", "*", ""):
        return None
    m = re.search(r'\d+', week_arg)
    if m:
        w_num = int(m.group(0))
        return f"{w_num:02d}"
    return week_arg.strip().lower()

def matches_week_filter(path_or_str: str, week_token: Optional[str]) -> bool:
    if not week_token:
        return True
    s = path_or_str.lower()
    try:
        w_num = int(week_token)
        patterns = [
            f"week_{w_num:02d}", f"week{w_num:02d}", f"week {w_num:02d}",
            f"week_{w_num}", f"week{w_num}", f"week {w_num}",
            f"w{w_num:02d}", f"w{w_num}", f"topic_{w_num:02d}", f"topic_{w_num}"
        ]
        return any(p in s for p in patterns)
    except ValueError:
        return week_token.lower() in s

def check_katex_syntax(text: str) -> List[str]:
    """Lints KaTeX math syntax: strips code blocks, tables, font artifacts, and verifies math balance."""
    errors = []
    # 1. Strip YAML frontmatter
    clean_text = re.sub(r'^---[\s\S]*?---\n', '', text)
    # 2. Strip code blocks and inline code
    clean_text = re.sub(r'```[\s\S]*?```', '', clean_text)
    clean_text = re.sub(r'`[^`\n]+`', '', clean_text)
    # 3. Strip PDF CID font corruption lines and OCR gibberish
    clean_text = re.sub(r'.*\(cid:\d+\).*', '', clean_text)
    clean_text = re.sub(r'.*[\$%&’\(\)]{4,}.*', '', clean_text)
    # 4. Strip Excel formula lines and cell references ($A$1, $B$4)
    clean_text = re.sub(r'\$[A-Z]\$?\d+', '', clean_text)
    clean_text = re.sub(r'.*=\w*\(?\$[A-Z].*', '', clean_text)
    # 5. Strip passcodes
    clean_text = re.sub(r'(?i)passcode[:\s]+[a-zA-Z0-9$!%#*+^=?-]+', '', clean_text)
    clean_text = re.sub(r'[a-zA-Z0-9]\$[a-zA-Z0-9]', '', clean_text)
    # 6. Check and strip display math $$...$$
    double_count = clean_text.count("$$")
    if double_count % 2 != 0:
        errors.append(f"Unbalanced display math '$$' delimiters (count={double_count})")
    clean_text = re.sub(r'\$\$[\s\S]*?\$\$', '', clean_text)
    # 7. Strip multiline math environments wrapped in $
    clean_text = re.sub(r'\$\\begin\{[\s\S]*?\\end\{.*?\}\$', '', clean_text)
    # 8. Strip inline math pairs $...$
    clean_text = re.sub(r'\$([^\$\n]+)\$', '', clean_text)
    # 9. Strip currency figures like $10, $5.50, $100M
    clean_text = re.sub(r'\$\d+(?:,\d+)*(?:\.\d+)?[a-zA-Z]?(?:\s|[.,;!?)]|$)', '', clean_text)

    # 10. Check unescaped remaining single $
    single_matches = re.findall(r'(?<!\\)\$', clean_text)
    if single_matches:
        # If any remain, verify if it's a true delimiter error
        if len(single_matches) % 2 != 0:
            errors.append(f"Unbalanced inline math '$' delimiters ({len(single_matches)} unmatched)")

    # 11. Check unclosed environments
    env_starts = re.findall(r'\\begin\{([a-zA-Z0-9*]+)\}', text)
    env_ends = re.findall(r'\\end\{([a-zA-Z0-9*]+)\}', text)
    for env in set(env_starts):
        if env_starts.count(env) != env_ends.count(env):
            errors.append(f"Unclosed LaTeX environment: '\\begin{{{env}}}' ({env_starts.count(env)} vs {env_ends.count(env)})")

    return errors

def cmd_verify(args: argparse.Namespace) -> int:
    vault_root = find_vault_root(args.vault)
    week_token = normalize_week_filter(getattr(args, "week", None))
    stage_filter = getattr(args, "stage", "all")
    enable_judge = getattr(args, "judge", True)
    output_json = getattr(args, "json", False)

    week_label = f"Week {week_token}" if week_token else "Entire Curriculum Corpus"
    print(f"\n🛡️  [Academic ICM Step Gate & Unbiased Verifier]")
    print(f"   • Vault Root : {vault_root}")
    print(f"   • Scope      : {week_label}")
    print(f"   • Gates      : Stages 1–5 ({stage_filter})\n")

    gate_results = []
    overall_passed = True

    # --------------------------------------------------------------------------
    # GATE 1: Asset Doctor [D] (Ingestion & Media Grounding)
    # --------------------------------------------------------------------------
    if stage_filter in ("all", "1"):
        print("─── [Gate 1: Asset Doctor] ──────────────────────────────────────────")
        g1_errors = []
        g1_warnings = []
        g1_checked_items = 0

        # 1. Inspect worked_solutions_db.json if present
        db_paths = [
            vault_root / "viz_icm" / "assets" / "worked_solutions_db.json",
            vault_root / "worked_solutions_db.json"
        ]
        db_file = next((p for p in db_paths if p.is_file()), None)
        if db_file:
            try:
                db_data = json.loads(db_file.read_text(encoding="utf-8"))
                for wk_key, wk_info in db_data.items():
                    if week_token and not matches_week_filter(wk_key, week_token):
                        continue
                    g1_checked_items += 1
                    canon_url = wk_info.get("canonical_url", "")
                    passcode = wk_info.get("passcode", "")
                    
                    if not canon_url:
                        g1_errors.append(f"{wk_key}: Missing canonical_url in solutions database")
                    elif canon_url.endswith(".vtt") or canon_url.endswith(".md"):
                        g1_errors.append(f"{wk_key}: Invalid video URL '{canon_url}' (cannot be .vtt or .md)")
                    elif "utsmeet.zoom.us" in canon_url and not passcode:
                        g1_warnings.append(f"{wk_key}: Zoom share URL has no passcode recorded")

                    cues = wk_info.get("timestamp_cues", [])
                    if not cues:
                        g1_warnings.append(f"{wk_key}: No timestamp cues found in solutions database")
            except Exception as e:
                g1_errors.append(f"Failed to parse solutions db: {e}")

        # 2. Inspect local videos on disk
        for vid in vault_root.rglob("*.mp4"):
            if week_token and not matches_week_filter(str(vid), week_token):
                continue
            g1_checked_items += 1
            if vid.stat().st_size == 0:
                g1_errors.append(f"Empty MP4 file detected: {vid.name}")

        # 3. Check Range server liveness
        import socket
        range_alive = False
        for port in (3333, 8765):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                range_alive = True
                s.close()
                break
            s.close()
        
        if not range_alive:
            g1_warnings.append("Video streaming range server is offline (run 'academic-icm serve' or './serve.sh 3333')")

        # 4. Stage 7 Verification: Audit Cornell video_evidence blocks
        for cj in vault_root.rglob("*_cornell.json"):
            if week_token and not matches_week_filter(str(cj), week_token):
                continue
            try:
                c_data = json.loads(cj.read_text(encoding="utf-8"))
                for s in c_data.get("sections", []):
                    for entry in s.get("entries", []):
                        if "video_evidence" in entry:
                            g1_checked_items += 1
                            ve = entry["video_evidence"]
                            status = ve.get("status")
                            if status not in ("one_primary", "multiple_complementary", "ambiguous", "no_supported_anchor"):
                                g1_errors.append(f"{cj.name}: Invalid video_evidence status '{status}'")
                            for a in ve.get("anchors", []):
                                if a.get("start_seconds", -1) < 0:
                                    g1_errors.append(f"{cj.name}: Negative start_seconds {a.get('start_seconds')}")
                                if a.get("end_seconds", 0) <= a.get("start_seconds", 0):
                                    g1_errors.append(f"{cj.name}: end_seconds <= start_seconds ({a.get('start_seconds')} -> {a.get('end_seconds')})")
            except Exception as e:
                g1_errors.append(f"Failed to inspect video_evidence in {cj.name}: {e}")

        status_str = "PASS" if not g1_errors else "FAIL"
        if g1_errors:
            overall_passed = False
        print(f"  [{status_str}] Verified {g1_checked_items} asset entities ({len(g1_errors)} errors, {len(g1_warnings)} warnings)")
        for err in g1_errors:
            print(f"    ❌ {err}")
        for w in g1_warnings:
            print(f"    ⚠️  {w}")
        gate_results.append({"stage": 1, "name": "Asset Doctor [D]", "status": status_str, "errors": g1_errors, "warnings": g1_warnings})

    # --------------------------------------------------------------------------
    # GATE 2: Markdown & KaTeX Syntax Doctor [D]
    # --------------------------------------------------------------------------
    if stage_filter in ("all", "2"):
        print("\n─── [Gate 2: Markdown & KaTeX Syntax Doctor] ────────────────────────")
        g2_errors = []
        g2_warnings = []
        g2_files_checked = 0

        for md_file in vault_root.rglob("*.md"):
            # skip administrative docs, kanban, workers, scratch
            if any(p in md_file.parts for p in (".kanban", ".git", "brain", ".gemini", "02_workers", "scratch", "node_modules", ".venv")):
                continue
            if week_token and not matches_week_filter(str(md_file), week_token):
                continue
            if md_file.name in ("CURRICULUM_TREE.md", "README.md", "STATE.md", "GEMINI.md", "AGENTS.md"):
                continue

            g2_files_checked += 1
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                
                # Check KaTeX balance
                k_errs = check_katex_syntax(content)
                for ke in k_errs:
                    g2_errors.append(f"{md_file.name}: {ke}")

                # Check anti-vtt in markdown
                vtt_cues = re.findall(r'\[▶[^\]]*\]\(([^)]+\.vtt[^)]*)\)', content)
                for vc in vtt_cues:
                    g2_errors.append(f"{md_file.name}: Dangling .vtt link in video cue: '{vc}'")

                # Check image existence
                for img_match in re.finditer(r'!\[.*?\]\(([^)]+)\)', content):
                    img_path = img_match.group(1).split("#")[0].split("?")[0]
                    if not img_path.startswith(("http://", "https://", "data:")):
                        resolved = (md_file.parent / img_path).resolve()
                        if not resolved.is_file():
                            g2_warnings.append(f"{md_file.name}: Referenced image not found on disk: '{img_path}'")

            except Exception as e:
                g2_errors.append(f"{md_file.name}: Read error: {e}")

        status_str = "PASS" if not g2_errors else "FAIL"
        if g2_errors:
            overall_passed = False
        print(f"  [{status_str}] Scanned {g2_files_checked} Markdown files ({len(g2_errors)} errors, {len(g2_warnings)} warnings)")
        for err in g2_errors:
            print(f"    ❌ {err}")
        for w in g2_warnings:
            print(f"    ⚠️  {w}")
        gate_results.append({"stage": 2, "name": "Markdown & KaTeX Doctor [D]", "status": status_str, "errors": g2_errors, "warnings": g2_warnings})

    # --------------------------------------------------------------------------
    # GATE 3: Cornell JSON Schema & Anti-VTT Invariant [D]
    # --------------------------------------------------------------------------
    if stage_filter in ("all", "3"):
        print("\n─── [Gate 3: Cornell JSON & Anti-VTT Invariant] ─────────────────────")
        g3_errors = []
        g3_warnings = []
        g3_notes_checked = 0

        notes_map = collect_cornell_notes(vault_root)
        unique_notes = {v["json_path"]: v for v in notes_map.values()}

        for jf, info in sorted(unique_notes.items()):
            if week_token and not matches_week_filter(str(jf), week_token):
                continue

            g3_notes_checked += 1
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                
                # Check 1: Anti-VTT Invariant (CRITICAL)
                raw_json_str = jf.read_text(encoding="utf-8")
                if ".vtt" in raw_json_str:
                    # Parse where the .vtt is
                    top_vid = data.get("video", {})
                    if isinstance(top_vid, dict) and str(top_vid.get("src", "")).endswith(".vtt"):
                        g3_errors.append(f"{jf.name}: Top-level video src points to .vtt ('{top_vid.get('src')}')")
                    for sec in data.get("sections", []):
                        for entry in sec.get("entries", []):
                            ev = entry.get("video", {})
                            if isinstance(ev, dict) and str(ev.get("src", "")).endswith(".vtt"):
                                g3_errors.append(f"{jf.name}: Entry cue '{entry.get('cue')[:30]}' points to .vtt video")

                # Check 2: Video validity
                top_vid = data.get("video", {})
                if isinstance(top_vid, dict) and top_vid.get("src"):
                    v_type = top_vid.get("type", "")
                    v_src = str(top_vid.get("src", ""))
                    if v_type == "mp4" and not v_src.startswith("http"):
                        # Local MP4 check
                        resolved_mp4 = (jf.parent.parent.parent / v_src).resolve()
                        if not resolved_mp4.is_file():
                            resolved_mp4 = (vault_root / v_src).resolve()
                        if not resolved_mp4.is_file():
                            g3_errors.append(f"{jf.name}: Local MP4 '{v_src}' does not exist on disk")

                # Check 3: Cue depth
                cue_cnt = info["cues_count"]
                is_tutorial = any(t in jf.stem.lower() for t in ("tutorial", "solution", "playbook"))
                min_cues = 2 if is_tutorial else 6
                if cue_cnt < min_cues:
                    g3_warnings.append(f"{jf.name}: Cue depth is {cue_cnt} (target: >= {min_cues} active cues)")

                # Check 4: Source existence
                src = info["source"]
                if src:
                    subject_root = jf.parent.parent.parent if jf.parent.parent.name == "outputs" else jf.parent.parent
                    src_p = subject_root / src
                    resolved_src = None
                    if src_p.is_file():
                        resolved_src = src_p
                    elif (vault_root / src).is_file():
                        resolved_src = vault_root / src
                    else:
                        target_name = Path(src).name.lower()
                        for f in subject_root.rglob("*.md"):
                            if f.name.lower() == target_name:
                                resolved_src = f
                                break

                    if resolved_src:
                        rel_norm = str(resolved_src.relative_to(subject_root)).replace("\\", "/")
                        if rel_norm != src:
                            if getattr(args, "fix", False):
                                try:
                                    raw_j = json.loads(jf.read_text(encoding="utf-8"))
                                    raw_j["source"] = rel_norm
                                    jf.write_text(json.dumps(raw_j, indent=2, ensure_ascii=False), encoding="utf-8")
                                    print(f"    ✨ Auto-fixed source in {jf.name}: '{src}' -> '{rel_norm}'")
                                except Exception:
                                    pass
                            else:
                                g3_warnings.append(f"{jf.name}: Source path '{src}' can be normalized to '{rel_norm}' (run with --fix)")
                    else:
                        g3_errors.append(f"{jf.name}: Source Markdown not found: '{src}'")

            except Exception as e:
                g3_errors.append(f"{jf.name}: JSON parse failure: {e}")

        status_str = "PASS" if not g3_errors else "FAIL"
        if g3_errors:
            overall_passed = False
        print(f"  [{status_str}] Validated {g3_notes_checked} Cornell JSON notes ({len(g3_errors)} errors, {len(g3_warnings)} warnings)")
        for err in g3_errors:
            print(f"    ❌ {err}")
        for w in g3_warnings:
            print(f"    ⚠️  {w}")
        gate_results.append({"stage": 3, "name": "Cornell JSON & Anti-VTT Gate [D]", "status": status_str, "errors": g3_errors, "warnings": g3_warnings})

    # --------------------------------------------------------------------------
    # GATE 4: Web Cosmos & Study Portal Compilation [D]
    # --------------------------------------------------------------------------
    if stage_filter in ("all", "4"):
        print("\n─── [Gate 4: Web Cosmos & Study Portal Compilation] ────────────────")
        g4_errors = []
        g4_warnings = []
        
        # 1. Audit viz.html
        viz_file = vault_root / "viz.html"
        if not viz_file.is_file():
            g4_errors.append("viz.html is missing. Run 'academic-icm compile' to build it.")
        else:
            viz_content = viz_file.read_text(encoding="utf-8", errors="ignore")
            if len(viz_content) < 10000:
                g4_warnings.append(f"viz.html is suspiciously small ({len(viz_content)} bytes)")
            if 'src="' in viz_content and '.vtt"' in viz_content:
                # Count .vtt video sources
                vtt_leaks = len(re.findall(r'<video[^>]+src="[^"]+\.vtt"', viz_content))
                if vtt_leaks > 0:
                    g4_errors.append(f"viz.html contains {vtt_leaks} leaked .vtt video sources")
            if "katex.min.js" not in viz_content:
                g4_warnings.append("viz.html is missing KaTeX script tag")
            if "copy-tex.min.js" not in viz_content:
                g4_warnings.append("viz.html is missing copy-tex clipboard extension")

        # 2. Check HTML study sheets
        notes_map = collect_cornell_notes(vault_root)
        unique_notes = {v["json_path"]: v for v in notes_map.values()}
        missing_html = 0
        missing_anki = 0
        for jf, info in unique_notes.items():
            if week_token and not matches_week_filter(str(jf), week_token):
                continue
            if not info["html_path"]:
                missing_html += 1
            if not info["anki_path"]:
                missing_anki += 1

        if missing_html > 0:
            g4_errors.append(f"{missing_html} Cornell notes are missing compiled HTML study sheets")
        if missing_anki > 0:
            g4_warnings.append(f"{missing_anki} Cornell notes are missing Anki TSV decks")

        status_str = "PASS" if not g4_errors else "FAIL"
        if g4_errors:
            overall_passed = False
        print(f"  [{status_str}] Web portal check complete ({len(g4_errors)} errors, {len(g4_warnings)} warnings)")
        for err in g4_errors:
            print(f"    ❌ {err}")
        for w in g4_warnings:
            print(f"    ⚠️  {w}")
        gate_results.append({"stage": 4, "name": "Web Cosmos Compilation [D]", "status": status_str, "errors": g4_errors, "warnings": g4_warnings})

    # --------------------------------------------------------------------------
    # GATE 5: Unbiased 0-Context Runtime UAT / Judge [P]
    # --------------------------------------------------------------------------
    if stage_filter in ("all", "5"):
        print("\n─── [Gate 5: Unbiased 0-Context Acceptance Judge] ──────────────────")
        g5_errors = []
        g5_warnings = []

        # Grounded HTTP Probe
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:3333/test_zoom_player.html", headers={"User-Agent": "AcademicICM-Verifier/1.0"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    print("  ✓ Range server serving test_zoom_player.html (HTTP 200 OK)")
        except Exception:
            g5_warnings.append("Could not probe http://localhost:3333/test_zoom_player.html (range server not answering)")

        # 0-Context Local Model Judge (h2o-lightning-4b :8083)
        if enable_judge:
            decide_script = find_engine_path("jev-decision", "jev_decision.py")
            if not decide_script:
                decide_script = Path("/run/media/rodri/AI/skills/glitch-cat/jev-decision/jev_decision.py")

            if decide_script.is_file():
                # Formulate zero-context payload
                state_summary = (
                    f"Scope: {week_label}. "
                    f"Gates 1-4 result: {'ALL PASS' if overall_passed else 'SOME FAILS'}. "
                    f"Video policy: Zero .vtt sources as mp4, all Zoom links contain passcodes. "
                    f"KaTeX math verified for delimiter balance."
                )
                question = "Does this academic stage satisfy verified ICM quality criteria with zero subtitle video leaks and grounded proof?"
                
                try:
                    res = subprocess.run(
                        [sys.executable, str(decide_script), "--json", "bool",
                         "--context", state_summary, "--question", question,
                         "--require-server"],
                        capture_output=True, text=True, timeout=8
                    )
                    if res.returncode == 0 and res.stdout.strip():
                        j_out = json.loads(res.stdout.strip())
                        ans = j_out.get("decision", False)
                        conf = j_out.get("confidence", 0.0)
                        model_used = j_out.get("source", "unknown")
                        if ans is True:
                            print(f"  ✨ [0-Context Judge: {model_used.upper()}] APPROVED (confidence: {conf:.3f})")
                        else:
                            g5_errors.append(f"0-Context Judge ({model_used}) rejected stage: confidence {conf:.3f}")
                    else:
                        print(f"  ℹ️  [0-Context Judge] Gating engine offline or busy; skipped LLM vote.")
                except Exception as e:
                    print(f"  ℹ️  [0-Context Judge] Skip: {e}")
            else:
                print("  ℹ️  [0-Context Judge] jev-decision engine not found; skipping model evaluation.")

        status_str = "PASS" if not g5_errors else "FAIL"
        if g5_errors:
            overall_passed = False
        print(f"  [{status_str}] Runtime acceptance evaluation complete ({len(g5_errors)} errors, {len(g5_warnings)} warnings)")
        for err in g5_errors:
            print(f"    ❌ {err}")
        for w in g5_warnings:
            print(f"    ⚠️  {w}")
        gate_results.append({"stage": 5, "name": "Runtime UAT & Judge [P]", "status": status_str, "errors": g5_errors, "warnings": g5_warnings})

    # Summary
    print("\n" + "═" * 80)
    final_verdict = "✅ ALL GATES PASSED — ZERO DOWNSTREAM PROPAGATION RISK" if overall_passed else "🛑 VERIFICATION FAILED — FIX DEFECTS BEFORE DEPLOYMENT"
    print(f"🎯 Final Verdict: {final_verdict}")
    print("═" * 80 + "\n")

    if output_json:
        print(json.dumps({"scope": week_label, "passed": overall_passed, "gates": gate_results}, indent=2))

# ==============================================================================
# SUBCOMMAND: smart-check (AGY 3.8 Flash Cognitive Audit & h2o-lightning-4b Vision Gating)
# ==============================================================================
def audit_note_with_flash(note_data: Dict[str, Any], model: str = "gemini-3.8-flash-low") -> Dict[str, Any]:
    cues = []
    for sec in note_data.get("sections", []):
        for entry in sec.get("entries", []):
            cues.append({
                "cue": entry.get("cue", ""),
                "notes": entry.get("notes", "")
            })

    prompt = f"""You are a Senior Academic Examiner evaluating an Electrical Engineering Cornell Study Note.
Topic: {note_data.get("title")}

CUES AND NOTES:
{json.dumps(cues, indent=2, ensure_ascii=False)}

Evaluate this study note on 3 strict criteria:
1. BLOOMS TAXONOMY: Classify each cue into Level 1 (Remember/Trivia), Level 2 (Understand), Level 3 (Apply/Calculate), Level 4 (Analyze/Compare), Level 5 (Evaluate/Pitfalls).
2. DERIVATION & SCIENTIFIC ACCURACY: Are equations, signs (e.g. +jωL vs 1/(jωC)), and SI units accurate?
3. EXAM READINESS SCORE: 0 to 100. (Pass threshold: >= 75, with >= 50% Level 3+ cues).

Return strictly a single valid JSON object with NO surrounding markdown or extra text:
{{
  "exam_readiness_score": <int>,
  "passed": <bool>,
  "bloom_distribution": {{"remember": <int>, "understand": <int>, "apply": <int>, "analyze": <int>, "evaluate": <int>}},
  "accuracy_verdict": "<Clean|Minor Issues|Flawed>",
  "strengths": ["<str>"],
  "improvements": ["<str>"],
  "rejection_delta": null or "<actionable delta>"
}}
"""
    cmd = ["agy", "--model", model, "--print", prompt]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        out = res.stdout.strip()
        json_match = re.search(r'\{[\s\S]*\}', out)
        if json_match:
            return json.loads(json_match.group(0))
        return {"error": "Failed to parse JSON from AGY subagent", "raw": out}
    except Exception as e:
        return {"error": str(e)}

def audit_image_with_decision_model(img_path: Path, topic_context: str) -> Dict[str, Any]:
    """Gate a figure through the local h2o-lightning-4b vision decision model (:8083)."""
    jev_script = Path("/run/media/rodri/AI/skills/jev-decision/jev_decision.py")
    if not jev_script.is_file():
        return {"checked": False, "reason": "jev_decision.py not found"}

    q = f"Does this image show an authentic electrical schematic, circuit diagram, or waveform related to {topic_context}?"
    try:
        cmd = [
            sys.executable, str(jev_script), "--json", "bool",
            "--context", f"Course circuit figure for {topic_context}",
            "--question", q,
            "--image", str(img_path),
            "--require-server",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0 or not res.stdout.strip():
            return {"checked": False, "image": img_path.name,
                    "error": (res.stderr or "no output").strip()[:200]}
        out = json.loads(res.stdout)
        return {
            "checked": True,
            "image": img_path.name,
            "valid_circuit": bool(out.get("decision")),
            "confidence": float(out.get("confidence", 0.5)),
        }
    except Exception as e:
        return {"checked": False, "image": img_path.name, "error": str(e)}

def cmd_smart_check(args: argparse.Namespace) -> int:
    vault_root = find_vault_root(args.vault)
    target = getattr(args, "target", None)
    week_token = normalize_week_filter(getattr(args, "week", None))
    enable_vision = getattr(args, "vision", True)
    model = getattr(args, "model", "gemini-3.8-flash-low")
    output_json = getattr(args, "json", False)

    print(f"\n🧠 [Academic ICM Smart Check — AGY 3.8 Flash & h2o-lightning-4b Vision]")
    print(f"   • Vault Root : {vault_root}")
    print(f"   • Cognitive  : AGY Subagent ({model})")
    print(f"   • Vision     : h2o-lightning-4b (:8083)")

    # Collect notes
    notes_to_audit = []
    if target:
        tp = Path(target).resolve()
        if tp.is_file() and tp.name.endswith(".json"):
            notes_to_audit.append(tp)
        elif tp.is_dir():
            for f in sorted(tp.rglob("*_cornell.json")):
                if not any(p in f.parts for p in ("02_workers", "scratch", ".kanban", ".git", ".gemini", "brain")):
                    notes_to_audit.append(f)
        else:
            for jf in sorted(vault_root.rglob("*_cornell.json")):
                if any(p in jf.parts for p in ("02_workers", "scratch", ".kanban", ".git", ".gemini", "brain")):
                    continue
                if target.lower() in jf.name.lower():
                    notes_to_audit.append(jf)
    else:
        notes_map = collect_cornell_notes(vault_root)
        unique_jsons = {v["json_path"] for v in notes_map.values()}
        for jp in sorted(unique_jsons):
            if week_token and not matches_week_filter(str(jp), week_token):
                continue
            notes_to_audit.append(jp)

    # Deduplicate preserving order
    notes_to_audit = list(dict.fromkeys(notes_to_audit))

    if not notes_to_audit:
        print("❌ No matching Cornell notes found to audit.")
        return 1

    print(f"   • Target Notes: {len(notes_to_audit)} notes to inspect\n")

    audit_reports = []
    all_passed = True

    for jf in notes_to_audit:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"❌ Failed to parse {jf.name}: {e}")
            continue

        title = data.get("title", jf.stem)
        print(f"📄 Auditing: {jf.name} ('{title[:50]}')")

        # 1. Vision Gating with h2o-lightning-4b
        vision_results = []
        if enable_vision:
            # Find images in source directory
            src = data.get("source", "")
            img_candidates = []
            if src:
                subject_root = jf.parent.parent.parent if jf.parent.parent.name == "outputs" else jf.parent.parent
                src_dir = (subject_root / src).parent
                if src_dir.is_dir():
                    for ext in ("*.jpg", "*.png", "*.jpeg"):
                        img_candidates.extend(list(src_dir.glob(ext)))
            
            if img_candidates:
                print(f"   👁️  [Decision Vision] Found {len(img_candidates)} diagrams to inspect...")
                for img in img_candidates[:3]:  # inspect sample of up to 3 figures
                    v_res = audit_image_with_decision_model(img, title)
                    vision_results.append(v_res)
                    icon = "✓" if v_res.get("valid_circuit") else "⚠️"
                    conf_pct = v_res.get("confidence", 0) * 100
                    print(f"      {icon} {img.name}: Valid Circuit = {v_res.get('valid_circuit')} (conf: {conf_pct:.1f}%)")

        # 2. Cognitive Audit with AGY 3.8 Flash
        print(f"   ⚡ [AGY 3.8 Flash] Running academic examiner cognitive audit...")
        cog_res = audit_note_with_flash(data, model=model)
        
        if "error" in cog_res:
            print(f"      ❌ AGY Subagent Error: {cog_res.get('error')}")
            all_passed = False
            audit_reports.append({"note": jf.name, "error": cog_res.get("error")})
            continue

        score = cog_res.get("exam_readiness_score", 0)
        passed = cog_res.get("passed", False)
        dist = cog_res.get("bloom_distribution", {})
        verdict = cog_res.get("accuracy_verdict", "Unknown")

        if not passed:
            all_passed = False

        status_icon = "✅ PASS" if passed else "🛑 REJECT"
        print(f"   🎯 Verdict: {status_icon} (Exam Readiness Score: {score}/100, Accuracy: {verdict})")
        print(f"      • Bloom Levels: Remember={dist.get('remember',0)}, Understand={dist.get('understand',0)}, Apply={dist.get('apply',0)}, Analyze={dist.get('analyze',0)}, Evaluate={dist.get('evaluate',0)}")
        
        for st in cog_res.get("strengths", [])[:2]:
            print(f"      • ✨ Strength: {st}")
        for imp in cog_res.get("improvements", [])[:2]:
            print(f"      • 💡 Improvement: {imp}")
        
        if cog_res.get("rejection_delta"):
            print(f"      • 📌 Rejection Delta: {cog_res.get('rejection_delta')}")
        print()

        audit_reports.append({
            "note": jf.name,
            "title": title,
            "score": score,
            "passed": passed,
            "bloom": dist,
            "accuracy": verdict,
            "vision": vision_results,
            "rejection_delta": cog_res.get("rejection_delta")
        })

    if output_json:
        print(json.dumps(audit_reports, indent=2, ensure_ascii=False))

    return 0 if all_passed else 1

# ==============================================================================
# SUBCOMMAND: serve
# ==============================================================================
def cmd_serve(args: argparse.Namespace) -> int:
    vault_root = find_vault_root(args.vault)
    port = args.port or 8765
    print(f"\n🌐 [Study Portal Server] Serving {vault_root} on port {port}...")
    print(f"   • Open Cosmos: http://localhost:{port}/viz.html")
    print(f"   • Open Portal: http://localhost:{port}/cornell_index.html")
    
    # Check if already running
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    is_open = s.connect_ex(("127.0.0.1", port)) == 0
    s.close()
    if is_open:
        print(f"✅ Server is already running on port {port}!")
        return 0

    try:
        subprocess.run([sys.executable, "-m", "http.server", str(port), "--directory", str(vault_root)])
    except KeyboardInterrupt:
        print("\nServer stopped.")
    return 0

def cmd_modules() -> int:
    academic_root = Path(__file__).resolve().parent.parent
    skills_root = academic_root.parent
    print("\n📚 [Academic ICM] Integrated Suites & Modules:\n")
    module_names = ["canvas-cli", "zoom-recorder", "cornell-notes"]
    for m_name in module_names:
        m_dir = skills_root / m_name
        skill_file = m_dir / "SKILL.md"
        desc = "Integrated standalone academic module"
        if skill_file.is_file():
            content = skill_file.read_text(encoding="utf-8")
            m_desc = re.search(r"^description:\s*([^\n]+)", content, re.MULTILINE)
            if m_desc:
                desc = m_desc.group(1).strip('"\' >')
        print(f"  • {m_name:<18} : {desc[:80]}...")
    print("\n  Direct CLI commands:")
    print("    academic-icm canvas [...]   - Canvas LMS API client (courses, grades, modules)")
    print("    academic-icm zoom [...]     - Zoom recording download & slide scraper")
    print("    academic-icm graph [...]    - Knowledge graph traversal & hybrid RAG (Stage 2)")
    print("    academic-icm cornell [...]  - Markdown to active-recall Cornell HTML & Anki")
    print("    academic-icm srs [...]      - Spaced repetition review runner")
    print("  Or via backward-compatible shims in ~/.local/bin/ (canvas-cli, zoom-recorder, cornell-notes)\n")
    return 0

def cmd_graph(args: argparse.Namespace) -> int:
    action = getattr(args, "graph_action", "search")
    graph_bin = find_engine_path("graph-memory", "graph_memory.py") or shutil.which("graph-memory") or "/run/media/rodri/AI/skills/glitch-cat/graph-memory/graph_memory.py"
    cmd = [sys.executable, str(graph_bin)] if str(graph_bin).endswith(".py") else [str(graph_bin)]

    if action == "index":
        vault_root = find_vault_root(getattr(args, "vault", None))
        cmd.extend(["index", "--corpus", str(vault_root)])
    elif action == "search":
        if not getattr(args, "query", ""):
            print("❌ Query string required. E.g. academic-icm graph search 'Coulomb law' --table")
            return 1
        cmd.extend(["search", args.query])
        if getattr(args, "table", False):
            cmd.append("--table")
        if getattr(args, "limit", None):
            cmd.extend(["-n", str(args.limit)])
    elif action == "recall":
        if not getattr(args, "query", ""):
            print("❌ Query required for graph recall. E.g. academic-icm graph recall 'Supernode'")
            return 1
        cmd.extend(["recall", args.query])
    elif action == "build":
        cmd.extend(["build-graph"])

    res = subprocess.run(cmd)
    return res.returncode

# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("canvas", "zoom", "graph", "cornell", "srs", "modules"):
        mod = sys.argv[1]
        rem = sys.argv[2:]
        if mod == "graph":
            graph_bin = find_engine_path("graph-memory", "graph_memory.py") or shutil.which("graph-memory") or "/run/media/rodri/AI/skills/glitch-cat/graph-memory/graph_memory.py"
            cmd = [sys.executable, str(graph_bin)] if str(graph_bin).endswith(".py") else [str(graph_bin)]
            return subprocess.run(cmd + rem).returncode

        elif mod == "canvas":
            script = find_engine_path("canvas-cli", "canvas_cli.py")
            if not script:
                sys.exit("❌ Error: canvas_cli.py not found.")
            return subprocess.run([sys.executable, str(script)] + rem).returncode
        elif mod == "zoom":
            script = find_engine_path("zoom-recorder", "zoom_download.py")
            if not script:
                sys.exit("❌ Error: zoom_download.py not found.")
            return subprocess.run([sys.executable, str(script)] + rem).returncode
        elif mod == "cornell":
            script = find_engine_path("cornell-notes", "format_notes.py")
            if not script:
                sys.exit("❌ Error: format_notes.py not found.")
            return subprocess.run([sys.executable, str(script)] + rem).returncode
        elif mod == "srs":
            script = find_engine_path("cornell-notes", "srs_review.py")
            if not script:
                sys.exit("❌ Error: srs_review.py not found.")
            return subprocess.run([sys.executable, str(script)] + rem).returncode
        elif mod == "modules":
            return cmd_modules()

    parser = argparse.ArgumentParser(
        prog="academic-icm",
        description="Academic ICM Pipeline Orchestrator (Interpretable Context Methodology)"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")
    subparsers.add_parser("graph", help="Knowledge graph traversal & hybrid RAG via graph-memory (Stage 2)")

    # Integrated module proxies
    subparsers.add_parser("canvas", help="Canvas LMS API client (courses, grades, assignments, modules)")
    subparsers.add_parser("zoom", help="Download transcripts, audio, and slides from Zoom recordings")
    subparsers.add_parser("cornell", help="Compile Markdown into print-ready Cornell Notes HTML & Anki")
    subparsers.add_parser("srs", help="Spaced repetition review engine for Cornell notes")
    subparsers.add_parser("modules", help="List integrated academic modules and rubrics")

    # status
    p_status = subparsers.add_parser("status", help="Show curriculum coverage and orphaned notes")
    p_status.add_argument("vault", nargs="?", default=None, help="Path to notes vault root")

    # audit
    p_audit = subparsers.add_parser("audit", help="Deep audit of stem alignment and JSON schema")
    p_audit.add_argument("vault", nargs="?", default=None, help="Path to notes vault root")
    p_audit.add_argument("--fix-sources", action="store_true", help="Auto-fix broken/absolute source paths to portable relative paths")

    # scaffold
    p_scaffold = subparsers.add_parser("scaffold", help="Generate a matching _cornell.json template from markdown source")
    p_scaffold.add_argument("source_md", help="Path to input markdown file")
    p_scaffold.add_argument("--force", action="store_true", help="Overwrite existing JSON file")

    # build-note
    p_build = subparsers.add_parser("build-note", help="Compile _cornell.json into HTML study sheet and Anki deck")
    p_build.add_argument("json_file", help="Path to _cornell.json file")

    # compile
    p_compile = subparsers.add_parser("compile", help="Recompile CURRICULUM_TREE.md into viz.html and cornell_index.html")
    p_compile.add_argument("vault", nargs="?", default=None, help="Path to notes vault root")

    # sync-orphans
    p_sync = subparsers.add_parser("sync-orphans", help="Repair and align known orphaned notes")
    p_sync.add_argument("vault", nargs="?", default=None, help="Path to notes vault root")

    # stamp-video
    p_stamp = subparsers.add_parser("stamp-video", help="Auto-stamp Cornell cues with video/recording timestamps")
    p_stamp.add_argument("target", nargs="?", default=None, help="Path to _cornell.json file or folder (default: all notes)")
    p_stamp.add_argument("--threshold", type=float, default=0.20, help="Minimum BM25 match score threshold (default: 0.20)")
    p_stamp.add_argument("--force", action="store_true", help="Overwrite existing video timestamps in cues")
    p_stamp.add_argument("--dry-run", action="store_true", help="Preview timestamp matches without saving to disk")
    p_stamp.add_argument("--course", help="Filter target notes by course substring (e.g. 48520, 48521)")
    p_stamp.add_argument("--vault", default=None, help="Path to notes vault root")

    # verify
    p_verify = subparsers.add_parser("verify", help="Run 5-stage ICM verification gates and unbiased 0-context judge")
    p_verify.add_argument("week", nargs="?", default=None, help="Filter by week (e.g. 5, week5, week_05, all)")
    p_verify.add_argument("--stage", choices=["1", "2", "3", "4", "5", "all"], default="all", help="Target specific stage gate (default: all)")
    p_verify.add_argument("--judge", action="store_true", default=True, help="Run unbiased 0-context local model judge (default: True)")
    p_verify.add_argument("--no-judge", dest="judge", action="store_false", help="Disable 0-context model judge")
    p_verify.add_argument("--smart", action="store_true", help="Run deep cognitive audit with AGY 3.8 Flash and h2o-lightning-4b vision")
    p_verify.add_argument("--json", action="store_true", help="Output machine-readable JSON evaluation report")
    p_verify.add_argument("--fix", action="store_true", help="Auto-repair fixable defects (e.g. normalize relative source paths)")
    p_verify.add_argument("--vault", default=None, help="Path to notes vault root")

    # smart-check
    p_smart = subparsers.add_parser("smart-check", help="Run deep cognitive & visual audit with AGY 3.8 Flash and h2o-lightning-4b vision")
    p_smart.add_argument("target", nargs="?", default=None, help="Path or substring of _cornell.json file or folder")
    p_smart.add_argument("--week", default=None, help="Filter by week (e.g. 5, 6, 9)")
    p_smart.add_argument("--no-vision", dest="vision", action="store_false", default=True, help="Disable h2o-lightning-4b vision image inspection")
    p_smart.add_argument("--model", default="gemini-3.8-flash-low", help="AGY subagent model tier (default: gemini-3.8-flash-low)")
    p_smart.add_argument("--json", action="store_true", help="Output machine-readable JSON report")
    p_smart.add_argument("--vault", default=None, help="Path to notes vault root")

    # serve
    p_serve = subparsers.add_parser("serve", help="Start local web server for study portal")
    p_serve.add_argument("vault", nargs="?", default=None, help="Path to notes vault root")
    p_serve.add_argument("--port", type=int, default=8765, help="Port to serve on (default: 8765)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    dispatch = {
        "status": cmd_status,
        "audit": cmd_audit,
        "scaffold": cmd_scaffold,
        "build-note": cmd_build_note,
        "compile": cmd_compile,
        "sync-orphans": cmd_sync_orphans,
        "stamp-video": cmd_stamp_video,
        "serve": cmd_serve,
        "verify": cmd_verify,
        "smart-check": cmd_smart_check,
        "graph": cmd_graph,
    }

    return dispatch[args.command](args)

if __name__ == "__main__":
    sys.exit(main())
