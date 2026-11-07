# Code-Mode Skill Compatibility Guide (`code-mode-skill-compatibility.md`)

> **Architectural Standard for Cloudflare Code-Mode & `omnicli` Tool Execution**  
> How to design, refactor, and verify agent skills so they automatically expose typed Python SDK bindings, bounded token footprints, and zero-hallucination contracts.

---

## 🏛️ What is Code-Mode?

Traditional LLM tool execution relies on JSON-RPC / MCP schemas where every tool argument and output passes through raw model context in giant text buffers. When an agent invokes 5–10 tools in sequence, token usage explodes exponentially.

**Cloudflare Code-Mode** (implemented workstation-wide via `omnicli`) replaces tool token bloat by allowing the agent to write and execute small, sandboxed Python code snippets against local tools:

```python
# Instead of dumping a 1000-line JSON response into context:
from catalog.bindings import clip_box, pdf_ocr

# Tool runs locally; agent projects only the exact fields it needs in memory
result = clip_box(image="receipt.png", target="total amount", min_confidence=0.4)
if result.get("present"):
    print("Found at:", result["box"])
```

For a skill script to work seamlessly in Code-Mode, it must adhere to **5 Core Compatibility Rules**.

---

## 📋 The 5 Core Compatibility Rules

| # | Invariant | Description | Failure Mode If Missing |
|---|---|---|---|
| **1** | **Explicit Metavar Typing** | CLI flags must define standard `metavar="..."` hints (`metavar="N"`, `metavar="SCORE"`, etc.). | Parameter types default to `str \| None` instead of `int`, `float`, or `bool`. |
| **2** | **Strict Stdout JSON Cleanliness** | `--json` must emit strictly valid JSON on `stdout`. All logs, diagnostics, and banners go to `stderr`. | Model receives `json.JSONDecodeError` because `[INFO]` banners contaminated stdout. |
| **3** | **Zero-Output Silent Exit on Failure** | On gate rejection or error, print the error to `stderr` and exit with non-zero code. Never emit half-baked JSON on stdout. | Pipeline treats an error as valid data and compounds downstream failures. |
| **4** | **Standardized Exit Codes** | `0` = Success / Gate Passed<br>`1` = Fatal / Request Error<br>`2` = Gate Rejected / Threshold Missed | Automated assertions cannot distinguish a bug from a calibrated rejection. |
| **5** | **Table & Field Projection Support** | Support `--fields id,name` or projection keys when returning lists or tabular data. | Context blowup from returning massive unneeded JSON trees. |

---

## 🛠️ Step-by-Step Implementation Guide

### Step 1: Adding Explicit Metavars in `argparse`

`omnicli`'s parser (`catalog/argspec.py`) reads `--help` output to construct typed Python function signatures. It matches metavars against strict hint sets:

```python
# Hints recognized by omnicli:
INT_HINTS = {"N", "COUNT", "NUM", "LIMIT", "PORT", "RETRIES", "JOBS", "WORKERS", "PAGES"}
FLOAT_HINTS = {"TIMEOUT", "THRESHOLD", "SECS", "SECONDS", "RATIO", "ALPHA", "TEMPERATURE", "SCORE"}
```

#### ❌ Non-Compatible CLI Flag:
```python
parser.add_argument("--limit", type=int, default=10, help="Max results")
parser.add_argument("--threshold", type=float, default=0.75, help="Confidence cutoff")
```
*Why this fails:* `argparse` outputs `--limit LIMIT` and `--threshold THRESHOLD`. Without explicit hint words, the parser may not infer `int` or `float` accurately.

#### ✅ Code-Mode Compatible CLI Flag:
```python
parser.add_argument(
    "--limit",
    type=int,
    default=10,
    metavar="LIMIT",  # Matches INT_HINTS -> becomes `limit: int = 10`
    help="Max results (default: %(default)s)"
)
parser.add_argument(
    "--threshold",
    type=float,
    default=0.75,
    metavar="SCORE",  # Matches FLOAT_HINTS -> becomes `threshold: float = 0.75`
    help="Confidence cutoff (default: %(default)s)"
)
parser.add_argument(
    "--port",
    type=int,
    default=8083,
    metavar="PORT",   # Matches INT_HINTS -> becomes `port: int = 8083`
    help="Service port"
)
```

