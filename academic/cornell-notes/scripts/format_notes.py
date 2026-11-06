#!/usr/bin/env python3
from __future__ import annotations
"""
format_notes.py - Deterministic Cornell Notes HTML generator & Study Exporter.

Features:
- Validates intermediate JSON schema.
- Safely formats text, tables, inline markdown, code blocks, and Obsidian callouts.
- Supports cognitive badges on cues (definition, mechanism, comparison, formula, pitfall).
- Renders A4 print-ready standalone HTML with embedded CSS and interactive self-quiz mode.
- Supports Anki flashcard export (--anki).
"""

import sys
import os
import csv
import json
import re
import html
import argparse
from datetime import datetime
from pathlib import Path


def render_inline(text: str) -> str:
    """
    Safely escapes HTML and formats inline Markdown constructs:
    - Code: `code`
    - Bold: **bold** or __bold__
    - Italic: *italic* or _italic_
    - Links: [label](url)
    """
    # 1. Protect inline code spans by extracting them
    code_spans = []
    def save_code(match):
        code_spans.append(match.group(1))
        return f"@@INLINECODE{len(code_spans)-1}@@"

    text = re.sub(r'`([^`]+)`', save_code, text)

    # 2. Protect display math $$...$$ and inline math $...$
    math_spans = []
    def save_display_math(match):
        # Sanitize any accidental double-backslashes (e.g. \\omega -> \omega)
        cleaned_math = match.group(1).replace('\\\\', '\\')
        math_spans.append(f"$${cleaned_math}$$")
        return f"@@MATHSPAN{len(math_spans)-1}@@"

    def save_inline_math(match):
        # Sanitize any accidental double-backslashes (e.g. \\omega -> \omega)
        cleaned_math = match.group(1).replace('\\\\', '\\')
        math_spans.append(f"${cleaned_math}$")
        return f"@@MATHSPAN{len(math_spans)-1}@@"

    text = re.sub(r'\$\$([\s\S]+?)\$\$', save_display_math, text)
    text = re.sub(r'\$([^\$\n]+?)\$', save_inline_math, text)

    # 3. Escape all plain text safely
    text = html.escape(text)

    # 4. Format images first: ![alt](url)
    def render_image(match):
        alt = match.group(1)
        url = match.group(2)
        return f'<img src="{url}" alt="{alt}" class="slide-diagram" loading="lazy">'

    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', render_image, text)

    # 5. Format links: [text](url)
    def render_link(match):
        label = match.group(1)
        url = match.group(2)
        if re.match(r'^(https?://|mailto:|#|/|\.\/|\.\.\/)', url, re.IGNORECASE):
            safe_url = html.escape(url, quote=True)
            return f'<a href="{safe_url}" target="_blank" rel="noopener">{label}</a>'
        return f'{label} ({url})'

    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', render_link, text)

    # 5. Bold: **text** or __text__
    text = re.sub(r'(\*\*|__)(.*?)\1', r'<strong>\2</strong>', text)

    # 6. Italic: *text* or _text_
    text = re.sub(r'(\*|_)(.*?)\1', r'<em>\2</em>', text)

    # 7. Restore math spans (preserving LaTeX delimiters intact for MathJax)
    for idx, math_str in enumerate(math_spans):
        placeholder = f"@@MATHSPAN{idx}@@"
        text = text.replace(placeholder, math_str)

    # 8. Restore code spans (safely escaped)
    for idx, code in enumerate(code_spans):
        placeholder = f"@@INLINECODE{idx}@@"
        escaped_code = html.escape(code)
        text = text.replace(placeholder, f"<code>{escaped_code}</code>")

    return text


