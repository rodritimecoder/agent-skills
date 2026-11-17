#!/usr/bin/env python3
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple, Union


def _drive_root() -> Path:
    """The AI volume root: $AI_ROOT, else the nearest ancestor holding models/.

    Launchers and model weights live under it, so resolving from here beats
    pinning the one mount point this was written for.
    """
    env = os.environ.get("AI_ROOT")
    if env:
        return Path(env).expanduser()
    for parent in Path(__file__).resolve().parents:
        if (parent / "models").is_dir():
            return parent
    return Path("/run/media/rodri/AI")


AI_DIR = Path(os.environ.get("OCR_AI_DIR", _drive_root()))
LIGHTON_LAUNCHER = AI_DIR / "sh" / "lighton-ocr.sh"
LIGHTON_MODEL_DIR = AI_DIR / "models" / "prithivMLmods" / "LightOnOCR-3-0.8B-GGUF"


def lighton_start_command(ctl: Optional[str] = None) -> Optional[list]:
    """How to start the LightOn slot: through the rig, or the launcher as a fallback.

    The rig applies the VRAM budget and pinned-King rules; spawning the launcher
    directly skips both, so it is only the fallback for a host without the rig.
    """
    ctl = ctl or shutil.which("llama-rig") or shutil.which("vram-rig-ctl")
    if ctl:
        return [ctl, "up", "ocr"]
    if LIGHTON_LAUNCHER.is_file():
        return [str(LIGHTON_LAUNCHER)]
    return None

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


