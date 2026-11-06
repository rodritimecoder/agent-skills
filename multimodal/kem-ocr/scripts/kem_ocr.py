#!/usr/bin/env python3
"""kem-ocr — Kem-pipeline OCR with Jev verification (lego-block stages).

Stages (each writes step_NN.json — resumable, auditable):
  01_acquire  load + hash the input image
  02_parse    MiniCPM-OCR-1.0 transcription (Text/Table/Formula prompt)
              + structural assertions (code gate, runs before Jev)
  03_render   render the candidate back into an image (chromium + KaTeX/HTML)
  04_verify   MiniCPM-OCR-Jev /v1/systemone -> P(consistent) + verdict
  05_holdout  corrupted candidate MUST be rejected (proves the gate can fail)
  06_decide   accept / reject / escalate (code, not model)
  07_emit     final.md + verification.json sidecar

Usage:
  kem-ocr page.png                       # text mode, full pipeline
  kem-ocr crop.png --type formula        # formula mode
  kem-ocr crop.png --type table          # table mode
  kem-ocr page.png --candidate "..."     # verify a known transcription
  kem-ocr page.png --no-holdout          # skip the negative control (not recommended)
  kem-ocr page.png --json                # machine-readable verdict on stdout (Code Mode)

Requires: llama-mtmd-cli (1.0), sh/minicpm-ocr-jev.sh running on :8090.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

DEFAULT_OCR_CLI = os.environ.get("KEM_OCR_CLI", "/run/media/rodri/AI/llama.cpp/build-vulkan/bin/llama-mtmd-cli")
DEFAULT_OCR_MODEL = os.environ.get("KEM_OCR_MODEL", "/run/media/rodri/AI/models/openbmb/MiniCPM-OCR-1.0-gguf/MiniCPM-OCR-1_0-Q8_0.gguf")
DEFAULT_OCR_MMPROJ = os.environ.get("KEM_OCR_MMPROJ", "/run/media/rodri/AI/models/openbmb/MiniCPM-OCR-1.0-gguf/mmproj-model-f16-4x.gguf")
DEFAULT_JEV_URL = os.environ.get("KEM_OCR_JEV_URL", "http://127.0.0.1:8090")
RENDER_JS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "render.js")

PROMPTS = {"text": "Text Recognition:", "table": "Table Recognition:", "formula": "Formula Recognition:"}

ACCEPT = 0.5
REJECT = 0.3

MIN_ALNUM = {"text": 4, "table": 1, "formula": 1}

LATEX_MARKERS = re.compile(
    r"\\(?:frac|sqrt|sum|prod|int|lim|partial|alpha|beta|gamma|delta|theta|lambda|mu|pi|sigma|phi|omega|"
    r"cdot|times|div|leq|geq|neq|approx|infty|begin|end|left|right|text|mathrm|mathcal|vec|hat|bar)\b"
    r"|\^\{|_\{|\^[0-9A-Za-z]|_[0-9A-Za-z]"
)



JSON_MODE = False


def log(msg, **kw):
    """Human-readable progress: stdout normally, stderr under --json."""
    print(msg, file=sys.stderr if JSON_MODE else sys.stdout, **kw)


def fmt_prob(p):
    return "None" if p is None else f"{p:.5f}"


def fmt_conf(p):
    return "None" if p is None else f"{p:.4f}"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def data_url(p):
    return "data:image/png;base64," + base64.b64encode(Path(p).read_bytes()).decode()


def stage(outdir, n, name, data):
    p = Path(outdir) / f"step_{n:02d}_{name}.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    if JSON_MODE:
        print(f"kem-ocr: step_{n:02d}_{name}.json", file=sys.stderr)
    return p


def jev_health(url):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=3) as r:
            return json.loads(r.read()).get("status") == "ok"
    except Exception:
        return False


def acquire(image_path, outdir):
    p = Path(image_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(p)
    out = Path(outdir) / "01_acquire"
    out.mkdir(parents=True, exist_ok=True)
    import shutil
    dst = out / p.name
    if dst.resolve() != p:
        shutil.copy2(p, dst)
    img = Image.open(dst)
    data = {
        "stage": "acquire",
        "source": str(p),
        "stored": str(dst),
        "sha256": sha256_file(dst),
        "size": list(img.size),
        "mode": img.mode,
    }
    stage(outdir, 1, "acquire", data)
    return dst, data


def parse(image_path, block_type, outdir, ocr_cli, ocr_model, ocr_mmproj):
    out = Path(outdir) / "02_parse"
    out.mkdir(parents=True, exist_ok=True)
    prompt = PROMPTS[block_type]
    cmd = [ocr_cli, "-m", ocr_model, "--mmproj", ocr_mmproj,
           "--image", str(image_path), "-p", prompt, "--jinja",
           "-ngl", "99", "-c", "8192", "--temp", "0", "-n", "2048"]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    latency = round((time.time() - t0) * 1000)
    if proc.returncode != 0:
        raise RuntimeError(f"ocr parse failed (rc={proc.returncode}):\n{proc.stderr[-500:]}")
    candidate = proc.stdout.strip()
    data = {
        "stage": "parse",
        "block_type": block_type,
        "prompt": prompt,
        "candidate": candidate,
        "latency_ms": latency,
        "stderr_tail": proc.stderr.strip().splitlines()[-3:],
    }
    stage(outdir, 2, "parse", data)
    return candidate, data


def assert_structure(candidate, block_type):
    text = candidate.strip()
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("non_empty", bool(text), f"{len(text)} chars")
    if not text:
        return {"ok": False, "checks": checks, "failed": ["non_empty"]}

    alnum = sum(ch.isalnum() for ch in text)
    add("alnum_floor", alnum >= MIN_ALNUM[block_type], f"{alnum} alnum chars")

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    top = max((lines.count(ln) for ln in set(lines)), default=0)
    add("no_line_loop", not (len(lines) >= 4 and top / len(lines) >= 0.75),
        f"{len(lines)} lines, most repeated x{top}")

    longest = max(len(m.group(0)) for m in re.finditer(r"([^\n])\1*", text))
    add("no_char_flood", longest / len(text) <= 0.5, f"longest run {longest}/{len(text)}")

    if block_type == "table":
        low = text.lower()
        pipe_rows = sum(1 for ln in lines if ln.count("|") >= 2)
        add("table_structure", "<table" in low or "<otsl" in low or pipe_rows >= 2,
            f"html={'<table' in low} otsl={'<otsl' in low} pipe_rows={pipe_rows}")
    elif block_type == "formula":
        add("latex_marker", bool(LATEX_MARKERS.search(text)) or "=" in text,
            "tex command, sub/superscript, or relation")

    failed = [c["check"] for c in checks if not c["ok"]]
    return {"ok": not failed, "checks": checks, "failed": failed}



def otsl_to_html(s):
    s = s.replace("<otsl>", "").replace("</otsl>", "")
    rows = [r for r in s.split("<nl>") if r.strip()]
    html = ["<table border='1' cellpadding='6' style='border-collapse:collapse;font-size:18px'>"]
    for row in rows:
        parts = re.split(r'(<fcel>|<ucel>|<ecel>)', row)
        cells = []
        i = 1
        while i < len(parts):
            tok = parts[i]
            content = parts[i + 1].strip() if i + 1 < len(parts) else ""
            if tok in ("<fcel>", "<ucel>", "<ecel>"):
                cells.append(f"<td>{content}</td>")
            i += 2
        if cells:
            html.append("<tr>" + "".join(cells) + "</tr>")
    html.append("</table>")
    return "\n".join(html)


def render_spec(candidate, block_type):
    if block_type == "formula":
        return "formula", candidate.strip()
    if block_type == "table":
        if "<table" in candidate.lower():
            return "html", candidate
        if "<otsl" in candidate.lower():
            return "html", otsl_to_html(candidate)
        return "text", candidate
    return "text", candidate


def render(candidate, block_type, outdir, orig_width=None, scale=None):
    out = Path(outdir) / "03_render"
    out.mkdir(parents=True, exist_ok=True)
    mode, text = render_spec(candidate, block_type)
    dst = out / "render.png"
    w = orig_width or 900
    sc = scale if scale is not None else (3.0 if block_type == "formula" else 1.0)
    spec = {"mode": mode, "text": text, "out": str(dst), "width": w, "scale": sc}
    t0 = time.time()
    proc = subprocess.run(["node", RENDER_JS], input=json.dumps(spec), capture_output=True, text=True, timeout=120)
    latency = round((time.time() - t0) * 1000)
    if proc.returncode != 0:
        raise RuntimeError(f"render failed: {proc.stderr[-300:]}")
    res = json.loads(proc.stdout.strip())
    if not res.get("ok"):
        raise RuntimeError(f"render error: {res.get('error')}")
    # trim trailing whitespace rows
    img = Image.open(dst).convert("RGB")
    gray = img.convert("L")
    mask = gray.point(lambda x: 255 if x < 200 else 0)
    bbox = mask.getbbox()
    if bbox:
        # pad a little
        x0, y0, x1, y1 = bbox
        pad = 16
        x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
        x1 = min(img.width, x1 + pad); y1 = min(img.height, y1 + pad)
        img.crop((x0, y0, x1, y1)).save(dst)
    data = {
        "stage": "render",
        "mode": mode,
        "renderer": "chromium" + ("+katex" if mode == "formula" else ""),
        "render_path": str(dst),
        "size": list(Image.open(dst).size),
        "latency_ms": latency,
    }
    stage(outdir, 3, "render", data)
    return dst, data


def verify(original, render_path, candidate, jev_url, outdir):
    out = Path(outdir) / "04_verify"
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": candidate,
        "images": [data_url(original), data_url(render_path)],
        "questions": {"q": {"type": "choice", "criteria": {"0": None, "1": None}}},
    }
    t0 = time.time()
    req = urllib.request.Request(jev_url.rstrip("/") + "/v1/systemone",
                                data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"jev http {e.code}: {e.read().decode()[:300]}")
    latency = round((time.time() - t0) * 1000)
    a = resp["answers"]["q"]
    prob = a["probabilities"]["1"]
    verdict = "scored" if prob is not None else "unscored"
    data = {
        "stage": "verify",
        "jev_url": jev_url,
        "choice": a["choice"],
        "probabilities": a["probabilities"],
        "confidence": a["confidence"],
        "prob_consistent": prob,
        "verdict": verdict,
        "latency_ms": latency,
        "input_tokens": resp.get("usage", {}).get("input_tokens"),
    }
    stage(outdir, 4, "verify", data)
    return data


def corrupt(text):
    out = []
    changed = False
    for ch in text:
        if not changed and ch.isdigit():
            out.append(str((int(ch) + 1) % 10)); changed = True
        else:
            out.append(ch)
    text = "".join(out)
    m = re.search(r"[A-Za-z]{4,}", text)
    if m:
        i = m.end() - 1
        text = text[:i] + "z" + text[i + 1:]
    # ensure it actually differs
    return text if text != text else text + " [corrupted]"


def holdout(original, candidate, block_type, outdir, jev_url, orig_width=None):
    out = Path(outdir) / "05_holdout"
    out.mkdir(parents=True, exist_ok=True)
    bad = corrupt(candidate)
    bad_render, _ = render(bad, block_type, outdir + "/_hr", jev_url) if False else (None, None)
    # render into a separate subdir to avoid clobbering
    hr_dir = Path(outdir) / "05_holdout" / "render"
    hr_dir.mkdir(parents=True, exist_ok=True)
    mode, text = render_spec(bad, block_type)
    dst = hr_dir / "holdout_render.png"
    w = orig_width or 900
    sc = 3.0 if block_type == "formula" else 1.0
    spec = {"mode": mode, "text": text, "out": str(dst), "width": w, "scale": sc}
    subprocess.run(["node", RENDER_JS], input=json.dumps(spec), capture_output=True, text=True, timeout=120)
    img = Image.open(dst).convert("RGB")
    gray = img.convert("L")
    mask = gray.point(lambda x: 255 if x < 200 else 0)
    bbox = mask.getbbox()
    if bbox:
        x0, y0, x1, y1 = bbox
        pad = 16
        x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
        x1 = min(img.width, x1 + pad); y1 = min(img.height, y1 + pad)
        img.crop((x0, y0, x1, y1)).save(dst)
    res = verify(original, dst, bad, jev_url, str(out))
    data = {
        "stage": "holdout",
        "original_candidate": candidate,
        "corrupted_candidate": bad,
        "holdout_render": str(dst),
        "prob_consistent": res["prob_consistent"],
        "verdict": res["verdict"],
        "accepted": res["prob_consistent"] is not None and res["prob_consistent"] >= ACCEPT,
        "gate_ok": not (res["prob_consistent"] is not None and res["prob_consistent"] >= ACCEPT),
    }
    # write holdout result as step_05
    stage(outdir, 5, "holdout", data)
    return data


def decide(v, h):
    prob = v["prob_consistent"]
    verdict = v["verdict"]
    if h is not None and h.get("accepted"):
        return "INVALID", "holdout was accepted — gate cannot fail, run is invalid"
    if verdict != "scored" or prob is None:
        return "UNSCORED", "Jev did not score this candidate; not accepted"
    if prob >= ACCEPT:
        return "ACCEPT", f"prob {prob:.4f} >= {ACCEPT}"
    if prob < 0.001:
        return "REJECT", f"prob {prob:.4f} < 0.001 (clearly wrong)"
    return "ESCALATE", f"prob {prob:.4f} in [0.001, {ACCEPT}) — route to human (normal for tables)"


def emit(outdir, image_path, block_type, candidate, render_path, v, h, decision, reason):
    out = Path(outdir) / "06_emit"
    out.mkdir(parents=True, exist_ok=True)
    final_md = out / "final.md"
    final_md.write_text(candidate + "\n")
    sidecar = {
        "stage": "emit",
        "image": str(image_path),
        "block_type": block_type,
        "candidate": candidate,
        "render": str(render_path),
        "verification": v,
        "holdout": h,
        "decision": decision,
        "reason": reason,
        "thresholds": {"accept": ACCEPT, "reject": REJECT},
    }
    stage(outdir, 7, "emit", sidecar)
    (out / "verification.json").write_text(json.dumps(sidecar, indent=2, ensure_ascii=False))
    return final_md, out / "verification.json"


def main():
    global JSON_MODE
    ap = argparse.ArgumentParser(description="kem-ocr: Kem-pipeline OCR with Jev verification")
    ap.add_argument("image", help="input image (png/jpg/pdf-page)")
    ap.add_argument("--type", choices=["text", "table", "formula"], default="text", help="block type (default: text)")
    ap.add_argument("--candidate", help="verify a known transcription instead of running OCR")
    ap.add_argument("--candidates", help="JSON file with an array of candidate strings (best-of-N mode)")
    ap.add_argument("--out", help="output directory (default: ./kem-ocr-out/<timestamp>)")
    ap.add_argument("--no-holdout", action="store_true", help="skip the negative control (not recommended)")
    ap.add_argument("--json", action="store_true", help="output clean JSON result on stdout")
    ap.add_argument("--jev-url", type=str, default=DEFAULT_JEV_URL)
    ap.add_argument("--ocr-cli", type=str, default=DEFAULT_OCR_CLI)
    ap.add_argument("--ocr-model", type=str, default=DEFAULT_OCR_MODEL)
    ap.add_argument("--ocr-mmproj", type=str, default=DEFAULT_OCR_MMPROJ)
    args = ap.parse_args()
    JSON_MODE = args.json

    if args.out:
        outdir = args.out
    else:
        outdir = f"./kem-ocr-out/{time.strftime('%Y%m%d-%H%M%S')}"
    Path(outdir).mkdir(parents=True, exist_ok=True)

    # 0. Jev liveness
    if not jev_health(args.jev_url):
        print(f"ERROR: Jev server not healthy at {args.jev_url}", file=sys.stderr)
        print(f"  start it with: /run/media/rodri/AI/sh/minicpm-ocr-jev.sh", file=sys.stderr)
        sys.exit(2)

    image_path, _ = acquire(args.image, outdir)
    orig_w = Image.open(image_path).width

    # determine candidate list
    if args.candidates:
        cands = json.loads(Path(args.candidates).read_text())
        if not isinstance(cands, list) or not cands:
            raise SystemExit("--candidates must be a non-empty JSON array of strings")
        source = "provided"
    elif args.candidate is not None:
        cands = [args.candidate]
        source = "provided"
    else:
        cand, _ = parse(image_path, args.type, outdir, args.ocr_cli, args.ocr_model, args.ocr_mmproj)
        cands = [cand]
        source = "ocr"

    # 02 parse (record) — structural assertions run here, before any model gate
    structural = [assert_structure(c, args.type) for c in cands]
    stage(outdir, 2, "parse", {"stage": "parse", "block_type": args.type, "candidates": cands,
                               "source": source, "count": len(cands), "structural": structural})

    keep = [i for i, s in enumerate(structural) if s["ok"]]
    if not keep:
        reason = "structural gate: " + "; ".join(
            f"#{i} {'+'.join(s['failed'])}" for i, s in enumerate(structural))
        stage(outdir, 6, "decide", {"stage": "decide", "decision": "REJECT", "reason": reason,
                                    "best_index": None, "num_candidates": len(cands),
                                    "gate": "structural", "structural": structural})
        if JSON_MODE:
            print(json.dumps({"stage": "emit", "decision": "REJECT", "reason": reason,
                              "best_index": None, "prob": None, "confidence": None,
                              "final_md": "", "sidecar": ""}))
        else:
            log(f"kem-ocr: REJECT — {reason}")
            log("  rejected before Jev: no model call spent on empty or malformed output")
        sys.exit(1)

    # 03+04: render + verify each surviving candidate (lego blocks, composable)
    results = []
    for i in keep:
        cand = cands[i]
        sub = Path(outdir) / f"candidate_{i:02d}"
        sub.mkdir(parents=True, exist_ok=True)
        rpath, _ = render(cand, args.type, str(sub), orig_width=orig_w)
        v = verify(image_path, rpath, cand, args.jev_url, str(sub))
        results.append({"index": i, "candidate": cand, "render": str(rpath), "verify": v,
                        "prob": v["prob_consistent"], "structure": structural[i]})


    # pick best
    best = max(results, key=lambda r: (r["prob"] is not None, r["prob"] or -1))
    best_idx = best["index"]
    candidate = best["candidate"]
    render_path = Path(best["render"])
    v = best["verify"]

    # 05 holdout on the best
    h = None
    if not args.no_holdout:
        h = holdout(image_path, candidate, args.type, outdir, args.jev_url, orig_width=orig_w)

    # 06 decide
    decision, reason = decide(v, h)
    stage(outdir, 6, "decide", {"stage": "decide", "decision": decision, "reason": reason,
                                "best_index": best_idx, "num_candidates": len(cands)})

    # 07 emit
    final_md, sidecar = emit(outdir, image_path, args.type, candidate, render_path, v, h, decision, reason)
    # enrich sidecar with all candidates
    sidecar_data = json.loads(Path(sidecar).read_text())
    sidecar_data["structural"] = structural[best_idx]
    sidecar_data["best_of_n"] = [{"index": r["index"], "prob": r["prob"],
                                  "candidate": r["candidate"][:200]} for r in results]
    Path(sidecar).write_text(json.dumps(sidecar_data, indent=2, ensure_ascii=False))

    # stdout summary
    if JSON_MODE:
        print(json.dumps({
            "stage": "emit",
            "decision": decision,
            "reason": reason,
            "best_index": best_idx,
            "prob": v["prob_consistent"],
            "confidence": v["confidence"],
            "final_md": str(final_md),
            "sidecar": str(sidecar),
        }))
    else:
        log(f"kem-ocr: {decision} — {reason}")
        log(f"  best candidate #{best_idx} of {len(cands)}: prob={fmt_prob(v['prob_consistent'])} conf={fmt_conf(v['confidence'])}")
        if len(cands) > 1:
            for r in results:
                mark = " *" if r["index"] == best_idx else "  "
                log(f"   {mark} #{r['index']}: prob={fmt_prob(r['prob'])}  {r['candidate'][:60].replace(chr(10),' ')}")
        log(f"  candidate: {candidate[:120].replace(chr(10), ' ')}{'...' if len(candidate) > 120 else ''}")
        if h is not None:
            log(f"  holdout: prob={fmt_prob(h['prob_consistent'])}  gate_ok={h['gate_ok']}")
        log(f"  final:     {final_md}")
        log(f"  sidecar:   {sidecar}")
        log(f"  stages:    {outdir}/step_*.json")

    if decision == "INVALID":
        sys.exit(3)
    if decision == "REJECT":
        sys.exit(1)


if __name__ == "__main__":
    main()
