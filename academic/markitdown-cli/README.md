# markitdown-cli

A pi skill that wraps Microsoft's [MarkItDown](https://github.com/microsoft/markitdown)
to turn documents into Markdown, with optional OCR running on a local vision model.

| | |
|---|---|
| Script | `scripts/markitdown_cli.py` |
| Interpreter | skill-local `.venv/` (the script re-execs into it) |
| Network | none required; OCR talks to a server you run |
| Command reference | `SKILL.md` |

## Quick start

```bash
CLI=~/.gemini/config/skills/markitdown-cli/scripts/markitdown_cli.py

python3 $CLI report.pdf                     # to stdout
python3 $CLI report.pdf -o report.md        # to a file
python3 $CLI ./papers/ -r -o ./markdown/    # a whole tree
python3 $CLI --list-formats                 # what this install supports
python3 $CLI --doctor                       # check the environment
```

Pipes into anything:

```bash
python3 $CLI syllabus.pdf | head -50
python3 $CLI grades.xlsx -o - | grep -i "final"
```

## Why the virtualenv

MarkItDown pulls in a large dependency tree (lxml, pandas, onnxruntime, Pillow),
and this machine's system Python is PEP-668 managed with no `pip` on it. Rather
than fight that, the skill owns a private `.venv/`. The script detects that
markitdown isn't importable and transparently re-execs itself into the venv, so
`python3 scripts/markitdown_cli.py` just works.

## OCR

Scanned documents need OCR. This skill delegates that to a **vision model you
host locally** — Ollama, llama.cpp, LM Studio, or vLLM all work since they share
an OpenAI-compatible API. No tesseract, no system packages, no image leaves the
machine.

```bash
ollama serve
ollama pull qwen2.5vl
python3 $CLI scan.png --ocr
```

`--doctor --ocr` confirms the endpoint is up and lists the models it serves
before you commit to a large batch.

Details and model recommendations are in `SKILL.md`.

## Gotcha worth knowing

Legacy binary Office files (`.doc`, `.ppt`, old `.xls`) are **not** converted.
In a batch run they're skipped; in a single-file run they can produce raw
binary-looking text. Convert to `.docx`/`.pptx` first.

## Tests

```bash
python3 scripts/test_markitdown_cli.py
```

27 tests, fully offline. The OCR tests stand up a stub OpenAI-compatible server
and assert that a real PNG is base64-encoded into the request and the returned
transcription lands in the output.
