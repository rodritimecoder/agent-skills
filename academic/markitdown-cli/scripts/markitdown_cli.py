#!/usr/bin/env python3
"""
markitdown-cli - convert documents to Markdown via Microsoft's MarkItDown.

Runs against a virtualenv that already has markitdown installed, preferring
`~/.venvs/markitdown-cli` over a skill-local `.venv/` (ephemeral venvs do not
belong on the model volume). This script re-execs itself into the first
interpreter that can actually import markitdown, so plain
`python3 markitdown_cli.py ...` works regardless of environment.

OCR / image description uses any OpenAI-compatible *vision* endpoint, including
one you host locally (Ollama, llama.cpp, LM Studio, vLLM). No system packages
such as tesseract are required.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def _imports_markitdown(python: Path) -> bool:
    """Is this interpreter actually usable, not merely present?"""
    try:
        return subprocess.run([str(python), "-c", "import markitdown"],
                              capture_output=True, timeout=120).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _bootstrap() -> None:
    """Re-exec into a venv that has markitdown, if this environment does not.

    Only when run as a script: importing this module (e.g. from the test
    suite) must not re-exec and hijack the caller's argv.
    """
    try:
        import markitdown  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    if os.environ.get("_MARKITDOWN_CLI_REEXEC") == "1":
        return
    # A venv that exists but lacks the package would re-exec into a dead end,
    # so probe each candidate instead of taking the first that exists. The
    # ext4 venv is preferred: the model volume is not for ephemeral venvs.
    candidates = (
        Path.home() / ".venvs" / SKILL_DIR.name / "bin" / "python",
        SKILL_DIR / ".venv" / "bin" / "python",
    )
    py = next((c for c in candidates if c.is_file() and _imports_markitdown(c)), None)
    if py is not None:
        os.environ["_MARKITDOWN_CLI_REEXEC"] = "1"
        os.execv(str(py), [str(py), str(Path(__file__).resolve()), *sys.argv[1:]])
    ext4 = Path.home() / ".venvs" / SKILL_DIR.name
    sys.exit(
        f"ERROR: markitdown is not installed.\n"
        f"Create the skill's virtualenv once (on ext4, not the model volume):\n"
        f"  python3 -m venv {ext4}\n"
        f"  {ext4 / 'bin' / 'pip'} install 'markitdown[all]'\n"
        f"or install it into your active environment with: pip install 'markitdown[all]'"
    )


if __name__ == "__main__":
    _bootstrap()

import argparse  # noqa: E402
import tempfile  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

from markitdown import MarkItDown, __version__ as MD_VERSION  # noqa: E402


# ── Config ────────────────────────────────────────────────────────────────────

def load_env() -> None:
    """Load KEY=VALUE pairs from .env in the skill dir (existing vars win)."""
    env_file = SKILL_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()

# Local-first defaults: a vision model served on your own machine.
DEFAULT_OCR_BASE_URL = "http://localhost:11434/v1"   # Ollama's default
DEFAULT_OCR_MODEL = "llava"
OCR_PROMPT = (
    "Transcribe all text in this image verbatim. Preserve reading order, "
    "paragraph breaks, and table structure. Output only the transcription, "
    "with no commentary."
)

# Extensions the library detects by content rather than by name. The xls/xlsx
# converters declare no ACCEPTED_FILE_EXTENSIONS, so they never show up in
# introspection, yet they are among the most common inputs.
SNIFFED_EXTENSIONS = {".xls", ".xlsx", ".tsv", ".xml", ".yaml", ".yml"}

# Fallback only, if the converters can't be introspected.
FALLBACK_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".html", ".htm", ".csv", ".tsv",
    ".json", ".jsonl", ".xml", ".yaml", ".yml", ".txt", ".md", ".epub",
    ".zip", ".msg", ".ipynb", ".png", ".jpg", ".jpeg", ".mp3", ".wav", ".m4a",
}


def supported_extensions(md: MarkItDown) -> set:
    """Ask markitdown which extensions its registered converters accept."""
    exts: set = set(SNIFFED_EXTENSIONS)
    try:
        import importlib
        for reg in md._converters:
            mod = importlib.import_module(type(reg.converter).__module__)
            exts.update(getattr(mod, "ACCEPTED_FILE_EXTENSIONS", set()) or set())
    except Exception:
        return set(FALLBACK_EXTENSIONS)
    return exts or set(FALLBACK_EXTENSIONS)


# ── Client / engine construction ──────────────────────────────────────────────

def build_client(kind: str, api_key: str | None, base_url: str | None):
    if kind == "anthropic":
        from anthropic import Anthropic
        return Anthropic(api_key=api_key or "local")
    if kind == "azure":
        from openai import AzureOpenAI
        return AzureOpenAI(api_key=api_key, azure_endpoint=base_url, api_version="2024-02-01")
    from openai import OpenAI
    # Local servers usually ignore the key, but the SDK requires one to be set.
    return OpenAI(api_key=api_key or "local", base_url=base_url or None)


def build_markitdown(ns) -> MarkItDown:
    kwargs: dict = {}
    if ns.ocr or (ns.llm_client and ns.llm_model):
        kwargs["llm_client"] = build_client(
            ns.ocr_client or ns.llm_client, ns.llm_api_key, ns.ocr_base_url or ns.llm_base_url
        )
        kwargs["llm_model"] = ns.ocr_model if ns.ocr else ns.llm_model
        if ns.llm_prompt:
            kwargs["llm_prompt"] = ns.llm_prompt
        elif ns.ocr:
            kwargs["llm_prompt"] = OCR_PROMPT
    return MarkItDown(**kwargs)


def probe_endpoint(base_url: str, model: str) -> str:
    """Ask a local server what it is serving, so OCR misconfig is obvious."""
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer local"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        names = [m.get("id") for m in data.get("data", [])]
        hit = f" (serves: {', '.join(n for n in names if n)[:200]})" if names else ""
        return f"  reachable: {url}{hit}"
    except urllib.error.HTTPError as e:
        return f"  HTTP {e.code} from {url} - is the server running and is {base_url} the right base URL?"
    except Exception as e:
        return f"  could not reach {url} ({type(e).__name__}: {e}) - start it, e.g. `ollama serve`"


# ── Output ────────────────────────────────────────────────────────────────────

def yaml_quote(value: str) -> str:
    """Quote a YAML scalar so titles containing : or # stay valid."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def with_frontmatter(content: str, title: str | None) -> str:
    if not title:
        return content
    return f"---\ntitle: {yaml_quote(title)}\n---\n\n{content}"


