#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

bin_path = Path(__file__).resolve().parent.parent / "bin" / "cgate"
if bin_path.is_file() and os.access(bin_path, os.X_OK):
    os.execv(str(bin_path), [str(bin_path)] + sys.argv[1:])

import argparse
import ast
import json
import re
import subprocess
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# `query` asks for prose, which the h2o-lightning-4b decision model cannot emit --
# it returns calibrated probabilities, not text. Generative projection therefore
# belongs to the local-llm skill on :8080 (Qwen3.6-35B Genesis).
GENERATIVE_URL = "http://127.0.0.1:8080/v1/chat/completions"

def query_local_llm(prompt: str, system_prompt: str = "You are a concise code analyst. Answer directly with minimal tokens and quote only the exact 2-5 relevant lines.", max_tokens: int = 250) -> str:
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens
    }
    data = json.dumps(payload).encode("utf-8")
    
    try:
        req = urllib.request.Request(GENERATIVE_URL, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            choice = res.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content", "").strip()
            if content:
                return content
    except Exception:
        pass

    return ("Error: Could not reach the local LLM on :8080. "
            "Start it with the `local-llm` skill (`scripts/llm_client.py start`).")


def extract_python_symbols(content: str) -> List[Dict[str, Any]]:
    symbols = []
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append({
                    "type": "function",
                    "name": node.name,
                    "start": node.lineno,
                    "end": getattr(node, "end_lineno", node.lineno)
                })
            elif isinstance(node, ast.ClassDef):
                symbols.append({
                    "type": "class",
                    "name": node.name,
                    "start": node.lineno,
                    "end": getattr(node, "end_lineno", node.lineno)
                })
    except Exception:
        pass
    symbols.sort(key=lambda s: s["start"])
    return symbols


def extract_regex_symbols(content: str) -> List[Dict[str, Any]]:
    symbols = []
    lines = content.splitlines()
    fn_pat = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function|def|class|interface|type)\s+([A-Za-z0-9_]+)")
    for idx, line in enumerate(lines, 1):
        m = fn_pat.match(line)
        if m:
            symbols.append({
                "type": "symbol",
                "name": m.group(1),
                "start": idx,
                "end": idx
            })
    return symbols


def get_outline(target_file: Path) -> Dict[str, Any]:
    text = target_file.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    ext = target_file.suffix.lower()
    if ext == ".py":
        symbols = extract_python_symbols(text)
    else:
        symbols = extract_regex_symbols(text)
        
    return {
        "file": str(target_file.resolve()),
        "total_lines": len(lines),
        "total_bytes": len(text.encode("utf-8")),
        "symbols": symbols
    }


def view_file_gated(
    file_path: Path,
    symbol: Optional[str] = None,
    lines_range: Optional[Tuple[int, int]] = None,
    max_preview: int = 35
) -> str:
    if not file_path.is_file():
        return f"Error: File '{file_path}' does not exist."

    text = file_path.read_text(encoding="utf-8", errors="replace")
    all_lines = text.splitlines()
    total_lines = len(all_lines)

    if lines_range:
        start, end = lines_range
        start = max(1, start)
        end = min(total_lines, end)
        sliced = all_lines[start - 1 : end]
        output = [f"📄 {file_path.name} (Lines {start}-{end} of {total_lines}):\n```"]
        for idx, line in enumerate(sliced, start):
            output.append(f"{idx:4d}: {line}")
        output.append("```")
        return "\n".join(output)

    if symbol:
        outline = get_outline(file_path)
        matching = [s for s in outline["symbols"] if s["name"].lower() == symbol.lower()]
        if not matching:
            return f"Symbol '{symbol}' not found in {file_path.name}. Available symbols:\n" + ", ".join(s["name"] for s in outline["symbols"][:30])
        
        target_sym = matching[0]
        start = target_sym["start"]
        end = target_sym["end"]
        sliced = all_lines[start - 1 : end]
        output = [f"🔍 Symbol `{target_sym['name']}` ({target_sym['type']}, lines {start}-{end} in {file_path.name}):\n```"]
        for idx, line in enumerate(sliced, start):
            output.append(f"{idx:4d}: {line}")
        output.append("```")
        return "\n".join(output)

    if total_lines <= max_preview:
        output = [f"📄 {file_path.name} (All {total_lines} lines):\n```"]
        for idx, line in enumerate(all_lines, 1):
            output.append(f"{idx:4d}: {line}")
        output.append("```")
        return "\n".join(output)

    outline = get_outline(file_path)
    output = [
        f"🛡️  [cgate] Context Protection Active for `{file_path.name}` ({total_lines} lines, {len(text)} bytes)",
        f"Dumping the full file would bloat your context window.",
        "",
        "### Key Symbols Defined in File:"
    ]
    if outline["symbols"]:
        for s in outline["symbols"][:25]:
            output.append(f"- `{s['name']}` ({s['type']}): Lines {s['start']}-{s['end']}")
        if len(outline["symbols"]) > 25:
            output.append(f"- ... and {len(outline['symbols']) - 25} more symbols")
    else:
        output.append("_(No AST/regex top-level symbols detected)_")

    output.append(f"\n### Preview (First {max_preview} lines):\n```")
    for idx, line in enumerate(all_lines[:max_preview], 1):
        output.append(f"{idx:4d}: {line}")
    output.append("```")
    output.append(f"\n👉 To view specific section without context bloat:")
    output.append(f"   cgate view {file_path} --symbol <symbol_name>")
    output.append(f"   cgate view {file_path} --lines <start>-<end>")
    output.append(f"   cgate query {file_path} \"<what you want to know>\"")
    return "\n".join(output)


