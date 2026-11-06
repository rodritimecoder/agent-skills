# Cornell Notes Formatting Skill

A reusable agent skill that converts existing Markdown (`.md`) study, technical, and lecture notes into clean, print-ready Cornell Notes HTML documents.

---

## Overview

The Cornell Notes method divides study notes into:
1. **Cues / Prompts / Keywords** (left column, ~32% width) — active recall questions and prompts.
2. **Notes & Explanations** (right column, ~68% width) — detailed concepts, formulas, code, and tables aligned with each cue.
3. **Summary** (bottom full width) — section-by-section synthesis.

This skill separates semantic reasoning from visual presentation:
- **LLM / Agent**: Analyzes Markdown notes and synthesizes them into active recall cue–note pairs and summaries in an intermediate JSON schema.
- **Python Formatter (`format_notes.py`)**: Deterministically validates data, escapes content to prevent injection, and renders standalone HTML with embedded CSS.

---

## Directory Layout

```text
cornell-notes/
├── SKILL.md                 # Agent instruction specification and frontmatter
├── scripts/
│   ├── format_notes.py      # Deterministic JSON-to-HTML validator & formatter (standard library only)
│   └── srs_review.py        # SM-2 spaced-repetition engine
├── assets/
│   └── template.html        # Standalone print & screen HTML/CSS template
├── tests/
│   └── test_cornell_notes.py
├── examples/
│   ├── input.md             # Sample Markdown technical notes
│   ├── expected-output.json # Structured intermediate JSON fixture
│   └── expected-output_cornell.html # Formatted output artifact
├── references/
│   └── guidelines.md        # Escaping, callouts, large-file rules
└── README.md                # Project documentation and usage guide
```

---

## Usage

### 1. Intermediate JSON Generation (by Agent or User)

Create a JSON file adhering to the Cornell schema:

```json
{
  "title": "Computer Systems: Memory Hierarchy",
  "source": "notes/memory.md",
  "sections": [
    {
      "heading": "Caches & Performance",
      "entries": [
        {
          "cue": "Why is caching critical for CPU performance?",
          "notes": "Bridges the access latency gap between sub-nanosecond CPU registers and 60-100ns DRAM main memory."
        }
      ],
      "summary": "Multi-level SRAM caches keep frequently accessed instructions and data close to the execution pipeline."
    }
  ]
}
```

### 2. Format to HTML

Run `scripts/format_notes.py`:

```bash
# Default output name will be <input_stem>_cornell.html:
python3 scripts/format_notes.py examples/expected-output.json

# Or specify a custom output path:
python3 scripts/format_notes.py examples/expected-output.json -o notes_cornell.html
```

---

## Formatting Features & Print Specifications

- **Page Layout**: A4 portrait (`210 × 297 mm`) with `14mm` vertical and `12mm` horizontal margins.
- **Strict Row Pairing**: Built with CSS Grid so that each cue and its corresponding notes cell are in a single synchronized row that stretches to the taller cell.
- **Print Optimization**: Uses `break-inside: avoid` to prevent mid-row pagination splits, repeats section and table headers, and avoids clipping.
- **Zero External Dependencies**: Standard library Python (`sys`, `os`, `json`, `html`, `re`, `argparse`). Standalone offline HTML with no external fonts, JS, or CDNs.
- **Rich Formatting Support**: Supports inline code (`` `x` ``), fenced code blocks, bulleted and numbered lists, bold, italics, links, and markdown tables inside notes.

---

## Browser Printing Note

Browser print engines (Chromium, Firefox, WebKit) paginate CSS Grid differently:
- Open the `.html` file in your browser and press `Ctrl+P` (or `Cmd+P`).
- Ensure paper size is set to **A4**, orientation to **Portrait**, and enable **Background graphics** for header borders and section highlights.
