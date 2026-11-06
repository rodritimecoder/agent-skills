---
name: cornell-notes

description: >
  Convert existing Markdown notes into print-ready Cornell Notes HTML with
  active-recall cue–note pairs, a self-quiz mode, and spaced repetition.
  Use for revision notes, study sheets, or Anki export from a .md file.

compatibility: "Requires Python 3.10+. No network access needed."
allowed-tools: "Bash(cornell-notes:*) Bash(python3:*) Read Write"
---

# Cornell Notes (`cornell-notes`)

Turns existing Markdown notes into print-ready Cornell Notes HTML. The
source notes already exist — you read them, restructure them into
active-recall cue–note pairs with a summary per section, write the
intermediate JSON, and a deterministic local script renders the HTML.

**Never overwrite the original Markdown file.**

---

## 🏛️ The Pipeline

| Stage | What you do | What it produces |
| :--- | :--- | :--- |
| **Read** | Read the source `.md`; keep every concept, formula, snippet, table, callout and link | the source, understood |
| **Transform** | Reorganise into sections; for each, write active-recall cues and the notes that answer them, plus a 2–4 sentence summary | cue–note pairs |
| **Save** | Write the structure to JSON beside the source, unfenced | `<name>_cornell.json` |
| **Render** | Run the formatter | standalone HTML with embedded CSS |
| **Report** | Confirm the HTML path; mention the self-quiz toggle and A4 print | the file path |

---

## 🧾 The Intermediate JSON

```json
{
  "title": "Topic or Document Title",
  "source": "path/to/original_notes.md",
  "sections": [
    {
      "heading": "Section / Chapter Title",
      "entries": [
        { "cue": "Active recall question or prompt?", "notes": "Direct answer, explanation, or code snippet." },
        { "cue": "Compare X and Y", "notes": "- X offers high speed but limited capacity.\n- Y offers high capacity but higher latency." }
      ],
      "summary": "High-level synthesis capturing the core takeaways of this section."
    }
  ]
}
```

---

## 🛠️ CLI Quickstart

```bash
# Run from this skill's directory; the paths are relative to it.
CN="scripts"

# 1. Render the HTML, with a compact Markdown receipt
python3 $CN/format_notes.py <input.json> --table

# 2. Inspect the section outline without rendering (~60 tokens)
python3 $CN/format_notes.py <input.json> --outline [--table] [--limit 5]

# 3. Document statistics, without rendering
python3 $CN/format_notes.py <input.json> --stats [--json]

# 4. Also export Anki flashcards (<input_stem>_anki.tsv)
python3 $CN/format_notes.py <input.json> --anki --table

# 5. Spaced repetition status across notes
python3 $CN/srs_review.py status <input.json or folder> --table

# 6. Interactive SM-2 quiz (1-day fail, 3-day pass)
python3 $CN/srs_review.py review <input.json or folder>
```

---

## Reference

- `references/guidelines.md` — LaTeX escaping, cognitive badges, callouts, large files