def write_output(content: str, target: Path | None) -> None:
    if target is None:
        print(content)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# ── Input collection ──────────────────────────────────────────────────────────

def collect_inputs(ns, md: MarkItDown) -> tuple[list, list]:
    """Return (convertible files, skipped paths)."""
    exts = supported_extensions(md)
    chosen, skipped = [], []

    def consider(p: Path) -> None:
        if not p.is_file():
            return
        (chosen if p.suffix.lower() in exts else skipped).append(p)

    for raw in ns.inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            walker = path.rglob("*") if ns.recursive else path.iterdir()
            for item in walker:
                consider(item)
        else:
            if path.exists():
                consider(path)
            else:
                skipped.append(path)
    return chosen, skipped


def output_target(input_path: Path, out_path: Path | None, ns, base: Path | None) -> Path | None:
    """Resolve where one input's Markdown should be written."""
    if out_path is None:
        return None                      # stdout
    if ns.output_is_file:
        return out_path                  # single input, explicit -o name.md
    rel = input_path.relative_to(base) if base else Path(input_path.name)
    return out_path / rel.parent / (rel.stem + ".md")


def disambiguate(target: Path, claimed: set) -> Path:
    """Two inputs like a.pdf and a.docx would both want a.md; keep both."""
    if target not in claimed:
        return target
    i = 2
    while (alt := target.with_name(f"{target.stem}-{i}{target.suffix}")) in claimed:
        i += 1
    return alt


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_list_formats(md: MarkItDown) -> None:
    print(f"markitdown {MD_VERSION} — supported inputs\n")
    for reg in md._converters:
        import importlib
        name = type(reg.converter).__name__.replace("Converter", "")
        try:
            mod = importlib.import_module(type(reg.converter).__module__)
            exts = sorted(getattr(mod, "ACCEPTED_FILE_EXTENSIONS", set()) or [])
        except Exception:
            exts = []
        shown = ", ".join(e.lstrip(".") for e in exts) if exts else "URL-based / sniffed by content"
        print(f"  {name:12} {shown}")
    print("\nOptional extras")
    print("  exiftool  `apt install libimage-exiftool-perl`  richer image metadata")
    print("  vision    any OpenAI-compatible endpoint for OCR (--ocr)")
    print("\nNote: legacy binary .doc/.ppt are NOT converted; rename to .docx/.pptx first.")


