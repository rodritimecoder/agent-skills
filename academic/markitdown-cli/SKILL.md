---
name: markitdown-cli

description: >
  Convert documents to Markdown with MarkItDown: PDF, DOCX, PPTX, XLSX, HTML,
  CSV, JSON, XML, EPUB, ZIP, Outlook .msg, notebooks, images with optional
  local OCR, and URLs. Use to read a document or attachment into text.

compatibility: "Requires the markitdown package. OCR needs a local OpenAI-compatible server (MARKITDOWN_OCR_BASE_URL); the optional LLM clients need ANTHROPIC_API_KEY."
allowed-tools: "Bash(markitdown-cli:*) Bash(python3:*) Read Write"
---

# MarkItDown CLI (`markitdown-cli`)

Converts files to Markdown using Microsoft's
[MarkItDown](https://github.com/microsoft/markitdown). Everything runs out of
a virtualenv inside this skill — no system packages needed. The script
re-execs itself, so plain `python3` is all you need.

---

## 🏛️ Supported Inputs

| Category | Extensions |
| :--- | :--- |
| Documents | `pdf`, `docx`, `pptx`, `xlsx`, `xls`, `epub`, `rtf`*, `msg` (Outlook) |
| Web | `html`, `htm` |
| Data | `csv`, `tsv`, `json`, `jsonl`, `xml`, `yaml`, `yml` |
| Text | `txt`, `md`, `markdown` |
| Notebook | `ipynb` |
| Archive | `zip` (converts each member) |
| Images | `png`, `jpg`, `jpeg` (metadata, plus OCR with `--ocr`) |
| Audio | `mp3`, `wav`, `m4a`, `mp4` (metadata only, no transcription) |
| URLs | YouTube, Wikipedia, RSS, Bing SERP — pass the URL as the input |

\* `rtf` is only handled if it is actually plain text; real RTF is not converted.

**Legacy binary `.doc`, `.ppt`, `.xls` from old Office are not supported.**
They are skipped during batch runs. Convert them first (LibreOffice, or Word
"Save As" to `.docx`/`.pptx`) — passing a legacy file to a single-file
conversion can emit raw binary-looking text rather than failing cleanly.

---

## 🛠️ CLI Quickstart

```bash
# Run from this skill's directory; the paths are relative to it.
CLI=scripts/markitdown_cli.py

# 1. One file to stdout
python3 $CLI report.pdf

# 2. One file to a named output
python3 $CLI report.pdf -o report.md

# 3. Several files into a directory
python3 $CLI a.pdf b.docx c.pptx -o ./markdown/

# 4. A whole tree, preserving subdirectory structure
python3 $CLI ./papers/ -r -o ./markdown/

# 5. From stdin, with the content sniffed
cat page.html | python3 $CLI -i - -o page.md

# 6. Token-shielded inspection — a heading outline instead of 50k tokens
python3 $CLI lecture_slides.pdf --outline --table

# 7. Extract one section, stopping at the next equal-or-higher heading
python3 $CLI lecture_notes.pdf --section "Inverter Propagation Delay"

# 8. Search a document for a pattern, with line numbers
python3 $CLI lecture_notes.pdf --grep "tpHL"

# 9. Project outline columns and cap the rows
python3 $CLI textbook.epub --outline -p heading,words -n 15

# 10. OCR a scanned image with a local vision model
python3 $CLI scan.png --ocr --ocr-base-url http://localhost:8080/v1 --ocr-model gemma-3-4b-it

# 11. Print the authoritative format list, or check the environment
python3 $CLI --list-formats
python3 $CLI --doctor
```

---

## Reference

- `references/ocr.md` — setting up a local OCR model, and the OCR flags
- `references/token-shielding.md` — the AST inspection flags in full
- `references/setup.md` — rebuilding the skill's virtualenv
- `references/notes.md` — output, exit status, and known limitations