def format_text_block(text: str) -> str:
    """
    Renders text to safe HTML, supporting:
    - Code blocks (```lang ... ```)
    - Callout blocks (> [!NOTE], > [!TIP], > [!WARNING], > [!DANGER])
    - Tables (| col | col |)
    - Unordered lists (- item / * item)
    - Ordered lists (1. item)
    - Paragraphs with inline markdown
    """
    if not isinstance(text, str):
        text = str(text)

    lines = text.replace('\r\n', '\n').split('\n')
    output_html = []
    
    in_code_block = False
    code_lines = []
    in_ul = False
    in_ol = False
    in_table = False
    table_rows = []
    para_lines = []
    in_callout = False
    callout_type = "note"
    callout_lines = []
    in_quote = False
    quote_lines = []

    def flush_para():
        nonlocal para_lines
        if para_lines:
            content = " ".join(para_lines).strip()
            if content:
                output_html.append(f"<p>{render_inline(content)}</p>")
            para_lines = []

    def flush_quote():
        nonlocal in_quote, quote_lines
        if in_quote and quote_lines:
            content = " ".join(quote_lines).strip()
            if content:
                output_html.append(f'<blockquote class="lecture-quote">{render_inline(content)}</blockquote>')
            quote_lines = []
            in_quote = False

    def flush_ul():
        nonlocal in_ul
        if in_ul:
            output_html.append("</ul>")
            in_ul = False

    def flush_ol():
        nonlocal in_ol
        if in_ol:
            output_html.append("</ol>")
            in_ol = False

    def flush_callout():
        nonlocal in_callout, callout_lines, callout_type
        if in_callout and callout_lines:
            content = " ".join(callout_lines).strip()
            title = callout_type.capitalize()
            output_html.append(
                f'<div class="callout {callout_type}">'
                f'<div class="callout-title">📌 {html.escape(title)}</div>'
                f'<div class="callout-body">{render_inline(content)}</div>'
                f'</div>'
            )
            callout_lines = []
            in_callout = False

    def flush_table():
        nonlocal in_table, table_rows
        if in_table and table_rows:
            html_table = ["<table class=\"notes-table\">"]
            is_header = True
            for r_idx, row in enumerate(table_rows):
                cleaned_cells = [c.strip() for c in row.split('|')[1:-1]] if row.strip().startswith('|') and row.strip().endswith('|') else [c.strip() for c in row.split('|')]
                if all(re.match(r'^:?-+:?$', c) for c in cleaned_cells if c):
                    continue
                tag = "th" if is_header and r_idx == 0 else "td"
                html_table.append("  <tr>")
                for cell in cleaned_cells:
                    html_table.append(f"    <{tag}>{render_inline(cell)}</{tag}>")
                html_table.append("  </tr>")
                if is_header and r_idx == 0:
                    is_header = False
            html_table.append("</table>")
            output_html.append("\n".join(html_table))
            table_rows = []
            in_table = False

    for line in lines:
        stripped = line.strip()

        # Check code fence
        if stripped.startswith('```'):
            if in_code_block:
                code_text = html.escape("\n".join(code_lines))
                output_html.append(f"<pre><code>{code_text}</code></pre>")
                code_lines = []
                in_code_block = False
            else:
                flush_para()
                flush_ul()
                flush_ol()
                flush_table()
                flush_callout()
                in_code_block = True
                code_lines = []
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        # Check standalone image line: ![alt](url)
        img_match = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)$', stripped)
        if img_match:
            flush_para()
            flush_ul()
            flush_ol()
            flush_table()
            flush_callout()
            flush_quote()
            alt_txt = html.escape(img_match.group(1))
            img_src = html.escape(img_match.group(2), quote=True)
            output_html.append(
                f'<figure class="slide-diagram-figure">'
                f'<img src="{img_src}" alt="{alt_txt}" class="slide-diagram" loading="lazy">'
                f'<figcaption>{alt_txt}</figcaption>'
                f'</figure>'
            )
            continue

        # Check Obsidian Callouts: > [!NOTE], > [!TIP], > [!WARNING], > [!DANGER]
        callout_match = re.match(r'^>\s*\[!(NOTE|TIP|WARNING|DANGER|IMPORTANT|CAUTION)\]\s*(.*)$', stripped, re.IGNORECASE)
        if callout_match:
            flush_para()
            flush_ul()
            flush_ol()
            flush_table()
            flush_callout()
            flush_quote()
            c_tag = callout_match.group(1).lower()
            if c_tag in ['important', 'caution']:
                c_tag = 'danger'
            callout_type = c_tag
            in_callout = True
            first_line = callout_match.group(2).strip()
            if first_line:
                callout_lines.append(first_line)
            continue

        if in_callout and stripped.startswith('>'):
            sub_line = stripped.lstrip('>').strip()
            if sub_line:
                callout_lines.append(sub_line)
            continue
        elif in_callout:
            flush_callout()

        # Check general blockquotes: > text (e.g. spoken transcript snippets)
        if stripped.startswith('>'):
            flush_para()
            flush_ul()
            flush_ol()
            flush_table()
            in_quote = True
            quote_lines.append(stripped.lstrip('>').strip())
            continue
        elif in_quote:
            flush_quote()

        # Check table line
        if stripped.startswith('|') and stripped.endswith('|') and '|' in stripped[1:-1]:
            flush_para()
            flush_ul()
            flush_ol()
            flush_callout()
            flush_quote()
            in_table = True
            table_rows.append(stripped)
            continue
        elif in_table:
            flush_table()

        # Check list items
        ul_match = re.match(r'^[\*\-]\s+(.*)$', stripped)
        ol_match = re.match(r'^\d+\.\s+(.*)$', stripped)

        if ul_match:
            flush_para()
            flush_ol()
            flush_callout()
            flush_quote()
            if not in_ul:
                output_html.append("<ul>")
                in_ul = True
            item_text = ul_match.group(1)
            output_html.append(f"  <li>{render_inline(item_text)}</li>")
            continue
        elif in_ul and not stripped:
            flush_ul()

        if ol_match:
            flush_para()
            flush_ul()
            flush_callout()
            flush_quote()
            if not in_ol:
                output_html.append("<ol>")
                in_ol = True
            item_text = ol_match.group(1)
            output_html.append(f"  <li>{render_inline(item_text)}</li>")
            continue
        elif in_ol and not stripped:
            flush_ol()

        if not stripped:
            flush_para()
            flush_ul()
            flush_ol()
            flush_table()
            flush_callout()
            flush_quote()
            continue

        # Regular text line (accumulates into paragraph)
        para_lines.append(stripped)

    # Clean up any unclosed blocks
    if in_code_block:
        code_text = html.escape("\n".join(code_lines))
        output_html.append(f"<pre><code>{code_text}</code></pre>")
    flush_para()
    flush_ul()
    flush_ol()
    flush_table()
    flush_callout()
    flush_quote()

    return "\n".join(output_html)


