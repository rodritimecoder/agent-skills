#!/usr/bin/env python3
"""okf_architect.py: Open Knowledge Format (OKF v0.2) bundle architect and validator."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

OKF_VERSION = "0.2"
RESERVED_FILENAMES = {
    "index.md", "log.md", "readme.md", "context.md", "agents.md", "state.md", "curriculum_tree.md"
}
ADMIN_PATTERNS = {
    "meet_the_team", "faq", "frequently_asked_questions", "how_to_be_successful", "welcome",
    "how_we_run", "assessment_overview", "epa_overview", "modules_overview", "weekly_program",
    "your_path_to_becoming", "uts_library", "important_guidance", "study_resources",
    "subject_resources", "teaching_staff", "subject_schedule", "open_labs", "study_help"
}
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


@dataclass(frozen=True)
class ModuleHub:
    id: str
    label: str
    order: int
    course: str


@dataclass(frozen=True)
class NoteAssignment:
    course: str
    module_id: str
    module: str
    order: int
    custom_title: str


@dataclass(frozen=True)
class CornellInfo:
    html_path: str
    title: str
    cues: int
    sections: int
    source: str
    cards: List[Dict[str, Any]]
    sections_data: List[Dict[str, Any]] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)


def parse_frontmatter(file_path: Path) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown document using zero-dependency parsing."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    raw_yaml = parts[1]
    body = parts[2].lstrip("\r\n")

    metadata: Dict[str, Any] = {}
    current_key: Optional[str] = None
    in_list = False

    for line in raw_yaml.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue

        if s.startswith("- ") and current_key and in_list:
            item = s[2:].strip().strip("\"'")
            metadata[current_key].append(item)
            continue

        if ":" in s:
            key, val = s.split(":", 1)
            key = key.strip()
            val = val.strip()

            if val == "":
                current_key = key
                metadata[key] = []
                in_list = True
            elif val.startswith("[") and val.endswith("]"):
                items = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
                metadata[key] = items
                in_list = False
                current_key = key
            elif val.startswith("{") and val.endswith("}"):
                metadata[key] = val
                in_list = False
                current_key = key
            else:
                metadata[key] = val.strip("\"'")
                in_list = False
                current_key = key

    return metadata, body


def _emit_json_report(bundle_root: Path, concepts_count: int, errors: int, warnings: int) -> None:
    """Emit the machine-readable validation verdict as pure JSON on stdout."""
    print(json.dumps({
        "valid": errors == 0,
        "concepts_count": concepts_count,
        "errors": errors,
        "warnings": warnings,
        "bundle_root": str(bundle_root),
    }))


def validate_bundle(bundle_root: Path, json_output: bool = False) -> bool:
    """Validate an OKF v0.2 bundle directory."""
    out = sys.stderr if json_output else sys.stdout

    def emit(*args: Any, **kwargs: Any) -> None:
        print(*args, file=out, **kwargs)

    emit(f"\n🔍 [OKF Audit] Validating bundle: {bundle_root.resolve()}")
    if not bundle_root.is_dir():
        emit(f"❌ Error: Not a directory: {bundle_root}")
        if json_output:
            _emit_json_report(bundle_root, 0, 1, 0)
        return False

    all_files = list(bundle_root.rglob("*.md"))
    if not all_files:
        emit(f"⚠️  No markdown documents found in {bundle_root}")
        if json_output:
            _emit_json_report(bundle_root, 0, 1, 0)
        return False

    errors = 0
    warnings = 0
    concepts_count = 0

    root_index = bundle_root / "index.md"
    if not root_index.is_file():
        emit("  ⚠️  Warning: Root index.md missing (recommended for progressive disclosure §8)")
        warnings += 1
    else:
        emit("  ✅ Root index.md present")

    for md_file in all_files:
        rel_path = md_file.relative_to(bundle_root)
        name = md_file.name

        if name in RESERVED_FILENAMES:
            continue

        concepts_count += 1
        meta, _ = parse_frontmatter(md_file)

        if not meta or "type" not in meta:
            emit(f"  ❌ Error: Concept '{rel_path}' is missing required frontmatter 'type:' (§4.1)")
            errors += 1
            continue

        ctype = meta.get("type", "Unknown")
        if ctype == "Attested Computation" and "runtime" not in meta:
            emit(f"  ❌ Error: Attested Computation '{rel_path}' missing required 'runtime:' (§10.2)")
            errors += 1

        if "title" not in meta:
            warnings += 1
        if "description" not in meta:
            warnings += 1

    # Audit Concept Title Uniqueness & Generic Placeholders
    course_titles: Dict[str, Dict[str, List[str]]] = {}
    for md_file in all_files:
        if md_file.name in RESERVED_FILENAMES: continue
        meta, _ = parse_frontmatter(md_file)
        t = meta.get("title", md_file.stem)
        parts = md_file.relative_to(bundle_root).parts
        crs = parts[0] if len(parts) > 1 else "General"
        course_titles.setdefault(crs, {}).setdefault(t, []).append(md_file.name)

    title_dups = 0
    for crs, t_map in course_titles.items():
        for t, flist in t_map.items():
            if len(flist) > 1:
                emit(f"  ⚠️  Warning [{crs}]: Duplicate concept title '{t}' shared across: {', '.join(flist)}")
                warnings += 1
                title_dups += 1

    if title_dups == 0:
        emit("  ✅ Concept titles are distinct across all courses (0 duplicates)")

    emit(f"\n📊 [Validation Summary]")
    emit(f"  • Concepts Found:   {concepts_count}")
    emit(f"  • Total Errors:     {errors}")
    emit(f"  • Total Warnings:   {warnings}")

    if json_output:
        _emit_json_report(bundle_root, concepts_count, errors, warnings)

    if errors == 0:
        emit("🎉 Bundle conforms to Open Knowledge Format (OKF v0.2) specification!")
        return True

    emit("❌ Bundle has validation errors that should be resolved.")
    return False


def scaffold_bundle(target_dir: Path, title: str, domain: str = "Knowledge") -> None:
    """Scaffold a new OKF v0.2 compliant bundle structure."""
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n🛠️  [Scaffold] Creating OKF v0.2 bundle in: {target_dir.resolve()}")

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today_str = datetime.date.today().isoformat()

    index_content = f"""---
okf_version: "{OKF_VERSION}"
---

# {title}

Welcome to the **{title}** knowledge bundle, structured in accordance with the [Open Knowledge Format (OKF v0.2)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md).

## Concepts & Topics

* [Overview](overview.md) - High-level introduction and scope of this knowledge bundle.
* [References](references/index.md) - Foundational schemas, external resources, and datasets.

## Governance & Updates
* See [Update Log](log.md) for chronological changes across this bundle.
"""
    (target_dir / "index.md").write_text(index_content, encoding="utf-8")
    print("  ✅ Created root index.md (with okf_version: 0.2)")

    log_content = f"""# Directory Update Log

## {today_str}
* **Initialization**: Established initial OKF bundle structure for {title}.
"""
    (target_dir / "log.md").write_text(log_content, encoding="utf-8")
    print("  ✅ Created log.md")

    overview_content = f"""---
type: Overview
title: {title} Overview
description: High-level purpose and navigational starting point for this bundle.
tags: [{domain.lower()}, overview, okf]
status: stable
generated: {{ by: okf-architect/v0.2, at: {now_iso} }}
verified: {{ by: human:user, at: {now_iso} }}
---

# {title}

> Autonomous knowledge bundle conforming to the Open Knowledge Format (OKF v0.2).

## Scope & Intent
This bundle captures structured domain knowledge, concepts, and relationships designed for human inspection and autonomous AI agent navigation.

## Navigation
Use the [Directory Index](/index.md) to progressively disclose concepts and relationships.
"""
    (target_dir / "overview.md").write_text(overview_content, encoding="utf-8")
    print("  ✅ Created overview.md (concept with full provenance & trust metadata)")

    refs_dir = target_dir / "references"
    refs_dir.mkdir(exist_ok=True)
    refs_index = """# References & Supporting Material

* [Data Sources](sources.md) - Canonical external sources and references.
"""
    (refs_dir / "index.md").write_text(refs_index, encoding="utf-8")

    sources_content = f"""---
type: Reference
title: Canonical Data Sources
description: Upstream materials, specifications, and URLs backing this knowledge bundle.
status: stable
generated: {{ by: okf-architect/v0.2, at: {now_iso} }}
---

# Data Sources & References

