"""omnicli MCP server — Face B of the Uber OmniCLI.

Speaks JSON-RPC 2.0 over stdio and exposes exactly four meta-tools. The
point is that a JSON-RPC tool-calling agent never sees the workstation's
hundreds of executables; it sees four tiny tools and pulls the contract for
one real tool at a time.

    omni_discover  intent -> ranked skill ids, best tool ids, one line each
    omni_describe  tool_id -> the exact input contract for that one tool
    omni_invoke    tool_id + args -> a bounded, projected result
    omni_status    -> endpoint health, catalog freshness, retrieval tier

Transport is hand-rolled rather than using the official SDK: the subset
needed here is small and stable, it keeps the control plane dependency-free,
and it matches the stdlib-only discipline of the rest of the catalog.

Protocol notes:
  * MCP uses newline-delimited JSON-RPC over stdio (one JSON object per line).
  * `initialize` must be answered with a `protocolVersion`, `capabilities`
    and `serverInfo`.
  * Tool results are returned as `content: [{type: "text", text: ...}]`.

Three properties this face must hold, because the agent cannot verify them:

  * **Every reply is bounded.** `max_bytes` applies to the encoded result of
    every meta-tool, not just to `omni_invoke`, and the ceiling includes the
    elision banner.
  * **One execution path.** Invocation, projection and capping come from
    `catalog.invoke`, the same code the CLI uses, so the two faces cannot
    disagree about what a projection or a cap means.
  * **A request never blocks the loop.** Tools can take minutes; a slow call
    must not stall a `ping` or a second client request. Requests run on a
    small pool and replies are serialised behind one stdout lock.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from catalog import argspec, builder, health, invoke, search  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "omnicli"
SERVER_VERSION = "1.2.0"

DEFAULT_MAX_BYTES = invoke.DEFAULT_MAX_BYTES
DEFAULT_DISCOVER_LIMIT = 5
TOOLS_PER_RESULT = 2
ENVELOPE_ALLOWANCE = invoke.ENVELOPE_ALLOWANCE


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _con():
    con = builder.connect()
    builder.ensure_built(con, progress=False)
    return con


def _text_result(payload: str, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": payload}],
        "isError": is_error,
    }


def _bounded(payload: Any, max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """Serialise a reply, or return a structured refusal that fits.

    Truncating JSON would hand the agent something it cannot parse, so an
    oversized reply is refused explicitly instead: the agent can narrow the
    request, which is a decision it can make, whereas a half-object is not.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    size = len(text.encode("utf-8"))
    if size <= max_bytes:
        return _text_result(text)
    return _text_result(invoke.refusal(size, max_bytes), is_error=True)