def infer_badge_type(cue_text: str, explicit_badge: str | None = None) -> tuple[str | None, str]:
    """
    Detects cognitive question type from cue text:
    - Definition / Concept
    - Mechanism / How it works
    - Comparison / Trade-off
    - Formula / Metric
    - Pitfall / Warning
    """
    if explicit_badge:
        return explicit_badge.lower(), cue_text

    cue_lower = cue_text.lower()
    if any(k in cue_lower for k in ["compare", "vs", "versus", "difference", "trade-off"]):
        return "comparison", cue_text
    elif any(k in cue_lower for k in ["how does", "how do", "mechanism", "why does", "process", "step"]):
        return "mechanism", cue_text
    elif any(k in cue_lower for k in ["what is", "define", "what are", "definition"]):
        return "definition", cue_text
    elif any(k in cue_lower for k in ["formula", "calculate", "equation", "latency", "size", "metric"]):
        return "formula", cue_text
    elif any(k in cue_lower for k in ["pitfall", "trap", "warning", "mistake", "error", "avoid"]):
        return "pitfall", cue_text

    return None, cue_text


def validate_schema(data: dict) -> list[str]:
    """
    Validates intermediate JSON structure against the Cornell Notes schema.
    """
    errors = []
    if not isinstance(data, dict):
        return ["Root JSON value must be an object/dict."]

    if "title" not in data or not isinstance(data["title"], str) or not data["title"].strip():
        errors.append("Missing or invalid 'title' (must be a non-empty string).")

    if "sections" not in data or not isinstance(data["sections"], list):
        errors.append("Missing or invalid 'sections' (must be a list).")
    else:
        if len(data["sections"]) == 0:
            errors.append("'sections' list must contain at least one section.")
        for s_idx, section in enumerate(data["sections"]):
            prefix = f"Section [{s_idx}]"
            if not isinstance(section, dict):
                errors.append(f"{prefix} must be an object/dict.")
                continue

            if "heading" not in section or not isinstance(section["heading"], str):
                errors.append(f"{prefix} missing or invalid 'heading' (must be string).")

            if "entries" not in section or not isinstance(section["entries"], list):
                errors.append(f"{prefix} missing or invalid 'entries' (must be a list).")
            else:
                if len(section["entries"]) == 0:
                    errors.append(f"{prefix} 'entries' list must not be empty.")
                for e_idx, entry in enumerate(section["entries"]):
                    entry_prefix = f"{prefix} Entry [{e_idx}]"
                    if not isinstance(entry, dict):
                        errors.append(f"{entry_prefix} must be an object/dict.")
                        continue
                    if "cue" not in entry or not isinstance(entry["cue"], str):
                        errors.append(f"{entry_prefix} missing or invalid 'cue' (must be string).")
                    if "notes" not in entry or not isinstance(entry["notes"], str):
                        errors.append(f"{entry_prefix} missing or invalid 'notes' (must be string).")

            if "summary" in section and not isinstance(section["summary"], str):
                errors.append(f"{prefix} 'summary' must be a string if provided.")

    return errors


