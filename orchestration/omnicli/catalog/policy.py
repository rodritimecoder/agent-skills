"""Tool enablement policy: the gate between discovery and exposure.

Uber's MCP Gateway is built on one sentence — *discovery does not imply
exposure*. AutoCrawler may catalogue any service it finds, but every server
and tool lands **disabled**, and the owning team has to review and enable it.

This module is that principle at single-user scale. A tool that appears in
the catalog is discoverable (`search`, `tools`, `describe`); it is runnable
only once it has been enabled here. Two consequences worth stating plainly:

* A tool that is new *relative to the previous catalog* starts disabled.
  Dropping a script into a skill does not make it callable by an agent.
* The decision is recorded as an append-only line containing the contract
  hash it was made against, so an enablement can be reviewed and reverted
  instead of being an invisible boolean.

The policy file is the source of truth, not the catalog. The catalog is
rebuilt from disk at any time; this file survives that and is re-applied.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

POLICY_VERSION = 1
POLICY_FILE = "policy.json"
LOG_FILE = "policy.log.jsonl"


def _dir() -> Path:
    from . import builder

    return builder.db_path().parent


def _path() -> Path:
    return _dir() / POLICY_FILE


def _log_path() -> Path:
    return _dir() / LOG_FILE


def load() -> dict[str, Any]:
    path = _path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": POLICY_VERSION, "tools": {}}
    if not isinstance(data, dict):
        return {"version": POLICY_VERSION, "tools": {}}
    data.setdefault("version", POLICY_VERSION)
    tools = data.get("tools")
    data["tools"] = tools if isinstance(tools, dict) else {}
    return data


def save(data: dict[str, Any]) -> None:
    """Write atomically: a half-written policy file would gate everything."""
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".policy-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def contract_digest(contract: Any) -> str:
    blob = json.dumps(contract or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def decide(tool_id: str, default: bool) -> bool:
    """The effective state: an explicit decision wins, otherwise the default."""
    entry = load()["tools"].get(tool_id)
    if isinstance(entry, dict) and isinstance(entry.get("enabled"), bool):
        return entry["enabled"]
    return default


def entry(tool_id: str) -> dict[str, Any] | None:
    item = load()["tools"].get(tool_id)
    return item if isinstance(item, dict) else None


def set_enabled(tool_id: str, enabled: bool, *, contract: Any = None,
                note: str = "") -> dict[str, Any]:
    """Record a decision and append the diff to the audit log."""
    data = load()
    before = data["tools"].get(tool_id, {}).get("enabled")
    record = {
        "enabled": bool(enabled),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "contract": contract_digest(contract),
    }
    if note:
        record["note"] = note
    data["tools"][tool_id] = record
    data["version"] = POLICY_VERSION
    save(data)

    line = {
        "at": record["at"],
        "tool": tool_id,
        "before": before,
        "after": bool(enabled),
        "contract": record["contract"],
    }
    try:
        with _log_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return record


def history(tool_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    try:
        lines = _log_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if tool_id and rec.get("tool") != tool_id:
            continue
        out.append(rec)
    return out[-limit:]


def disabled_ids() -> set[str]:
    return {k for k, v in load()["tools"].items()
            if isinstance(v, dict) and v.get("enabled") is False}