def cmd_doctor(ns, md: MarkItDown) -> None:
    print(f"python        {sys.version.split()[0]}  ({sys.executable})")
    print(f"markitdown    {MD_VERSION}")
    print(f"exts          {len(supported_extensions(md))} recognised input extensions")
    import shutil
    print(f"exiftool      {shutil.which('exiftool') or 'not installed (image metadata will be sparse)'}")
    if ns.ocr or ns.llm_model:
        base = ns.ocr_base_url or ns.llm_base_url or DEFAULT_OCR_BASE_URL
        model = ns.ocr_model if ns.ocr else ns.llm_model
        print(f"vision model  {model}")
        print(probe_endpoint(base, model))
    else:
        print("vision model  disabled (pass --ocr to enable local OCR)")


def render_table(rows: list[dict], columns: list[str], headers: list[str] | None = None) -> str:
    if not rows:
        return "*(no records)*\n"
    if headers is None:
        headers = [col.replace("_", " ").title() for col in columns]
    col_widths = [len(h) for h in headers]
    for r in rows:
        for idx, col in enumerate(columns):
            val_str = str(r.get(col, "")).replace("\n", " ")
            if len(val_str) > col_widths[idx]:
                col_widths[idx] = len(val_str)
    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * col_widths[i] for i in range(len(headers))) + " |"
    row_lines = []
    for r in rows:
        row_str = "| " + " | ".join(str(r.get(col, "")).replace("\n", " ").ljust(col_widths[i]) for i, col in enumerate(columns)) + " |"
        row_lines.append(row_str)
    return "\n".join([header_line, sep_line] + row_lines) + "\n"


def extract_outline(content: str) -> list[dict]:
    lines = content.splitlines()
    atx_re = re.compile(r"^(#{1,6})\s+(.+)$")
    headings = []

    for idx, line in enumerate(lines):
        m = atx_re.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            title = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", title)
            headings.append({
                "level": f"H{level}",
                "level_int": level,
                "heading": title,
                "line": idx + 1,
            })
        elif idx > 0 and line and not line.startswith(" "):
            prev_line = lines[idx - 1].strip()
            if prev_line and not prev_line.startswith("#") and not prev_line.startswith("|"):
                if re.match(r"^={3,}\s*$", line):
                    title = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", prev_line)
                    headings.append({
                        "level": "H1",
                        "level_int": 1,
                        "heading": title,
                        "line": idx,
                    })
                elif re.match(r"^-{3,}\s*$", line) and not prev_line.startswith("-"):
                    title = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", prev_line)
                    headings.append({
                        "level": "H2",
                        "level_int": 2,
                        "heading": title,
                        "line": idx,
                    })

    headings.sort(key=lambda x: x["line"])
    for i, h in enumerate(headings):
        start_line = h["line"]
        next_line = len(lines)
        for next_h in headings[i + 1:]:
            if next_h["level_int"] <= h["level_int"]:
                next_line = next_h["line"] - 1
                break
        section_lines = lines[start_line:next_line]
        h["words"] = len(" ".join(section_lines).split())

    return headings


def extract_section(content: str, target_heading: str) -> str:
    lines = content.splitlines()
    atx_re = re.compile(r"^(#{1,6})\s+(.+)$")
    target_lower = target_heading.lower().strip()

    start_idx = -1
    target_level = -1
    for idx, line in enumerate(lines):
        m = atx_re.match(line)
        if m:
            title = m.group(2).strip()
            if target_lower in title.lower():
                start_idx = idx
                target_level = len(m.group(1))
                break

    if start_idx == -1:
        return f"*(Section matching '{target_heading}' not found)*\n"

    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        m = atx_re.match(lines[idx])
        if m and len(m.group(1)) <= target_level:
            end_idx = idx
            break

    return "\n".join(lines[start_idx:end_idx]).strip() + "\n"