| Source ID | Title | Resource URI |
|---|---|---|
| `okf-spec` | Open Knowledge Format (OKF v0.2) | `https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md` |
"""
    (refs_dir / "sources.md").write_text(sources_content, encoding="utf-8")
    print("  ✅ Created references/ directory with sources.md and index.md")
    print(f"\n🎉 OKF bundle scaffolded successfully in {target_dir}")


def refresh_indexes(bundle_root: Path) -> None:
    """Scan bundle and rebuild all index.md listings for progressive disclosure (§8)."""
    print(f"\n🔄 [Index Refresh] Updating index.md files across: {bundle_root.resolve()}")

    for dirpath, dirnames, filenames in os.walk(bundle_root):
        current_dir = Path(dirpath)
        concepts = []
        for f in sorted(filenames):
            if f.endswith(".md") and f not in RESERVED_FILENAMES:
                f_path = current_dir / f
                meta, _ = parse_frontmatter(f_path)
                title = meta.get("title", f[:-3].replace("_", " ").title())
                desc = meta.get("description", "Concept document")
                ctype = meta.get("type", "Concept")
                concepts.append((f, title, desc, ctype))

        subdirs = [d for d in sorted(dirnames) if not d.startswith(".") and not d.startswith("_")]
        if not concepts and not subdirs:
            continue

        index_lines = []
        if current_dir == bundle_root:
            index_lines.append("---\nokf_version: \"0.2\"\n---\n")
            index_lines.append(f"# {bundle_root.name.replace('_', ' ').title()} Knowledge Bundle\n")
        else:
            index_lines.append(f"# {current_dir.name.replace('_', ' ').title()} Directory Index\n")

        if subdirs:
            index_lines.append("## Subdirectories\n")
            for d in subdirs:
                index_lines.append(f"* [{d.replace('_', ' ').title()}]({d}/index.md) - Explore {d} concepts")
            index_lines.append("")

        if concepts:
            index_lines.append("## Concepts\n")
            for fname, title, desc, ctype in concepts:
                index_lines.append(f"* [{title}]({fname}) ({ctype}) - {desc}")
            index_lines.append("")

        index_file = current_dir / "index.md"
        index_file.write_text("\n".join(index_lines), encoding="utf-8")
        print(f"  ✅ Updated: {index_file.relative_to(bundle_root)}")


def extract_links(body: str) -> List[str]:
    """Extract markdown links and wikilinks from body content."""
    links: List[str] = []
    md_links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', body)
    for _, url in md_links:
        if not url.startswith("http") and not url.startswith("#"):
            links.append(url.split("#")[0].strip())

    wikilinks = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', body)
    for target in wikilinks:
        links.append(target.strip())

    return links


def classify_canvas_module(rel_path_input: Any, meta: Dict[str, Any], course_name: str) -> Tuple[str, str, int]:
    """Classify a note into its canonical Canvas LMS Module or Week."""
    c_tag = course_name.split()[0] if course_name else "Course"
    rel_p = Path(rel_path_input)
    parts = rel_p.parts
    top_folder = parts[1] if len(parts) > 1 else ""
    low_sub = "/".join(parts[1:]).lower() if len(parts) > 1 else str(rel_p).lower()

    if any(k in low_sub for k in [
        "get started", "meet_the_team", "faq", "how_to_be_successful", "welcome", "how_we_run",
        "assessment_overview", "epa_overview", "modules_overview", "weekly_program",
        "your_path", "uts_library", "guidance", "study_resources", "subject_resources",
        "teaching_staff", "subject_schedule", "open_labs"
    ]):
        return f"{course_name}/mod_orientation", f"[{c_tag}] 🧭 Orientation & Course Admin", 950

    if meta.get("module"):
        m_str = str(meta["module"]).strip()
        m_m = re.search(r'\bmodule[_\s-]*(\d{1,2})\b', m_str, re.IGNORECASE)
        m_w = re.search(r'\b(?:week|w)[_\s-]*(\d{1,2})\b', m_str, re.IGNORECASE)
        if m_m:
            num = int(m_m.group(1))
            return f"{course_name}/mod_m{num:02d}", f"[{c_tag}] Module {num:02d}", num
        elif m_w:
            num = int(m_w.group(1))
            return f"{course_name}/mod_w{num:02d}", f"[{c_tag}] Week {num:02d}", num
        else:
            clean_slug = "mod_" + re.sub(r'[^a-zA-Z0-9]+', '_', m_str.lower()).strip('_')
            return f"{course_name}/{clean_slug}", f"[{c_tag}] {m_str}", 50

    if top_folder.lower() == "recordings" and len(parts) > 2:
        rec_folder = parts[2]
        m_rec_w = re.search(r'(?:^|[\s/_-])(?:week|w)[_\s-]*(\d{1,2})(?!\d)', rec_folder, re.IGNORECASE)
        if m_rec_w:
            w_num = int(m_rec_w.group(1))
            return f"{course_name}/mod_w{w_num:02d}", f"[{c_tag}] Week {w_num:02d}", w_num

    m_top_m = re.search(r'(?:^|[\s/_-])module[_\s-]*(\d{1,2})(?!\d)', top_folder, re.IGNORECASE)
    if m_top_m:
        m_num = int(m_top_m.group(1))
        return f"{course_name}/mod_m{m_num:02d}", f"[{c_tag}] Module {m_num:02d}", m_num

    m_top_w = re.search(r'(?:^|[\s/_-])(?:week|w)[_\s-]*(\d{1,2})(?!\d)', top_folder, re.IGNORECASE)
    if m_top_w:
        w_num = int(m_top_w.group(1))
        return f"{course_name}/mod_w{w_num:02d}", f"[{c_tag}] Week {w_num:02d}", w_num

    m_sub_m = re.search(r'(?:^|[\s/_-])module[_\s-]*(\d{1,2})(?!\d)', low_sub, re.IGNORECASE)
    if m_sub_m:
        m_num = int(m_sub_m.group(1))
        return f"{course_name}/mod_m{m_num:02d}", f"[{c_tag}] Module {m_num:02d}", m_num

    m_sub_w = re.search(r'(?:^|[\s/_-])(?:week|w)[_\s-]*(\d{1,2})(?!\d)', low_sub, re.IGNORECASE)
    if m_sub_w:
        w_num = int(m_sub_w.group(1))
        return f"{course_name}/mod_w{w_num:02d}", f"[{c_tag}] Week {w_num:02d}", w_num

    if "assignment" in low_sub or "project" in low_sub:
        return f"{course_name}/mod_assignments", f"[{c_tag}] Assignments & Projects", 90
    if "quiz" in low_sub or "past_paper" in low_sub:
        return f"{course_name}/mod_quizzes", f"[{c_tag}] Quizzes & Practice", 85
    if "slide" in low_sub:
        return f"{course_name}/mod_slides", f"[{c_tag}] Lecture Slides", 80

    return f"{course_name}/mod_overview", f"[{c_tag}] Course Overview", 0


def clean_display_title(s: str) -> str:
    """Clean note title by removing redundant course codes and stutter while preserving week/module identity."""
    if not s:
        return ""
    raw = s
    m_bracket = re.match(r'^\[(?:\d+\s+)?(?:(W\d+)|([A-Za-z0-9_-]+))\]\s*', s)
    w_prefix = ""
    if m_bracket:
        if m_bracket.group(1):
            w_prefix = m_bracket.group(1).upper()
        s = s[m_bracket.end():]

    s = re.sub(r'\b(week\s*\d+)\s+(?:week\s*\d+)\b', r'\1', s, flags=re.IGNORECASE)
    s = re.sub(r'\b(w\d+)\s+(?:w\d+)\b', r'\1', s, flags=re.IGNORECASE)
    s = re.sub(r'^(?:week|w)\d+[\s:_-]+(week\s*\d+)', r'\1', s, flags=re.IGNORECASE)
    s = re.sub(r'^(?:f|l)\s*\d+[\s:_-]+', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+(?:26|tl|v2)\b', '', s, flags=re.IGNORECASE)
    s = re.sub(r'_+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()

    has_week = bool(re.search(r'\b(?:week\s*\d+|w\d+|module\s*\d+)\b', s, re.IGNORECASE))
    if not has_week and w_prefix:
        s = f"{w_prefix} {s}"

    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    return s or raw


def week_sort_key(name: str) -> Tuple[int, int, str]:
    """Sort module/week names naturally and chronologically."""
    m = re.search(r'\b(?:week|w)[s]?[\s_-]*(\d+)', name, re.IGNORECASE)
    if m:
        return (0, int(m.group(1)), name)
    m2 = re.search(r'\bmodule[\s_-]*(\d+)', name, re.IGNORECASE)
    if m2:
        return (0, int(m2.group(1)), name)
    if any(k in name.lower() for k in ['overview', 'get started', 'orientation', 'intro']):
        return (-1, 0, name)
    if any(k in name.lower() for k in ['quiz', 'exam', 'assessment', 'project']):
        return (2, 999, name)
    return (1, 500, name)


def normalize_stem(s: str) -> str:
    """Normalize note stem by standardizing week prefixes, stripping course prefixes and noise suffixes."""
    s = s.lower().replace("-", "_").replace(" ", "_")
    # Strip course prefixes: e.g. 48520_, 48521_, 48430_, 41200_
    s = re.sub(r'^(?:48520|48521|48430|41200)_+', '', s)
    m = re.match(r'^(?:w(?:eek)?_?(\d+)_+)+', s)
    if m:
        w_num = int(m.group(1))
        rest = s[m.end():]
        s = f"w{w_num:02d}_{rest}"
    # Strip trailing noisy suffix numbers like _26, _tl, _1, _2
    s = re.sub(r'_(?:26|tl|1|2)$', '', s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")



def parse_time_to_seconds(ts: str) -> int:
    """Convert timestamp 'HH:MM:SS', 'MM:SS', or 'SS' to total integer seconds."""
    parts = ts.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(float(parts[1]))
        elif len(parts) == 1:
            return int(float(parts[0]))
    except Exception:
        pass
    return 0


def extract_video_info(
    cue: str, notes: str, jf: Path, bundle_root: Path
) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """Detect and parse video timestamp badges and walkthrough clips."""
    video_data: Optional[Dict[str, Any]] = None
    combined = f"{cue} {notes}"

    # 1. Explicit Markdown badge: [▶ 14:20](URL) or [▶ 01:14:20](URL) or [▶ Solution @ 14:20](URL)
    m_exp = re.search(r'\[▶\s*([0-9:]+[^\]]*)\]\(([^)]+)\)', cue) or re.search(r'\[▶\s*([0-9:]+[^\]]*)\]\(([^)]+)\)', notes)
    if m_exp:
        raw_ts = m_exp.group(1).strip()
        raw_url = m_exp.group(2).strip()

        cue = re.sub(r'\[▶\s*([0-9:]+[^\]]*)\]\(([^)]+)\)', '', cue).strip()
        notes = re.sub(r'\[▶\s*([0-9:]+[^\]]*)\]\(([^)]+)\)', '', notes).strip()

        m_time = re.search(r'(\d{1,2}:\d{2}(?::\d{2})?)', raw_ts)
        time_str = m_time.group(1) if m_time else raw_ts
        sec = parse_time_to_seconds(time_str)

        m_yt = re.search(r'(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/))([a-zA-Z0-9_-]{11})', raw_url)
        if m_yt:
            yt_id = m_yt.group(1)
            m_t = re.search(r'[?&#]t=(?:(\d+)m)?(?:(\d+)s)?', raw_url) or re.search(r'[?&](?:start|t)=(\d+)', raw_url)
            if m_t:
                if m_t.group(1) and m_t.group(2):
                    sec = int(m_t.group(1)) * 60 + int(m_t.group(2))
                elif m_t.group(1):
                    sec = int(m_t.group(1))
            video_data = {
                "type": "youtube",
                "src": f"https://www.youtube-nocookie.com/embed/{yt_id}?start={sec}&autoplay=1",
                "time_str": time_str,
                "seconds": sec,
                "label": f"Solution @ {time_str}"
            }
        elif "zoom.us" in raw_url:
            clean_zurl = raw_url.split('#')[0]
            passcode = ""
            sol_db_path = TEMPLATE_DIR / "viz" / "data" / "worked_solutions_db.json"
            if sol_db_path.is_file():
                try:
                    sol_data = json.loads(sol_db_path.read_text(encoding="utf-8"))
                    for key, sol in sol_data.items():
                        v_src = sol.get("videoSrc", "")
                        fb_src = sol.get("fallbackSrc", "")
                        if v_src and (clean_zurl in v_src or v_src in clean_zurl):
                            passcode = sol.get("passcode", "")
                            break
                        if fb_src and (clean_zurl in fb_src or fb_src in clean_zurl):
                            passcode = sol.get("passcode", "")
                            break
                    if not passcode:
                        m_w = re.search(r'\b(?:week|w)[_\s-]*0?(\d+)(?!\d)', f"{jf.stem} {cue} {notes}", re.IGNORECASE)
                        if m_w:
                            w_target = m_w.group(1)
                            for key, sol in sol_data.items():
                                m_sol_w = re.search(r'week_0?(\d+)(?!\d)', key, re.IGNORECASE)
                                if m_sol_w and m_sol_w.group(1) == w_target:
                                    passcode = sol.get("passcode", "")
                                    break
                except Exception:
                    pass
            video_data = {
                "type": "zoom",
                "src": raw_url,
                "time_str": time_str,
                "seconds": sec,
                "passcode": passcode,
                "label": f"Zoom @ {time_str}"
            }
        else:
            clean_url = raw_url.split('#')[0]
            # Intercept accidental .vtt or .md transcript files and resolve to real Zoom cloud links
            if clean_url.lower().endswith('.vtt') or clean_url.lower().endswith('.md'):
                resolved_zoom = None
                sol_db_path = TEMPLATE_DIR / "viz" / "data" / "worked_solutions_db.json"
                if sol_db_path.is_file():
                    try:
                        sol_data = json.loads(sol_db_path.read_text(encoding="utf-8"))
                        search_target = f"{clean_url} {jf.stem} {cue} {notes}".lower()
                        for key, sol in sol_data.items():
                            m_w = re.search(r'week_?(\d+)', key, re.IGNORECASE)
                            w_num = m_w.group(1) if m_w else ""
                            matches_week = bool(w_num and re.search(rf'\b(?:week|w)[_\s-]*0?{w_num}(?!\d)', search_target, re.IGNORECASE))
                            if key in search_target or matches_week:
                                if sol.get("videoSrc") and sol["videoSrc"].startswith("http"):
                                    resolved_zoom = {
                                        "type": "zoom",
                                        "src": sol["videoSrc"],
                                        "time_str": time_str,
                                        "seconds": sec,
                                        "passcode": sol.get("passcode", ""),
                                        "label": f"Zoom @ {time_str}"
                                    }
                                    break
                    except Exception:
                        pass
                video_data = resolved_zoom
            else:
                video_data = {
                    "type": "mp4",
                    "src": clean_url,
                    "time_str": time_str,
                    "seconds": sec,
                    "label": f"Video @ {time_str}"
                }

    # 2. Implicit timestamp references (e.g. [Timestamp: 00:11:00] or **Video Walkthrough Timestamp**: [00:11:00])
    if not video_data:
        m_imp = re.search(r'\[Timestamp:\s*([0-9:]+)\]', combined, re.IGNORECASE) or \
                re.search(r'\*\*Video Walkthrough Timestamp\*\*:\s*`?\[([0-9:]+)\]`?', combined, re.IGNORECASE) or \
                re.search(r'\[([0-9]{1,2}:\d{2}(?::\d{2})?)\]', combined)
        if m_imp:
            time_str = (m_imp.group(1) if m_imp.lastindex >= 1 and m_imp.group(1) else m_imp.group(0).strip("[]`"))
            sec = parse_time_to_seconds(time_str)

            course_dir = None
            for p in jf.parents:
                if p.parent == bundle_root:
                    course_dir = p
                    break

            # 1. Determine the week of this note
            m_wk = re.search(r'\b(?:week|w)[_\s-]*0?(\d+)(?!\d)', str(jf), re.IGNORECASE) or \
                   re.search(r'\b(?:week|w)[_\s-]*0?(\d+)(?!\d)', f"{cue} {notes}", re.IGNORECASE)
            note_week = m_wk.group(1) if m_wk else None

            # 2. Look up worked_solutions_db for this exact week
            sol_db_path = TEMPLATE_DIR / "viz" / "data" / "worked_solutions_db.json"
            if sol_db_path.is_file() and note_week:
                try:
                    sol_data = json.loads(sol_db_path.read_text(encoding="utf-8"))
                    for key, sol in sol_data.items():
                        m_sol_w = re.search(r'week_0?(\d+)(?!\d)', key, re.IGNORECASE)
                        if m_sol_w and m_sol_w.group(1) == note_week:
                            v_type = sol.get("type", "zoom")
                            v_src = sol.get("videoSrc", "")
                            # If MP4 type, verify that local MP4 actually exists on disk
                            if v_type == "mp4" and v_src:
                                local_mp4 = bundle_root / v_src
                                if not local_mp4.is_file():
                                    v_src = sol.get("fallbackSrc", v_src)
                                    v_type = "zoom"
                            video_data = {
                                "type": v_type,
                                "src": v_src,
                                "time_str": time_str,
                                "seconds": sec,
                                "passcode": sol.get("passcode", ""),
                                "fallbackSrc": sol.get("fallbackSrc", ""),
                                "label": f"{'Zoom' if v_type == 'zoom' else 'Video'} @ {time_str}"
                            }
                            break
                except Exception:
                    pass

            # 3. If still not found, check if a local MP4 explicitly matches this week
            if not video_data and course_dir and note_week:
                cand_mp4s = [
                    f for f in (list(course_dir.glob("videos/*.mp4")) + list(course_dir.glob("*.mp4")))
                    if re.search(rf'\b(?:week|w)[_\s-]*0?{note_week}(?!\d)', f.name, re.IGNORECASE)
                ]
                if cand_mp4s:
                    rel_mp4 = str(cand_mp4s[0].relative_to(bundle_root)).replace("\\", "/")
                    video_data = {
                        "type": "mp4",
                        "src": rel_mp4,
                        "time_str": time_str,
                        "seconds": sec,
                        "passcode": "",
                        "label": f"Walkthrough ({time_str})"
                    }

    return cue.strip(), notes.strip(), video_data


def sanitize_cornell_card(cue: str, notes: str) -> Tuple[str, str]:
    """Sanitize video timestamps, slide footers, and OCR table artifacts from flashcards."""
    # Strip video timestamp references from displayed text
    notes = re.sub(r'\*\*Video Walkthrough Timestamp\*\*:\s*`?\[[\d:]+\]`?\s*', '', notes)
    notes = re.sub(r'^\[[\d: -]+\]\s*', '', notes)
    # Strip lecture slide footers like 10/11/2022 48520 E&C: Frequency Response 8
    notes = re.sub(r'\|\s*\d{1,2}/\d{1,2}/\d{4}\s*\|[^|]+\|\s*\d+\s*\|\s*', '', notes)
    notes = re.sub(r'\d{1,2}/\d{1,2}/\d{4}\s+48520\s+E&C:[^\n]+', '', notes)
    # Strip isolated private unicode bullets (e.g. \uf000-\uf8ff)
    notes = re.sub(r'[\uf000-\uf8ff]', '', notes)
    # Strip any residual video timestamp badges or links from the cue
    cue = re.sub(r'\[▶\s*[^\]]+\]\([^)]+\)', '', cue)
    cue = re.sub(r'\[(?:Timestamp:?\s*)?[0-9]{1,2}:\d{2}(?::\d{2})?\]\([^)]*\)', '', cue)
    cue = re.sub(r'\[(?:Timestamp:?\s*)?[0-9]{1,2}:\d{2}(?::\d{2})?\]', '', cue)
    cue = re.sub(r'\(?https?://[^\s\)]+\)?', '', cue)
    cue = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cue)
    cue = re.sub(r'\$H\(', '$H(s)$', cue)
    cue = re.sub(r'\$Z\(', '$Z(s)$', cue)
    cue = re.sub(r'\s{2,}', ' ', cue).strip()
    # Clean generic repetitive cues like 'What is the key principle or formula in Second Order Circuits?'
    m_cue = re.match(r'^What is the key principle or formula in (.+)\??$', cue.strip(), re.IGNORECASE)
    if m_cue:
        concept = m_cue.group(1).strip().rstrip('?')
        cue = f"What are the key governing principles and equations for {concept}?"
    return cue.strip(), notes.strip()


def collect_cornell_map(bundle_root: Path) -> Dict[str, CornellInfo]:
    """Scan bundle for generated Cornell notes JSON and HTML sidecars."""
    cornell_map: Dict[str, CornellInfo] = {}
    json_files = [p for p in bundle_root.rglob("*.json") if p.name.lower().endswith(("_cornell.json", "_cornell_cornell.json")) and "viz_icm" not in p.parts and "02_workers" not in p.parts]
    for jf in json_files:
        if "outputs" in jf.parts:
            try:
                c_data = json.loads(jf.read_text(encoding="utf-8"))
                src = c_data.get("source", "")
                html_candidate = jf.parent.parent / "html" / f"{jf.stem}.html"
                if not html_candidate.is_file():
                    html_candidate = jf.with_suffix(".html")
                if not html_candidate.is_file():
                    # Check case-insensitive or double _cornell
                    alt = jf.parent.parent / "html" / f"{jf.name.replace('.json', '.html')}"
                    if alt.is_file():
                        html_candidate = alt
                if html_candidate.is_file():
                    rel_html = str(html_candidate.relative_to(bundle_root)).replace("\\", "/")
                    clean_jf_stem = re.sub(r'_cornell(_cornell)?$', '', jf.stem, flags=re.IGNORECASE).lower().replace("-", "_").replace(" ", "_")
                    cards_list: List[Dict[str, Any]] = []
                    sections_list: List[Dict[str, Any]] = []
                    raw_sections = c_data.get("sections", [])
                    if not raw_sections and "cues" in c_data:
                        raw_sections = [{
                            "heading": "Worked Problem Solutions",
                            "summary": c_data.get("summary", ""),
                            "entries": [
                                {
                                    "cue": c.get("cue", ""),
                                    "notes": c.get("note", c.get("notes", "")),
                                    "badge": "problem",
                                    "timestamp": c.get("timestamp", ""),
                                    "seconds": c.get("seconds", 0)
                                }
                                for c in c_data.get("cues", [])
                            ]
                        }]
                    for sec_idx, sec in enumerate(raw_sections):
                        heading = sec.get("heading", "")
                        sec_entries = []
                        for e_idx, entry in enumerate(sec.get("entries", [])):
                            cue_text = entry.get("cue", "").strip()
                            notes_text = entry.get("notes", "").strip()
                            badge_text = entry.get("badge", "concept")
                            if cue_text:
                                raw_cue, raw_notes, video_payload = extract_video_info(cue_text, notes_text, jf, bundle_root)
                                clean_cue, clean_notes = sanitize_cornell_card(raw_cue, raw_notes)
                                card_item = {
                                    "id": f"{clean_jf_stem}_{sec_idx}_{e_idx}",
                                    "section": heading,
                                    "badge": badge_text,
                                    "cue": clean_cue,
                                    "notes": clean_notes
                                }
                                if video_payload:
                                    card_item["video"] = video_payload
                                    card_item["video_evidence"] = {
                                        "anchors": [{
                                            "start_seconds": video_payload.get("seconds", 0),
                                            "time_str": video_payload.get("time_str", "00:00"),
                                            "canonical_url": video_payload.get("src", ""),
                                            "role": "concept_explanation"
                                        }]
                                    }
                                cards_list.append(card_item)
                                sec_entries.append(card_item)
                        sections_list.append({
                            "heading": heading,
                            "entries": sec_entries,
                            "summary": sec.get("summary", "")
                        })

                    info = CornellInfo(
                        html_path=rel_html,
                        title=c_data.get("title", clean_jf_stem.replace("_", " ").title()),
                        cues=len(cards_list),
                        sections=len(c_data.get("sections", [])),
                        source=src,
                        cards=cards_list,
                        sections_data=sections_list,
                        raw_data=c_data
                    )
                    # Index under original and normalized stems
                    cornell_map[clean_jf_stem] = info
                    cornell_map[normalize_stem(clean_jf_stem)] = info
                    if src:
                        src_stem = Path(src).stem.lower().replace("-", "_").replace(" ", "_")
                        if src_stem not in ("index", "readme", "notes", "summary", "topic_notes", "tutorial_solutions"):
                            cornell_map[src_stem] = info
                            cornell_map[normalize_stem(src_stem)] = info
                            clean_src = re.sub(r'^(?:48520|48521|48430|41200)_+', '', src_stem)
                            cornell_map[clean_src] = info
                            cornell_map[normalize_stem(clean_src)] = info
            except Exception:
                pass
    return cornell_map


def generate_curriculum_tree_template(bundle_root: Path, target_file: Optional[Path] = None) -> Path:
    """Generate an editable, human-readable CURRICULUM_TREE.md outline of all courses and weekly modules."""
    tree_path = target_file if target_file else (bundle_root / "CURRICULUM_TREE.md")
    print(f"\n🌲 [Curriculum Tree] Generating editable Markdown tree outline at {tree_path.resolve()}")

    courses = [d for d in bundle_root.iterdir() if d.is_dir() and not d.name.startswith(".") and d.name not in ["references", "concepts"]]
    if not courses:
        courses = [bundle_root]

    tree_lines = [
        "# 🎓 University Curriculum Tree",
        "> **Canonical Canvas LMS Curriculum Hierarchy for all subjects.**",
        "> Edit this outline to rearrange modules, rename weeks, adjust sequencing, or add new notes.",
        "> Run `python3 compile_tree.py` to regenerate the interactive Knowledge Cosmos and Cornell Study Portal.",
        ""
    ]

    for course_dir in sorted(courses, key=lambda c: c.name):
        course_name = course_dir.name
        md_files = [f for f in course_dir.rglob("*.md") if f.name not in RESERVED_FILENAMES and "outputs" not in f.parts]
        if not md_files:
            continue

        tree_lines.append(f"## {course_name}\n")
        modules_map: Dict[Tuple[int, str], List[Tuple[str, str]]] = {}
        for mf in sorted(md_files):
            rel_to_bundle = str(mf.relative_to(bundle_root)).replace("\\", "/")
            meta, _ = parse_frontmatter(mf)
            _, m_label, order = classify_canvas_module(rel_to_bundle, meta, course_name)
            title = meta.get("title", mf.stem.replace("_", " ").title())
            rel_to_course = str(mf.relative_to(course_dir)).replace("\\", "/")
            modules_map.setdefault((order, m_label), []).append((rel_to_course, title))

        for (_, m_label), items in sorted(modules_map.items(), key=lambda x: (x[0][0], x[0][1])):
            tree_lines.append(f"### {m_label}")
            for rel_c, title in items:
                clean_path = rel_c.replace(".md", "")
                tree_lines.append(f"- [[{clean_path}]] {title}")
            tree_lines.append("")

    tree_path.write_text("\n".join(tree_lines), encoding="utf-8")
    print(f"  ✅ Saved Curriculum Tree outline: {tree_path.name}")
    return tree_path


def parse_curriculum_tree(
    tree_file: Path, bundle_root: Path
) -> Tuple[Dict[str, Dict[str, ModuleHub]], Dict[Tuple[str, str], NoteAssignment], Dict[str, NoteAssignment]]:
    """Parse CURRICULUM_TREE.md into typed module hubs and path-indexed note assignments."""
    print(f"\n📖 [Curriculum Tree] Parsing curriculum hierarchy from {tree_file.resolve()}")
    content = tree_file.read_text(encoding="utf-8")

    course_modules: Dict[str, Dict[str, ModuleHub]] = {}
    path_assignments: Dict[Tuple[str, str], NoteAssignment] = {}
    stem_assignments: Dict[str, NoteAssignment] = {}

    current_course: Optional[str] = None
    current_module_label = "Course Overview"
    current_module_order = 0
    current_module_id = "mod_overview"
    seq_counter = 1

    for line in content.splitlines():
        sline = line.strip()
        if not sline or sline.startswith(">"):
            continue

        if sline.startswith("# ") and not current_course:
            continue

        if sline.startswith("## "):
            current_course = sline.replace("## ", "").strip()
            c_tag = current_course.split()[0] if current_course else "Course"
            current_module_label = f"[{c_tag}] Course Overview"
            current_module_order = 0
            current_module_id = f"{current_course}/mod_overview"
            seq_counter = 1
            course_modules.setdefault(current_course, {})
            course_modules[current_course][current_module_id] = ModuleHub(
                id=current_module_id,
                label=current_module_label,
                order=0,
                course=current_course
            )
            continue

        if not current_course:
            continue

        is_module_header = False
        mod_text = ""
        if sline.startswith("### "):
            is_module_header = True
            mod_text = sline.replace("### ", "").strip()
        elif sline.startswith("- **") and sline.endswith("**") and "[[" not in sline and "(" not in sline:
            is_module_header = True
            mod_text = sline.strip("- *")

        if is_module_header:
            c_tag = current_course.split()[0] if current_course else ""
            current_module_label = mod_text
            m_num = re.search(r'\b(?:week|module|w|m)[_\s-]*(\d{1,2})\b', mod_text, re.IGNORECASE)
            if m_num:
                current_module_order = int(m_num.group(1))
                if re.search(r'\b(?:week|w)\b', mod_text, re.IGNORECASE) or mod_text.lower().startswith(("week", "w")):
                    clean_slug = f"mod_w{current_module_order:02d}"
                    current_module_label = f"[{c_tag}] Week {current_module_order:02d}"
                else:
                    clean_slug = f"mod_m{current_module_order:02d}"
                    current_module_label = f"[{c_tag}] Module {current_module_order:02d}"
            elif "overview" in mod_text.lower() or "intro" in mod_text.lower():
                current_module_order = 0
                clean_slug = "mod_overview"
                current_module_label = f"[{c_tag}] Course Overview"
            elif "quiz" in mod_text.lower() or "exam" in mod_text.lower():
                current_module_order = 85
                clean_slug = "mod_quizzes"
                current_module_label = f"[{c_tag}] Quizzes & Practice"
            elif "assignment" in mod_text.lower() or "project" in mod_text.lower():
                current_module_order = 90
                clean_slug = "mod_assignments"
                current_module_label = f"[{c_tag}] Assignments & Projects"
            else:
                current_module_order = seq_counter
                seq_counter += 1
                clean_slug = "mod_" + re.sub(r'[^a-zA-Z0-9]+', '_', mod_text.lower()).strip('_')
                current_module_label = f"[{c_tag}] {mod_text}" if c_tag and not mod_text.startswith("[") else mod_text

            current_module_id = f"{current_course}/{clean_slug}"

            course_modules.setdefault(current_course, {})
            course_modules[current_course][current_module_id] = ModuleHub(
                id=current_module_id,
                label=current_module_label,
                order=current_module_order,
                course=current_course
            )
            continue

        if sline.startswith("- ") or sline.startswith("* "):
            item_body = sline[2:].strip()
            wm = re.search(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\](?:\s*(.*))?', item_body)
            mm = re.search(r'\[([^\]]+)\]\(([^)]+)\)', item_body)

            target = None
            custom_title = None
            if wm:
                target = wm.group(1).strip()
                custom_title = wm.group(2) or wm.group(3) or ""
            elif mm:
                custom_title = mm.group(1).strip()
                target = mm.group(2).strip()

            if target:
                target_clean = target.replace(".md", "").strip("/")
                stem = Path(target_clean).name.lower().replace("-", "_").replace(" ", "_")
                clean_target = target_clean.lower().replace("\\", "/").replace("-", "_").replace(" ", "_")

                assignment = NoteAssignment(
                    course=current_course,
                    module_id=current_module_id,
                    module=current_module_label,
                    order=current_module_order,
                    custom_title=custom_title.strip() if custom_title else ""
                )
                path_assignments[(current_course, clean_target)] = assignment
                path_assignments[(current_course, stem)] = assignment
                stem_assignments[stem] = assignment

    total_hubs = sum(len(m) for m in course_modules.values())
    print(f"  ✅ Parsed {len(course_modules)} courses with {total_hubs} module hubs")
    return course_modules, path_assignments, stem_assignments


def build_graph_nodes(
    bundle_root: Path,
    md_files: List[Path],
    cornell_map: Dict[str, CornellInfo],
    tree_hubs: Optional[Dict[str, Dict[str, ModuleHub]]] = None,
    path_assignments: Optional[Dict[Tuple[str, str], NoteAssignment]] = None,
    stem_assignments: Optional[Dict[str, NoteAssignment]] = None,
) -> Tuple[List[Dict[str, Any]], Set[str], Dict[str, str], Dict[str, Dict[str, ModuleHub]]]:
    """Extract content nodes and module hub nodes for the graph simulation."""
    nodes: List[Dict[str, Any]] = []
    node_ids: Set[str] = set()
    file_to_id: Dict[str, str] = {}
    module_hubs: Dict[str, Dict[str, ModuleHub]] = dict(tree_hubs) if tree_hubs else {}

    worked_weeks_by_course: Dict[str, Set[int]] = {}
    for mf in md_files:
        rel = mf.relative_to(bundle_root)
        c = rel.parts[0] if len(rel.parts) > 1 else "General"
        s_low = mf.stem.lower()
        if "worked_solutions" in s_low:
            m = re.search(r'(?:^|[\s/_-])(?:week|w)[_\s-]*(\d{1,2})(?!\d)', s_low)
            if m:
                worked_weeks_by_course.setdefault(c, set()).add(int(m.group(1)))

    seen_body_hashes: Set[Tuple[str, str]] = set()
    seen_dialogue_sigs: Set[Tuple[str, str]] = set()

    def file_priority_key(mf: Path) -> Tuple[int, int, str]:
        rel = mf.relative_to(bundle_root)
        is_rec = "recordings" in rel.parts
        return (1 if is_rec else 0, len(rel.parts), str(rel))

    for md_file in sorted(md_files, key=file_priority_key):
        rel_path = md_file.relative_to(bundle_root)
        fname_low = md_file.name.lower()
        fstem_low = md_file.stem.lower()
        parts = rel_path.parts
        course = parts[0] if len(parts) > 1 else "General"

        if fname_low in RESERVED_FILENAMES or "outputs" in md_file.parts:
            continue

        if any(pat in fstem_low for pat in ADMIN_PATTERNS) or "get started" in str(rel_path).lower():
            continue

        if "passcode" in fstem_low:
            continue

        if ("tutorial_solutions" in fstem_low or "tutorial_solutions_ocr" in fstem_low) and "worked" not in fstem_low:
            m_w = re.search(r'(?:^|[\s/_-])(?:week|w)[_\s-]*(\d{1,2})(?!\d)', fstem_low)
            if m_w and int(m_w.group(1)) in worked_weeks_by_course.get(course, set()):
                continue

        meta, body = parse_frontmatter(md_file)

        words = len(re.findall(r'\b\w+\b', body))
        if words < 25:
            continue

        if "canvas.uts.edu.au/courses" in body and words < 40 and "topic_notes" in fstem_low:
            continue

        if "transcript" in fstem_low:
            matches = re.findall(r'-\s*`?\[?\d{1,2}:\d{2}(?::\d{2})?\]?`?\s*\*\*[^*]+\*\*:[^\n]+', body)
            if matches:
                dia_sample = "".join(matches[:15])
                dia_sig = hashlib.sha256(dia_sample.encode("utf-8")).hexdigest()
                dia_key = (course, dia_sig)
                if dia_key in seen_dialogue_sigs:
                    continue
                seen_dialogue_sigs.add(dia_key)

        body_hash = hashlib.sha256(body.strip().encode("utf-8")).hexdigest()
        hash_key = (course, body_hash)
        if hash_key in seen_body_hashes:
            continue
        seen_body_hashes.add(hash_key)

        concept_id = str(rel_path.with_suffix("")).replace("\\", "/")
        file_to_id[str(rel_path).replace("\\", "/")] = concept_id
        file_to_id[md_file.name] = concept_id

        title = meta.get("title", md_file.stem.replace("_", " ").title())
        desc = meta.get("description", "")
        ctype = meta.get("type", "Concept")
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]

        assigned: Optional[NoteAssignment] = None
        if path_assignments and stem_assignments:
            clean_stem = md_file.stem.lower().replace("-", "_").replace(" ", "_")
            course_dir = bundle_root / course
            try:
                rel_to_course = str(md_file.relative_to(course_dir).with_suffix("")).lower().replace("\\", "/").replace("-", "_").replace(" ", "_")
            except Exception:
                rel_to_course = clean_stem

            assigned = (
                path_assignments.get((course, rel_to_course))
                or path_assignments.get((course, clean_stem))
                or stem_assignments.get(clean_stem)
            )

        if assigned:
            mod_id = assigned.module_id
            mod_label = assigned.module
            mod_order = assigned.order
            course = assigned.course
            if assigned.custom_title:
                title = assigned.custom_title
        elif path_assignments is not None and len(path_assignments) > 0:
            continue
        else:
            mod_id, mod_label, mod_order = classify_canvas_module(rel_path, meta, course)

        module_hubs.setdefault(course, {})
        if mod_id not in module_hubs[course]:
            module_hubs[course][mod_id] = ModuleHub(id=mod_id, label=mod_label, order=mod_order, course=course)

        # Fallback guard: Auto-enrich bare generic titles if they lack academic context
        cleaned_check = re.sub(r'^\[[^\]]+\]\s*', '', title)
        cleaned_check = re.sub(r'^(?:week|w)\s*\d+[\s:_-]*', '', cleaned_check, flags=re.IGNORECASE).strip()
        GENERIC_TITLES = {
            "overview", "topic notes", "tutorial recording", "tutorial solutions",
            "knowledge recap", "lecture notes", "ppt", "tutorial", "notes", "summary"
        }
        if cleaned_check.lower() in GENERIC_TITLES and mod_label and mod_label not in ("Overview", "Course Overview"):
            course_code = course.split()[0]
            w_match = re.search(r'\b(?:week|w)[_\s-]*(\d{1,2})\b', str(rel_path), re.IGNORECASE)
            w_badge = f" W{int(w_match.group(1)):02d}" if w_match else ""
            title = f"[{course_code}{w_badge}] {cleaned_check.title()}: {mod_label}"

        clean_stem = md_file.stem.lower().replace("-", "_").replace(" ", "_")
        norm_stem = normalize_stem(clean_stem)
        cornell_info = cornell_map.get(clean_stem) or cornell_map.get(norm_stem)
        has_cornell = cornell_info is not None
        cornell_path = cornell_info.html_path if cornell_info else ""
        cornell_cues = cornell_info.cues if cornell_info else 0

        verified = meta.get("verified", None)
        if not verified:
            trust = "Unverified"
        elif "human:" in str(verified):
            trust = "Human-Reviewed"
        else:
            trust = "Machine-Confirmed"

        nodes.append({
            "data": {
                "id": concept_id,
                "label": title,
                "type": ctype,
                "description": desc,
                "tags": tags,
                "trust": trust,
                "course": course,
                "module": mod_label,
                "moduleId": mod_id,
                "path": str(rel_path).replace("\\", "/"),
                "degree": 0,
                "has_cornell": has_cornell,
                "cornell_path": cornell_path,
                "cornell_cues": cornell_cues,
                "cornell_cards": cornell_info.cards if cornell_info else [],
                "cornell_sections": cornell_info.sections_data if cornell_info else []
            }
        })
        node_ids.add(concept_id)

    for course, hubs in module_hubs.items():
        for mod_id, hub in hubs.items():
            nodes.append({
                "data": {
                    "id": mod_id,
                    "label": hub.label,
                    "type": "ModuleHub",
                    "description": f"Canvas LMS Module container for {hub.label}",
                    "tags": ["canvas-module", hub.label.lower().replace(" ", "-")],
                    "trust": "Machine-Confirmed",
                    "course": course,
                    "module": hub.label,
                    "moduleId": mod_id,
                    "order": hub.order,
                    "degree": 0,
                    "has_cornell": False,
                    "cornell_path": "",
                    "cornell_cues": 0,
                    "cornell_cards": []
                }
            })
            node_ids.add(mod_id)

    return nodes, node_ids, file_to_id, module_hubs


def build_graph_edges(
    nodes: List[Dict[str, Any]],
    node_ids: Set[str],
    module_hubs: Dict[str, Dict[str, ModuleHub]],
    md_files: List[Path],
    file_to_id: Dict[str, str],
    bundle_root: Path
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Build chronological spines, module containment, and cross-reference links."""
    edges: List[Dict[str, Any]] = []
    edge_set: Set[Tuple[str, str]] = set()
    degree_map: Dict[str, int] = {}
    node_course: Dict[str, str] = {n["data"]["id"]: n["data"].get("course", "General") for n in nodes}

    def add_edge(src: str, tgt: str, etype: str) -> None:
        # Strictly insulate subjects: prevent cross-course contamination
        if node_course.get(src) != node_course.get(tgt):
            return
        key = (src, tgt)
        if key not in edge_set and src in node_ids and tgt in node_ids and src != tgt:
            edge_set.add(key)
            edges.append({
                "data": {
                    "id": f"{src}->{tgt}",
                    "source": src,
                    "target": tgt,
                    "type": etype
                }
            })
            degree_map[src] = degree_map.get(src, 0) + 1
            degree_map[tgt] = degree_map.get(tgt, 0) + 1

    # 1. Weekly Spines between consecutive ModuleHubs
    for _, hubs in module_hubs.items():
        sorted_hubs = sorted(hubs.values(), key=lambda x: x.order)
        for i in range(len(sorted_hubs) - 1):
            add_edge(sorted_hubs[i].id, sorted_hubs[i + 1].id, "spine")

    # 2. Module Containment edges from ModuleHubs to concept nodes
    for n in nodes:
        if n["data"]["type"] != "ModuleHub":
            m_id = n["data"].get("moduleId")
            n_id = n["data"]["id"]
            if m_id:
                add_edge(m_id, n_id, "containment")

    # 3. Explicit Reference links extracted from markdown bodies
    for md_file in md_files:
        rel_path = md_file.relative_to(bundle_root)
        if md_file.name in RESERVED_FILENAMES or "outputs" in md_file.parts:
            continue

        source_id = str(rel_path.with_suffix("")).replace("\\", "/")
        _, body = parse_frontmatter(md_file)
        for l in extract_links(body):
            target_id = None
            cleaned = l.lstrip("/").replace(".md", "")
            if cleaned in node_ids:
                target_id = cleaned
            elif l in file_to_id:
                target_id = file_to_id[l]
            elif Path(l).name in file_to_id:
                target_id = file_to_id[Path(l).name]

            if target_id and target_id in node_ids and target_id != source_id:
                add_edge(source_id, target_id, "reference")

    # 4. Intra-module Pedagogical Workflow edges
    by_course_mod: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for n in nodes:
        d = n["data"]
        if d.get("type") == "ModuleHub":
            continue
        c = d.get("course", "General")
        m = d.get("moduleId", "")
        if m:
            by_course_mod.setdefault((c, m), []).append(d)
        else:
            by_course_mod.setdefault((c, "root"), []).append(d)

    def get_pedagogical_role(it: Dict[str, Any]) -> int:
        lbl = (it.get("label", "") + " " + it.get("id", "")).lower()
        if "overview" in lbl or "guide" in lbl or "learning guide" in lbl or "timetable" in lbl or "get started" in lbl:
            return 1
        if "prework" in lbl or "preparation" in lbl or "reading" in lbl:
            return 2
        if any(k in lbl for k in ["topic", "notes", "lecture", "material", "semiconductor", "electrostatic", "slide", "ppt", "scope", "circuit", "diode", "transistor", "magnetic", "motor", "meter", "c_prog"]):
            return 3
        if "lab" in lbl or "workshop" in lbl or "excel" in lbl:
            return 4
        if "tutorial" in lbl and not any(k in lbl for k in ["solution", "recording"]):
            return 5
        if "solution" in lbl or "quiz" in lbl or "exam" in lbl or "answer" in lbl:
            return 6
        if any(k in lbl for k in ["recording", "video", "transcript"]):
            return 7
        if "recap" in lbl or "summary" in lbl:
            return 8
        return 3

    for (c, m), items in by_course_mod.items():
        sorted_items = sorted(items, key=lambda x: (get_pedagogical_role(x), x.get("label", "")))
        # Sequential intra-module chain connecting the full learning journey
        for i in range(len(sorted_items) - 1):
            add_edge(sorted_items[i]["id"], sorted_items[i + 1]["id"], "pedagogical")
        # Star connection from primary core lecture to all module materials
        lectures = [it for it in sorted_items if get_pedagogical_role(it) == 3]
        prim = lectures[0] if lectures else sorted_items[0]
        for it in sorted_items:
            if it["id"] != prim["id"]:
                add_edge(prim["id"], it["id"], "pedagogical")

    # 5. Curriculum Progression & Prerequisite chains across modules
    mod_order_map = {n["data"]["id"]: n["data"].get("order", 0) for n in nodes if n["data"].get("type") == "ModuleHub"}
    by_course: Dict[str, List[Dict[str, Any]]] = {}
    for n in nodes:
        d = n["data"]
        if d.get("type") == "ModuleHub":
            continue
        by_course.setdefault(d.get("course", "General"), []).append(d)

    for c, c_nodes in by_course.items():
        c_mods: Dict[str, List[Dict[str, Any]]] = {}
        for cn in c_nodes:
            m = cn.get("moduleId", "root")
            c_mods.setdefault(m, []).append(cn)

        sorted_m_keys = sorted(c_mods.keys(), key=lambda m: mod_order_map.get(m, 999))
        for i in range(len(sorted_m_keys) - 1):
            m1, m2 = sorted_m_keys[i], sorted_m_keys[i + 1]
            add_edge(c_mods[m1][0]["id"], c_mods[m2][0]["id"], "prerequisite")

    # 6. General ecosystem links (strictly intra-General)
    general_links = [
        ("cornell_notes_skill_agent_brief", "AGENTS")
    ]
    for s, t in general_links:
        add_edge(s, t, "pedagogical")

    return edges, degree_map


