## OCR (local, opt-in)

Scanned pages and images have no text layer, so OCR is needed. This skill uses a
**vision model served on your own machine** — there is no tesseract or other
system package, and nothing is sent to a hosted API unless you point it at one.

Pick whichever local server you already run; they all speak the same API.

**Ollama** (simplest):
```bash
ollama serve
ollama pull qwen2.5vl          # or: llava, minicpm-v, gemma3
python3 $CLI scan.png --ocr
```

**llama.cpp / LM Studio / vLLM**:
```bash
python3 $CLI scan.png --ocr \
  --ocr-base-url http://localhost:8080/v1 \
  --ocr-model gemma-3-4b-it
```

Good OCR-capable vision models: `qwen2.5vl`, `dots.ocr`, `got-ocr2.0`,
`PaddleOCR-VL`, `minicpm-v`, `llava`. For dense tables or handwriting, an
OCR-specialised model beats a general captioner.

Verify the wiring before a long batch job:
```bash
python3 $CLI --doctor --ocr --ocr-base-url http://localhost:8080/v1
```
It reports whether the endpoint is reachable and which models it serves.

| Option | Purpose |
|---|---|
| `--ocr` | enable OCR via the local vision endpoint |
| `--ocr-base-url` | endpoint (default `http://localhost:11434/v1`, Ollama) |
| `--ocr-model` | model name (default `llava`) |
| `--llm-prompt` | override the prompt; defaults to a transcription instruction |
| `--no-metadata` | omit the `title` frontmatter block |

Defaults can live in `.env` next to the script:
```
MARKITDOWN_OCR_BASE_URL=http://localhost:8080/v1
MARKITDOWN_OCR_MODEL=qwen2.5vl
```

OCR applies to images and image-only PDFs. A PDF with a real text layer does not
need it — text is extracted directly and is faster and more accurate.
