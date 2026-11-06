#!/usr/bin/env python3
"""
pdf_ocr.py - Scanned & Handwritten PDF OCR utility with zero-token stroke detection.

Features:
  - Zero-Token Pre-flight Heuristics:
      1. Digital selectable text detection (skips OCR if native text exists).
      2. Vector stylus stroke analysis (iPad / Surface / tablet handwriting).
      3. Raster ink stroke density analysis (scanned physical paper).
  - Page-level granularity: Only sends pages with unhighlightable handwriting/scans
    to LightOnOCR, preserving speed and zero-redundancy.
  - Generates clean Markdown with LaTeX mathematical formulas.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

def _drive_root() -> Path:
    """The AI volume root: $AI_ROOT, else the nearest ancestor holding models/.

    The weights and the mtmd binary live under it, so resolving from here keeps
    the skill working wherever the volume is mounted.
    """
    env = os.environ.get("AI_ROOT")
    if env:
        return Path(env).expanduser()
    for parent in Path(__file__).resolve().parents:
        if (parent / "models").is_dir():
            return parent
    return Path("/run/media/rodri/AI")


DRIVE = _drive_root()
DEFAULT_MODEL = os.environ.get(
    "LIGHTON_MODEL",
    str(DRIVE / "models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.Q4_K_M.gguf"),
)
DEFAULT_MMPROJ = os.environ.get(
    "LIGHTON_MMPROJ",
    str(DRIVE / "models/prithivMLmods/LightOnOCR-3-0.8B-GGUF/LightOnOCR-3-0.8B.mmproj-q8_0.gguf"),
)
DEFAULT_LLAMA_CLI = os.environ.get("LLAMA_MTMD_CLI", str(DRIVE / "llama.cpp/build/bin/llama-mtmd-cli"))

def detect_page_mode(page, min_chars: int = 50) -> tuple[str, str]:
    """
    Zero-token heuristic: determines whether a page has native digital text,
    tablet vector handwriting, or scanned paper handwriting/images.

    Returns:
        (mode, reason) where mode is 'TEXT', 'HANDWRITING_OCR', or 'BLANK'
    """
    text_content = page.get_text().strip()

    # 1. Native selectable text exists
    if len(text_content) >= min_chars:
        return ("TEXT", f"Native digital text found ({len(text_content)} chars)")

    # 2. Check for digital stylus strokes (iPad / Apple Pencil / OneNote)
    drawings = page.get_drawings()
    thin_strokes = [d for d in drawings if (d.get("width") or 0.0) <= 3.5]
    if len(thin_strokes) >= 20:
        return ("HANDWRITING_OCR", f"Digital tablet ink detected ({len(thin_strokes)} vector strokes)")

    # 3. Check for scanned physical paper (raster bitmap analysis)
    # Fast 72 DPI thumbnail sampling for zero-lag inspection
    pix = page.get_pixmap(dpi=72)
    samples = pix.samples
    channels = pix.n
    total_samples = len(samples) // channels

    dark_pixels = 0
    stride = 4  # sample every 4th pixel for speed (< 1ms)
    total_checked = total_samples // stride

    for i in range(0, len(samples), channels * stride):
        if channels >= 3:
            luma = (samples[i] * 77 + samples[i + 1] * 150 + samples[i + 2] * 29) >> 8
        else:
            luma = samples[i]

        if luma < 175:
            dark_pixels += 1

    if total_checked > 0:
        stroke_density = dark_pixels / total_checked
    else:
        stroke_density = 0.0

    if stroke_density < 0.005:
        return ("BLANK", f"Near-empty page (stroke density: {stroke_density:.4f})")
    elif 0.01 <= stroke_density <= 0.15:
        return ("HANDWRITING_OCR", f"Scanned ink/handwriting strokes detected (density: {stroke_density:.3%})")
    elif stroke_density > 0.15:
        # High density: might be dark slides or dense diagrams
        return ("HANDWRITING_OCR", f"Dense raster content detected (density: {stroke_density:.3%})")

    # Fallback if there's any text at all
    if len(text_content) > 0:
        return ("TEXT", f"Sparse digital text ({len(text_content)} chars)")

    return ("BLANK", "No significant content detected")

def ocr_page_image(
    image_path: str,
    llama_cli: str = DEFAULT_LLAMA_CLI,
    model: str = DEFAULT_MODEL,
    mmproj: str = DEFAULT_MMPROJ,
    prompt: str = "Transcribe the text and mathematical formulas in this image to Markdown LaTeX format."
) -> str:
    """Runs LightOnOCR via llama-mtmd-cli on a single rendered page."""
    cmd = [
        llama_cli,
        "-m", model,
        "--mmproj", mmproj,
        "--image", image_path,
        "-p", prompt,
        "-ngl", "99",
        "-c", "4096"
    ]
    env = os.environ.copy()
    env["PAGER"] = "cat"
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)

    output = proc.stdout
    if not output and proc.stderr:
        output = proc.stderr

    lines = output.splitlines()
    clean_lines = []
    started = False
    for line in lines:
        if (line.startswith("WARNING:") or line.startswith("0.") or 
            line.startswith("<|im_start|>") or line.startswith("<|im_end|>") or 
            "llama threadpool init" in line or "mtmd batch encoding done" in line or 
            "chat template" in line or "loading model:" in line or "WARN:" in line):
            continue
        if any(line.strip().startswith(prefix) for prefix in ["#", "$$", "■", "Solution", "Exercise", "---", "(", "Find", "1.", "2."]):
            started = True
        if started or line.strip():
            clean_lines.append(line)

    return "\n".join(clean_lines).strip()

def process_pdf(
    pdf_path: str,
    output_path: str = None,
    dpi: int = 200,
    force_ocr: bool = False,
    pages: list = None,
    json_output: bool = False,
):
    def log(message: str = "") -> None:
        print(message, file=sys.stderr if json_output else sys.stdout)

    pdf_p = Path(pdf_path).resolve()
    if not pdf_p.exists():
        print(f"Error: PDF file '{pdf_path}' not found.", file=sys.stderr)
        sys.exit(1)

    import fitz
    doc = fitz.open(str(pdf_p))
    num_pages = len(doc)
    log(f"[*] Analyzing '{pdf_p.name}' ({num_pages} pages) with zero-token heuristics...")

    page_indices = range(num_pages)
    if pages:
        page_indices = [p - 1 for p in pages if 0 <= p - 1 < num_pages]

    results = []
    page_records = []
    ocr_count = 0
    text_count = 0
    blank_count = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        for idx in page_indices:
            page_num = idx + 1
            page = doc[idx]
            mode, reason = detect_page_mode(page)

            if force_ocr and mode != "BLANK":
                mode = "HANDWRITING_OCR"
                reason = "Forced OCR"

            log(f"  • Page {page_num:2d}: [{mode:15s}] - {reason}")
            record = {"page": page_num, "mode": mode, "reason": reason}

            if mode == "TEXT":
                text_count += 1
                text_extracted = page.get_text().strip()
                record["chars"] = len(text_extracted)
                results.append(f"<!-- Page {page_num} (Native Text) -->\n\n{text_extracted}")

            elif mode == "HANDWRITING_OCR":
                ocr_count += 1
                log(f"    [>] Rendering page {page_num} @ {dpi} DPI & transcribing via LightOnOCR...")
                pix = page.get_pixmap(dpi=dpi)
                img_path = os.path.join(tmpdir, f"page_{page_num:03d}.png")
                pix.save(img_path)

                ocr_markdown = ocr_page_image(img_path)
                record["chars"] = len(ocr_markdown)
                results.append(f"<!-- Page {page_num} (Handwriting OCR) -->\n\n{ocr_markdown}")

            else:
                blank_count += 1

            page_records.append(record)

    doc.close()

    log(f"\n[*] Summary: {ocr_count} OCR'd | {text_count} Native Text | {blank_count} Blank/Skipped")

    full_markdown = "\n\n---\n\n".join(results)
    out_p = None

    if output_path:
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            f.write(full_markdown)
        log(f"[✓] Output written to: {out_p}")
    elif not json_output:
        log("\n" + "="*40 + " OUTPUT " + "="*40)
        log(full_markdown)

    report = {
        "pdf": str(pdf_p),
        "output": str(out_p) if out_p else None,
        "dpi": dpi,
        "force_ocr": force_ocr,
        "pages": page_records,
        "summary": {"ocr": ocr_count, "text": text_count, "blank": blank_count},
    }
    if out_p is None:
        report["markdown"] = full_markdown
    return report

def main():
    parser = argparse.ArgumentParser(description="Zero-token handwritten stroke detector & OCR pipeline.")
    parser.add_argument("pdf", type=Path, help="Path to PDF file")
    parser.add_argument("-o", "--output", type=Path, help="Output markdown file path")
    parser.add_argument("--dpi", type=int, default=200, metavar="N", help="Rasterization DPI for OCR (default: 200)")
    parser.add_argument("--force-ocr", action="store_true", help="Force OCR across all non-blank pages")
    parser.add_argument("--pages", type=int, nargs="+", metavar="N", help="Specific pages (1-indexed) to process")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report on stdout")
    args = parser.parse_args()

    report = process_pdf(
        str(args.pdf),
        str(args.output) if args.output else None,
        args.dpi,
        args.force_ocr,
        args.pages,
        json_output=args.json,
    )
    if args.json:
        print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