def generate_cornell_portal(bundle_root: Path, nodes: List[Dict[str, Any]]) -> bool:
    """Generate standalone Canvas Cornell Notes Study Portal HTML using external template."""
    portal_path = bundle_root / "cornell_index.html"
    print(f"\n📖 [Cornell Portal] Building Canvas Study Portal at {portal_path.resolve()}")

    grouped: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    total_cues = 0

    for n in nodes:
        d = n["data"]
        if d.get("has_cornell") and d.get("cornell_path"):
            c = d.get("course", "General")
            m = d.get("module", "Overview")
            grouped.setdefault(c, {}).setdefault(m, []).append(d)
            total_cues += d.get("cornell_cues", 0)

    total_cornell_notes = sum(len(items) for c_dict in grouped.values() for items in c_dict.values())
    template_file = TEMPLATE_DIR / "cornell_portal_template.html"
    if not template_file.is_file():
        print(f"❌ Error: Cornell template not found: {template_file}")
        return False

    sections_html: List[str] = []
    course_filter_buttons: List[str] = ['<button class="course-filter-btn active" onclick="filterByCourse(\'all\', this)">All Subjects</button>']
    for course, mods in sorted(grouped.items()):
        short_course = course.split()[0]
        course_filter_buttons.append(f'<button class="course-filter-btn" onclick="filterByCourse(\'{course}\', this)">{short_course}</button>')
        sections_html.append(f'  <section class="course-section" data-course="{course}">\n    <div class="course-header"><span>🏛️</span> {course}</div>')
        for mod_name, items in sorted(mods.items(), key=lambda x: week_sort_key(x[0])):
            sections_html.append(f'    <div class="module-group" data-module="{mod_name}">\n      <div class="module-header"><span>📅 {mod_name}</span><span style="font-size:12px; color:var(--text-dim);">{len(items)} Study Notes</span></div>\n      <div class="notes-grid">')
            for itm in sorted(items, key=lambda x: clean_display_title(x.get("label", ""))):
                raw_title = itm.get("label", "Note")
                clean_title = clean_display_title(raw_title)
                cues = itm.get("cornell_cues", 0)
                note_id = itm.get("id", "")
                html_rel = itm.get("cornell_path", "#")
                sections_html.append(f'        <div class="note-card" data-title="{clean_title.lower()}">\n          <div>\n            <div class="note-title">{clean_title}</div>\n            <div class="note-badges"><span class="badge-cues">⚡ {cues} Active Recall Cues</span></div>\n          </div>\n          <div class="card-actions"><a href="study.html?note={note_id}&mode=sync" class="btn-study" target="_blank">🎬 Study Workspace &rsaquo;</a><a href="{html_rel}" class="btn-study" style="background:#1a2332; color:#89b4fa; border-color:rgba(137,180,250,0.3);" target="_blank">📄 Print Sheet</a></div>\n        </div>')
            sections_html.append('      </div>\n    </div>')
        sections_html.append('  </section>')

    content = template_file.read_text(encoding="utf-8")
    content = content.replace("{{TOTAL_CORNELL_NOTES}}", str(total_cornell_notes))
    content = content.replace("{{TOTAL_CUES}}", str(total_cues))
    content = content.replace("{{TOTAL_SUBJECTS}}", str(len(grouped)))
    content = content.replace("{{COURSE_FILTER_BUTTONS}}", "\n    ".join(course_filter_buttons))
    content = content.replace("{{COURSE_SECTIONS}}", "\n".join(sections_html))

    portal_path.write_text(content, encoding="utf-8")
    print(f"  🎉 Cornell Study Portal generated: {portal_path.resolve()}")
    return True