def clean_cue_text(cue: str) -> str:
    """Strips video timestamps and seek chips from the flashcard cue."""
    clean = re.sub(r'\[▶\s*[^\]]+\]\([^)]+\)', '', cue)
    clean = re.sub(r'\[\d{1,2}:\d{2}(?::\d{2})?\]', '', clean)
    return clean.strip()


def atomize_entry_to_cards(sec_heading: str, entry: dict) -> list[tuple[str, str]]:
    """
    Atomizes a single Cornell entry into high-yield, quick-to-review Anki cards (under 35 words).
    Returns list of (front_html, back_html).
    """
    # 1. Explicit cards array declared in JSON entry: use verbatim
    if "cards" in entry and isinstance(entry["cards"], list) and entry["cards"]:
        cards = []
        for c in entry["cards"]:
            if isinstance(c, dict) and "front" in c and "back" in c:
                f = f"<strong>[{html.escape(sec_heading)}]</strong><br>{format_text_block(c['front'])}"
                b = format_text_block(c['back'])
                cards.append((f.replace("\n", " "), b.replace("\n", " ")))
        if cards:
            return cards

    cue_raw = entry.get("cue", "").strip()
    cue_clean = clean_cue_text(cue_raw)
    notes_raw = entry.get("notes", "").strip()
    lines = notes_raw.splitlines()

    # 2. Check for Markdown Tables: Atomize each table row into an individual decision card
    table_lines = [l for l in lines if l.strip().startswith("|")]
    if len(table_lines) >= 3:
        header = [c.strip() for c in table_lines[0].split("|")[1:-1]]
        data_rows = []
        for l in table_lines[2:]:
            cols = [c.strip() for c in l.split("|")[1:-1]]
            if len(cols) == len(header):
                data_rows.append(cols)

        if data_rows and len(header) >= 2 and any("scenario" in h.lower() or "method" in h.lower() for h in header):
            cards = []
            for row in data_rows:
                scenario = row[0].replace("**", "").strip()
                method = row[1].strip() if len(row) > 1 else ""
                rationale = f" — {row[2].strip()}" if len(row) > 2 else ""
                f = f"<strong>[{html.escape(sec_heading)}]</strong> Scenario: <em>{html.escape(scenario)}</em><br>{html.escape(cue_clean)}"
                b = f"{format_text_block(method)}{html.escape(rationale)}"
                cards.append((f.replace("\n", " "), b.replace("\n", " ")))
            return cards

    # 3. Check for multi-point Pitfalls/Traps: extract distinct warnings
    if any(kw in cue_clean.lower() for kw in ["pitfall", "trap", "mistake", "warning"]) or any("warning" in l.lower() or "pitfall" in l.lower() for l in lines):
        pitfalls = [re.sub(r'^\d+\.\s*', '', l).strip() for l in lines if re.match(r'^\d+\.\s*\*\*', l)]
        if len(pitfalls) >= 2:
            cards = []
            for p in pitfalls:
                parts = p.split("**:", 1)
                if len(parts) == 2:
                    p_title = parts[0].replace("**", "").strip()
                    p_desc = parts[1].strip()
                    f = f"<strong>[{html.escape(sec_heading)}]</strong> ⚠️ Pitfall in {html.escape(cue_clean)}:<br><strong>{html.escape(p_title)}</strong>"
                    b = format_text_block(p_desc)
                    cards.append((f.replace("\n", " "), b.replace("\n", " ")))
            if cards:
                return cards

    # Strip spoken transcript quote chips from Anki cards to prevent clutter
    notes_clean = re.sub(r'>\s*💬[^\n]+(?:\n\s*>[^\n]+)*', '', notes_raw).strip()
    if not notes_clean:
        notes_clean = notes_raw

    # Default / Clean fallback card:
    f = f"<strong>[{html.escape(sec_heading)}]</strong><br>{html.escape(cue_clean)}"
    b = format_text_block(notes_clean)
    return [(f.replace("\n", " "), b.replace("\n", " "))]


