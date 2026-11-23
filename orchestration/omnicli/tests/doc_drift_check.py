#!/usr/bin/env python3
"""Kem-style doc-drift gate for omnicli: prove the docs match the live tool surface."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
REPO = SKILL.parent.parent
# Overridable so a test can point the curated routing-doc scan at a temp tree
# containing a mutant copy of a scanned document.
DOC_ROOT = Path(os.environ.get("OMNICLI_DOC_DRIFT_ROOT", str(REPO)))
NATIVE = {"exec"}
MCP = {"omni_exec"}
# The registered native surface is exec-only (NATIVE above). `invoke` survives
# as a retired-but-known binding name inside historical plans; `search` was the
# retired discovery verb and is NOT whitelisted. STALE_SEARCH below is the
# authority for stale search-routing claims.
KNOWN_METHODS = NATIVE | {"invoke"}

STALE = (
    r"omnicli_describe",
    r"tools\.omnicli\.describe",
    r"\b(?:four|4)\s+native\s+tools\b",
    r"\b(?:four|4)\s+tools\b",
    r"\b(?:four|4)\s+meta-?tools\b",
    r"\b580\+",
    r"\b550\+",
    r"\b494\b",
    r"\b5\d{2}\+?\s+tools\b",
)

# Stale claims that teach an agent to route through the retired discovery verb.
# Deliberately narrow: BM25/dense prose and generic `search()` mentions are
# historical background in the reference docs, not routing instructions.
STALE_SEARCH = (
    r"\bomnicli\s+search\b",
    r"`omnicli`\s+search\b",
    r"call the omnicli_tools bindings \(search",
    r"\bDiscover with search\b",
    r"\bsearch/spec plan\b",
    r"\bsearch\(\)/invoke\(\) inside the plan\b",
    r"\bomnicli eval\b",
    r"\bomnicli do\b",
)


def docs():
    files = [SKILL / "CONTEXT.md", SKILL / "SKILL.md", SKILL / "README.md"]
    files += sorted((SKILL / "harnesses").glob("*.md"))
    files += sorted(p for p in (SKILL / "references").glob("*.md")
                    if not p.name.startswith("plan-"))
    return [p for p in files if p.exists()]


def search_routing_docs():
    """Bounded, explicit set of files that teach the routing contract.

    Hooks and the plugin inject instructions at runtime; root CONTEXT.md is the
    machine-level routing doc; omnicli reference docs are the long-form contract.
    plan-* docs are historical working notes and are excluded.
    """
    root = DOC_ROOT
    files = [root / "CONTEXT.md"]
    files += sorted((root / "orchestration" / "omnicli" / "hooks").glob("*.py"))
    files += sorted((root / "orchestration" / "omnicli" / "plugin").glob("*.js"))
    files += sorted(p for p in (root / "orchestration" / "omnicli" / "references").glob("*.md")
                    if not p.name.startswith("plan-"))
    return [p for p in files if p.exists()]


def item(name, ok, detail):
    return {"name": name, "status": "PASS" if ok else "FAIL", "detail": " ".join(str(detail).split())[:240]}


def native_tools():
    text = (SKILL / "plugin" / "omnicli-route.js").read_text()
    found = set(re.findall(r"def\(\s*\"([a-z][a-z0-9_-]*)\"", text))
    return item("native_tools", found == NATIVE,
                f"plugin registers {sorted(found)}; want {sorted(NATIVE)}")


def mcp_face(timeout):
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    def probe(opt_in):
        env = dict(os.environ)
        env.pop("OMNICLI_MCP_ALLOW_EXEC", None)
        if opt_in:
            env["OMNICLI_MCP_ALLOW_EXEC"] = "1"
        p = subprocess.run([sys.executable, str(SKILL / "omnicli.py"), "mcp"],
                           input=json.dumps(req) + "\n", text=True,
                           capture_output=True, timeout=timeout, cwd=str(SKILL), env=env)
        return {t["name"] for t in json.loads(p.stdout)["result"]["tools"]}

    try:
        default = probe(False)
        enabled = probe(True)
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError) as e:
        return item("mcp_face", False, f"probe failed: {e}")
    # One-tool shape: omni_exec is the only visible tool in both states. The
    # opt-in flag now gates execution, not listing.
    ok = default == MCP and enabled == MCP
    return item("mcp_face", ok,
                f"default={sorted(default)}; with OMNICLI_MCP_ALLOW_EXEC=1={sorted(enabled)}")


def doc_claims():
    hits = []
    for path in docs():
        for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if any(re.search(p, line, re.I) for p in STALE):
                hits.append(f"{path.name}:{n}: {line.strip()[:100]}")
    return item("doc_claims", not hits,
                "no stale tool-count claims" if not hits else " | ".join(hits[:4]))


def stale_search_routing():
    hits = []
    for path in search_routing_docs():
        for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if any(re.search(p, line, re.I) for p in STALE_SEARCH):
                hits.append(f"{path.name}:{n}: {line.strip()[:100]}")
    return item("stale_search", not hits,
                "no stale search-routing claims" if not hits else " | ".join(hits[:4]))


def documented_commands(timeout):
    verbs = set()
    methods = set()
    for path in docs():
        text = path.read_text(errors="replace")
        verbs.update(re.findall(r"`omnicli\s+([a-z][a-z0-9_-]*)\b", text))
    # Code-mode method names are validated against the authoritative routing
    # docs only. Retired names in historical adapter docs are owned by that
    # doc's slice, not by this gate.
    for path in search_routing_docs():
        text = path.read_text(errors="replace")
        methods.update(re.findall(r"`tools\.omnicli\.([a-z][a-z0-9_-]*)\b", text))
    try:
        p = subprocess.run(["omnicli", "--help"], capture_output=True, text=True,
                           timeout=timeout, cwd=str(SKILL))
        help_text = (p.stdout or "") + (p.stderr or "")
        m = re.search(r"\{([a-z][a-z0-9_,\-]+)\}", help_text)
        live = {v.strip() for v in m.group(1).split(",")} if m else set()
        aliases = {"health": "status", "plan": "exec", "browser": "cdp"}
        for canonical, alias in re.findall(
            r"^\s{4}([a-z][a-z0-9_-]*)\s+\(([a-z][a-z0-9_-]*)\)", help_text, re.M
        ):
            aliases[alias] = canonical
    except (OSError, subprocess.TimeoutExpired) as e:
        return item("commands", False, f"omnicli --help failed: {e}")
    bad_verbs = sorted(v for v in verbs if v not in live and v not in aliases)
    bad_methods = sorted(methods - KNOWN_METHODS)
    ok = not bad_verbs and not bad_methods
    detail = f"{len(verbs)} verbs, {len(methods)} code-mode methods checked"
    if not ok:
        detail = f"unknown verbs={bad_verbs} methods={bad_methods}"
    return item("commands", ok, detail)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--timeout", type=float, default=20.0)
    a = ap.parse_args(argv)
    checks = [native_tools(), mcp_face(a.timeout), doc_claims(),
              stale_search_routing(), documented_commands(a.timeout)]
    ok = all(c["status"] == "PASS" for c in checks)
    if a.json:
        print(json.dumps({"ok": ok, "checks": checks}, indent=2))
    else:
        for c in checks:
            print(f"{c['status']:<4}  {c['name']:<20}  {c['detail']}")
        print(f"doc drift: {'clean' if ok else 'DETECTED'} "
              f"({sum(c['status'] == 'PASS' for c in checks)}/{len(checks)} pass)")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # pragma: no cover - unexpected only
        print(f"doc_drift_check: internal error: {e}", file=sys.stderr)
        sys.exit(2)
