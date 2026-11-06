#!/usr/bin/env python3
"""Deterministic tests for doc-layout markdown assembly (no model, no VLM)."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("doc_layout", ROOT / "scripts" / "doc_layout.py")
dl = importlib.util.module_from_spec(spec)
sys.modules["doc_layout"] = dl
spec.loader.exec_module(dl)


def region(label, text, order=0):
    return {"label": label, "text": text, "order": order,
            "class_id": 0, "score": 0.9, "bbox": [0, 0, 1, 1], "polygon": []}


def test_drops_ignored_labels():
    out = dl.render_markdown([region("footer", "Page"), region("number", "65"),
                              region("text", "body")])
    assert "Page" not in out and "65" not in out
    assert "body" in out


def test_keep_ignored_flag():
    out = dl.render_markdown([region("footer", "Page")], keep_ignored=True)
    assert "Page" in out


def test_title_levels():
    assert dl.render_markdown([region("doc_title", "T")]).startswith("# T")
    assert dl.render_markdown([region("paragraph_title", "P")]).startswith("## P")
    assert "*F*" in dl.render_markdown([region("figure_title", "F")])


def test_images_are_references_not_ocr():
    out = dl.render_markdown([region("image", "should not appear")])
    assert "![image]()" in out and "should not appear" not in out


def test_display_formula_single_fence():
    out = dl.render_markdown([region("display_formula", "\\[\nE=mc^2\n\\]")])
    assert out.strip() == "$$\nE=mc^2\n$$"


def test_inline_formula_pure_math():
    out = dl.render_markdown([region("inline_formula", "\\(x=1\\)")])
    assert out.strip() == "$x=1$"


def test_inline_formula_mixed_text_passthrough():
    out = dl.render_markdown([region("inline_formula", "In")])
    assert out.strip() == "In"


def box(x1, y1, x2, y2, label="text"):
    return {"label": label, "text": "", "order": 0, "class_id": 0, "score": 0.9,
            "bbox": [x1, y1, x2, y2], "polygon": []}


def test_xy_cut_reads_left_column_before_right():
    # Two similarly wide columns: all left boxes must precede all right boxes.
    boxes = [box(135, 139, 832, 206), box(135, 206, 832, 475), box(135, 475, 832, 815),
             box(864, 131, 1563, 803, "chart"), box(864, 834, 1563, 1149, "figure_title"),
             box(864, 1190, 1563, 1596)]
    order = dl.order_regions(boxes, 1700, 2200)
    xs = [b["bbox"][0] for b in order]
    assert xs == [135, 135, 135, 864, 864, 864], xs


def test_xy_cut_keeps_single_column_row_major():
    # One text column plus narrow side figures: must stay top-to-bottom, not
    # "all text then all figures".
    boxes = [box(77, 14, 421, 46), box(50, 129, 314, 195),
             box(329, 109, 433, 155, "image"), box(50, 215, 314, 240)]
    order = dl.order_regions(boxes, 505, 630)
    ys = [round(b["bbox"][1]) for b in order]
    assert ys == sorted(ys), ys
    assert order[0]["bbox"][1] == 14


def test_engine_for_model():
    assert dl.engine_for_model("LightOnOCR-3-0.8B.Q4_K_M.gguf") == "lighton"
    assert dl.engine_for_model("/x/prithivMLmods/LightOnOCR-3-0.8B-GGUF/m.gguf") == "lighton"
    assert dl.engine_for_model("MiniCPM-OCR-1_0-Q8_0.gguf") == "layout"
    assert dl.engine_for_model("gpt-4o") == "layout"
    assert dl.engine_for_model("") == "layout"


def test_parse_pages_spec():
    assert dl._parse_pages_spec(None, 5) == [0, 1, 2, 3, 4]
    assert dl._parse_pages_spec("1-3", 5) == [0, 1, 2]
    assert dl._parse_pages_spec("2,4", 5) == [1, 3]
    assert dl._parse_pages_spec("9", 5) == []


def test_otsl_to_html():
    otsl = "<otsl><fcel>Time<fcel>Strain<nl><fcel>0.28<fcel>-0.7<nl></otsl>"
    html = dl.otsl_to_html(otsl)
    assert html == ("<table><tr><td>Time</td><td>Strain</td></tr>"
                    "<tr><td>0.28</td><td>-0.7</td></tr></table>"), html
    assert dl.otsl_to_html("<p>already html</p>") == "<p>already html</p>"


def test_contained_inline_formula_is_suppressed():
    dets = [box(50, 129, 314, 195, "text"),
            box(249, 155, 263, 172, "inline_formula"),
            box(400, 129, 460, 172, "inline_formula")]  # outside the text block
    out = dl._suppress_contained_inline(dets)
    labels = [d["label"] for d in out]
    assert labels.count("inline_formula") == 1, labels
    assert out[1]["bbox"][0] == 400  # the outside one survives


def test_unwrap_math_variants():
    assert dl._unwrap_math("\\[a\\]") == "a"
    assert dl._unwrap_math("$$b$$") == "b"
    assert dl._unwrap_math("\\(c\\)") == "c"
    assert dl._unwrap_math("plain") == "plain"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"{len(fns)} tests passed")