def grep_content(content: str, pattern: str, context_lines: int = 1) -> str:
    lines = content.splitlines()
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"*(Invalid regex pattern: {e})*\n"

    matched_indices = set()
    for idx, line in enumerate(lines):
        if regex.search(line):
            for i in range(max(0, idx - context_lines), min(len(lines), idx + context_lines + 1)):
                matched_indices.add(i)

    if not matched_indices:
        return f"*(No matches found for pattern '{pattern}')*\n"

    sorted_idx = sorted(matched_indices)
    output_lines = []
    prev = None
    for i in sorted_idx:
        if prev is not None and i > prev + 1:
            output_lines.append("---")
        output_lines.append(f"{i + 1:4d}: {lines[i]}")
        prev = i
    return "\n".join(output_lines) + "\n"


def convert_one(md: MarkItDown, path: Path, target: Path | None, ns) -> bool:
    if ns.verbose:
        print(f"converting {path}")
    try:
        result = md.convert(str(path))
    except Exception as e:
        print(f"ERROR {path}: {type(e).__name__}: {e}", file=sys.stderr)
        return False
    content = with_frontmatter(result.text_content, None if ns.no_metadata else getattr(result, "title", None))

    if getattr(ns, "outline", False):
        headings = extract_outline(content)
        if getattr(ns, "limit", 0) and ns.limit > 0:
            headings = headings[:ns.limit]
        cols = ["level", "heading", "line", "words"]
        if getattr(ns, "project", None):
            proj = [k.strip().lower() for k in ns.project.split(",") if k.strip()]
            cols = [c for c in cols if c in proj] or cols
        if getattr(ns, "json", False):
            print(json.dumps({"file": str(path), "total_headings": len(headings), "headings": headings}, indent=2))
        else:
            print(f"### Outline: {path.name}")
            print(render_table(headings, cols))
        if target:
            write_output(content, target)
        return True

    if getattr(ns, "section", None):
        section_text = extract_section(content, ns.section)
        if target:
            write_output(section_text, target)
        else:
            print(section_text, end="")
        return True

    if getattr(ns, "grep", None):
        grep_text = grep_content(content, ns.grep)
        if target:
            write_output(grep_text, target)
        else:
            print(grep_text, end="")
        return True

    write_output(content, target)
    if hasattr(ns, "_receipts") and target:
        headings = extract_outline(content)
        words = len(content.split())
        ns._receipts.append({
            "input": path.name,
            "output": str(target),
            "words": words,
            "headings": len(headings),
            "status": "converted"
        })
    if ns.verbose and target:
        print(f"  -> {target}")
    return True


