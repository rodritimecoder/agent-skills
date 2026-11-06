#!/usr/bin/env python3
"""doc-layout — PP-DocLayoutV3 layout detection -> crops -> VLM -> Markdown.

Layout-first document parsing. The layout model (PP-DocLayoutV3, ONNX) segments
a page into 25 region types with boxes/polygons/reading order; each region is
cropped and sent to a vision VLM with a type-appropriate prompt; the assembler
renders the official Markdown conventions ported from OpenBMB's `minicpmvocr`
SDK (`sdk/minicpmvocr/prompts.py`, `postprocess/markdown.py`).

The VLM never controls the layout model: control flows CLI -> {layout, VLM}.
No torch, no PaddlePaddle.

Commands:
  doctor  — check model + VLM endpoint
  layout  — detect regions (JSON: boxes, quads, order, labels)
  crops   — detect and crop each region
  parse   — full pipeline to Markdown
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import argparse
import base64
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tempfile
import urllib.error
import urllib.request

# --- venv hop -----------------------------------------------------------------

def _reexec_in_venv() -> None:
    """Re-exec under the skill venv when onnxruntime/cv2 are missing."""
    try:
        import onnxruntime  # noqa: F401
        import cv2  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("_DOC_LAYOUT_VENV_REEXEC") == "1":
        return
    from pathlib import Path
    here = Path(__file__).resolve()
    candidates = (
        here.parent.parent / ".venv" / "bin" / "python",
        Path.home() / ".venvs" / "doc-layout" / "bin" / "python",
    )
    venv_py = next((c for c in candidates if c.is_file()), None)
    if venv_py is None:
        return
    if venv_py.resolve() == Path(sys.executable).resolve():
        return
    env = dict(os.environ)
    env["_DOC_LAYOUT_VENV_REEXEC"] = "1"
    os.execve(str(venv_py), [str(venv_py), str(here), *sys.argv[1:]], env)


# --- model defaults -----------------------------------------------------------

DEFAULT_ONNX = ("/run/media/rodri/AI/models/Bei0001/PP-DocLayoutV3-ONNX/"
                "PP-DocLayoutV3.onnx")
# There is no canonical OCR VLM port: :8080 is the primary LLM (not vision),
# :8084 is CrispEmbed (not OpenAI-compatible), and MiniCPM-OCR is launched
# ad-hoc. Require an explicit endpoint rather than defaulting onto the LLM.
DEFAULT_VLM = None
DEFAULT_MODEL_NAME = "minicpm-ocr"
TARGET = 800
MASK_RES = 200

LABELS = ["abstract", "algorithm", "aside_text", "chart", "content",
          "display_formula", "doc_title", "figure_title", "footer",
          "footer_image", "footnote", "formula_number", "header",
          "header_image", "image", "inline_formula", "number",
          "paragraph_title", "reference", "reference_content", "seal",
          "table", "text", "vertical_text", "vision_footnote"]

# Ported from OpenBMB sdk/minicpmvocr/prompts.py (DEFAULT_PROMPT_MAP).
ELEMENT_PROMPTS = {
    "text": ("Text Recognition:", 4096, "text"),
    "content": ("Text Recognition:", 4096, "text"),
    "abstract": ("Text Recognition:", 4096, "text"),
    "reference": ("Text Recognition:", 2048, "text"),
    "reference_content": ("Text Recognition:", 2048, "text"),
    "vertical_text": ("Text Recognition:", 2048, "text"),
    "vision_footnote": ("Text Recognition:", 1024, "text"),
    "algorithm": ("Text Recognition:", 4096, "text"),
    "doc_title": ("Text Recognition:", 512, "text"),
    "paragraph_title": ("Text Recognition:", 512, "text"),
    "figure_title": ("Text Recognition:", 512, "text"),
    "table": ("Table Recognition:", 8192, "html"),
    "display_formula": ("Formula Recognition:", 2048, "latex"),
    "inline_formula": ("Text Recognition:", 1024, "latex"),
    "formula_number": ("Text Recognition:", 256, "text"),
    "header": ("Text Recognition:", 512, "text"),
    "footer": ("Text Recognition:", 512, "text"),
    "footnote": ("Text Recognition:", 1024, "text"),
    "aside_text": ("Text Recognition:", 1024, "text"),
    "number": ("Text Recognition:", 256, "text"),
    "chart": ("Chart to Table:", 4096, "html"),
    "seal": ("Seal Recognition:", 256, "text"),
}

# Ported from prompts.py markdown_assembly.
IGNORE_LABELS = {"number", "footnote", "header", "header_image", "footer",
                 "footer_image", "aside_text"}
TITLE_FORMAT = {"doc_title": "# {c}", "paragraph_title": "## {c}",
                "figure_title": "*{c}*"}
FORMULA_FORMAT = {"display_formula": "$$\n{c}\n$$", "inline_formula": "${c}$"}
NO_VLM_LABELS = {"image", "header_image", "footer_image"}

INLINE_MATH_RE = re.compile(r"(?<!\\)\$(?!\$)(?:[^$\n]|\\.)+?(?<!\\)\$(?!\$)|\\\([^\n]*?\\\)")
DISPLAY_SPAN_RE = re.compile(r"\\\[(.*?)\\\]|\$\$(.*?)\$\$", re.DOTALL)


# --- layout -------------------------------------------------------------------

def _softmax(x, axis=-1):
    import numpy as np
    e = np.exp(x - x.max(axis=axis, keepdims=True))
    return e / e.sum(axis=axis, keepdims=True)


def _preprocess(img_path):
    import numpy as np
    from PIL import Image
    im = Image.open(img_path).convert("RGB")
    ow, oh = im.size
    im_r = im.resize((TARGET, TARGET), Image.BICUBIC)
    pv = (np.asarray(im_r).astype("float32") / 255.0).transpose(2, 0, 1)[None]
    return pv, (ow, oh)


def _nms(dets, iou_thr):
    def iou(a, b):
        ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
        inter = ix * iy
        ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
        return inter / ua if ua > 0 else 0.0
    order = sorted(range(len(dets)), key=lambda i: -dets[i]["score"])
    keep = []
    while order:
        i = order.pop(0)
        keep.append(i)
        order = [j for j in order
                 if not (dets[j]["class_id"] == dets[i]["class_id"]
                         and iou(dets[i]["bbox"], dets[j]["bbox"]) > iou_thr)]
    return keep



# --- reading order: recursive XY-cut -----------------------------------------
# A row-major (y, then x) sort interleaves columns: on a 2-column page it emits
# the right column's figure after the first left paragraph. XY-cut fixes that by
# recursively cutting on the widest uncovered whitespace: vertical cuts split
# columns (left first), horizontal cuts split bands (top first). Full-width
# headers/figures block a vertical cut and force a band split, which is exactly
# what makes two-column pages come out column-by-column.

def _covered_gaps(intervals, min_gap):
    """Uncovered spans of at least min_gap between merged intervals."""
    if len(intervals) < 2:
        return []
    ivs = sorted((float(a), float(b)) for a, b in intervals)
    merged = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    gaps = []
    for i in range(len(merged) - 1):
        g0, g1 = merged[i][1], merged[i + 1][0]
        if g1 - g0 >= min_gap:
            gaps.append((g0, g1))
    return gaps


def _split_by(boxes, axis, split):
    lo, hi = [], []
    for b in boxes:
        x1, y1, x2, y2 = b["bbox"]
        c = (x1 + x2) / 2 if axis == "x" else (y1 + y2) / 2
        (lo if c < split else hi).append(b)
    return lo, hi


def _columns_balanced(left, right, page_w):
    """True two-column bodies have two similarly wide columns.

    A single column with side figures also shows a vertical gap, but its right
    side is much narrower than its left. Requiring balanced widths keeps that
    layout on the row-major path instead of reading all figures after all text.
    """
    if len(left) < 2 or len(right) < 2:
        return False
    lw = max(b["bbox"][2] for b in left) - min(b["bbox"][0] for b in left)
    rw = max(b["bbox"][2] for b in right) - min(b["bbox"][0] for b in right)
    if min(lw, rw) < 0.15 * page_w:
        return False
    return min(lw, rw) / max(lw, rw) >= 0.6


def _xy_cut(boxes, page_w, page_h, depth=0):
    if len(boxes) <= 1 or depth > 24:
        return list(boxes)
    min_gv = max(8.0, 0.012 * page_w)
    min_gh = max(6.0, 0.006 * page_h)

    vgaps = _covered_gaps([(b["bbox"][0], b["bbox"][2]) for b in boxes], min_gv)
    if vgaps:
        g0, g1 = max(vgaps, key=lambda g: g[1] - g[0])
        left, right = _split_by(boxes, "x", (g0 + g1) / 2)
        if left and right and _columns_balanced(left, right, page_w):
            return (_xy_cut(left, page_w, page_h, depth + 1)
                    + _xy_cut(right, page_w, page_h, depth + 1))

    hgaps = _covered_gaps([(b["bbox"][1], b["bbox"][3]) for b in boxes], min_gh)
    if hgaps:
        g0, g1 = max(hgaps, key=lambda g: g[1] - g[0])
        top, bot = _split_by(boxes, "y", (g0 + g1) / 2)
        if top and bot:
            return (_xy_cut(top, page_w, page_h, depth + 1)
                    + _xy_cut(bot, page_w, page_h, depth + 1))

    return sorted(boxes, key=lambda b: (round(b["bbox"][1] / 20), b["bbox"][0]))


def order_regions(dets, page_w, page_h, mode="xcut"):
    if mode == "y":
        return sorted(dets, key=lambda d: (round(d["bbox"][1] / 20), d["bbox"][0]))
    return _xy_cut(list(dets), float(page_w), float(page_h))


TEXT_CONTAINERS = {"text", "content", "abstract", "reference", "reference_content",
                   "vertical_text", "vision_footnote", "algorithm", "figure_title"}


def _containment(inner, outer):
    """Fraction of `inner`'s area that lies inside `outer`."""
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    area = max(1e-6, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return (ix * iy) / area


def _suppress_contained_inline(dets, contain_thr=0.8):
    """Drop inline-formula regions already transcribed inside a text block.

    The VLM reads a text crop with its inline math intact, so a separate
    inline_formula crop that sits inside one duplicates the same content.
    """
    containers = [d["bbox"] for d in dets if d["label"] in TEXT_CONTAINERS]
    out = []
    for d in dets:
        if d["label"] == "inline_formula" and containers:
            if any(_containment(d["bbox"], c) >= contain_thr for c in containers):
                continue
        out.append(d)
    return out


_SESSIONS = {}


def _session(onnx_path, threads):
    """Reuse the ONNX session: building it costs ~250 ms per process."""
    key = (onnx_path, threads)
    if key not in _SESSIONS:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        _SESSIONS[key] = ort.InferenceSession(
            onnx_path, so, providers=["CPUExecutionProvider"])
    return _SESSIONS[key]


def detect(img_path, onnx_path=DEFAULT_ONNX, score_thr=0.4, iou_thr=0.45,
           order_mode="xcut", threads=0):
    import numpy as np
    import cv2
    import onnxruntime as ort

    pv, (ow, oh) = _preprocess(img_path)
    if not threads:
        threads = min(8, os.cpu_count() or 4)
    sess = _session(onnx_path, threads)
    names = [o.name for o in sess.get_outputs()]
    logits, pred_boxes, out_masks, order_logits = sess.run(names, {"pixel_values": pv})

    probs = _softmax(logits[0], -1)
    scores = probs.max(-1)
    labels = probs.argmax(-1)
    cx, cy, w, h = pred_boxes[0].T
    x1, y1 = (cx - w/2) * ow, (cy - h/2) * oh
    x2, y2 = (cx + w/2) * ow, (cy + h/2) * oh

    raw = []
    for i in np.where(scores >= score_thr)[0]:
        poly = []
        try:
            m = (out_masks[0, i] > 0).astype("uint8")
            cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cnts:
                c = max(cnts, key=cv2.contourArea)
                if cv2.contourArea(c) > 4:
                    approx = cv2.approxPolyDP(c, 0.01 * cv2.arcLength(c, True), True)
                    poly = [[float(p[0][0]) * ow / MASK_RES, float(p[0][1]) * oh / MASK_RES]
                            for p in approx]
        except cv2.error:
            pass
        cls = int(labels[i])
        raw.append({"query": int(i), "class_id": cls,
                    "label": LABELS[cls] if 0 <= cls < len(LABELS) else f"?{cls}",
                    "score": float(scores[i]),
                    "bbox": [float(x1[i]), float(y1[i]), float(x2[i]), float(y2[i])],
                    "polygon": poly})

    dets = [raw[i] for i in _nms(raw, iou_thr)]
    dets = _suppress_contained_inline(dets)
    dets = order_regions(dets, ow, oh, order_mode)
    for k, d in enumerate(dets):
        d["order"] = k

    order_head = None
    try:
        order_head = "present"
    except Exception:
        pass
    return {"image": img_path, "orig_size": [ow, oh], "score_thr": score_thr,
            "iou_thr": iou_thr, "order_mode": order_mode,
            "n_raw": len(raw), "n_final": len(dets),
            "order_head": order_head, "detections": dets}


def crop_regions(det_result, outdir, pad=4):
    import cv2
    from PIL import Image
    import numpy as np
    os.makedirs(outdir, exist_ok=True)
    rgb = np.asarray(Image.open(det_result["image"]).convert("RGB"))
    H, W = rgb.shape[:2]
    paths = []
    for d in det_result["detections"]:
        x1, y1, x2, y2 = [int(round(v)) for v in d["bbox"]]
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(W, x2 + pad), min(H, y2 + pad)
        p = os.path.join(outdir, f"{d['order']:02d}_{d['label']}_{d['query']}.png")
        cv2.imwrite(p, cv2.cvtColor(rgb[y1:y2, x1:x2], cv2.COLOR_RGB2BGR))
        d["crop"] = p
        paths.append(p)
    return paths


# --- VLM ----------------------------------------------------------------------

def _b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def vlm_recognize(url, model, crop_path, prompt, max_tokens, timeout=180):
    payload = {
        "model": model, "max_tokens": max_tokens, "temperature": 0.0,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{_b64(crop_path)}"}},
        ]}],
    }
    req = urllib.request.Request(
        f"{url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    msg = d["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    if not content and msg.get("reasoning_content"):
        content = msg["reasoning_content"].strip()
    return content


# --- LightOnOCR engine (one call per page) -------------------------------------

GROUNDING_RE = re.compile(r"!\[(\w+)\]\((\d+),(\d+),(\d+),(\d+)\)")
FIGURE_LABELS = {"image", "header_image", "footer_image"}


def engine_for_model(model_id):
    """Pick the engine from the served model id."""
    return "lighton" if "lighton" in (model_id or "").lower() else "layout"


def probe_engine(url, timeout=5):
    """Ask the endpoint what model it serves; fall back to the layout engine."""
    base = url.rstrip("/")
    model_id = ""
    try:
        with urllib.request.urlopen(f"{base}/v1/models", timeout=timeout) as r:
            d = json.load(r)
        items = d.get("models") or d.get("data") or []
        if items:
            it = items[0]
            model_id = it.get("name") or it.get("id") or it.get("model") or ""
    except Exception:
        pass
    if not model_id:
        try:
            with urllib.request.urlopen(f"{base}/props", timeout=timeout) as r:
                d = json.load(r)
            model_id = d.get("model_path") or d.get("model_alias") or ""
        except Exception:
            pass
    return engine_for_model(model_id), model_id


def lighton_page(url, model, image_path, prompt="", max_tokens=4096, timeout=900):
    """Whole-page call. LightOnOCR-3 requires thinking disabled or content is empty."""
    content = [{"type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{_b64(image_path)}"}}]
    if prompt:
        content.append({"type": "text", "text": prompt})
    payload = {
        "model": model, "max_tokens": max_tokens, "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": content}],
    }
    req = urllib.request.Request(
        f"{url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    msg = d["choices"][0]["message"]
    txt = (msg.get("content") or "").strip()
    if not txt and msg.get("reasoning_content"):
        txt = msg["reasoning_content"].strip()
    return txt, d.get("usage", {})


def _parse_grounding(text):
    """Split grounding output into blocks: label, bbox (0-1000), content."""
    ms = list(GROUNDING_RE.finditer(text))
    blocks = []
    for i, m in enumerate(ms):
        start = m.end()
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        blocks.append({"label": m.group(1),
                       "bbox": [int(m.group(j)) for j in range(2, 6)],
                       "text": text[start:end].strip()})
    return blocks


def _assemble_grounding(blocks, image_path, asset_dir, out_dir, embed_images):
    """Crop figures from their bboxes and emit clean Markdown."""
    from PIL import Image
    os.makedirs(asset_dir, exist_ok=True)
    im = Image.open(image_path).convert("RGB")
    W, H = im.size
    out, k = [], 0
    for b in blocks:
        lab, txt, bb = b["label"], b["text"], b["bbox"]
        is_figure = lab in FIGURE_LABELS or (lab == "chart" and "<table" not in txt.lower())
        if is_figure:
            if embed_images:
                x1, y1, x2, y2 = (int(bb[0] * W / 1000), int(bb[1] * H / 1000),
                                  int(bb[2] * W / 1000), int(bb[3] * H / 1000))
                k += 1
                pth = os.path.join(asset_dir, f"figure_{k}.png")
                im.crop((max(0, x1), max(0, y1), min(W, x2), min(H, y2))).save(pth)
                alt = (txt.splitlines()[0][:80] if txt else lab) or lab
                out.append(f"![{alt}]({os.path.relpath(pth, start=out_dir)})")
            else:
                out.append(f"![{lab}]()")
            continue
        if txt:
            out.append(txt)
    return "\n\n".join(out) + ("\n" if out else "")


def _lighton_parse(image_path, a, out_dir=None, asset_name="assets"):
    prompt = "grounding" if getattr(a, "grounding", False) else ""
    txt, usage = lighton_page(a.vlm, a.model, image_path, prompt,
                              a.max_tokens or 4096)
    meta = {"engine": "lighton",
            "mode": "grounding" if prompt else "text",
            "chars": len(txt), "usage": usage}
    if not prompt:
        return txt, meta
    blocks = _parse_grounding(txt)
    meta["blocks"] = len(blocks)
    asset_dir = os.path.join(out_dir or ".", asset_name)
    return _assemble_grounding(blocks, image_path, asset_dir, out_dir or ".",
                               a.embed_images), meta


# --- markdown assembly (ported from postprocess/markdown.py) -------------------

def _strip_spacing_tokens(s):
    s = re.sub(r"\\(?:quad|qquad|enspace|thinspace|medspace|thickspace|"
               r"negthinspace|negmedspace|negthickspace)(?![A-Za-z])", "", s)
    s = re.sub(r"\\[,;:!]", "", s)
    s = re.sub(r"\\ ", "", s)
    s = re.sub(r"\\(?:hspace|vspace)\s*\{[^{}]*\}", "", s)
    return re.sub(r"[\s{}]", "", s.replace("~", ""))


def repair_display_formula(content):
    content = re.sub(r"\\\[\s*\\\]|\\\(\s*\\\)", " ", content)

    def clean(m):
        is_bracket = m.group(0).startswith(r"\[")
        body = m.group(1) if is_bracket else m.group(2)
        if body.strip() and not _strip_spacing_tokens(body):
            return " "
        return (r"\[" + body + r"\]") if is_bracket else f"$${body}$$"
    return DISPLAY_SPAN_RE.sub(clean, content)


def _unwrap_math(s):
    """Strip a surrounding math delimiter so the assembler owns the wrapping."""
    s = (s or "").strip()
    for pat in (r"\\\[(.*)\\\]", r"\$\$(.*)\$\$", r"\\\((.*)\\\)"):
        m = re.fullmatch(pat, s, re.DOTALL)
        if m:
            return m.group(1).strip()
    return s


OTSL_CELL_RE = re.compile(r"<(fcel|ecel|lcel|ucel|xcel|bcel)>")


def otsl_to_html(text):
    """Convert OpenTable/OTSL markup to an HTML table; pass non-OTSL through.

    OTSL: <fcel>cell, <ecel> empty, <lcel>/<ucel>/<xcel> merge continuations,
    <nl> row break.
    """
    t = (text or "").strip()
    if "<fcel>" not in t and "<ecel>" not in t:
        return text
    t = t.replace("<otsl>", "").replace("</otsl>", "")
    rows = re.split(r"<nl>", t)
    out = ["<table>"]
    for row in rows:
        row = row.strip()
        if not row:
            continue
        parts = OTSL_CELL_RE.split(row)
        out.append("<tr>")
        i = 1
        while i < len(parts):
            tag = parts[i]
            content = parts[i + 1] if i + 1 < len(parts) else ""
            if tag == "fcel":
                out.append(f"<td>{content.strip()}</td>")
            else:
                out.append("<td></td>")
            i += 2
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def is_pure_inline_math(s):
    s = (s or "").strip()
    return bool(s) and bool(INLINE_MATH_RE.fullmatch(s))


def has_mixed_inline_formula_content(content):
    """True when an inline-formula crop also contains ordinary text.

    Ported from OpenBMB postprocess/markdown.py: if the crop's content is a
    pure inline-math span it is a formula; otherwise the crop mixed text in and
    must be rendered as text.
    """
    s = (content or "").strip()
    if not s:
        return False
    if INLINE_MATH_RE.fullmatch(s):
        return False
    return bool(INLINE_MATH_RE.sub("", s).strip())


def render_markdown(regions, keep_ignored=False, embed_images=False):
    """Assemble regions (already in reading order) into Markdown."""
    out = []
    for d in regions:
        lab = d["label"]
        txt = (d.get("text") or "").strip()
        if lab in IGNORE_LABELS and not keep_ignored:
            continue
        if lab in NO_VLM_LABELS:
            ref = d.get("image_ref", "") if embed_images else ""
            out.append(f"![image]({ref})")
            continue
        if not txt:
            continue
        if lab in TITLE_FORMAT:
            out.append(TITLE_FORMAT[lab].format(c=txt))
        elif lab in ("display_formula",):
            body = _unwrap_math(repair_display_formula(txt))
            out.append(FORMULA_FORMAT[lab].format(c=body) if body else "")
        elif lab == "inline_formula":
            if has_mixed_inline_formula_content(txt):
                out.append(txt)
            else:
                body = _unwrap_math(txt) or txt
                out.append(FORMULA_FORMAT[lab].format(c=body))
        elif lab in ("table", "chart"):
            out.append(otsl_to_html(txt))
        elif lab == "seal":
            out.append(txt)
        else:
            out.append(txt)
    return "\n\n".join(out) + ("\n" if out else "")


# --- commands -----------------------------------------------------------------

VLM_GUIDANCE = """\
error: --vlm is required (port 8080 is the primary LLM, not an OCR model).
  standing OCR VLM   : --vlm http://127.0.0.1:8085   (LightOnOCR-3-0.8B)
  MiniCPM-OCR        : start llama-server ad-hoc, then pass its port
  CrispEmbed (:8084) : NOT OpenAI-compatible; use the `ocr` skill instead
"""


def _require_vlm(a):
    if getattr(a, "vlm", None):
        return a.vlm
    sys.stderr.write(VLM_GUIDANCE)
    sys.exit(2)


def cmd_doctor(a):
    _require_vlm(a)
    import importlib
    status = {"ok": True, "checks": {}}
    onnx = a.layout_model or os.environ.get("DOC_LAYOUT_MODEL") or DEFAULT_ONNX
    present = os.path.isfile(onnx) and os.path.isfile(onnx + ".data")
    status["checks"]["layout_model"] = {"path": onnx, "present": present}
    if not present:
        status["ok"] = False
    for mod in ("numpy", "cv2", "onnxruntime", "PIL"):
        try:
            importlib.import_module(mod)
            status["checks"][mod] = True
        except Exception:
            status["checks"][mod] = False
            status["ok"] = False
    vlm = {"url": a.vlm}
    try:
        with urllib.request.urlopen(f"{a.vlm.rstrip('/')}/health", timeout=3) as r:
            vlm["health"] = r.status
        vlm["reachable"] = True
    except Exception as e:
        vlm["reachable"] = False
        vlm["error"] = str(e)
        status["ok"] = False
    status["checks"]["vlm"] = vlm
    sys.stdout.write(json.dumps(status, indent=2) + "\n")
    sys.stdout.flush()
    return 0 if status["ok"] else 1


def _detect_or_die(a):
    onnx = a.layout_model or os.environ.get("DOC_LAYOUT_MODEL") or DEFAULT_ONNX
    if not os.path.isfile(onnx):
        print(f"error: layout model not found: {onnx}", file=sys.stderr)
        sys.exit(2)
    return detect(a.image, onnx, a.thr, a.iou, a.order)


def cmd_layout(a):
    res = _detect_or_die(a)
    if a.images_only:
        res["detections"] = [d for d in res["detections"] if d["label"] == "image"]
        res["n_final"] = len(res["detections"])
    where = a.json or "-"
    txt = json.dumps(res, indent=2)
    if where == "-":
        sys.stdout.write(txt + "\n")
    else:
        with open(where, "w") as f:
            f.write(txt)
        sys.stderr.write(f"wrote {where}  ({res['n_final']} regions)\n")
    return 0


def cmd_crops(a):
    res = _detect_or_die(a)
    if a.images_only:
        res["detections"] = [d for d in res["detections"] if d["label"] == "image"]
        res["n_final"] = len(res["detections"])
    paths = crop_regions(res, a.outdir)
    print(f"wrote {len(paths)} crops -> {a.outdir}")
    return 0


def _parse_pages_spec(spec, n_pages):
    """'1-5', '3', or '1,3,5' -> zero-based page indices."""
    if not spec:
        return list(range(n_pages))
    sel = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            sel.extend(range(int(lo) - 1, int(hi)))
        else:
            sel.append(int(part) - 1)
    return [i for i in sel if 0 <= i < n_pages]


def _render_pdf(path, dpi, pages_spec, outdir, max_edge=2048):
    try:
        import pymupdf
    except ImportError:
        sys.stderr.write("error: PDF input needs pymupdf (uv pip install pymupdf)\n")
        sys.exit(2)
    doc = pymupdf.open(path)
    os.makedirs(outdir, exist_ok=True)
    rendered = []
    for i in _parse_pages_spec(pages_spec, doc.page_count):
        png = os.path.join(outdir, f"page{i + 1:03d}.png")
        pix = doc[i].get_pixmap(dpi=dpi)
        if max_edge and max(pix.width, pix.height) > max_edge:
            from PIL import Image
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            img.thumbnail((max_edge, max_edge))
            img.save(png)
        else:
            pix.save(png)
        rendered.append((i + 1, png))
    doc.close()
    return rendered


def _detect_path(image, a):
    onnx = a.layout_model or os.environ.get("DOC_LAYOUT_MODEL") or DEFAULT_ONNX
    if not os.path.isfile(onnx):
        print(f"error: layout model not found: {onnx}", file=sys.stderr)
        sys.exit(2)
    return detect(image, onnx, a.thr, a.iou, a.order, a.threads)


def _layout_and_crop(image_path, a, cropdir):
    """CPU stage: detect regions and write crops."""
    res = _detect_path(image_path, a)
    if a.images_only:
        res["detections"] = [d for d in res["detections"] if d["label"] == "image"]
        res["n_final"] = len(res["detections"])
    crop_regions(res, cropdir)
    return res


def _ocr_regions(res, a, out_dir=None):
    """GPU stage: send each crop to the VLM and assemble Markdown."""
    targets = [d for d in res["detections"]
               if d["label"] not in NO_VLM_LABELS
               and not (d["label"] in IGNORE_LABELS and not a.keep_ignored)]

    def _work(d):
        prompt, mt, _fmt = ELEMENT_PROMPTS.get(
            d["label"], ("Text Recognition:", 4096, "text"))
        if a.max_tokens:
            mt = a.max_tokens
        try:
            return vlm_recognize(a.vlm, a.model, d["crop"], prompt, mt), None
        except Exception as e:
            return "", str(e)

    jobs = max(1, a.jobs)
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        for d, (txt, err) in zip(targets, ex.map(_work, targets)):
            d["text"] = txt
            if err:
                d["error"] = err
            print(f"  [{d['order']:2d}] {d['label']:16s} -> {(txt or '')[:60]!r}",
                  file=sys.stderr)
    if a.embed_images and out_dir:
        for d in res["detections"]:
            if d.get("crop"):
                d["image_ref"] = os.path.relpath(d["crop"], start=out_dir)
    return render_markdown(res["detections"], keep_ignored=a.keep_ignored,
                           embed_images=a.embed_images)


def _parse_one(image_path, a, cropdir, out_dir=None):
    res = _layout_and_crop(image_path, a, cropdir)
    return res, _ocr_regions(res, a, out_dir)


def _parse_pdf_overlap(a, pages, workdir, out_dir):
    """Overlap layout (CPU) with OCR (GPU) across pages.

    The producer detects page N+1 while the consumer OCRs page N. They use
    different hardware, so this overlaps cleanly without the GPU contention
    that OCR-vs-OCR concurrency causes on llama.cpp.
    """
    q = queue.Queue(maxsize=max(1, a.buffers))
    errs = []

    def producer():
        try:
            for n, png in pages:
                sub = os.path.join(workdir, f"p{n:03d}")
                res = _layout_and_crop(png, a, sub)
                res["page"] = n
                q.put((n, res, sub))
        except BaseException as e:  # surfaced on the consumer side
            errs.append(e)
        finally:
            q.put(None)

    t = threading.Thread(target=producer, name="layout-producer", daemon=True)
    t.start()
    parts, results = [], []
    while True:
        item = q.get()
        if item is None:
            break
        n, res, _sub = item
        sys.stderr.write(f"-- page {n} --\n")
        md = _ocr_regions(res, a, out_dir)
        results.append(res)
        parts.append(f"<!-- page {n} -->\n\n{md.rstrip()}")
    t.join()
    if errs:
        raise errs[0]
    return "\n\n---\n\n".join(parts) + "\n", results


def cmd_parse(a):
    _require_vlm(a)
    workdir = a.cropdir or tempfile.mkdtemp(prefix="doc-layout-")
    out_dir = os.path.dirname(os.path.abspath(a.output)) or "."

    engine = getattr(a, "engine", "auto")
    detected = ""
    if engine == "auto":
        engine, detected = probe_engine(a.vlm)
        sys.stderr.write(
            f"engine: {engine} (detected {os.path.basename(detected) or 'unknown'})\n")
    if getattr(a, "grounding", False) and engine == "lighton" and "1b" in detected.lower():
        sys.stderr.write(
            "warning: grounding needs LightOnOCR-3-0.8B/4B; the 1B is LightOnOCR-2 "
            "and ignores the grounding prompt\n")

    if a.image.lower().endswith(".pdf"):
        pages = _render_pdf(a.image, a.dpi, a.pages,
                            os.path.join(workdir, "pages"),
                            getattr(a, "max_edge", 2048))
        if not pages:
            sys.stderr.write("error: no pages selected\n")
            return 2
        if engine == "lighton":
            parts, results = [], []
            for n, png in pages:
                sys.stderr.write(f"-- page {n} --\n")
                p_md, meta = _lighton_parse(png, a, out_dir, f"p{n:03d}-assets")
                meta["page"] = n
                results.append(meta)
                parts.append(f"<!-- page {n} -->\n\n{p_md.rstrip()}")
            md = "\n\n---\n\n".join(parts) + "\n"
        elif a.overlap and len(pages) > 1:
            md, results = _parse_pdf_overlap(a, pages, workdir, out_dir)
        else:
            parts, results = [], []
            for n, png in pages:
                sys.stderr.write(f"-- page {n} --\n")
                sub = os.path.join(workdir, f"p{n:03d}")
                res, p_md = _parse_one(png, a, sub, out_dir)
                res["page"] = n
                results.append(res)
                parts.append(f"<!-- page {n} -->\n\n{p_md.rstrip()}")
            md = "\n\n---\n\n".join(parts) + "\n"
        payload = {"source": a.image, "kind": "pdf", "engine": engine,
                   "pages": len(pages), "results": results}
    elif engine == "lighton":
        md, payload = _lighton_parse(a.image, a, out_dir, "assets")
    else:
        res, md = _parse_one(a.image, a, workdir, out_dir)
        payload = res

    with open(a.output, "w") as f:
        f.write(md)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(payload, f, indent=2)
    print(f"wrote {a.output}  ({len(md.splitlines())} lines)")
    return 0


def cmd_render(a):
    """Markdown -> standalone HTML with typeset math (KaTeX via node)."""
    here = os.path.dirname(os.path.abspath(__file__))
    js = os.path.join(here, "render_md.js")
    node = shutil.which("node")
    if not node:
        sys.stderr.write("error: render needs node on PATH\n")
        return 2
    if not os.path.isfile(js):
        sys.stderr.write(f"error: renderer missing: {js}\n")
        return 2
    args = [node, js, a.markdown, a.output]
    if a.cdn:
        args.append("--cdn")
    return subprocess.run(args, check=False).returncode


def main():
    _reexec_in_venv()
    ap = argparse.ArgumentParser(prog="doc-layout",
                                 description="PP-DocLayoutV3 -> crops -> VLM -> Markdown")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--vlm", type=str, default=DEFAULT_VLM,
                        help="OpenAI-compatible vision endpoint (required; "
                             "e.g. http://127.0.0.1:8085 for LightOnOCR)")
        sp.add_argument("--model", type=str, default=DEFAULT_MODEL_NAME,
                        help=f"served model id (default {DEFAULT_MODEL_NAME})")
        sp.add_argument("--layout-model", type=str, default=None,
                        help="PP-DocLayoutV3 .onnx (default: Bei0001 export)")

    p = sub.add_parser("doctor")
    add_common(p)
    p.set_defaults(fn=cmd_doctor)

    for name, fn in (("layout", cmd_layout), ("crops", cmd_crops), ("parse", cmd_parse)):
        sp = sub.add_parser(name)
        add_common(sp)
        sp.add_argument("image", type=str)
        sp.add_argument("--thr", type=float, default=0.4, metavar="THRESHOLD")
        sp.add_argument("--iou", type=float, default=0.45, metavar="THRESHOLD")
        sp.add_argument("--images-only", action="store_true")
        sp.add_argument("--order", choices=("xcut", "y"), default="xcut",
                        help="reading order: xcut (column-aware, default) or y (row-major)")
        sp.add_argument("--threads", type=int, default=0, metavar="N",
                        help="ONNX threads (default min(8, cores))")
        sp.add_argument("--jobs", type=int, default=1, metavar="N",
                        help="parallel VLM requests (default 1; >1 crashes llama.cpp "
                             "with DSpark + multiple slots, so raise only if verified")
        if name == "layout":
            sp.add_argument("--json", nargs="?", const="-", type=str,
                            default=None, metavar="PATH",
                            help="write JSON to PATH; bare --json or '-' prints "
                                 "to stdout")
        if name == "crops":
            sp.add_argument("-o", "--outdir", type=str, required=True)
        if name == "parse":
            sp.add_argument("-o", "--output", type=str, required=True)
            sp.add_argument("--json", type=str, default=None, metavar="PATH")
            sp.add_argument("--cropdir", type=str, default=None)
            sp.add_argument("--max-tokens", type=int, default=None, metavar="N")
            sp.add_argument("--keep-ignored", action="store_true")
            sp.add_argument("--embed-images", action="store_true",
                            help="reference saved crops instead of ![image]()")
            sp.add_argument("--pages", type=str, default=None, metavar="SPEC",
                            help="PDF pages: '1-5', '3', '1,3,5' (default all)")
            sp.add_argument("--dpi", type=int, default=400, metavar="N",
                            help="PDF render DPI (default 400, LightOnOCR spec)")
            sp.add_argument("--max-edge", type=int, default=2048, metavar="N",
                            help="downscale longest edge to N px (default 2048; 0 = off)")
            sp.add_argument("--engine", choices=("auto", "layout", "lighton"),
                            default="auto",
                            help="auto (default) detects from the served model; "
                                 "layout: DocLayoutV3 + per-crop VLM; "
                                 "lighton: one whole-page call")
            sp.add_argument("--grounding", action="store_true",
                            help="lighton engine: emit labels + bboxes + figure crops")
            sp.add_argument("--overlap", action="store_true",
                            help="PDF: overlap layout (CPU) with OCR (GPU) across pages")
            sp.add_argument("--buffers", type=int, default=2, metavar="N",
                            help="pages buffered ahead when --overlap (default 2)")
        sp.set_defaults(fn=fn)

    rp = sub.add_parser("render")
    rp.add_argument("markdown", type=str)
    rp.add_argument("-o", "--output", type=str, required=True)
    rp.add_argument("--cdn", action="store_true",
                    help="use CDN KaTeX instead of the local dist")
    rp.set_defaults(fn=cmd_render)

    a = ap.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
