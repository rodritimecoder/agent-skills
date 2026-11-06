## Token Shielding & AST Inspection (Glitch Cat / ICM Architecture)

When dealing with large PDFs, Word documents, slide decks, or spreadsheets, dumping full contents can exhaust 50k+ tokens. Use targeted AST extraction flags to inspect and slice documents before slurping pages:

```bash
# 1. View high-density heading outline with word counts (~80 tokens instead of 50k):
python3 $CLI lecture_slides.pdf --outline --table

# 2. Extract only a specific chapter or section (stops at next equal/higher heading):
python3 $CLI lecture_notes.pdf --section "Inverter Propagation Delay"

# 3. Search pattern with line numbers and 1-line context:
python3 $CLI lecture_notes.pdf --grep "tpHL"

# 4. Project outline columns and cap rows:
python3 $CLI textbook.epub --outline -p heading,words -n 15

# 5. Save to disk with a concise receipt table instead of terminal spew:
python3 $CLI ./papers/ -r -o ./markdown/ --table
```

| Token Shielding Flag | Purpose | Default |
|---|---|---|
| `--outline`, `--toc` | Extract AST heading hierarchy with line numbers and section word counts | Disabled |
| `--section <heading>` | Extract only the target heading and its subsections | Disabled |
| `--grep <pattern>` | Search regex pattern with line numbers and 1-line context | Disabled |
| `--table, -t` | Render output as Markdown pipe tables | Disabled |
| `--project, -p <keys>` | Project specific columns (e.g. `heading,words` or `input,status`) | Disabled |
| `--limit, -n <N>` | Cap the number of outline rows or output lines | `0` (unlimited) |
| `--receipt` | Emit structured conversion receipt instead of file text | Disabled |
| `--json` | Output outline or receipts in JSON format | Disabled |
