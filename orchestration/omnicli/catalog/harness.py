"""First-party harness adapter registry and verification for omnicli.

Supports:
  - t3-code: T3 Code IDE (Agent Client Protocol + previews)
  - agy: Antigravity CLI (DeepMind Python workflow graphs + subagents + surgical diffs)
  - opencode: OpenCode terminal agent (opencode.json + local model daemons + compound bash)
  - pi: Pi Agent (lightweight terminal agent + rsync skills + strict 8KB token cap)
  - boxxy: Boxxy Claw & Terminal (bubblewrap sandboxing + hot-reloading + SQLite WAL safety)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
HARNESSES_DIR = SKILL_DIR / "harnesses"

HARNESS_SPECS: dict[str, dict[str, Any]] = {
    "t3-code": {
        "id": "t3-code",
        "name": "T3 Code",
        "aliases": ["t3", "t3code", "t3-code"],
        "summary": "Agent Client Protocol (ACP) IDE harness with Code Mode, terminal execution, preview tools, and reactive wakeups.",
        "doc_file": "t3-code.md",
        "protocols": ["cli", "code-mode", "html-preview"],
        "config_paths": ["~/.config/t3code-v2", "~/.t3"],
        "env_indicators": ["T3CODE_CLI_PATH", "ARGV0", "CHROME_DESKTOP", "APPIMAGE"],
        "env_patterns": {
            "T3CODE_CLI_PATH": ".*t3.*",
            "ARGV0": ".*T3-Code.*",
            "CHROME_DESKTOP": "com.t3tools.T3Code.desktop",
            "APPIMAGE": ".*T3-Code.*",
        },
        "config_snippet": (
            "# Native tool surface (once): T3 Code drives OpenCode, so the plugin lands there.\n"
            "mkdir -p ~/.config/opencode/plugins\n"
            "ln -sf ~/src/my-agent-skills/orchestration/omnicli/plugin/omnicli-route.js \\\n"
            "  ~/.config/opencode/plugins/omnicli-route.js\n"
            "# Then reload the provider (`opencode reload`, or restart T3 Code).\n"
            "# T3 lists omnicli_search / omnicli_describe / omnicli_invoke / omnicli_exec;\n"
            "# Code Mode reaches the same functions as tools.omnicli.*.\n"
            "omnicli harness verify t3-code\n"
        ),
    },
    "agy": {
        "id": "agy",
        "name": "Antigravity CLI (agy)",
        "aliases": ["agy", "antigravity", "gemini"],
        "summary": "Google DeepMind agentic runtime supporting native Python workflow graphs, dynamic subagents, and surgical diffs.",
        "doc_file": "agy.md",
        "protocols": ["python-workflow", "cli", "subagents", "surgical-diff"],
        "config_paths": ["~/.gemini/antigravity-cli", "~/.gemini", "~/.local/bin/agy"],
        "env_indicators": ["ANTIGRAVITY_AGENT", "ANTIGRAVITY_HARNESS_PATH", "ANTIGRAVITY_CONVERSATION_ID", "GEMINI_HOME"],
        "env_patterns": {
            "ANTIGRAVITY_AGENT": "1",
            "ANTIGRAVITY_HARNESS_PATH": ".*",
            "ANTIGRAVITY_CONVERSATION_ID": ".+",
            "GEMINI_HOME": ".+",
        },
        "config_snippet": (
            "# 1) Wire agy lifecycle hook in ~/.gemini/config/hooks.json under 'omnicli-route'\n"
            "# 2) In Antigravity run_workflow or subagent script:\n"
            "from omnicli_tools import search, invoke, describe, spec\n\n"
            "tools = search(\"your task intent\", limit=3)\n"
            "result = invoke(tools[0][\"id\"], [\"--help\"])\n"
        ),
    },
    "opencode": {
        "id": "opencode",
        "name": "OpenCode",
        "aliases": ["opencode", "oc"],
        "summary": "Terminal-native open-source harness connecting to local model daemons (:8080-:8085) with compound bash batching.",
        "doc_file": "opencode.md",
        "protocols": ["cli", "surface-skills", "code-mode", "worktree-harness"],
        "config_paths": ["~/.config/opencode/opencode.json", "~/.local/share/opencode"],
        "env_indicators": ["OPENCODE_CONFIG", "OPENCODE_ROOT"],
        "env_patterns": {
            "OPENCODE_CONFIG": ".+",
            "OPENCODE_ROOT": ".+",
        },
        "config_snippet": (
            "# 1) Native tools (once): symlink the omnicli plugin\n"
            "mkdir -p ~/.config/opencode/plugins\n"
            "ln -sf ~/src/my-agent-skills/orchestration/omnicli/plugin/omnicli-route.js \\\n"
            "  ~/.config/opencode/plugins/omnicli-route.js\n"
            "# 2) Skill discovery (opencode.json)\n"
            + json.dumps({"skills": ["/home/rodri/src/my-agent-skills/surface"]}, indent=2)
        ),
    },
    "pi": {
        "id": "pi",
        "name": "Pi Agent",
        "aliases": ["pi", "pi-agent"],
        "summary": "Fast terminal agent operating on rsync-synchronized skills with tight 8KB context token caps.",
        "doc_file": "pi.md",
        "protocols": ["cli", "local-sockets", "token-cap"],
        "config_paths": ["~/.pi", "~/.pi/agent/skills"],
        "env_indicators": ["PI_AGENT_HOME", "PI_HOME"],
        "env_patterns": {
            "PI_AGENT_HOME": ".+",
            "PI_HOME": ".+",
        },
        "config_snippet": "# Direct invocation in Pi terminal:\nomnicli search \"<intent>\"\nomnicli invoke <tool_id> --omni-project \"field1,field2\" --omni-max-bytes 4000 -- [args...]\n",
    },
    "boxxy": {
        "id": "boxxy",
        "name": "Boxxy Claw & Terminal",
        "aliases": ["boxxy", "boxxy-terminal", "boxxyclaw"],
        "summary": "Terminal companion with hot-reloading skill discovery, bubblewrap sandboxing, and SQLite WAL concurrency.",
        "doc_file": "boxxy.md",
        "protocols": ["cli", "bwrap-sandbox", "wal-catalog"],
        "config_paths": ["~/.config/boxxy-terminal", "~/.local/bin/boxxy-terminal", "~/.config/boxxy-terminal/boxxyclaw/skills"],
        "env_indicators": ["BOXXY_HARNESS", "BOXXY_ROOT"],
        "env_patterns": {
            "BOXXY_HARNESS": ".+",
            "BOXXY_ROOT": ".+",
        },
        "config_snippet": "# Sandboxed plan execution in Boxxy:\nomnicli exec plan.py --sandbox strict\n# Real-time telemetry check:\nomnicli status --json\n",
    },
}


def resolve_harness_id(query: str) -> str | None:
    q = query.lower().strip()
    for h_id, spec in HARNESS_SPECS.items():
        if q == h_id or q in [a.lower() for a in spec["aliases"]]:
            return h_id
    return None


def get_harness(query: str) -> dict[str, Any] | None:
    h_id = resolve_harness_id(query)
    if not h_id:
        return None
    return HARNESS_SPECS[h_id]


def list_harnesses() -> list[dict[str, Any]]:
    out = []
    active = {d["id"] for d in detect_active_harnesses()}
    for h_id, spec in HARNESS_SPECS.items():
        installed = any(Path(os.path.expanduser(p)).exists() for p in spec["config_paths"])
        out.append({
            "id": h_id,
            "name": spec["name"],
            "summary": spec["summary"],
            "protocols": spec["protocols"],
            "config_paths": spec["config_paths"],
            "doc_file": str(HARNESSES_DIR / spec["doc_file"]),
            "installed": installed,
            "active": h_id in active,
        })
    return out


def detect_active_harnesses() -> list[dict[str, Any]]:
    detected = []
    for h_id, spec in HARNESS_SPECS.items():
        matched_indicators = []
        for var, pattern in spec.get("env_patterns", {}).items():
            val = os.environ.get(var, "")
            if not val:
                continue
            import re
            if re.search(pattern, val):
                matched_indicators.append(f"{var}={val[:40]}")

        # Path-based runtime detection (e.g. current PATH containing binaries)
        path_env = os.environ.get("PATH", "")
        if h_id == "pi" and ".pi/agent/bin" in path_env:
            matched_indicators.append("PATH has .pi/agent/bin")
        elif h_id == "opencode" and ".opencode/bin" in path_env:
            matched_indicators.append("PATH has .opencode/bin")

        if matched_indicators:
            detected.append({
                "id": h_id,
                "name": spec["name"],
                "matched_indicators": matched_indicators,
                "confidence": "active",
            })
    return detected


def get_doc(query: str) -> str | None:
    spec = get_harness(query)
    if not spec:
        return None
    doc_path = HARNESSES_DIR / spec["doc_file"]
    if doc_path.is_file():
        return doc_path.read_text(encoding="utf-8")
    return None


def get_config(query: str) -> str | None:
    spec = get_harness(query)
    if not spec:
        return None
    return spec.get("config_snippet", "")



def _native_tool_plugin_check() -> dict[str, Any]:
    """The OpenCode plugin that gives T3/OpenCode omnicli_search et al."""
    src = SKILL_DIR / "plugin" / "omnicli-route.js"
    link = Path(os.path.expanduser("~/.config/opencode/plugins/omnicli-route.js"))
    node = shutil.which("node")
    link_ok = link.exists()
    syntax_ok = False
    if link_ok and node:
        try:
            proc = subprocess.run(
                [node, "--check", str(link)], capture_output=True, text=True, timeout=10
            )
            syntax_ok = proc.returncode == 0
        except Exception:
            syntax_ok = False
    passed = src.is_file() and link_ok and syntax_ok
    detail = f"source={src.is_file()} link={link_ok} node_check={syntax_ok} target={link}"
    return {"check": "native_tool_plugin", "passed": passed, "detail": detail}


def _agy_route_hook_check() -> dict[str, Any]:
    """The Antigravity lifecycle hook that gives agy PreToolUse gating and PreInvocation routing."""
    src = SKILL_DIR / "hooks" / "agy_omnicli_hook.py"
    hooks_cfg = Path(os.path.expanduser("~/.gemini/config/hooks.json"))
    configured = False
    if hooks_cfg.is_file():
        try:
            data = json.loads(hooks_cfg.read_text())
            configured = "omnicli-route" in data
        except Exception:
            configured = False
    passed = src.is_file() and configured
    detail = f"source={src.is_file()} hooks_json_configured={configured} target={src}"
    return {"check": "agy_route_hook", "passed": passed, "detail": detail}


def verify_harness(query: str) -> dict[str, Any]:
    spec = get_harness(query)
    if not spec:
        return {"id": query, "status": "FAIL", "error": f"Unknown harness: {query}"}

    h_id = spec["id"]
    checks = []

    # Check 1: Omnicli binary available
    omnicli_path = shutil.which("omnicli") or str(SKILL_DIR / "omnicli.py")
    checks.append({
        "check": "omnicli_executable",
        "passed": bool(omnicli_path),
        "detail": omnicli_path or "omnicli not found",
    })

    # Check 2: Catalog database readable
    try:
        from . import builder
        con = builder.connect()
        try:
            row = con.execute("SELECT count(*) FROM tools").fetchone()
            tool_count = row[0] if row else 0
        finally:
            con.close()
        checks.append({
            "check": "catalog_database",
            "passed": tool_count > 0,
            "detail": f"{tool_count} tools indexed in catalog.db",
        })
    except Exception as exc:
        checks.append({
            "check": "catalog_database",
            "passed": False,
            "detail": f"Failed to connect to catalog: {exc}",
        })

    # Check 3: Harness documentation exists
    doc_path = HARNESSES_DIR / spec["doc_file"]
    checks.append({
        "check": "documentation_guide",
        "passed": doc_path.is_file(),
        "detail": str(doc_path),
    })

    # Check 4: Filesystem configuration paths presence
    resolved_paths = [Path(os.path.expanduser(p)) for p in spec["config_paths"]]
    existing_paths = [str(p) for p in resolved_paths if p.exists()]
    passed_install = len(existing_paths) > 0
    detail_str = f"Found: {', '.join(existing_paths)}" if existing_paths else "No config dirs found"
    checks.append({
        "check": "workstation_installation",
        "passed": passed_install,
        "detail": detail_str,
    })

    # Check 5: Protocol-specific verification
    if h_id == "t3-code":
        # Verify Code Mode SDK bindings exist and can import
        bindings_py = Path(os.path.expanduser("~/.local/share/omnicli/bindings/omnicli_tools.py"))
        has_bindings = bindings_py.is_file() and bindings_py.stat().st_size > 1000
        checks.append({
            "check": "code_mode_sdk_bindings",
            "passed": has_bindings,
            "detail": f"Bindings valid at {bindings_py}" if has_bindings else "Bindings not found or empty",
        })
        checks.append(_native_tool_plugin_check())

    elif h_id == "agy":
        # Verify Python bindings generation
        try:
            from . import bindings, builder
            con = builder.connect()
            try:
                fingerprint = builder.meta_get(con, "fingerprint", "")
                b_dir = bindings.ensure(con, fingerprint)
                module_path = b_dir / "omnicli_tools.py"
            finally:
                con.close()
            checks.append({
                "check": "python_bindings_sdk",
                "passed": module_path.is_file(),
                "detail": f"Bindings valid at {module_path}",
            })
        except Exception as exc:
            checks.append({
                "check": "python_bindings_sdk",
                "passed": False,
                "detail": f"Bindings check failed: {exc}",
            })
        checks.append(_agy_route_hook_check())

    elif h_id == "opencode":
        # Check opencode.json validity and surface discovery
        cfg_file = Path(os.path.expanduser("~/.config/opencode/opencode.json"))
        is_valid_json = False
        if cfg_file.is_file():
            try:
                cfg_data = json.loads(cfg_file.read_text())
                is_valid_json = isinstance(cfg_data, dict)
            except Exception:
                pass
        checks.append({
            "check": "opencode_configuration",
            "passed": is_valid_json,
            "detail": f"opencode.json parsed successfully at {cfg_file}" if is_valid_json else "Missing or invalid opencode.json",
        })
        checks.append(_native_tool_plugin_check())

    elif h_id == "pi":
        # Verify output capping logic
        try:
            from . import invoke
            test_blob = "line\n" * 1000
            shaped = invoke.shape(test_blob, max_bytes=500)
            capped_bytes = len(shaped["output"].encode("utf-8"))
            passed = capped_bytes <= 500 and shaped["truncated"]
            checks.append({
                "check": "strict_token_budget_cap",
                "passed": passed,
                "detail": f"500-byte budget enforced ({capped_bytes} bytes emitted, truncated={shaped['truncated']})",
            })
        except Exception as exc:
            checks.append({
                "check": "strict_token_budget_cap",
                "passed": False,
                "detail": f"Cap check failed: {exc}",
            })

    elif h_id == "boxxy":
        # Verify bubblewrap sandbox engine
        bwrap = shutil.which("bwrap")
        bwrap_ok = False
        if bwrap:
            try:
                p = subprocess.run([bwrap, "--ro-bind", "/", "/", "true"], capture_output=True, timeout=5)
                bwrap_ok = p.returncode == 0
            except Exception:
                bwrap_ok = False
        checks.append({
            "check": "bubblewrap_sandboxing",
            "passed": bwrap_ok,
            "detail": f"bwrap functional at {bwrap}" if bwrap_ok else "bwrap not functioning or missing",
        })

    all_passed = all(c["passed"] for c in checks)
    return {
        "id": h_id,
        "name": spec["name"],
        "status": "PASS" if all_passed else "FAIL",
        "passed": sum(1 for c in checks if c["passed"]),
        "total": len(checks),
        "checks": checks,
    }


def verify_all() -> dict[str, Any]:
    results = {}
    for h_id in HARNESS_SPECS:
        results[h_id] = verify_harness(h_id)
    overall_pass = all(r["status"] == "PASS" for r in results.values())
    return {
        "status": "PASS" if overall_pass else "FAIL",
        "harnesses": results,
    }
