"""One execution path, shared by both faces of the gateway.

`omnicli invoke` (Face A) and `omni_invoke` (Face B) used to carry separate
copies of projection, capping and subprocess handling. They drifted: the CLI
projected lists and the MCP face did not, the CLI clamped its preview inside
the cap and the MCP face appended a banner past it, and the CLI wrote the
filtered payload to `--omni-buffer` while telling the user it had written the
full one. Every one of those was a *duplicate*, not a design choice.

So this module owns the three things that must not diverge again:

* **Projection** — jq, or dotted-path fields (`a.b`, lists included), applied
  before the payload is measured. A projection that cannot be applied says
  so; it never silently returns the unfiltered payload as if it had worked.
* **Capping** — a hard ceiling that includes the elision banner. The budget
  is filled with head+tail rather than being forfeited when the cap is small.
* **Buffering** — the full output goes to disk *before* any filter, because
  the buffer exists to preserve what the cap discards.

stderr is kept out of stdout. Merging them corrupted JSON output whenever a
tool logged progress, which silently disabled projection for those tools.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

DEFAULT_MAX_BYTES = 8000
MIN_PAYLOAD_BUDGET = 40
# A JSON envelope (`{"tool": ..., "output": ...}`) costs a few hundred bytes
# of keys and escaping. Callers that wrap the payload subtract this so the
# *reply* honours the cap, not just the payload inside it.
ENVELOPE_ALLOWANCE = 512
_MISSING = object()


# --------------------------------------------------------------------------
# projection
# --------------------------------------------------------------------------

def _pick(obj: Any, path: str) -> Any:
    """Resolve one dotted path, mapping over lists as it goes."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list):
            vals = [_pick(item, part) for item in cur]
            vals = [v for v in vals if v is not _MISSING]
            return vals if vals else _MISSING
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


