#!/usr/bin/env python3
"""Token cost of skill discovery: the prompt-shelf path vs the omnicli path.

Two questions, measured on this machine:

  1. What does the model have in context when it has to *choose* a tool?
  2. What does it have in context when it *invokes* one?

Path A ("shelf") is what a skill-library harness does natively: every skill's
frontmatter is present, the model picks one, the body is read, the tool's
--help is read.

Path B ("omnicli") is the 4-metatool design: 4 meta-tool contracts, then one
tool contract fetched on demand, then a bounded response.

Token counting uses the local Qwen3.5 tokenizer (the same family the local
inference servers run), so the numbers are comparable to a real session.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

DRIVE = Path("/run/media/rodri/AI")
OMNICLI = DRIVE / "skills/orchestration/omnicli"
SKILLS_DIR = DRIVE / "skills"
TOKENIZER = DRIVE / "models/perplexity-ai/pplx-decider-flash-v1.2"

_counter = None


def counter():
    """A cheap token counter backed by the local Qwen tokenizer."""
    global _counter
    if _counter is None:
        from transformers import AutoTokenizer

        _counter = AutoTokenizer.from_pretrained(str(TOKENIZER))
    return _counter


def tokens(text: str) -> int:
    return len(counter()(text, add_special_tokens=False)["input_ids"])


def frontmatter(md: str) -> str:
    match = re.match(r"^---\s*\n(.*?)\n---", md, re.DOTALL)
    return match.group(1) if match else ""


def main() -> None:
    # ---- collect the skill library -------------------------------------------
    skills = []
    for md_path in sorted(SKILLS_DIR.rglob("SKILL.md")):
        if "archived" in md_path.parts or ".venv" in md_path.parts:
            continue
        md = md_path.read_text(encoding="utf-8", errors="replace")
        if not md.startswith("---"):
            continue
        name_match = re.search(r"^name:\s*(.+)$", frontmatter(md), re.MULTILINE)
        skills.append({
            "dir": md_path.parent.name,
            "name": name_match.group(1).strip().strip("\"'") if name_match else md_path.parent.name,
            "fm": frontmatter(md),
            "body": re.sub(r"^---\s*\n.*?\n---\s*\n", "", md, flags=re.DOTALL),
            "path": md_path,
        })
    n = len(skills)

    shelf_fm = sum(tokens(s["fm"]) for s in skills)
    shelf_fm_names = sum(tokens(s["name"]) for s in skills)
    shelf_all_bodies = sum(tokens(s["body"]) for s in skills)

    # a typical skill body the agent would read after choosing
    bodies = sorted((tokens(s["body"]), s["name"]) for s in skills)
    median_body = bodies[len(bodies) // 2][0]
    median_body_name = bodies[len(bodies) // 2][1]

    # ---- path B: the omnicli metatool face -----------------------------------
    # Ground truth: ask the real MCP server for its tools/list and count what an
    # agent actually receives (name + description + inputSchema).
    mcp_tools = []
    mcp_path = OMNICLI / "scripts/mcp_server.py"
    if mcp_path.is_file():
        try:
            proc = subprocess.Popen(
                [sys.executable, str(mcp_path)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1,
            )

            def send(obj):
                proc.stdin.write(json.dumps(obj) + "\n")
                proc.stdin.flush()

            send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "probe", "version": "1"}}})
            proc.stdout.readline()
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            mcp_tools = json.loads(proc.stdout.readline())["result"]["tools"]
            proc.stdin.close()
            proc.terminate()
        except Exception:
            mcp_tools = []

    if mcp_tools:
        meta_tokens = tokens(json.dumps(mcp_tools, indent=1))
        meta_names = [t["name"] for t in mcp_tools]
    else:
        mcp_src = mcp_path.read_text(encoding="utf-8", errors="replace")
        meta_names = sorted(set(re.findall(r'"name"\s*:\s*"(omni_\w+)"', mcp_src)))
        meta_contracts = []
        for name in meta_names:
            block = re.search(
                r'"name"\s*:\s*"' + name + r'".{0,3000}?"description"\s*:\s*"((?:[^"\\]|\\.)*)"',
                mcp_src, re.DOTALL,
            )
            meta_contracts.append(f"{name}: {block.group(1) if block else ''}")
        meta_tokens = tokens("\n".join(meta_contracts))

    # one tool contract, fetched on demand
    tool_contract_tokens = 0
    tool_contract_name = "-"
    try:
        out = subprocess.run(
            [sys.executable, str(OMNICLI / "omnicli.py"), "describe", "local/decide"],
            capture_output=True, text=True, timeout=120,
        )
        if out.returncode == 0:
            tool_contract_tokens = tokens(out.stdout)
            tool_contract_name = "local/decide"
    except Exception:
        pass

    # bounded response: the 8 KB cap
    bounded_response = 8000 // 4  # ~4 chars per token, the usual English ratio

    # ---- report ---------------------------------------------------------------
    print("=" * 74)
    print("TOKEN COST OF SKILL DISCOVERY")
    print("=" * 74)
    print(f"library: {n} skills, tokenized with the local Qwen3.5 tokenizer\n")

    print("PATH A - prompt shelf (what a skill-library harness does natively)")
    print(f"  A1  all {n} skill names in context            {shelf_fm_names:>8,} tok")
    print(f"  A2  all {n} skill frontmatters in context       {shelf_fm:>8,} tok")
    print(f"  A3  + the chosen skill's SKILL.md body          {median_body:>8,} tok   (median: {median_body_name})")
    print(f"  A4  + that tool's --help contract                {tool_contract_tokens:>8,} tok   ({tool_contract_name})")
    a_total = shelf_fm + median_body + tool_contract_tokens
    print(f"      ---------------------------------------------")
    print(f"      A = tokens in context to invoke one tool     {a_total:>8,} tok")
    print(f"      (if the agent read every skill body:         {shelf_fm + shelf_all_bodies + tool_contract_tokens:>8,} tok)")

    print("\nPATH B - omnicli metatools (4 tools, fetch one contract on demand)")
    print(f"  B1  {len(meta_names)} metatool contracts in context  {meta_tokens:>8,} tok   ({', '.join(meta_names)})")
    print(f"  B2  + one tool contract, fetched on demand    {tool_contract_tokens:>8,} tok")
    print(f"  B3  + bounded response (8 KB cap)              {bounded_response:>8,} tok")
    b_total = meta_tokens + tool_contract_tokens + bounded_response
    print(f"      ---------------------------------------------")
    print(f"      B = tokens in context to invoke one tool     {b_total:>8,} tok")

    print("\nSAVING")
    print(f"  selection phase  A2 {shelf_fm:>8,}  vs  B1 {meta_tokens:>8,}   "
          f"{100 * (1 - meta_tokens / max(1, shelf_fm)):.1f}% smaller")
    print(f"  to invoke        A  {a_total:>8,}  vs  B {b_total:>8,}   "
          f"{100 * (1 - b_total / max(1, a_total)):.1f}% smaller")
    print(f"  token ratio      A/B = {a_total / max(1, b_total):.2f}x")

    print("\n  caveat: B's saving depends on the 8 KB response cap. A tool that")
    print("  returned its whole output would put that output in context; the cap")
    print("  is what makes B smaller than A, not the discovery itself.")


if __name__ == "__main__":
    main()