def export_anki_tsv(data: dict, output_tsv_path: Path) -> int:
    """
    Exports cue-note pairs as an atomic, high-yield TSV file ready for Anki import.
    Field 1: Front (Section + Clean Cue or Scenario Prompt)
    Field 2: Back (Atomic Explanation / Cloze / Answer, under 35 words)
    Field 3: Tag (Title / Heading)
    Returns total number of cards written.
    """
    output_tsv_path.parent.mkdir(parents=True, exist_ok=True)
    card_count = 0
    with open(output_tsv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        for section in data.get("sections", []):
            sec_heading = section.get("heading", "")
            tag = re.sub(r'[^a-zA-Z0-9_-]', '_', sec_heading)
            for entry in section.get("entries", []):
                cards = atomize_entry_to_cards(sec_heading, entry)
                for front, back in cards:
                    writer.writerow([front, back, tag])
                    card_count += 1
    return card_count



def render_cornell_html(data: dict, template_path: Path, srs_path: Path | None = None) -> str:
    """
    Renders structured JSON into standalone HTML with CSS and study mode.
    """
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found at: {template_path}")

    template_str = template_path.read_text(encoding="utf-8")

    title_safe = html.escape(data.get("title", "Cornell Notes"))
    source = data.get("source", "")
    meta_source_html = f'<span class="meta-item"><strong>Source:</strong> {html.escape(source)}</span>' if source else ""
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    meta_date_html = f'<span class="meta-item"><strong>Generated:</strong> {created_at}</span>'

    sections_html_parts = []

    for section in data.get("sections", []):
        heading = html.escape(section.get("heading", ""))
        entries = section.get("entries", [])
        summary = section.get("summary", "")

        sec_part = ['<section class="section-block">']
        if heading:
            sec_part.append(f'  <h2 class="section-heading">{heading}</h2>')

        sec_part.append('  <div class="grid-header">')
        sec_part.append('    <div class="grid-header-col">Cue / Prompt / Keyword</div>')
        sec_part.append('    <div class="grid-header-col">Notes / Explanations</div>')
        sec_part.append('  </div>')

        # Check if sidecar .srs.json exists for this document to hydrate review boxes
        srs_state = {}
        if srs_path and srs_path.exists():
            try:
                with open(srs_path, "r", encoding="utf-8") as sf:
                    srs_state = json.load(sf)
            except Exception:
                pass

        sec_part.append('  <div class="entries-container">')
        for entry in entries:
            cue_text = entry.get("cue", "")
            notes_text = entry.get("notes", "")
            badge_type, clean_cue = infer_badge_type(cue_text, entry.get("type"))

            # Derive card id and look up SRS state
            from srs_review import card_id
            cid = card_id(heading, cue_text)
            c_info = srs_state.get(cid, {})
            reps = c_info.get("reps", 0)
            due_date = c_info.get("due_date", "")

            cue_formatted = format_text_block(clean_cue)
            notes_formatted = format_text_block(notes_text)

            # Metadata header above the cue text: badge + spaced-repetition checkboxes
            badge_html = f'<span class="cue-badge {badge_type}">{badge_type}</span>' if badge_type else '<span></span>'
            
            box1_cls = "checked" if reps >= 1 else ""
            box2_cls = "checked" if reps >= 2 else ""
            box3_cls = "checked" if reps >= 3 else ""
            due_str = f"Due: {due_date}" if due_date else "New"

            review_boxes_html = (
                f'<div class="review-checks" title="SRS Retention Level ({due_str})">'
                f'<span class="review-box {box1_cls}" title="Pass 1 (1d)"></span>'
                f'<span class="review-box {box2_cls}" title="Pass 2 (3d)"></span>'
                f'<span class="review-box {box3_cls}" title="Pass 3 (Mastery)"></span>'
                f'</div>'
            )

            sec_part.append('    <div class="entry-row">')
            sec_part.append('      <div class="cue-col">')
            sec_part.append(f'        <div class="cue-top-meta">{badge_html}{review_boxes_html}</div>')
            sec_part.append(f'        {cue_formatted}')
            sec_part.append('      </div>')
            sec_part.append(f'      <div class="notes-col">{notes_formatted}</div>')
            sec_part.append('    </div>')
        sec_part.append('  </div>')

        if summary and summary.strip():
            summary_formatted = format_text_block(summary.strip())
            sec_part.append('  <div class="section-summary-block">')
            sec_part.append('    <div class="summary-title">Summary &amp; Key Synthesis</div>')
            sec_part.append(f'    <div class="summary-content">{summary_formatted}</div>')
            sec_part.append('  </div>')

        sec_part.append('</section>')
        sections_html_parts.append("\n".join(sec_part))

    sections_final = "\n\n".join(sections_html_parts)

    course_val = data.get("course", "")
    module_val = data.get("module", "") or data.get("week", "")
    src = data.get("source", "")
    if not course_val or not module_val:
        m_c = re.search(r'(41200|48430|48520|48521)', src)
        if m_c and not course_val:
            course_map = {
                "41200": "41200 EPA",
                "48430": "48430 C Prog",
                "48520": "48520 Circuits",
                "48521": "48521 FEET"
            }
            course_val = course_map.get(m_c.group(1), m_c.group(1))
        m_w = re.search(r'(?:week|w)[_\s-]*(\d{1,2})', src, re.IGNORECASE)
        if m_w and not module_val:
            module_val = f"Week {int(m_w.group(1)):02d}"

    breadcrumb_html = ""
    if course_val or module_val:
        crumb_parts = []
        if course_val:
            crumb_parts.append(f'<span class="crumb-course">{html.escape(course_val)}</span>')
        if module_val:
            crumb_parts.append(f'<span class="crumb-module">{html.escape(module_val)}</span>')
        crumb_sep = ' <span class="crumb-sep">&rsaquo;</span> '
        breadcrumb_html = f'<div class="document-breadcrumb">{crumb_sep.join(crumb_parts)}</div>'

    rendered = template_str.replace("{{PAGE_TITLE}}", title_safe)
    rendered = rendered.replace("{{TITLE}}", title_safe)
    rendered = rendered.replace("{{META_BREADCRUMB}}", breadcrumb_html)
    rendered = rendered.replace("{{META_SOURCE}}", meta_source_html)
    rendered = rendered.replace("{{META_DATE}}", meta_date_html)
    rendered = rendered.replace("{{SECTIONS_HTML}}", sections_final)

    return rendered


def render_table(rows: list[dict], columns: list[str] | None = None, headers: list[str] | None = None) -> str:
    if not rows:
        return "*(no records)*\n"
    if columns is None:
        columns = list(rows[0].keys())
    if headers is None:
        headers = [col.replace("_", " ").title() for col in columns]

    col_widths = [len(h) for h in headers]
    for r in rows:
        for idx, col in enumerate(columns):
            val_str = str(r.get(col, "")).replace("\n", " ").strip()
            if len(val_str) > col_widths[idx]:
                col_widths[idx] = len(val_str)

    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * col_widths[i] for i in range(len(headers))) + " |"
    row_lines = []
    for r in rows:
        row_str = "| " + " | ".join(str(r.get(col, "")).replace("\n", " ").strip().ljust(col_widths[i]) for i, col in enumerate(columns)) + " |"
        row_lines.append(row_str)
    return "\n".join([header_line, sep_line] + row_lines) + "\n"