#### Handling Enum Choices:
For discrete choices, use `choices=[...]` or `metavar="{a,b,c}"`:
```python
parser.add_argument(
    "--format",
    choices=["json", "markdown", "csv"],
    default="json",
    help="Output format"
)
# Resulting Python binding: format: Literal['json', 'markdown', 'csv'] = 'json'
```

---

### Step 2: Isolating `stdout` vs `stderr`

Code-Mode scripts are piped directly into `json.loads(proc.stdout)`. If a progress bar or `print("[*] Processing...")` touches stdout, Code-Mode breaks.

#### Standard Pattern:
```python
import sys
import json

def log(msg: str):
    """Diagnostics go to stderr only."""
    sys.stderr.write(f"{msg}\n")
    sys.stderr.flush()

def main():
    parser = build_parser()
    args = parser.parse_args()

    log(f"[*] Starting job on {args.input}...")

    result = compute(args)

    if args.json:
        # Strictly valid JSON on stdout; no trailing whitespace or extra text
        print(json.dumps(result, indent=2))
    else:
        # Human-readable markdown or text table
        print(format_human_readable(result))
```

---

### Step 3: Bounded Responses & Token Shielding

When returning search results, transcripts, or file listings, never dump unbounded arrays into stdout. Implement truncation or top-K limiting:

```python
parser.add_argument(
    "--limit",
    type=int,
    default=20,
    metavar="LIMIT",
    help="Maximum items to return (default: 20)"
)
parser.add_argument(
    "--fields",
    type=str,
    metavar="FIELDS",
    help="Comma-separated keys to include in output (e.g. 'id,title,score')"
)
```

In your serializer:
```python
if args.fields:
    allowed = {f.strip() for f in args.fields.split(",")}
    results = [{k: v for k, v in item.items() if k in allowed} for item in results]

if len(results) > args.limit:
    results = results[:args.limit]
```

---

### Step 4: Verification Protocol (Rule 7: Negative & Positive Controls)

Before shipping a skill or refactor to production, run the 4-step verification gate:

#### 1. Positive Control: Check `--help` Metavars
```bash
python3 path/to/script.py --help
# Assert: shows --limit LIMIT, --threshold SCORE, --port PORT
```

#### 2. Negative Control: Bogus Flag Rejection
```bash
python3 path/to/script.py --bogus-test-flag
# Assert: non-zero exit code (code 2 for argparse errors)
```

#### 3. Refresh Catalog Index
```bash
omnicli index
# Re-reads help contracts and regenerates SQLite catalog bindings
```

#### 4. Automated Type Gate Assertion
Run a quick Python check against `catalog.db` to prove the types were correctly inferred:
```python
import sqlite3, json, sys
from catalog.argspec import parse_flags

db = sqlite3.connect("/home/rodri/.local/share/omnicli/catalog.db")
row = db.execute("SELECT contract FROM tools WHERE id = ?", ("my-skill/my_tool",)).fetchone()
params = parse_flags(json.loads(row[0]))
kind_map = {p.name: p.kind for p in params}

print(kind_map)
assert kind_map["limit"] == "int"
assert kind_map["threshold"] == "float"
assert kind_map["json"] == "bool"
print("✅ Code-Mode typing gate passed!")
```

---

## 🚀 Summary Checklist for Skill Authors

- [ ] Every integer flag has `metavar="N"`, `LIMIT`, `PORT`, or `COUNT`.
- [ ] Every float flag has `metavar="SCORE"`, `TIMEOUT`, or `THRESHOLD`.
- [ ] All informational messages, logs, and spinners use `sys.stderr`.
- [ ] `--json` produces pure JSON without markdown fences on `stdout`.
- [ ] Unknown or malformed options exit with non-zero exit codes.
- [ ] Catalog index updated and asserted with `omnicli index`.
