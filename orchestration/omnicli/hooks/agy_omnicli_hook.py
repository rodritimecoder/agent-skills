#!/usr/bin/env python3
"""
agy_omnicli_hook.py — Antigravity lifecycle hook for omnicli routing and bypass prevention.

Integrates with ~/.gemini/config/hooks.json under "omnicli-route":
  - PreInvocation / SessionStart: Injects [omnicli route] using agy protojson
    `injectSteps: [{"systemMessage": {"systemMessage": ...}}]`.
  - PreToolUse: Extracts agy camelCase `toolCall` payloads, primes sessions on
    `omnicli` CLI usage, and blocks raw reads/greps inside ~/src/my-agent-skills
    until omnicli search/exec is called.
  - Logs decisions to ~/.local/share/omnicli/route.jsonl for unified metrics across harnesses.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ID = "agy-omnicli-route"
SKILLS_ROOT = os.environ.get(
    "OMNICLI_SKILLS_ROOT", os.path.expanduser("~/src/my-agent-skills")
)
EXEMPT_MARKER = os.path.join(SKILLS_ROOT, ".omnicli-route-exempt")
ROUTE_LOG = Path(os.path.expanduser("~/.local/share/omnicli/route.jsonl"))
PRIMED_DIR = Path(os.path.expanduser("~/.local/share/omnicli/primed_sessions"))

ROUTING = (
    "[omnicli route] The workstation tool catalogue is exposed via omnicli. "
    "Use it; do not re-derive a tool's CLI from its source.\n"
    "- omnicli search \"<intent>\" — find catalogued tools by intent.\n"
    "- omnicli describe <tool_id> — read one tool's contract before calling it.\n"
    "- omnicli invoke <tool_id> — run one catalogued tool; output is capped at 8 KB.\n"
    "- omnicli exec -c '<python code>' or omnicli exec plan.py — run Python Code Mode in sandbox with omnicli_tools bindings.\n"
    "Rules: For multi-step exploration or data parsing (≥ 2 tool calls or parsing files/binaries), DO NOT probe incrementally with python3 -c / bash. Run a Code Mode script via omnicli exec in one turn.\n"
    "Discover with search, never by viewing or grepping skill directories. "
    "Ordinary code and file work in the current repo still uses native tools."
)

NATIVE_READ_TOOLS = {
    "view_file",
    "read_file",
    "search_code",
    "code_search",
    "grep",
    "grep_search",
    "glob",
    "read",
    "list_dir",
    "find_by_name",
    "view_file_outline",
    "view_code_item",
}
SHELL_TOOLS = {"run_command", "bash", "shell", "execute_command", "run_terminal_command"}
SHELL_READ_VERBS = re.compile(
    r"(^|[;&|]\s*|\b(?:sudo|command|exec)\s+)(cat|bat|less|head|tail|grep|rg|ag|sed|awk|find|ls|tree|python3?)\b"
)
OMNICLI_CMD = re.compile(
    r"\b(?:omnicli|omnicli\.py)\s+(search|describe|invoke|exec|plan|spec|tools|list|status|policy|bindings)\b"
)


def _is_inside(child: str, parent: str) -> bool:
    try:
        c = Path(child).resolve()
        p = Path(parent).resolve()
        return c == p or p in c.parents
    except Exception:
        return False


def _get_session_id(payload: dict) -> str:
    val = (
        payload.get("conversationId")
        or payload.get("conversation_id")
        or payload.get("common", {}).get("conversationId")
        or ""
    )
    return str(val).strip()


def _is_session_primed(session_id: str) -> bool:
    if not session_id:
        return False
    marker = PRIMED_DIR / f"{session_id}.primed"
    return marker.exists()


def _mark_session_primed(session_id: str) -> None:
    if not session_id:
        return
    try:
        PRIMED_DIR.mkdir(parents=True, exist_ok=True)
        marker = PRIMED_DIR / f"{session_id}.primed"
        marker.touch()
    except Exception:
        pass


def _is_session_injected(session_id: str) -> bool:
    if not session_id:
        return False
    marker = PRIMED_DIR / f"{session_id}.injected"
    return marker.exists()


def _mark_session_injected(session_id: str) -> None:
    if not session_id:
        return
    try:
        PRIMED_DIR.mkdir(parents=True, exist_ok=True)
        marker = PRIMED_DIR / f"{session_id}.injected"
        marker.touch()
    except Exception:
        pass


def _log_route(row: dict) -> None:
    try:
        ROUTE_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "plugin": ID,
            **row,
        }
        with open(ROUTE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _extract_tool_info(payload: dict) -> tuple[str, dict]:
    # Antigravity (agy) sends protojson camelCase: top-level `toolCall`
    # (keep snake_case fallbacks for legacy/synthetic callers).
    tool_call = (
        payload.get("toolCall")
        or payload.get("preToolHookArgs", {}).get("toolCall")
        or payload.get("tool_call")
        or payload.get("pre_tool_hook_args", {}).get("tool_call")
        or payload.get("toolRequest")
        or {}
    )

    name = (
        tool_call.get("name")
        or tool_call.get("toolName")
        or tool_call.get("tool_name")
        or payload.get("toolName")
        or payload.get("tool")
        or ""
    )

    args = (
        tool_call.get("args")
        or tool_call.get("arguments")
        or payload.get("args")
        or {}
    )
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {"raw": args}

    return name, args if isinstance(args, dict) else {"raw": args}


def _iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_strings(v)


def _detect_skills_hit(tool_name: str, args: dict, cwd: str) -> str | None:
    if tool_name in NATIVE_READ_TOOLS:
        candidates = [
            args.get("Path"),
            args.get("AbsolutePath"),
            args.get("TargetFile"),
            args.get("SearchDirectory"),
            args.get("SearchPath"),
            args.get("DirectoryPath"),
            args.get("Directory"),
            args.get("path"),
            args.get("file_path"),
            args.get("target_file"),
            args.get("filePath"),
            args.get("filepath"),
            args.get("file"),
            args.get("directory"),
            args.get("uri"),
        ]
        seen = set()
        for val in list(candidates) + list(_iter_strings(args)):
            if not isinstance(val, str):
                continue
            raw = val.strip()
            if not raw or raw in seen:
                continue
            seen.add(raw)
            if raw.startswith("file://"):
                raw = raw[len("file://"):]
            expanded = os.path.expanduser(raw)
            resolved = os.path.abspath(os.path.join(cwd, expanded))
            if _is_inside(resolved, SKILLS_ROOT):
                return resolved
        return None

    if tool_name in SHELL_TOOLS:
        cmd = args.get("CommandLine") or args.get("command") or ""
        if isinstance(cmd, str) and cmd:
            expanded_cmd = cmd.replace("~/", os.path.expanduser("~/"))
            if SHELL_READ_VERBS.search(expanded_cmd) and (
                SKILLS_ROOT in expanded_cmd or "my-agent-skills" in expanded_cmd
            ):
                return SKILLS_ROOT

    return None


def handle_pre_invocation(payload: dict) -> dict:
    session_id = _get_session_id(payload)
    if session_id and _is_session_injected(session_id):
        return {"terminationBehavior": ""}
    if session_id:
        _mark_session_injected(session_id)
    _log_route({
        "session": session_id or "global",
        "tool": "",
        "kind": "inject",
        "decision": "inject",
    })
    return {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": ROUTING,
                }
            }
        ],
        "terminationBehavior": "",
    }


def handle_pre_tool_use(payload: dict) -> dict:
    session_id = _get_session_id(payload) or "global"
    cwd = str(payload.get("cwd") or payload.get("common", {}).get("cwd") or os.getcwd())
    workspaces = payload.get("workspacePaths") or [cwd]

    tool_name, args = _extract_tool_info(payload)

    # Check if this tool invocation is omnicli itself
    is_omnicli = False
    if tool_name.startswith("omnicli"):
        is_omnicli = True
    elif tool_name in SHELL_TOOLS:
        cmd = args.get("CommandLine") or args.get("command") or ""
        if isinstance(cmd, str) and OMNICLI_CMD.search(cmd):
            is_omnicli = True

    if is_omnicli:
        _mark_session_primed(session_id)
        _log_route({
            "session": session_id,
            "tool": tool_name,
            "kind": "omnicli",
            "decision": "allow",
        })
        return {"decision": "allow"}

    skills_hit = _detect_skills_hit(tool_name, args, cwd)
    if not skills_hit:
        _log_route({
            "session": session_id,
            "tool": tool_name,
            "kind": "native",
            "decision": "allow",
        })
        return {"decision": "allow"}

    # Project root inside skills repo is exempt
    project_inside_skills = any(_is_inside(w, SKILLS_ROOT) for w in workspaces) or _is_inside(cwd, SKILLS_ROOT)
    exempt_marker_present = Path(EXEMPT_MARKER).exists()
    primed = _is_session_primed(session_id)

    if primed or project_inside_skills or exempt_marker_present:
        exempt_reason = "primed" if primed else ("project" if project_inside_skills else "marker")
        _log_route({
            "session": session_id,
            "tool": tool_name,
            "kind": "native",
            "decision": "allow",
            "skills": skills_hit,
            "exempt": exempt_reason,
        })
        return {"decision": "allow"}

    # Hard denial
    _log_route({
        "session": session_id,
        "tool": tool_name,
        "kind": "native",
        "decision": "deny",
        "skills": skills_hit,
    })
    return {
        "decision": "deny",
        "reason": (
            "Denied by agy-omnicli-route: reading skill directories to find a tool is the bypass this gate exists to stop. "
            "Call 'omnicli search <intent>' first (or 'omnicli exec -c ...' for Code Mode); "
            "after one catalogue call, direct reads are allowed. "
            f"To work on the skills repo from a project outside it, create {EXEMPT_MARKER}."
        ),
    }


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ORCA_ANTIGRAVITY_EVENT", "")

    payload = {}
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read()
            if raw.strip():
                payload = json.loads(raw)
        except Exception:
            payload = {}

    if not event:
        event = payload.get("hookEventName") or "PreToolUse"

    if event in ("PreInvocation", "SessionStart"):
        result = handle_pre_invocation(payload)
    elif event == "PreToolUse":
        result = handle_pre_tool_use(payload)
    else:
        result = {"decision": "allow"}

    print(json.dumps(result))


if __name__ == "__main__":
    main()