def determine_output_path(input_json_path: Path, output_arg: str | None) -> Path:
    if output_arg:
        return Path(output_arg)
    
    stem = input_json_path.stem
    if stem.endswith("_cornell"):
        out_name = f"{stem}.html"
    else:
        out_name = f"{stem}_cornell.html"

    # Canonical academic output routing: if json is in outputs/json, route html to outputs/html
    if input_json_path.parent.name == "json" and input_json_path.parent.parent.name == "outputs":
        html_dir = input_json_path.parent.parent / "html"
        html_dir.mkdir(parents=True, exist_ok=True)
        return html_dir / out_name

    return input_json_path.parent / out_name


def main():
    parser = argparse.ArgumentParser(
        description="Format structured JSON into print-ready Cornell Notes HTML & Anki flashcards."
    )
    parser.add_argument("json_file", help="Path to intermediate Cornell notes JSON file.")
    parser.add_argument(
        "-o", "--output",
        help="Optional output HTML path. Defaults to <input_stem>_cornell.html"
    )
    parser.add_argument(
        "--anki",
        action="store_true",
        help="Also export flashcards as Anki-compatible TSV (<stem>_anki.tsv)."
    )
    parser.add_argument(
        "--template",
        help="Custom path to template.html. Defaults to template.html in script's directory."
    )
    parser.add_argument(
        "-t", "--table",
        action="store_true",
        help="Emit receipt or outline as compact Markdown table."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit receipt or outline as structured JSON."
    )
    parser.add_argument(
        "--outline",
        action="store_true",
        help="Display high-level outline table (sections, cues, summary) without rendering HTML."
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Display document summary statistics without rendering HTML."
    )
    parser.add_argument(
        "-p", "--project",
        nargs="*",
        help="Filter fields in outline or receipt table/JSON."
    )
    parser.add_argument(
        "-n", "--limit",
        type=int,
        default=0,
        help="Limit number of outline entries."
    )

    args = parser.parse_args()

    input_path = Path(args.json_file)
    if not input_path.exists():
        print(f"Error: JSON file '{input_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON format in '{input_path}':\n  {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file '{input_path}': {e}", file=sys.stderr)
        sys.exit(1)

    errors = validate_schema(data)
    if errors:
        print("Schema validation failed with errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    # 1. Outline Mode (Token Shield)
    if args.outline:
        rows = []
        for s in data.get("sections", []):
            summary_raw = s.get("summary", "") or ""
            summary_preview = (summary_raw[:55] + "...") if len(summary_raw) > 55 else summary_raw
            rows.append({
                "section": s.get("heading", "General"),
                "cues": len(s.get("entries", [])),
                "summary": summary_preview
            })
        if args.limit and args.limit > 0:
            rows = rows[:args.limit]
        if args.json:
            if args.project:
                p_keys = [k.lower() for k in args.project]
                rows = [{k: v for k, v in r.items() if k.lower() in p_keys} for r in rows]
            print(json.dumps(rows, indent=2, ensure_ascii=False))
            return
        cols = ["section", "cues", "summary"]
        if args.project:
            p_keys = [k.lower() for k in args.project]
            cols = [c for c in cols if c.lower() in p_keys] or cols
        table_rows = [{k: r.get(k, "") for k in cols} for r in rows]
        print(f"### Cornell Notes Outline: {data.get('title', input_path.stem)}\n")
        print(render_table(table_rows, cols))
        return

    # 2. Stats Mode (Token Shield)
    if args.stats:
        total_cues = sum(len(s.get("entries", [])) for s in data.get("sections", []))
        total_summaries = sum(1 for s in data.get("sections", []) if s.get("summary"))
        stats_obj = {
            "title": data.get("title", ""),
            "source": data.get("source", ""),
            "sections": len(data.get("sections", [])),
            "cues": total_cues,
            "summaries": total_summaries
        }
        if args.json:
            if args.project:
                p_keys = [k.lower() for k in args.project]
                stats_obj = {k: v for k, v in stats_obj.items() if k.lower() in p_keys}
            print(json.dumps(stats_obj, indent=2, ensure_ascii=False))
            return
        rows = [
            {"metric": "Title", "value": stats_obj["title"] or "(untitled)"},
            {"metric": "Source", "value": stats_obj["source"] or "N/A"},
            {"metric": "Sections", "value": str(stats_obj["sections"])},
            {"metric": "Cue-Note Pairs", "value": str(stats_obj["cues"])},
            {"metric": "Summaries", "value": str(stats_obj["summaries"])},
        ]
        if args.project:
            p_keys = [k.lower() for k in args.project]
            rows = [r for r in rows if r["metric"].lower() in p_keys]
        print(f"### Cornell Notes Statistics: {input_path.name}\n")
        print(render_table(rows, ["metric", "value"], ["Metric", "Value"]))
        return

    # 3. HTML Rendering
    # The template is an asset, one level up from scripts/; the script-local
    # location is still honoured so an older layout keeps rendering.
    script_dir = Path(__file__).resolve().parent
    local_template = script_dir / "template.html"
    asset_template = script_dir.parent / "assets" / "template.html"
    default_template = local_template if local_template.exists() else asset_template
    template_path = Path(args.template) if args.template else default_template
    if not template_path.exists():
        print(f"Error: Template not found at '{template_path}'.", file=sys.stderr)
        sys.exit(1)

    try:
        srs_path = input_path.with_suffix(".srs.json")
        html_content = render_cornell_html(data, template_path, srs_path=srs_path)
    except Exception as e:
        print(f"Error during HTML rendering: {e}", file=sys.stderr)
        sys.exit(1)

    output_path = determine_output_path(input_path, args.output)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
    except Exception as e:
        print(f"Error writing output file '{output_path}': {e}", file=sys.stderr)
        sys.exit(1)

    tsv_path = None
    card_count = 0
    if args.anki:
        if input_path.parent.name == "json" and (input_path.parent.parent / "anki").is_dir():
            tsv_path = input_path.parent.parent / "anki" / f"{input_path.stem}_anki.tsv"
        else:
            tsv_path = input_path.parent / f"{input_path.stem}_anki.tsv"
        try:
            card_count = export_anki_tsv(data, tsv_path)
        except Exception as e:
            print(f"Error writing Anki TSV file: {e}", file=sys.stderr)
            tsv_path = None


    # Emit Token-Shielded Receipt or human output
    total_cues = sum(len(s.get("entries", [])) for s in data.get("sections", []))
    receipt = {
        "title": data.get("title", ""),
        "sections": len(data.get("sections", [])),
        "cues": total_cues,
        "html_file": str(output_path.resolve()),
        "html_size_kb": round(output_path.stat().st_size / 1024, 1),
        "anki_tsv": str(tsv_path.resolve()) if tsv_path else None,
    }

    if args.json:
        if args.project:
            p_keys = [k.lower() for k in args.project]
            receipt = {k: v for k, v in receipt.items() if k.lower() in p_keys}
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
        return

    if args.table:
        rows = [
            {"metric": "Document Title", "value": receipt["title"] or "(untitled)"},
            {"metric": "Sections", "value": str(receipt["sections"])},
            {"metric": "Cue-Note Pairs", "value": str(receipt["cues"])},
            {"metric": "Generated HTML", "value": f"{output_path.name} ({receipt['html_size_kb']} KB)"},
            {"metric": "Anki Cards", "value": f"{tsv_path.name} ({card_count} cards)" if tsv_path else "Disabled"},
        ]

        print(f"### Cornell Notes Receipt\n")
        print(render_table(rows, ["metric", "value"], ["Metric", "Value"]))
        return

    print(f"Successfully generated Cornell Notes HTML: {output_path.resolve()}")
    if tsv_path:
        print(f"Successfully exported Anki flashcards: {tsv_path.resolve()}")


if __name__ == "__main__":
    main()