def convert_stdin(md: MarkItDown, ns, suffix: str) -> bool:
    data = sys.stdin.buffer.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return convert_one(md, Path(tmp_path), Path(ns.output) if ns.output else None, ns)
    finally:
        os.unlink(tmp_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="markitdown_cli.py",
        description="Convert documents to Markdown with MarkItDown.",
        epilog="OCR uses a local OpenAI-compatible vision endpoint; see --ocr.",
    )
    p.add_argument("inputs", nargs="*", help="input file(s) or directory(ies)")
    p.add_argument("-i", "--input", dest="input_file", help="input file, or '-' for stdin")
    p.add_argument("-o", "--output", help="output file (single input) or directory (many)")
    p.add_argument("-r", "--recursive", action="store_true", help="recurse into directories")
    p.add_argument("--stdin-filename", default=".bin",
                   help="extension hint for stdin, e.g. .pdf (default: .bin, content is sniffed)")

    g = p.add_argument_group("OCR / image description (local vision endpoint)")
    g.add_argument("--ocr", action="store_true",
                   help="enable OCR via a local OpenAI-compatible vision server")
    g.add_argument("--ocr-base-url", default=os.environ.get("MARKITDOWN_OCR_BASE_URL", DEFAULT_OCR_BASE_URL),
                   help=f"vision server base URL (default: {DEFAULT_OCR_BASE_URL})")
    g.add_argument("--ocr-model", default=os.environ.get("MARKITDOWN_OCR_MODEL", DEFAULT_OCR_MODEL),
                   help=f"vision model name (default: {DEFAULT_OCR_MODEL})")
    g.add_argument("--ocr-client", choices=["openai", "azure", "anthropic"], default="openai",
                   help="client shape (default: openai, which any local server speaks)")
    g.add_argument("--llm-prompt", help="override the prompt sent to the vision model")

    g = p.add_argument_group("generic LLM options")
    g.add_argument("--llm-client", choices=["openai", "azure", "anthropic"],
                   help="same as --ocr-client, without enabling OCR")
    g.add_argument("--llm-model", help="model name for image description")
    g.add_argument("--llm-base-url", default=os.environ.get("OPENAI_BASE_URL"),
                   help="base URL override for the LLM client")
    g.add_argument("--llm-api-key", default=os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"),
                   help="API key (local servers ignore this)")

    p.add_argument("--no-metadata", action="store_true", help="omit the title frontmatter")
    p.add_argument("--list-formats", action="store_true", help="list supported inputs and exit")
    p.add_argument("--doctor", action="store_true", help="check the environment and vision endpoint")
    p.add_argument("-v", "--verbose", action="store_true", help="log each conversion")

    g_token = p.add_argument_group("token shielding / ICM inspection")
    g_token.add_argument("--outline", "--toc", action="store_true", help="extract heading outline / table of contents")
    g_token.add_argument("--section", help="extract only the section under the specified heading")
    g_token.add_argument("--grep", help="search for regex pattern and extract matching lines with context")
    g_token.add_argument("--table", "-t", action="store_true", help="output tables in Markdown pipe table format")
    g_token.add_argument("--project", "-p", help="comma-separated fields to project in outline table or receipt")
    g_token.add_argument("--limit", "-n", type=int, default=0, help="cap number of outline rows or output lines")
    g_token.add_argument("--receipt", action="store_true", help="emit conversion receipt instead of silent completion")
    g_token.add_argument("--json", action="store_true", help="emit output as JSON")

    return p


def main() -> int:
    parser = build_parser()
    ns = parser.parse_args()
    ns._receipts = []

    md = MarkItDown()          # probe instance for --list-formats / --doctor
    if ns.list_formats:
        cmd_list_formats(md)
        return 0
    if ns.doctor:
        cmd_doctor(ns, md)
        return 0
    if ns.ocr and not ns.ocr_model:
        parser.error("--ocr needs a vision model: pass --ocr-model")

    if not ns.input_file and not ns.inputs:
        parser.error("no input given (positional file(s)/directory, or -i - for stdin)")

    out_path = Path(ns.output).expanduser() if ns.output else None
    ns.output_is_file = out_path is not None and out_path.suffix != ""
    if ns.output_is_file and (ns.recursive or len(ns.inputs) > 1):
        parser.error("-o with a file extension only works for a single input; use a directory for many")
    ns.output = str(out_path) if out_path else None

    engine = build_markitdown(ns)

    if ns.input_file == "-":
        return 0 if convert_stdin(engine, ns, ns.stdin_filename) else 1

    files, skipped = collect_inputs(ns, engine)
    if skipped and ns.verbose:
        print(f"skipping {len(skipped)} file(s) with unrecognised extensions", file=sys.stderr)
    if not files:
        print("no convertible files found", file=sys.stderr)
        return 1

    out_dir = out_path if (out_path and not ns.output_is_file) else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    base = None
    for raw in ns.inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            base = base or p

    claimed: set = set()
    failures = 0
    for f in files:
        target = output_target(f, out_path, ns, base)
        if target is not None:
            target = disambiguate(target, claimed)
            claimed.add(target)
        if not convert_one(engine, f, target, ns):
            failures += 1

    if getattr(ns, "receipt", False) or getattr(ns, "table", False) or (getattr(ns, "json", False) and not getattr(ns, "outline", False)):
        if ns._receipts:
            if getattr(ns, "json", False):
                print(json.dumps({"status": "ok", "converted": ns._receipts}, indent=2))
            else:
                cols = ["input", "output", "words", "headings", "status"]
                if getattr(ns, "project", None):
                    proj = [k.strip().lower() for k in ns.project.split(",") if k.strip()]
                    cols = [c for c in cols if c in proj] or cols
                print(render_table(ns._receipts, cols))

    if ns.verbose:
        print(f"converted {len(files) - failures}/{len(files)} file(s), skipped {len(skipped)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