def generate_study_workspace(bundle_root: Path, nodes: List[Dict[str, Any]], cornell_map: Dict[str, CornellInfo]) -> bool:
    """Generate standalone study.html interactive lecture companion and active recall workspace."""
    template_path = TEMPLATE_DIR / "study_workspace_template.html"
    if not template_path.is_file():
        print(f"⚠️ Warning: Study workspace template not found at {template_path}")
        return False

    out_path = bundle_root / "study.html"
    print(f"\n📖 [Study Workspace] Compiling Interactive Study Companion at {out_path.resolve()}")

    courses_map: Dict[str, Dict[str, Any]] = {}
    notes_payload: Dict[str, Any] = {}

    all_mp4s: List[Path] = [p for p in bundle_root.rglob("*.mp4") if "viz_icm" not in p.parts and "02_workers" not in p.parts]

    solutions_db = {}
    sol_path = TEMPLATE_DIR / "viz" / "data" / "worked_solutions_db.json"
    if sol_path.is_file():
        try:
            solutions_db = json.loads(sol_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    for n in nodes:
        d = n["data"]
        course_name = d.get("course", "General")
        mod_label = d.get("module", "Overview")
        concept_id = d.get("id")

        if course_name not in courses_map:
            courses_map[course_name] = {
                "id": course_name,
                "label": course_name
            }

        if d.get("type") == "ModuleHub":
            continue

        file_path_str = d.get("path", "")
        clean_stem = Path(file_path_str).stem.lower().replace("-", "_").replace(" ", "_") if file_path_str else concept_id
        c_info = cornell_map.get(clean_stem) or cornell_map.get(normalize_stem(clean_stem)) if clean_stem else None

        raw_sections = []
        cues_list = []
        if c_info:
            if c_info.sections_data:
                raw_sections = c_info.sections_data
            elif c_info.raw_data and "sections" in c_info.raw_data:
                raw_sections = c_info.raw_data["sections"]
            cues_list = c_info.cards

        # Read markdown fallback if sections are empty
        markdown_body = ""
        if file_path_str:
            full_md_path = bundle_root / file_path_str
            if full_md_path.is_file():
                try:
                    _, markdown_body = parse_frontmatter(full_md_path)
                except Exception:
                    pass

        # Try to match local MP4 video
        matched_mp4 = ""
        course_code = course_name.split()[0]
        w_match_mod = re.search(r'(?:week|w)[_\s-]*(\d{1,2})', mod_label, re.IGNORECASE)
        target_week = int(w_match_mod.group(1)) if w_match_mod else None

        # Check if note is genuinely video-linked (transcript, recording, worked solutions, or video cues)
        is_video_doc = (
            "recording" in clean_stem
            or "transcript" in clean_stem
            or "worked_solutions" in clean_stem
            or "video" in file_path_str.lower()
            or (c_info and any(getattr(c, "video", None) for c in getattr(c_info, "cards", [])))
        )

        if is_video_doc and target_week is not None:
            is_tutorial = "tutorial" in clean_stem or "tutorial" in file_path_str.lower()
            for mp4 in all_mp4s:
                if course_code in str(mp4):
                    w_match_mp4 = re.search(r'(?:week|w)[_\s-]*(\d{1,2})', str(mp4), re.IGNORECASE)
                    if w_match_mp4 and int(w_match_mp4.group(1)) == target_week:
                        if is_tutorial and "tutorial" in mp4.name.lower():
                            matched_mp4 = str(mp4.relative_to(bundle_root)).replace("\\", "/")
                            break
                        elif not is_tutorial and "topic" in mp4.name.lower():
                            matched_mp4 = str(mp4.relative_to(bundle_root)).replace("\\", "/")
                            break
                        elif not matched_mp4:
                            matched_mp4 = str(mp4.relative_to(bundle_root)).replace("\\", "/")

        # Find Zoom info
        zoom_url = ""
        passcode = ""
        for sec in raw_sections:
            for entry in sec.get("entries", []):
                ve = entry.get("video_evidence", {})
                for anc in ve.get("anchors", []):
                    curl = anc.get("canonical_url", "")
                    if "zoom.us" in curl:
                        zoom_url = curl
                        break
                if zoom_url:
                    break
            if zoom_url:
                break

        if not zoom_url and not matched_mp4:
            clean_id = concept_id.lower()
            for k, v in solutions_db.items():
                if k in clean_id:
                    zoom_url = v.get("videoSrc", "")
                    passcode = v.get("passcode", "")
                    break

        is_transcript = "transcript" in clean_stem or "transcript" in d.get("label", "").lower()
        is_spreadsheet = "excel" in clean_stem or "sheet" in clean_stem or bool(re.search(r'\|\s*[-:]+\s*\|', markdown_body))
        is_solutions = "solution" in clean_stem
        has_video = bool(matched_mp4 or zoom_url)

        if cues_list:
            asset_type = "cornell"
        elif is_transcript:
            asset_type = "transcript"
        elif is_solutions:
            asset_type = "solutions"
        elif has_video:
            asset_type = "video"
        elif is_spreadsheet:
            asset_type = "spreadsheet"
        else:
            asset_type = "document"

        note_entry = {
            "id": concept_id,
            "stem": clean_stem,
            "title": clean_display_title(d.get("label", "Note")),
            "course": course_name,
            "module": mod_label,
            "source": file_path_str,
            "asset_type": asset_type,
            "html_path": d.get("cornell_path", ""),
            "video_src": matched_mp4,
            "zoom_url": zoom_url,
            "passcode": passcode,
            "sections": raw_sections,
            "cues": cues_list,
            "markdown_content": markdown_body
        }
        notes_payload[concept_id] = note_entry

    courses_list = sorted(list(courses_map.values()), key=lambda x: x["label"])
    study_payload = {
        "courses": courses_list,
        "notes": notes_payload
    }

    template_content = template_path.read_text(encoding="utf-8")
    rendered = template_content.replace("/* __STUDY_DATA__ */ {}", f"window.STUDY_DATA = {json.dumps(study_payload, indent=2)};")
    out_path.write_text(rendered, encoding="utf-8")
    print(f"  🎉 Study Workspace generated: {out_path.resolve()}")
    return True



def load_and_assemble_viz_template(template_dir: Path) -> str:
    """Load and assemble viz_template from modular templates/viz/ or fallback to monolithic viz_template.html."""
    modular_index = template_dir / "viz" / "index.html"
    if modular_index.is_file():
        viz_root = template_dir / "viz"
        raw_index = modular_index.read_text(encoding="utf-8")

        solutions_json_path = viz_root / "data" / "worked_solutions_db.json"
        solutions_json = "{}"
        if solutions_json_path.is_file():
            solutions_json = solutions_json_path.read_text(encoding="utf-8")

        def replace_include(match):
            rel_inc = match.group(1).strip("\"' ")
            inc_file = viz_root / rel_inc
            if inc_file.is_file():
                content = inc_file.read_text(encoding="utf-8")
                if "/* __WORKED_SOLUTIONS_DB__ */ {}" in content:
                    content = content.replace("/* __WORKED_SOLUTIONS_DB__ */ {}", solutions_json)
                elif "/* __WORKED_SOLUTIONS_DB__ */" in content:
                    content = content.replace("/* __WORKED_SOLUTIONS_DB__ */", solutions_json)
                return content
            print(f"⚠️ Warning: Included template module not found: {inc_file}")
            return f"<!-- Missing include: {rel_inc} -->"

        assembled = re.sub(r'<!--\s*@include\s+["\']([^"\']+)["\']\s*-->', replace_include, raw_index)
        return assembled

    fallback = template_dir / "viz_template.html"
    if fallback.is_file():
        return fallback.read_text(encoding="utf-8")
    return ""


def generate_viz(bundle_root: Path, output_file: Optional[Path] = None, tree_file: Optional[Path] = None) -> bool:
    """Generate standalone viz.html interactive graph and cornell study portal for OKF bundle."""
    print(f"\n📊 [Knowledge Graph] Generating Canvas-Structured viz.html for bundle: {bundle_root.resolve()}")
    if not bundle_root.is_dir():
        print(f"❌ Error: Not a directory: {bundle_root}")
        return False

    md_files = [
        f for f in bundle_root.rglob("*.md")
        if "viz_icm" not in f.parts
        and "02_workers" not in f.parts
        and ".git" not in f.parts
        and ".kanban" not in f.parts
        and "outputs" not in f.parts
        and not any(p.startswith(".") for p in f.parts)
        and len(f.relative_to(bundle_root).parts) > 1
    ]
    cornell_map = collect_cornell_map(bundle_root)

    active_tree = tree_file
    tree_hubs = None
    path_assignments = None
    stem_assignments = None
    if active_tree and active_tree.is_file():
        tree_hubs, path_assignments, stem_assignments = parse_curriculum_tree(active_tree, bundle_root)

    nodes, node_ids, file_to_id, module_hubs = build_graph_nodes(
        bundle_root, md_files, cornell_map, tree_hubs, path_assignments, stem_assignments
    )
    edges, degree_map = build_graph_edges(nodes, node_ids, module_hubs, md_files, file_to_id, bundle_root)

    for n in nodes:
        n["data"]["degree"] = degree_map.get(n["data"]["id"], 0)

    template_html = load_and_assemble_viz_template(TEMPLATE_DIR)
    if not template_html:
        print(f"❌ Error: viz template missing at {TEMPLATE_DIR}")
        return False

    graph_payload = {"nodes": nodes, "edges": edges}
    graph_json = json.dumps(graph_payload, indent=2)

    d3_path = TEMPLATE_DIR / "d3.min.js"
    d3_code = d3_path.read_text(encoding="utf-8") if d3_path.is_file() else ""
    rendered_html = template_html.replace("/* __D3_INLINE__ */", d3_code)
    if "/* __GRAPH_DATA__ */ {}" in rendered_html:
        rendered_html = rendered_html.replace("/* __GRAPH_DATA__ */ {}", graph_json)
    else:
        rendered_html = rendered_html.replace("/* __GRAPH_DATA__ */", graph_json)

    out_path = output_file if output_file else (bundle_root / "viz.html")
    out_path.write_text(rendered_html, encoding="utf-8")

    print(f"  ✅ Extracted {len(nodes)} total nodes ({len(module_hubs)} course galaxies) and {len(edges)} relation edges")
    print(f"  🎉 Knowledge graph generated: {out_path.resolve()}")

    generate_cornell_portal(bundle_root, nodes)
    generate_study_workspace(bundle_root, nodes, cornell_map)
    return True


def compile_tree(bundle_root: Path, tree_file: Optional[Path] = None, init: bool = False, output_file: Optional[Path] = None) -> bool:
    """Compile university notes into interactive knowledge cosmos and study portal using dynamic discovery."""
    return generate_viz(bundle_root, output_file=output_file, tree_file=tree_file)


def clean_concept_filename(old_name: str, parent_dir_name: str = "") -> str:
    """Normalize messy filename into clean OKF kebab/snake slug."""
    SYSTEM_FILES = {"index.md", "log.md", "agents.md", "readme.md", "context.md"}
    if old_name.lower() in SYSTEM_FILES:
        return old_name

    stem = Path(old_name).stem
    stem = re.sub(r'[\U00010000-\U0010ffff]', '', stem)
    stem = re.sub(r'[^\x00-\x7F]+', '', stem)
    stem = re.sub(r'\s*-\s*by\s+Dr.*$', '', stem, flags=re.IGNORECASE)
    stem = re.sub(r'\s*-\s*Passcode.*$', '', stem, flags=re.IGNORECASE)
    stem = re.sub(r'_\d{4}_\d+(nd|rd|th|st)?', '', stem, flags=re.IGNORECASE)
    stem = re.sub(r'\s*worked\s+solutions', '_solutions', stem, flags=re.IGNORECASE)

    m_week = re.search(r'\b(?:week|w)[_\s-]*(\d{1,2})\b', stem, re.IGNORECASE)
    week_prefix = f"w{int(m_week.group(1)):02d}_" if m_week else ""

    cleaned = re.sub(r'[\s_:\-\—\–\/\(\)\,\@\%\&]+', '_', stem).strip('_').lower()
    cleaned = re.sub(r'_+', '_', cleaned)

    if re.match(r'^w\d{2}_', cleaned):
        final_slug = cleaned
    else:
        final_slug = f"{week_prefix}{cleaned}" if week_prefix and not cleaned.startswith(week_prefix) else cleaned

    return f"{final_slug}.md"


def normalize_bundle(bundle_root: Path, dry_run: bool = False) -> bool:
    """Normalize all concept markdown filenames and rewrite cross-references."""
    print(f"\n✨ [OKF Normalize] Scanning bundle: {bundle_root.resolve()}")
    if not bundle_root.is_dir():
        print(f"❌ Error: Not a directory: {bundle_root}")
        return False

    rename_map: Dict[Path, Path] = {}
    link_rewrites: Dict[str, str] = {}

    for md_file in bundle_root.rglob("*.md"):
        if md_file.name.lower() in RESERVED_FILENAMES or "outputs" in md_file.parts:
            continue

        new_name = clean_concept_filename(md_file.name, md_file.parent.name)
        if new_name != md_file.name:
            target_path = md_file.parent / new_name
            rename_map[md_file] = target_path

            old_rel = str(md_file.relative_to(bundle_root)).replace("\\", "/")
            new_rel = str(target_path.relative_to(bundle_root)).replace("\\", "/")
            link_rewrites[f"/{old_rel}"] = f"/{new_rel}"
            link_rewrites[f"/{old_rel.replace('.md', '')}"] = f"/{new_rel.replace('.md', '')}"
            link_rewrites[md_file.name] = new_name

    print(f"  🔍 Found {len(rename_map)} concept files to normalize")
    if not rename_map:
        print("  ✅ All concept filenames already conform to OKF slug standards!")
        return True

    if dry_run:
        print("\n[Dry Run Preview]:")
        for old_p, new_p in list(rename_map.items())[:15]:
            print(f"  • {old_p.name} -> {new_p.name}")
        if len(rename_map) > 15:
            print(f"  ... and {len(rename_map) - 15} more files.")
        return True

    for old_p, new_p in rename_map.items():
        old_p.rename(new_p)
        print(f"  ✏️  Renamed: {old_p.name} -> {new_p.name}")

    print("\n  🔗 Rewriting internal links to match normalized filenames...")
    for md_file in bundle_root.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8", errors="replace")
        updated = content
        for old_link, new_link in link_rewrites.items():
            if old_link in updated:
                updated = updated.replace(old_link, new_link)
        if updated != content:
            md_file.write_text(updated, encoding="utf-8")

    print("\n  🔄 Rebuilding progressive disclosure indexes and viz.html...")
    refresh_indexes(bundle_root)
    generate_viz(bundle_root)
    print("🎉 Bundle normalized and synchronized successfully!")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="okf-architect: Open Knowledge Format (OKF v0.2) architect & validator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_audit = subparsers.add_parser("validate", aliases=["audit"], help="Validate an OKF bundle against spec v0.2")
    p_audit.add_argument("path", type=str, nargs="?", default=".", help="Path to OKF bundle root")
    p_audit.add_argument("--json", action="store_true", help="Emit validation report as JSON on stdout")

    p_scaffold = subparsers.add_parser("scaffold", help="Scaffold a new OKF bundle structure")
    p_scaffold.add_argument("path", type=str, nargs="?", default=".", help="Target directory")
    p_scaffold.add_argument("--title", type=str, default="Knowledge Bundle", help="Bundle title")
    p_scaffold.add_argument("--domain", type=str, default="Knowledge", help="Primary domain tag")

    p_index = subparsers.add_parser("index", help="Rebuild index.md files for progressive disclosure")
    p_index.add_argument("path", type=str, nargs="?", default=".", help="Path to OKF bundle root")

    p_viz = subparsers.add_parser("viz", aliases=["graph"], help="Generate interactive knowledge graph (viz.html)")
    p_viz.add_argument("path", type=str, nargs="?", default=".", help="Path to OKF bundle root")
    p_viz.add_argument("--tree", type=str, default=None, help="Path to CURRICULUM_TREE.md outline")
    p_viz.add_argument("-o", "--output", type=str, default=None, help="Custom output path for HTML")

    p_tree = subparsers.add_parser("compile-tree", aliases=["tree", "curriculum"], help="Compile CURRICULUM_TREE.md outline into interactive knowledge cosmos and study portal")
    p_tree.add_argument("path", type=str, nargs="?", default=".", help="Path to OKF bundle root")
    p_tree.add_argument("--tree", type=str, default=None, help="Custom path to CURRICULUM_TREE.md")
    p_tree.add_argument("--init", action="store_true", help="Initialize or regenerate CURRICULUM_TREE.md outline template from bundle")
    p_tree.add_argument("-o", "--output", type=str, default=None, help="Custom output path for viz.html")

    p_norm = subparsers.add_parser("normalize", help="Normalize concept filenames to clean OKF kebab/snake slugs")
    p_norm.add_argument("path", type=str, nargs="?", default=".", help="Path to OKF bundle root")
    p_norm.add_argument("--dry-run", action="store_true", help="Print changes without renaming")

    args = parser.parse_args()
    target_path = Path(args.path).resolve()

    if args.command in ("validate", "audit"):
        success = validate_bundle(target_path, json_output=args.json)
        sys.exit(0 if success else 1)
    elif args.command == "scaffold":
        scaffold_bundle(target_path, title=args.title, domain=args.domain)
    elif args.command == "index":
        refresh_indexes(target_path)
    elif args.command in ("viz", "graph"):
        out_f = Path(args.output).resolve() if args.output else None
        tree_p = Path(args.tree).resolve() if getattr(args, "tree", None) else None
        generate_viz(target_path, out_f, tree_file=tree_p)
    elif args.command in ("compile-tree", "tree", "curriculum"):
        tree_p = Path(args.tree).resolve() if getattr(args, "tree", None) else None
        out_f = Path(args.output).resolve() if args.output else None
        compile_tree(target_path, tree_file=tree_p, init=args.init, output_file=out_f)
    elif args.command == "normalize":
        normalize_bundle(target_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