def clean_transcript(text: str) -> str:
    cleaned = re.sub(r"\n\nNote:.*$", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"\n\nExplanation:.*$", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


import ssl

class OCREngine:
    def __init__(
        self,
        lighton_port: int = 8082,
        host: Optional[str] = None,
        timeout: float = 60.0
    ):
        env_host = os.environ.get("OCR_HOST")
        self.host = host or env_host or "127.0.0.1"
        self.lighton_port = lighton_port
        self.timeout = timeout
        
        self.is_remote = self.host not in ("127.0.0.1", "localhost")
        self.scheme = "https" if (".ts.net" in self.host or os.environ.get("OCR_SCHEME") == "https") else "http"
        
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

        self.lighton_endpoint = f"{self.scheme}://{self.host}:{self.lighton_port}/v1/chat/completions"
        self.lighton_health = f"{self.scheme}://{self.host}:{self.lighton_port}/health"

    def is_lighton_online(self) -> bool:
        try:
            req = urllib.request.Request(self.lighton_health)
            ctx = self.ssl_ctx if self.scheme == "https" else None
            with urllib.request.urlopen(req, timeout=0.8, context=ctx) as resp:
                return resp.status == 200
        except Exception:
            return False

    def ensure_lighton(self, timeout: float = 12.0) -> bool:
        if self.is_lighton_online():
            return True
        cmd = lighton_start_command()
        if not cmd:
            return False
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_lighton_online():
                return True
            time.sleep(0.5)
        return False

    def ocr_image_lighton(self, img_bytes: bytes, prompt: Optional[str] = None) -> Tuple[str, float]:
        if not self.is_lighton_online():
            started = self.ensure_lighton()
            if not started:
                raise RuntimeError(f"LightOnOCR server not reachable on port {self.lighton_port} and auto-start failed.")

        b64 = base64.b64encode(img_bytes).decode("ascii")
        image_part = {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        if prompt == "grounding":
            content = [image_part, {"type": "text", "text": "grounding"}]
        else:
            user_prompt = prompt or "Transcribe all visible text in Markdown. Output only the verbatim text."
            content = [{"type": "text", "text": user_prompt}, image_part]
        payload = {
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 4096 if prompt == "grounding" else 2048,
            "temperature": 0.0
        }

        t0 = time.time()
        req = urllib.request.Request(
            self.lighton_endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        ctx = self.ssl_ctx if self.scheme == "https" else None
        with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        msg = data["choices"][0]["message"]
        raw_content = msg.get("content") or msg.get("reasoning_content") or ""
        cleaned = clean_transcript(raw_content)
        latency_ms = round((time.time() - t0) * 1000, 1)
        return cleaned, latency_ms

    def _page_images(
        self, p: Path, pages: Optional[str], scratch: Path
    ) -> Tuple[List[Path], int]:
        if p.suffix.lower() in IMAGE_EXTENSIONS:
            return [p], 1

        import pymupdf

        doc = pymupdf.open(p)
        total = len(doc)
        indices = list(range(total))
        if pages:
            selected: List[int] = []
            for part in pages.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = part.split("-", 1)
                    selected.extend(range(int(start) - 1, int(end)))
                elif part.isdigit():
                    selected.append(int(part) - 1)
            indices = [idx for idx in selected if 0 <= idx < total]

        mat = pymupdf.Matrix(2.0, 2.0)
        out: List[Path] = []
        for idx in indices:
            pix = doc[idx].get_pixmap(matrix=mat, alpha=False)
            target = scratch / f"page_{idx + 1:04d}.png"
            pix.save(str(target))
            out.append(target)
        doc.close()
        if not out:
            raise ValueError(f"No pages selected from {p.name}")
        return out, len(out)

    GROUNDED_RE = re.compile(r"!\[([A-Za-z_+]+)\]\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")

    @classmethod
    def parse_grounded(cls, text: str) -> List[Dict[str, Any]]:
        marks = list(cls.GROUNDED_RE.finditer(text))
        blocks: List[Dict[str, Any]] = []
        for i, match in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            blocks.append({
                "label": match.group(1),
                "bbox": [int(match.group(j)) for j in range(2, 6)],
                "content": text[match.end():end].strip(),
            })
        return blocks

    @staticmethod
    def _crop_grounded(src_png: Path, bbox: List[int], dest: Path) -> bool:
        import pymupdf

        page = pymupdf.open(str(src_png))[0]
        rect = page.rect
        pix = pymupdf.Pixmap(str(src_png))
        matrix = pymupdf.Matrix(pix.width / rect.width, pix.height / rect.height)
        x1, y1, x2, y2 = (max(0, min(1000, v)) for v in bbox)
        clip = pymupdf.Rect(rect.width * x1 / 1000, rect.height * y1 / 1000,
                            rect.width * x2 / 1000, rect.height * y2 / 1000)
        if clip.is_empty:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        page.get_pixmap(clip=clip, matrix=matrix).save(str(dest))
        return True

    def _render_grounded(
        self, raw: str, src_png: Path, assets_dir: Optional[Path], prefix: str
    ) -> Tuple[str, List[Dict[str, Any]]]:
        assets: List[Dict[str, Any]] = []
        parts: List[str] = []
        figure = 0
        for block in self.parse_grounded(raw):
            label = block["label"].rstrip("+")
            content = block["content"]
            if label in ("image", "header_image", "footer_image", "chart"):
                if assets_dir is None:
                    if content:
                        parts.append(content)
                    continue
                figure += 1
                name = f"{prefix}fig{figure}.png"
                dest = assets_dir / name
                if self._crop_grounded(src_png, block["bbox"], dest):
                    assets.append({
                        "file": name,
                        "path": str(dest.resolve()),
                        "bbox": block["bbox"],
                        "label": label,
                    })
                    parts.append(f"![]({dest.resolve()})")
                if content:
                    if label == "chart" and content.lstrip().startswith("<"):
                        parts.append(content)
                    elif label != "chart":
                        parts.append(content)
                continue
            if not content:
                continue
            if label == "title":
                parts.append("# " + content.lstrip("# ").strip())
            elif label == "caption":
                parts.append(f"*{content}*")
            else:
                parts.append(content)
        return "\n\n".join(parts), assets

    def ocr_document_lighton(
        self,
        file_path: Path,
        pages: Optional[str] = None,
        grounding: bool = False,
        assets_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not self.ensure_lighton():
            raise RuntimeError(f"LightOnOCR server not reachable on port {self.lighton_port}.")

        mode = "grounding" if (grounding or assets_dir is not None) else None
        scratch = Path(tempfile.mkdtemp(prefix="ocr-lighton-"))
        try:
            if p.suffix.lower() in IMAGE_EXTENSIONS:
                started = time.time()
                raw, _ = self.ocr_image_lighton(p.read_bytes(), prompt=mode)
                markdown, assets = self._render_grounded(raw, p, assets_dir, "")
                latency = round((time.time() - started) * 1000, 1)
                return {
                    "task": "document_ocr",
                    "engine": "lighton",
                    "mode": "grounding" if mode else "transcription",
                    "file": str(p),
                    "pages_count": 1,
                    "pages": [{"page": 1, "text": markdown}],
                    "text": markdown,
                    "markdown": markdown,
                    "assets": assets,
                    "latency_ms": latency,
                    "source": "lighton_grounding" if mode else "lighton_1b_server",
                }

            images, count = self._page_images(p, pages, scratch)
            started = time.time()
            page_docs = []
            all_assets: List[Dict[str, Any]] = []
            for idx, page_png in enumerate(images):
                raw, _ = self.ocr_image_lighton(page_png.read_bytes(), prompt=mode)
                prefix = f"p{idx + 1}_" if count > 1 else ""
                markdown, assets = self._render_grounded(raw, page_png, assets_dir, prefix)
                page_docs.append({"page": idx + 1, "text": markdown})
                all_assets.extend(assets)
            latency = round((time.time() - started) * 1000, 1)
            combined = "\n\n".join(f"<!-- Page {d['page']} -->\n{d['text']}" for d in page_docs)
            return {
                "task": "document_ocr",
                "engine": "lighton",
                "mode": "grounding" if mode else "transcription",
                "file": str(p),
                "pages_count": count,
                "pages": page_docs,
                "text": combined,
                "markdown": combined,
                "assets": all_assets,
                "latency_ms": latency,
                "source": "lighton_grounding" if mode else "lighton_1b_server",
            }
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def ocr_document(
        self,
        file_path: Path,
        prompt: Optional[str] = None,
        pages: Optional[str] = None
    ) -> Dict[str, Any]:
        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        suffix = p.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            content, ms = self.ocr_image_lighton(p.read_bytes(), prompt=prompt)
            return {
                "task": "document_ocr",
                "engine": "lighton",
                "file": str(p),
                "pages_count": 1,
                "text": content,
                "markdown": content,
                "latency_ms": ms,
                "source": "lighton_1b_server"
            }

        if suffix == ".pdf":
            try:
                import pymupdf
            except ImportError:
                # ocr.py re-execs under the skill venv, so this only fires when
                # someone imports the engine directly from a bare interpreter.
                raise RuntimeError(
                    "PyMuPDF is required for PDF OCR. Run `ocr` (which re-execs "
                    "into the skill venv) or install pymupdf into this interpreter."
                )

            doc = pymupdf.open(p)
            total_pages = len(doc)
            page_indices = list(range(total_pages))
            if pages:
                selected = []
                for part in pages.split(","):
                    part = part.strip()
                    if "-" in part:
                        start, end = part.split("-", 1)
                        selected.extend(range(int(start) - 1, int(end)))
                    elif part.isdigit():
                        selected.append(int(part) - 1)
                page_indices = [idx for idx in selected if 0 <= idx < total_pages]

            page_results = []
            total_ms = 0.0
            mat = pymupdf.Matrix(2.0, 2.0)
            for idx in page_indices:
                page_pix = doc[idx].get_pixmap(matrix=mat, alpha=False)
                png_bytes = page_pix.tobytes("png")
                page_text, page_ms = self.ocr_image_lighton(png_bytes, prompt=prompt)
                total_ms += page_ms
                page_results.append({
                    "page": idx + 1,
                    "text": page_text
                })
            doc.close()

            combined_md = "\n\n".join(f"<!-- Page {pr['page']} -->\n{pr['text']}" for pr in page_results)
            return {
                "task": "document_ocr",
                "engine": "lighton",
                "file": str(p),
                "pages_count": len(page_indices),
                "pages": page_results,
                "markdown": combined_md,
                "text": combined_md,
                "latency_ms": round(total_ms, 1),
                "source": "lighton_1b_server"
            }

        raise ValueError(f"Unsupported file format: {suffix}")