def grep_gated(pattern: str, search_path: Path, max_hits_per_file: int = 3, max_total_files: int = 8) -> str:
    cmd = ["rg", "-n", "--no-heading", pattern, str(search_path)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        cmd = ["grep", "-rn", pattern, str(search_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)

    if res.returncode != 0 and not res.stdout:
        return f"No matches found for '{pattern}' in {search_path}."

    lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
    file_matches: Dict[str, List[Tuple[int, str]]] = {}
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) >= 3:
            f_path = parts[0]
            try:
                line_no = int(parts[1])
                match_text = parts[2].strip()
            except ValueError:
                continue
            file_matches.setdefault(f_path, []).append((line_no, match_text))

    output = [
        f"🔍 [cgate grep] Query: `{pattern}` (Found {len(lines)} total occurrences across {len(file_matches)} files)\n"
    ]

    for f_idx, (f_path, matches) in enumerate(list(file_matches.items())[:max_total_files]):
        output.append(f"📄 **{f_path}** ({len(matches)} matches):")
        for l_no, text in matches[:max_hits_per_file]:
            output.append(f"  Line {l_no:4d}: `{text[:100]}`")
        if len(matches) > max_hits_per_file:
            output.append(f"  ... and {len(matches) - max_hits_per_file} more matches in this file.")
        output.append("")

    if len(file_matches) > max_total_files:
        output.append(f"⚠️  ... and {len(file_matches) - max_total_files} additional files with matches omitted to protect context.")

    return "\n".join(output)


def query_gated(file_path: Path, question: str) -> str:
    if not file_path.is_file():
        return f"Error: File '{file_path}' does not exist."

    content = file_path.read_text(encoding="utf-8", errors="replace")
    if len(content) > 30000:
        content = content[:30000] + "\n\n... [truncated for local decision engine] ..."

    prompt = f"File Content:\n```\n{content}\n```\n\nQuestion: {question}\n\nAnswer concisely and quote only the exact lines."
    answer = query_local_llm(prompt)
    return f"🤖 [cgate query: {file_path.name}]\n**Question:** {question}\n\n{answer}"


def main() -> int:
    parser = argparse.ArgumentParser(description="cgate: Context-Gated Reader & Filter (Kem Glitch Architecture)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    v_p = sub.add_parser("view", help="View a file with automatic context guarding")
    v_p.add_argument("file", help="Path to file")
    v_p.add_argument("--symbol", help="Extract only specific function/class symbol")
    v_p.add_argument("--lines", help="Extract specific line range, e.g. 50-80")
    v_p.add_argument("--max-preview", type=int, default=35, metavar="LIMIT", help="Max preview lines for un-gated display")

    o_p = sub.add_parser("outline", help="Display symbol outline and line spans of a file")
    o_p.add_argument("file", help="Path to file")

    g_p = sub.add_parser("grep", help="Context-gated ripgrep search")
    g_p.add_argument("pattern", help="Search pattern")
    g_p.add_argument("path", nargs="?", default=".", help="Target directory or file (default: .)")
    g_p.add_argument("--limit", type=int, default=3, metavar="LIMIT", help="Max hits per file")

    q_p = sub.add_parser("query", help="Ask the local LLM (:8080) a question about a file without context bloat")
    q_p.add_argument("file", help="Path to file")
    q_p.add_argument("question", help="Question about file")

    args = parser.parse_args()

    if args.cmd == "view":
        lines_range = None
        if args.lines:
            try:
                parts = [int(p.strip()) for p in args.lines.split("-")]
                lines_range = (parts[0], parts[1])
            except Exception:
                print(f"Invalid lines format '{args.lines}'. Expected format: 10-30")
                return 1
        print(view_file_gated(Path(args.file), symbol=args.symbol, lines_range=lines_range, max_preview=args.max_preview))
        return 0

    elif args.cmd == "outline":
        p = Path(args.file)
        if not p.is_file():
            print(f"Error: {p} does not exist.")
            return 1
        out = get_outline(p)
        print(f"\n📂 File: {out['file']} ({out['total_lines']} lines)")
        print("-" * 50)
        for s in out["symbols"]:
            print(f"  [{s['type'][:4].upper()}] {s['name']:30} : Lines {s['start']:4d} - {s['end']:4d}")
        print("-" * 50 + "\n")
        return 0

    elif args.cmd == "grep":
        print(grep_gated(args.pattern, Path(args.path), max_hits_per_file=args.limit))
        return 0

    elif args.cmd == "query":
        print(query_gated(Path(args.file), args.question))
        return 0

    return 1

if __name__ == "__main__":
    sys.exit(main())