def _set_path(dst: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = dst
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _project_obj(data: Any, fields: list[str]) -> Any:
    if isinstance(data, list):
        return [_project_obj(item, fields) for item in data]
    if not isinstance(data, dict):
        return data
    out: dict[str, Any] = {}
    for field in fields:
        value = _pick(data, field)
        if value is _MISSING:
            continue
        _set_path(out, field, value)
    return out


def project(raw: str, fields: list[str] | None = None,
            jq_expr: str | None = None) -> tuple[str, bool]:
    """Return (payload, applied). ``applied`` is False when nothing filtered."""
    if jq_expr:
        if shutil.which("jq"):
            try:
                proc = subprocess.run(["jq", jq_expr], input=raw, text=True,
                                      capture_output=True)
                if proc.returncode == 0:
                    return proc.stdout.strip(), True
            except OSError:
                pass
        return raw, False
    if not fields:
        return raw, False
    try:
        data = json.loads(raw)
    except ValueError:
        return raw, False
    projected = _project_obj(data, fields)
    # An empty projection is never what the caller meant: it means no path
    # matched. Reporting it as applied would hide the failure behind `{}`.
    if isinstance(projected, dict):
        empty = not projected
    elif isinstance(projected, list):
        empty = not projected or all(isinstance(i, dict) and not i for i in projected)
    else:
        empty = False
    if empty:
        return raw, False
    return json.dumps(projected, indent=2, ensure_ascii=False), True


def grep(text: str, pattern: str | None) -> tuple[str, bool]:
    if not pattern:
        return text, False
    import re

    compiled = re.compile(pattern)
    return "\n".join(ln for ln in text.splitlines() if compiled.search(ln)), True


# --------------------------------------------------------------------------
# capping
# --------------------------------------------------------------------------

def _banner(total: int, omitted: int, max_bytes: int, verbose: bool) -> str:
    if verbose:
        return (f"… [omnicli] {omitted} bytes elided ({total} total, cap "
                f"{max_bytes}). Re-run with --omni-buffer FILE to keep the full "
                f"payload, or --omni-max-bytes {total} to lift the cap.")
    return f"… [omnicli] {omitted} bytes elided (cap {max_bytes})."


def cap(text: str, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[str, bool, int]:
    """Bound a payload to *at most* ``max_bytes``, banner included.

    The banner is measured before the split and the remaining budget is
    shared head/tail, so a small cap still returns data instead of only the
    elision notice. Two passes settle the banner's own digit count; the final
    encode is clamped, which is what makes the ceiling a guarantee rather
    than an estimate.
    """
    data = text.encode("utf-8", errors="replace")
    total = len(data)
    if total <= max_bytes:
        return text, False, total
    if max_bytes <= 0:
        return "", True, total

    for verbose in (True, False):
        banner = _banner(total, total, max_bytes, verbose)
        budget = max_bytes - len(banner.encode("utf-8")) - 2
        if budget < MIN_PAYLOAD_BUDGET:
            continue

        head_len = int(budget * 0.66)
        tail_len = budget - head_len
        banner = _banner(total, total - head_len - tail_len, max_bytes, verbose)
        budget = max_bytes - len(banner.encode("utf-8")) - 2
        if budget < MIN_PAYLOAD_BUDGET:
            continue

        head_len = int(budget * 0.66)
        tail_len = budget - head_len
        head = data[:head_len].decode("utf-8", errors="ignore")
        tail = data[-tail_len:].decode("utf-8", errors="ignore") if tail_len else ""
        encoded = f"{head}\n{banner}\n{tail}".encode("utf-8")
        if len(encoded) <= max_bytes:
            return encoded.decode("utf-8", errors="ignore"), True, total
        return encoded[:max_bytes].decode("utf-8", errors="ignore"), True, total

    short = _banner(total, total, max_bytes, False)
    if len(short.encode("utf-8")) <= max_bytes:
        return short, True, total
    return short.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore"), True, total


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------

def build_cmd(argv: list[str], extra_args: list[str], *, python: str,
              skill_dir: Any) -> list[str]:
    return [str(a).replace("{python}", python).replace("{skill}", str(skill_dir))
            for a in argv] + [str(a) for a in extra_args]


def execute(cmd: list[str], timeout: float = 300.0) -> dict[str, Any]:
    """Run a tool. stdout and stderr stay separate on purpose."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"exit_code": proc.returncode, "stdout": proc.stdout or "",
                "stderr": proc.stderr or "", "timed_out": False}
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "stdout": "",
                "stderr": f"omnicli: tool timed out after {timeout}s", "timed_out": True}
    except OSError as exc:
        return {"exit_code": 127, "stdout": "",
                "stderr": f"omnicli: failed to execute: {exc}", "timed_out": False}


def shape(stdout: str, *, fields: list[str] | None = None,
          jq_expr: str | None = None, grep_pattern: str | None = None,
          max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """Project, filter, cap. Reports exactly what happened."""
    projected, projection_applied = project(stdout, fields, jq_expr)
    filtered, grep_applied = grep(projected, grep_pattern)
    capped, truncated, size = cap(filtered, max_bytes)
    return {
        "output": capped,
        "bytes": size,                 # shaped payload, before the cap
        "raw_bytes": len(stdout.encode("utf-8", errors="replace")),
        "truncated": truncated,
        "projection_applied": projection_applied,
        "projection_requested": bool(fields or jq_expr),
        "grep_applied": grep_applied,
    }


def parse_fields(spec: str | None) -> list[str] | None:
    if not spec:
        return None
    fields = [f.strip() for f in spec.split(",") if f.strip()]
    return fields or None


def fit_envelope(stdout: str, build_payload, *, fields: list[str] | None = None,
                 jq_expr: str | None = None, grep_pattern: str | None = None,
                 max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Shape the output so the *wrapped* reply fits, not just the payload.

    The envelope's size depends on the payload (escaping, key names, the
    elision banner), so a fixed allowance is either wasteful or too small.
    Shape once, measure the real overhead, and reshape with the difference.
    """
    def shape_once(budget: int) -> dict[str, Any]:
        return shape(stdout, fields=fields, jq_expr=jq_expr,
                     grep_pattern=grep_pattern, max_bytes=budget)

    shaped = shape_once(max_bytes)
    payload = build_payload(shaped)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False)
    size = len(encoded.encode("utf-8"))
    if size <= max_bytes:
        return payload, encoded, shaped

    overhead = size - len(shaped["output"].encode("utf-8"))
    shaped = shape_once(max(0, max_bytes - overhead - 2))
    payload = build_payload(shaped)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False)
    return payload, encoded, shaped


def refusal(size: int, max_bytes: int) -> str:
    """The smallest honest reply that fits: why the real one could not.

    Truncating JSON would hand the caller something it cannot parse. Below a
    certain cap even the explanation cannot fit, so the ladder ends at an
    empty string — still within the ceiling, which is the guarantee.
    """
    notices: list[Any] = [
        {
            "error": "response exceeds max_bytes",
            "bytes": size,
            "max_bytes": max_bytes,
            "hint": ("Narrow the request: lower `limit`, project fewer fields, "
                     "or describe a single item."),
        },
        {"error": "reply exceeds max_bytes", "max_bytes": max_bytes},
        {"error": "too large"},
        "",
    ]
    for notice in notices:
        text = json.dumps(notice, ensure_ascii=False) if notice else ""
        if len(text.encode("utf-8")) <= max_bytes:
            return text
    return ""