def _json_result(payload: Any, max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    return _bounded(payload, max_bytes)


def _int_arg(args: dict[str, Any], key: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(args.get(key) if args.get(key) is not None else default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


# --------------------------------------------------------------------------
# meta-tool implementations
# --------------------------------------------------------------------------

def tool_discover(args: dict[str, Any]) -> dict[str, Any]:
    """Rank skills for an intent, with the few tool ids worth describing."""
    intent = (args.get("intent") or "").strip()
    if not intent:
        return _json_result({"error": "intent is required"})
    limit = _int_arg(args, "limit", DEFAULT_DISCOVER_LIMIT, low=1, high=20)
    max_bytes = _int_arg(args, "max_bytes", DEFAULT_MAX_BYTES, low=64, high=10_000_000)

    # `rerank` is the contract; `no_rerank` is the legacy boolean. Passing the
    # string straight through matters: `always` used to be swallowed by a
    # truthiness check and behaved exactly like `never`.
    if args.get("rerank") is not None:
        mode: Any = args.get("rerank")
    elif args.get("no_rerank"):
        mode = "never"
    else:
        mode = "auto"

    con = _con()
    fusion: Any = args.get("fusion", "auto")
    res = search.search(con, intent, limit=limit, rerank_enabled=mode, fusion=fusion)

    results = []
    for r in res["results"]:
        tools = con.execute(
            "SELECT id, kind, enabled FROM tools WHERE skill = ? ORDER BY id",
            (r["skill"],),
        ).fetchall()
        entry = {
            "skill": r["skill"],
            "score": r["score"],
            "why": (r["chunks"][0]["snippet"][:100] if r["chunks"] else ""),
            "tool_count": len(tools),
            "tools": [t["id"] for t in tools[:TOOLS_PER_RESULT]],
        }
        if len(tools) > TOOLS_PER_RESULT:
            entry["tools_truncated"] = True
        disabled = [t["id"] for t in tools if not t["enabled"]]
        if disabled:
            entry["disabled"] = disabled
        results.append(entry)

    return _json_result({
        "intent": intent,
        "tier": res["tier"],
        "shape": "compact",
        "results": results,
        "next": ("Call omni_describe with one tool id for its input contract, "
                 "or with a skill name for that skill's section outline."),
    }, max_bytes)


def tool_describe(args: dict[str, Any]) -> dict[str, Any]:
    """Return the exact input contract for a single tool, or a skill's body.

    A tool id gives that tool's usage, flags, positionals and subcommands.
    A skill name gives the skill itself: its frontmatter and a section
    outline, so the agent can pull one section rather than the whole body.
    """
    tool_id = (args.get("tool_id") or "").strip()
    if not tool_id:
        return _json_result({"error": "tool_id is required"})
    section_name = (args.get("section") or "").strip()
    doc_name = (args.get("doc") or "").strip()
    max_bytes = _int_arg(args, "max_bytes", DEFAULT_MAX_BYTES, low=64, high=10_000_000)

    con = _con()
    if args.get("stub") or tool_id in ("*", "all"):
        pattern = re.compile((args.get("grep") or "").strip(), re.IGNORECASE) \
            if (args.get("grep") or "").strip() else None
        rows = con.execute(
            "SELECT id, skill, kind, summary, contract FROM tools ORDER BY id"
        ).fetchall()
        if pattern:
            rows = [r for r in rows
                    if pattern.search(r["id"]) or pattern.search(r["summary"] or "")]
        sigs = argspec.signatures(rows)
        body = "\n".join(sig.line() for sig in sigs) or "No tool matched that filter."
        return _bounded({
            "matched": len(sigs),
            "signatures": body,
            "next": "Call omni_invoke with tool_id and those keyword arguments.",
        }, max_bytes)

    row = con.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone()
    if row is None:
        # A skill name gives the skill itself. This is checked before the
        # legacy "fall back to the skill's primary script" path, because a
        # skill name and a script contract are different things and the
        # caller asked for the skill.
        if con.execute("SELECT 1 FROM skills WHERE name = ?", (tool_id,)).fetchone():
            if doc_name:
                return _describe_doc(con, tool_id, doc_name, max_bytes)
            return _describe_skill(con, tool_id, section_name, max_bytes)
        cands = con.execute(
            "SELECT id FROM tools WHERE skill = ? AND kind = 'script' LIMIT 1", (tool_id,)
        ).fetchall()
        if cands:
            row = con.execute("SELECT * FROM tools WHERE id = ?", (cands[0]["id"],)).fetchone()
        else:
            return _text_result(f"No tool or skill named {tool_id!r}.", is_error=True)

    contract = json.loads(row["contract"] or "{}")
    payload = {
        "id": row["id"],
        "skill": row["skill"],
        "kind": row["kind"],
        "enabled": bool(row["enabled"]),
        "summary": row["summary"],
        "argv": json.loads(row["argv"] or "[]"),
        "contract": contract,
        "next": f"Call omni_invoke with tool_id={row['id']!r} and your arguments.",
    }
    if not row["enabled"]:
        payload["next"] = (
            f"Tool {row['id']!r} is DISABLED: it is discoverable but not runnable. "
            f"Enable it on the workstation with `omnicli enable {row['id']}`."
        )
    return _json_result(payload, max_bytes)


def _describe_doc(con, name: str, query: str, max_bytes: int) -> dict[str, Any]:
    """Read one document the skill declared as part of its searchable body."""
    q = (query or "").strip().lower()
    rows = con.execute(
        "SELECT title, path, body FROM docs WHERE skill = ? AND kind IN ('doc', 'reference')", (name,)
    ).fetchall()
    if not rows:
        return _text_result(
            f"Skill {name!r} declares no documents. Call omni_describe with "
            f"tool_id={name!r} to see the skill itself.", is_error=True)

    scored = []
    for title, path, body in rows:
        t = (title or "").lower()
        p = (path or "").lower()
        stem = Path(p).stem.lower()
        rel = p.split("/suites/")[-1] if "/suites/" in p else p
        score = 0
        if t == q or rel == q:
            score = 100
        elif t.startswith(q) or rel.startswith(q):
            score = 80
        elif t.endswith("/" + q) or rel.endswith("/" + q):
            score = 70
        elif q and q in t:
            score = 50
        elif q and q in p:
            score = 40
        elif stem == q:
            score = 30
        if score:
            scored.append((score, title, path, body))
    if not scored:
        return _text_result(f"No document matching {query!r} in {name!r}.", is_error=True)

    scored.sort(key=lambda r: -r[0])
    _, title, path, body = scored[0]
    return _json_result({
        "skill": name,
        "title": title,
        "path": path,
        "tokens": len(body) // 4,
        "body": body,
    }, max_bytes)


def _describe_skill(con, name: str, section_name: str, max_bytes: int) -> dict[str, Any]:
    """A skill id: frontmatter + outline, or one section on request."""
    from catalog import skilldoc

    row = con.execute("SELECT * FROM skills WHERE name = ?", (name,)).fetchone()
    if row is None:
        return _text_result(f"No tool or skill named {name!r}.", is_error=True)
    md_path = row["md_path"]
    if not md_path or not Path(md_path).is_file():
        return _text_result(f"Skill {name!r} has no readable SKILL.md.", is_error=True)

    doc = skilldoc.load_skill_doc(md_path)

    if section_name:
        section = skilldoc.pick_section(doc, section_name)
        if section is None:
            return _text_result(
                f"No section {section_name!r} in {name!r}. Available: "
                + ", ".join(s["heading"] for s in doc["sections"] if s["heading"]),
                is_error=True,
            )
        return _json_result({
            "skill": name,
            "section": section["heading"],
            "tokens": section["tokens"],
            "body": section["body"],
            "next": "Call omni_discover or omni_describe for anything else you need.",
        }, max_bytes)

    tools = con.execute(
        "SELECT id, kind, enabled FROM tools WHERE skill = ? ORDER BY kind, id", (name,)
    ).fetchall()
    return _json_result({
        "skill": name,
        "kind": "skill",
        "path": doc["path"],
        "frontmatter": doc["frontmatter"],
        "body_tokens": doc["tokens"],
        "outline": skilldoc.outline(doc),
        "tools": [{"id": t["id"], "kind": t["kind"], "enabled": bool(t["enabled"])}
                  for t in tools],
        "next": (
            f"Call omni_describe with tool_id={name!r} and section=\"<heading>\" to read "
            f"one section, or omni_describe with a tool id for its input contract."
        ),
    }, max_bytes)


def tool_invoke(args: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool and return a bounded, projected result."""
    tool_id = (args.get("tool_id") or "").strip()
    if not tool_id:
        return _json_result({"error": "tool_id is required"})
    max_bytes = _int_arg(args, "max_bytes", DEFAULT_MAX_BYTES, low=64, high=10_000_000)
    timeout = args.get("timeout")
    try:
        timeout = float(timeout) if timeout is not None else 300.0
    except (TypeError, ValueError):
        timeout = 300.0

    con = _con()
    row = con.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone()
    if row is None:
        return _text_result(f"No tool named {tool_id!r}.", is_error=True)

    if not row["enabled"]:
        return _json_result({
            "tool": tool_id,
            "error": "tool is disabled",
            "hint": f"Review it with omni_describe, then enable it on the workstation "
                    f"with `omnicli enable {tool_id}`.",
        }, max_bytes)

    argv = json.loads(row["argv"] or "[]")
    cmd = invoke.build_cmd(argv, [str(a) for a in (args.get("args") or [])],
                           python=sys.executable, skill_dir=SKILL_DIR)
    run = invoke.execute(cmd, timeout=timeout)

    projection = args.get("projection") or []
    if isinstance(projection, str):
        projection = [f.strip() for f in projection.split(",") if f.strip()]

    def build(shaped: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "tool": tool_id,
            "exit_code": run["exit_code"],
            "bytes": shaped["bytes"],
            "raw_bytes": shaped["raw_bytes"],
            "truncated": shaped["truncated"],
            "projection_applied": shaped["projection_applied"],
            "output": shaped["output"],
        }
        if shaped["projection_requested"] and not shaped["projection_applied"]:
            payload["projection_warning"] = (
                "projection was requested but could not be applied (output was not JSON, "
                "or no requested field matched); the unfiltered payload was returned."
            )
        if run["stderr"]:
            payload["stderr"] = run["stderr"][-2000:]
        return payload

    try:
        payload, encoded, _ = invoke.fit_envelope(
            run["stdout"], build, fields=projection or None,
            jq_expr=args.get("jq") or None,
            grep_pattern=args.get("grep") or None,
            max_bytes=max_bytes,
        )
    except Exception as exc:  # invalid regex, unreadable jq output, etc.
        return _json_result({"tool": tool_id, "error": f"projection failed: {exc}"},
                            max_bytes)

    if len(encoded.encode("utf-8")) <= max_bytes:
        return _text_result(encoded)
    return _bounded(payload, max_bytes)


def tool_status(args: dict[str, Any]) -> dict[str, Any]:
    """Endpoint health, catalog freshness, and the active retrieval tier."""
    max_bytes = _int_arg(args, "max_bytes", DEFAULT_MAX_BYTES, low=64, high=10_000_000)
    probe = health.probe_all()

    con = _con()
    skills = con.execute("SELECT count(*) AS c FROM skills").fetchone()["c"]
    tools = con.execute("SELECT count(*) AS c FROM tools").fetchone()["c"]
    enabled = con.execute("SELECT count(*) AS c FROM tools WHERE enabled = 1").fetchone()["c"]
    docs = con.execute("SELECT count(*) AS c FROM docs").fetchone()["c"]
    tier = "bm25+dense(rrf)" if search.embedding_available() else "bm25"

    return _json_result({
        "tailscale_address": probe["tailscale_address"],
        "services": [
            {"port": s["port"], "name": s["service"], "status": s["status"]}
            for s in probe["services"]
        ],
        "catalog": {
            "skills": skills,
            "tools": tools,
            "tools_enabled": enabled,
            "docs": docs,
            "built_at": builder.meta_get(con, "built_at"),
        },
        "retrieval_tier": tier,
    }, max_bytes)


# --------------------------------------------------------------------------
# tool manifest
# --------------------------------------------------------------------------

TOOLS = [
    {
        "name": "omni_discover",
        "description": (
            "Find the right tool for a natural-language intent. Returns ranked skill "
            "names, each with its best tool ids and a one-line reason. Start here. "
            "Call omni_describe with a returned skill name for that skill's section "
            "outline, or with a tool id for its input contract."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "description": "What you want to do, in plain language."},
                "limit": {"type": "integer",
                          "description": f"Max skills (default {DEFAULT_DISCOVER_LIMIT}).",
                          "default": DEFAULT_DISCOVER_LIMIT},
                "rerank": {
                    "type": "string",
                    "enum": ["auto", "always", "never"],
                    "description": "Re-ranker mode. auto (default) only re-ranks when the "
                                   "lexical ranking is unsure.",
                },
                "fusion": {
                    "type": "string",
                    "enum": ["auto", "always", "never"],
                    "description": "Dense-leg fusion. auto (default) fuses BM25 with the "
                                   "bge-small skill vectors only when BM25 is unsure; "
                                   "always fuses every query (better on paraphrase).",
                },
                "no_rerank": {"type": "boolean",
                              "description": "Legacy alias for rerank=\"never\"."},
                "max_bytes": {"type": "integer", "description": "Hard cap on the reply."},
            },
            "required": ["intent"],
        },
    },
    {
        "name": "omni_describe",
        "description": (
            "Get the exact input contract for ONE tool: usage, flags, positionals and "
            "subcommands. Call this before invoking. Given a skill name instead of a "
            "tool id, returns the skill's frontmatter and section outline; add "
            "section=\"<heading>\" to read that one section of its body, or "
            "doc=\"<path>\" to read one of the documents the skill declares. "
            "Set stub=true with tool_id=\"*\" and an optional grep to get many "
            "annotated signatures instead of one prose contract."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {"type": "string", "description": "A tool id from omni_discover, a skill name, or \"*\" with stub=true."},
                "section": {
                    "type": "string",
                    "description": "Optional. Heading of the skill section to read.",
                },
                "doc": {
                    "type": "string",
                    "description": "Optional. Path or title of a document the skill declares, e.g. \"pstack/playbooks/hillclimb.md\".",
                },
                "stub": {
                    "type": "boolean",
                    "description": "Optional. Return annotated Python signatures instead of one prose contract.",
                },
                "grep": {
                    "type": "string",
                    "description": "Optional with stub=true: case-insensitive regex over tool ids and summaries.",
                },
                "max_bytes": {"type": "integer", "description": "Hard cap on the reply."},
            },
            "required": ["tool_id"],
        },
    },
    {
        "name": "omni_invoke",
        "description": (
            "Execute a tool. Output is always bounded by max_bytes and can be "
            "projected down to specific JSON fields, so a large payload never floods "
            "the context window. A disabled tool refuses with an enable hint."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"},
                         "description": "Command-line arguments for the tool."},
                "projection": {"type": "array", "items": {"type": "string"},
                               "description": "JSON fields to keep; dotted paths like "
                                              "\"a.b\" and list elements are supported."},
                "jq": {"type": "string", "description": "A jq filter, when jq is installed."},
                "grep": {"type": "string", "description": "Keep only lines matching this regex."},
                "max_bytes": {"type": "integer", "description": "Hard cap on the reply."},
                "timeout": {"type": "number", "description": "Seconds before the tool is killed."},
            },
            "required": ["tool_id"],
        },
    },
    {
        "name": "omni_status",
        "description": (
            "Report which local inference services are online, how fresh the tool "
            "catalog is, how many tools are enabled, and which retrieval tier search "
            "is currently running (bm25 or bm25+rerank)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_bytes": {"type": "integer", "description": "Hard cap on the reply."},
            },
        },
    },
]

HANDLERS = {
    "omni_discover": tool_discover,
    "omni_describe": tool_describe,
    "omni_invoke": tool_invoke,
    "omni_status": tool_status,
}


# --------------------------------------------------------------------------
# JSON-RPC plumbing
# --------------------------------------------------------------------------

def respond(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def respond_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    msg_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return respond(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "omnicli exposes this workstation's tools through four meta-tools. "
                "Call omni_discover with a plain-language intent, then omni_describe "
                "for the single tool you want, then omni_invoke."
            ),
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # notification, no response

    if method == "ping":
        return respond(msg_id, {})

    if method == "tools/list":
        return respond(msg_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            return respond_error(msg_id, -32602, f"Unknown tool: {name}")
        try:
            result = handler(params.get("arguments") or {})
        except Exception as exc:  # pragma: no cover - surface errors, never crash the loop
            result = _text_result(f"omnicli error in {name}: {exc}", is_error=True)
        return respond(msg_id, result)

    if method == "shutdown":
        return respond(msg_id, {})

    if msg_id is None:
        return None  # any other notification

    return respond_error(msg_id, -32601, f"Method not found: {method}")


def serve(max_workers: int = 4) -> None:
    """Read newline-delimited JSON-RPC from stdin, write replies to stdout.

    Requests are handled on a small pool so a long tool call cannot stall the
    transport. JSON-RPC correlates replies by `id`, so out-of-order completion
    is legal; the only shared resource is stdout, which is written under a
    lock and flushed per line.
    """
    lock = threading.Lock()

    def emit(reply: dict[str, Any] | None) -> None:
        if reply is None:
            return
        data = json.dumps(reply, ensure_ascii=False) + "\n"
        with lock:
            sys.stdout.write(data)
            sys.stdout.flush()

    def work(req: dict[str, Any]) -> None:
        try:
            emit(handle(req))
        except Exception as exc:  # pragma: no cover - never lose a reply
            emit(respond_error(req.get("id"), -32603, f"internal error: {exc}"))

    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                emit(respond_error(None, -32700, "Parse error"))
                continue
            if not isinstance(req, dict):
                continue
            pool.submit(work, req)
    finally:
        pool.shutdown(wait=True)


if __name__ == "__main__":
    try:
        serve()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
