#!/usr/bin/env python3
"""
ocr-cli - local OCR for PDFs, slides, and images via local vision models (LightOnOCR-3-0.8B).

Talks to any OpenAI-compatible /v1/chat/completions endpoint. The default
endpoint is a llama-server running LightOnOCR-3-0.8B on port 8085.

The server is NOT started by this script: `--doctor` and `--server-cmd` report
whether it is reachable and print the exact llama-server invocation to run.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> list[str]:
    """Minimal .env loader: KEY=VALUE lines, optional `export`, `#` comments.

    Real environment variables always win, so an inline export overrides the
    file without needing to edit it. Runs before any defaults below are
    computed, which is why the module-level constants see the result.
    """
    loaded: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return loaded
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, val = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key and key not in os.environ:
            os.environ[key] = val
            loaded.append(key)
    return loaded


# Accepted locations, in order; every one that exists is applied.
DOTENV_FILES = [SKILL_DIR / "scripts" / ".env", SKILL_DIR / ".env"]
DOTENV_LOADED = [k for f in DOTENV_FILES for k in _load_dotenv(f)]


def _bootstrap() -> None:
    """Re-exec into the skill's .venv if pymupdf isn't importable here."""
    try:
        import pymupdf  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    if os.environ.get("_NAVIDC_REEXEC") == "1":
        return
    py = SKILL_DIR / ".venv" / "bin" / "python"
    if py.exists():
        os.environ["_NAVIDC_REEXEC"] = "1"
        os.execv(str(py), [str(py), str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.exit(
        "ERROR: pymupdf is not installed.\n"
        f"  python3 -m venv {SKILL_DIR / '.venv'}\n"
        f"  {SKILL_DIR / '.venv' / 'bin' / 'pip'} install pymupdf requests tqdm"
    )


if __name__ == "__main__":
    _bootstrap()

import argparse  # noqa: E402

import pymupdf  # noqa: E402
import requests  # noqa: E402

# ── OCR Engine Defaults ───────────────────────────────────────────────────────

ENGINES = {
    "lighton": {
        "name": "LightOnOCR-3-0.8B",
        "port": 8085,
        "default_model_dir": "/run/media/rodri/AI/models/prithivMLmods/LightOnOCR-3-0.8B-GGUF",
        "description": "Ultra-fast document and video slide OCR (thinking variant). Best for video-miner.",
    },
    "navidc": {
        "name": "NaviDC-OCR",
        "port": 8082,
        "default_model_dir": "/run/media/rodri/AI/models/konradjr007/NaviDC-OCR-GGUF",
        "description": "Dense document and scanned PDF OCR.",
    },
    "crispembed": {
        "name": "CrispEmbed Scene Text",
        "port": 8084,
        "default_model_dir": "/run/media/rodri/AI/models/cstr",
        "description": "Scene-text OCR (DBNet + PARSeq).",
    },
    "smoldocling": {
        "name": "SmolDocling-256M",
        "port": 8084,
        "default_model_dir": "/run/media/rodri/AI/models/cstr/smoldocling-GGUF",
        "description": "Structured DocTags layout, tables, formulas, and document understanding.",
    }
}

DEFAULT_ENGINE = os.environ.get("OCR_ENGINE", "lighton")
port_str = os.environ.get("OCR_PORT") or os.environ.get("NAVIDC_OCR_PORT")
PORT = int(port_str) if port_str else ENGINES.get(DEFAULT_ENGINE, {}).get("port", 8085)
ACTIVE_PORT = PORT

host_str = os.environ.get("OCR_HOST") or os.environ.get("NAVIDC_OCR_HOST")
HOST = host_str if host_str else "127.0.0.1"

BASE = f"http://{HOST}:{PORT}"
ENDPOINT = os.environ.get("OCR_ENDPOINT") or os.environ.get("NAVIDC_OCR_ENDPOINT") or f"{BASE}/v1/chat/completions"
HEALTH = os.environ.get("OCR_HEALTH") or os.environ.get("NAVIDC_OCR_HEALTH") or f"{BASE}/health"

model_dir_str = os.environ.get("OCR_MODEL_DIR") or os.environ.get("NAVIDC_OCR_MODEL_DIR")
if model_dir_str:
    MODEL_DIR = Path(model_dir_str)
else:
    MODEL_DIR = Path(ENGINES.get(DEFAULT_ENGINE, {}).get("default_model_dir", "/run/media/rodri/AI/models/prithivMLmods/LightOnOCR-3-0.8B-GGUF"))

DEFAULT_PROMPT = "Extract all text faithfully, preserving layout, tables, and structure in Markdown."
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
PAGE_MARKER = "<!-- Page {n} -->"
TIMEOUT = 120


def find_model() -> tuple[Path | None, Path | None]:
    """Locate model weights and the multimodal projector, if present."""
    if not MODEL_DIR.exists():
        return None, None
    weights = next((p for p in sorted(MODEL_DIR.glob("*.gguf"))
                    if "mmproj" not in p.name.lower()), None)
    mmproj = next((p for p in sorted(MODEL_DIR.glob("*.gguf"))
                   if "mmproj" in p.name.lower()), None)
    return weights, mmproj


def find_server_bin() -> Path | None:
    """Locate a llama-server known to load these GGUFs.

    Stock llama.cpp CANNOT load NaviDC-OCR-GGUF: the model sets head_dim=128
    while hidden_size/num_heads is 64, so the loader rejects attn_q and
    attn_output. The patched Vulkan build is searched first for that reason;
    PATH is only a fallback and may well be unpatched.
    """
    override = os.environ.get("NAVIDC_OCR_SERVER")
    if override:
        return Path(override)
    for cand in (Path("/run/media/rodri/AI/llama.cpp/build/bin/llama-server"),
                 Path("/run/media/rodri/AI/sh/navidc-ocr.sh")):
        if cand.exists() and os.access(cand, os.X_OK):
            return cand
    import shutil
    which = shutil.which("llama-server")
    return Path(which) if which else None


def server_command() -> str:
    """The llama-server invocation this skill expects (not run automatically)."""
    weights, mmproj = find_model()
    if not weights or not mmproj:
        return (f"# Expected NaviDC weights in {MODEL_DIR} but found: "
                f"{sorted(p.name for p in MODEL_DIR.glob('*.gguf')) or 'nothing'}")
    exe = find_server_bin()
    exe_str = str(exe) if exe else "llama-server  # NOT FOUND - see --doctor"
    return (
        f"{exe_str} \\\n"
        f"  -m {weights} \\\n"
        f"  --mmproj {mmproj} \\\n"
        f"  --host {HOST} --port {PORT} -ngl 99 -c 8192 -np 2"
    )


# ── Server interaction ────────────────────────────────────────────────────────

def health_url(endpoint: str = ENDPOINT) -> str:
    """Derive the health URL from the endpoint, so --endpoint stays consistent."""
    override = os.environ.get("NAVIDC_OCR_HEALTH")
    if override:
        return override
    base = endpoint.split("/v1/")[0]
    return f"{base}/health"


def health_check(endpoint: str = ENDPOINT, timeout: float = 5.0) -> tuple[bool, str]:
    url = health_url(endpoint)
    try:
        r = requests.get(url, timeout=timeout)
        if r.ok:
            return True, r.text[:200]
        # Some builds have no /health; a 404 still proves something is listening.
        if r.status_code == 404:
            return True, "(no /health route; server is listening)"
        return False, f"HTTP {r.status_code}"
    except requests.RequestException as e:
        return False, str(e)


def ocr_image(img_bytes: bytes, endpoint: str, prompt: str,
              max_tokens: int, model: str | None, retries: int = 2) -> str:
    b64 = base64.b64encode(img_bytes).decode("ascii")
    payload: dict = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    if model:
        payload["model"] = model

    last = None
    for attempt in range(retries + 1):
        try:
            res = requests.post(endpoint, json=payload, timeout=TIMEOUT)
            res.raise_for_status()
            msg = res.json()["choices"][0]["message"]
            return msg.get("content") or msg.get("reasoning_content") or ""
        except Exception as e:                      # noqa: BLE001 - reported below
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"after {retries + 1} attempts: {last}")


def parse_pages(spec: str | None, total: int) -> list[int]:
    """'1-3,7' -> [0, 1, 2, 6], validated against the document length."""
    if not spec:
        return list(range(total))
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            pages.extend(range(int(a) - 1, int(b)))
        else:
            pages.append(int(part) - 1)
    bad = [p + 1 for p in pages if p < 0 or p >= total]
    if bad:
        raise SystemExit(f"page numbers out of range (document has {total}): {bad}")
    return sorted(set(pages))


# ── Document handling ─────────────────────────────────────────────────────────

def ocr_pdf(path: Path, ns) -> str:
    doc = pymupdf.open(path)
    try:
        indices = parse_pages(ns.pages, len(doc))
        scale = ns.dpi / 72
        mat = pymupdf.Matrix(scale, scale)
        images = {i: doc[i].get_pixmap(matrix=mat, alpha=False).tobytes("png") for i in indices}
    finally:
        doc.close()

    results: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=ns.workers) as pool:
        futures = {
            pool.submit(ocr_image, img, ns.endpoint, ns.prompt, ns.max_tokens, ns.model): i
            for i, img in images.items()
        }
        for done, fut in enumerate(as_completed(futures), start=1):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:                   # noqa: BLE001
                results[i] = f"[OCR FAILED: {e}]"
                print(f"page {i + 1} failed: {e}", file=sys.stderr)
            if ns.verbose:
                print(f"  page {done}/{len(indices)}", file=sys.stderr)
    return "\n\n".join(f"{PAGE_MARKER.format(n=i + 1)}\n{results[i].strip()}" for i in indices)


def ocr_image_file(path: Path, ns) -> str:
    return ocr_image(path.read_bytes(), ns.endpoint, ns.prompt, ns.max_tokens, ns.model).strip()


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_doctor(ns) -> int:
    url = health_url(ns.endpoint)
    ok, detail = health_check(ns.endpoint)
    print(f"server       {url}")
    print(f"  reachable  {'yes' if ok else 'NO'}  {detail}")
    weights, mmproj = find_model()
    print(f"model dir    {MODEL_DIR}")
    print(f"  weights    {weights.name if weights else 'not found'}")
    print(f"  mmproj     {mmproj.name if mmproj else 'not found'}")
    exe = find_server_bin()
    if exe:
        print(f"llama-server {exe}")
        if "llama.cpp" in str(exe):
            print("  patch      yes - NaviDC head_dim fix applied")
        else:
            print("  patch      UNVERIFIED - stock llama.cpp rejects these GGUFs")
    else:
        print("llama-server not found (set NAVIDC_OCR_SERVER or put it on PATH)")
    if DOTENV_LOADED:
        print(f"env file     loaded from .env: {', '.join(sorted(set(DOTENV_LOADED)))}")
    if not ok:
        print("\nStart it with:\n" + server_command())
    return 0 if ok else 1


def cmd_server_cmd(ns) -> int:
    print(server_command())
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="ocr.py",
        description="OCR PDFs, slides, and images with local vision models (LightOnOCR-3-0.8B / SmolDocling / CrispEmbed).",
    )
    p.add_argument("file", nargs="?", help="PDF or image to OCR")
    p.add_argument("-p", "--prompt", default=DEFAULT_PROMPT, help="extraction prompt")
    p.add_argument("--pages", help="page selection for PDFs, e.g. 1-3,7 (default: all)")
    p.add_argument("--dpi", type=int, default=200, help="rasterisation DPI (default: 200)")
    p.add_argument("--workers", type=int, default=2, help="parallel page requests (default: 2)")
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument("--model", default=os.environ.get("OCR_MODEL") or os.environ.get("NAVIDC_OCR_MODEL"),
                   help="model name to send (llama-server usually ignores this)")
    p.add_argument("--endpoint", default=ENDPOINT, help=f"default: {ENDPOINT}")
    p.add_argument("-o", "--output", help="write here instead of stdout")
    p.add_argument("--tree", action="store_true",
                   help="post-process the transcription into a Markdown nested "
                        "list (for directory-tree / ASCII-art listings). "
                        "Done client-side; see scripts/tree_to_md.py.")
    p.add_argument("--tree-prompt", default=DEFAULT_PROMPT,
                   help="prompt to use with --tree (default: plain extraction)")
    p.add_argument("--doctor", action="store_true", help="check the server and model files")
    p.add_argument("--server-cmd", action="store_true", help="print the llama-server command")
    p.add_argument("-v", "--verbose", action="store_true")
    ns = p.parse_args()

    if ns.server_cmd:
        return cmd_server_cmd(ns)
    if ns.doctor:
        return cmd_doctor(ns)
    if not ns.file:
        p.error("no input file (or use --doctor / --server-cmd)")

    path = Path(ns.file).expanduser()
    if not path.exists():
        sys.exit(f"no such file: {path}")

    ok, detail = health_check(ns.endpoint)
    if not ok:
        sys.exit(
            f"OCR server not reachable at {health_url(ns.endpoint)} ({detail}).\n"
            f"Check it with: {Path(__file__).name} --doctor\n"
            f"Or start it with:\n{server_command()}"
        )

    ext = path.suffix.lower()
    if ns.tree:
        # NaviDC ignores formatting instructions, so use a plain extraction
        # prompt and do the Markdown conversion ourselves afterwards.
        ns.prompt = ns.tree_prompt
    if ext == ".pdf":
        text = ocr_pdf(path, ns)
    elif ext in IMAGE_EXTS:
        text = ocr_image_file(path, ns)
    else:
        sys.exit(f"unsupported input '{ext}'. Expected .pdf or one of: "
                 + ", ".join(sorted(IMAGE_EXTS)))

    if ns.tree:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from tree_to_md import to_markdown
        except ImportError:
            sys.exit("--tree needs scripts/tree_to_md.py next to this script")
        text = to_markdown(text)

    if ns.output:
        out = Path(ns.output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
