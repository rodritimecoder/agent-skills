#!/usr/bin/env python3
"""One-tool harness adapter: expose only the code-exec surface, reversibly.

The harness front line (``plugin/omnicli-route.js``, mirrored by the MCP face)
registers three native omnicli tools: ``omnicli_search``, ``omnicli_invoke``
and ``omnicli_exec``. This adapter puts a view in front of that surface that
can collapse it to exactly one visible tool -- the code-exec surface
(``omnicli_exec``) -- and switch back to the full surface on demand.

Two properties are deliberate and load-bearing:

* **Reversible, no committed host state.** Enabling or disabling flips an
  in-memory flag on the adapter object. Nothing is written to the checkout,
  ``opencode.json``, the plugin, ``ports.json`` or the policy file. A
  ``--one-tool`` invocation is per-process; the context-manager form restores
  the previous surface even when the body raises. There is no persistent
  "installed" state to forget to undo.
* **The gate is unchanged.** One-tool mode alters *visibility*, never
  authorization. Every inner call made from the exec plan still goes through
  the existing enable/disable gate (``policy.json``, the source of truth that
  ``omnicli enable`` / ``omnicli disable`` write and ``omnicli invoke``
  enforces). The check is fail-closed: a tool with no explicit enable decision
  is refused. The adapter cannot be used to reach a disabled tool.

``visible_tool_count()`` is the observable claim: in enabled mode it is 1, in
disabled mode it is the size of the previous (full) harness surface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

_HERE = Path(__file__).resolve().parent
_SKILL_DIR = _HERE.parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

try:
    from catalog import policy as _policy  # type: ignore
except ImportError:  # pragma: no cover - degraded install
    _policy = None  # type: ignore

# The harness-native omnicli tool surface, as registered by
# plugin/omnicli-route.js and asserted by tests/doc_drift_check.py. This is the
# "previous surface" the adapter restores when switched off.
HARNESS_SURFACE: tuple[str, ...] = (
    "omnicli_search", "omnicli_invoke", "omnicli_exec",
)

# The single tool kept visible in one-tool mode: the code-exec surface.
EXEC_TOOL = "omnicli_exec"

GATE_NAME = "omnicli enable/disable policy.json (fail-closed)"


class DisabledToolError(PermissionError):
    """An inner call targeted a tool the enable gate has not enabled."""

    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        super().__init__(
            f"tool {tool_id!r} is disabled by the omnicli enable gate; "
            f"enable it with `omnicli enable <tool_id>` after reviewing its contract"
        )


def _decisions() -> dict[str, bool]:
    """Explicit enable/disable decisions recorded in policy.json."""
    if _policy is None:
        return {}
    try:
        tools = _policy.load().get("tools", {})
    except Exception:
        return {}
    return {
        str(k): bool(v.get("enabled"))
        for k, v in tools.items() if isinstance(v, dict)
    }


def _catalog_state() -> dict[str, bool]:
    """Effective enabled flags from the catalog, opened strictly read-only.

    ``omnicli invoke`` gates on the catalog's ``enabled`` column. The catalog
    rebuild re-applies policy.json on top of it, so reading the column is the
    same decision enforcement sees. ``immutable=1`` prevents SQLite from
    creating or writing the database when it is missing.
    """
    try:
        from catalog import builder  # type: ignore

        path = builder.db_path()
        if not path.is_file():
            return {}
        con = sqlite3.connect(
            f"{path.resolve().as_uri()}?immutable=1", uri=True, timeout=5.0
        )
        try:
            return {str(row[0]): bool(row[1])
                    for row in con.execute("SELECT id, enabled FROM tools")}
        finally:
            con.close()
    except Exception:
        return {}


def _effective_enabled(tool_id: str) -> bool:
    """An explicit policy decision wins; otherwise the catalog flag decides.

    Fail-closed: an unknown tool (in neither policy.json nor the catalog) is
    not runnable. Nothing here writes host state.
    """
    if not isinstance(tool_id, str) or not tool_id:
        return False
    decisions = _decisions()
    if tool_id in decisions:
        return decisions[tool_id]
    return _catalog_state().get(tool_id, False)


def policy_gate(tool_id: str) -> bool:
    """The existing enable/disable gate, evaluated without side effects."""
    return _effective_enabled(tool_id)


def disabled_tool_ids() -> list[str]:
    state = _catalog_state()
    state.update(_decisions())
    return sorted(tid for tid, enabled in state.items() if not enabled)


def enabled_tool_ids() -> list[str]:
    state = _catalog_state()
    state.update(_decisions())
    return sorted(tid for tid, enabled in state.items() if enabled)


def _policy_digest() -> str:
    """Fingerprint of the gate file, to prove the adapter never writes it."""
    if _policy is None:
        return "unavailable"
    try:
        data = _policy._path().read_bytes()
    except OSError:
        return "missing"
    return hashlib.sha256(data).hexdigest()


class OneToolAdapter:
    """View over the harness surface that can collapse to the exec tool only.

    ``previous_surface`` is a snapshot taken at construction; ``disable()``
    always restores exactly that snapshot, so switching back cannot drift.
    """

    def __init__(
        self,
        surface: Sequence[str] = HARNESS_SURFACE,
        exec_tool: str = EXEC_TOOL,
        gate: Callable[[str], bool] = policy_gate,
    ) -> None:
        tools = tuple(dict.fromkeys(surface))
        if not tools:
            raise ValueError("harness surface must not be empty")
        if exec_tool not in tools:
            raise ValueError(f"exec tool {exec_tool!r} is not part of the surface")
        self.previous_surface = tools
        self.exec_tool = exec_tool
        self.gate = gate
        self._one_tool = False
        self._calls: list[dict[str, Any]] = []

    def enable(self) -> "OneToolAdapter":
        self._one_tool = True
        return self

    def disable(self) -> "OneToolAdapter":
        """Switch back to the full, previous harness surface."""
        self._one_tool = False
        return self

    @property
    def one_tool(self) -> bool:
        return self._one_tool

    def visible_tools(self) -> tuple[str, ...]:
        return (self.exec_tool,) if self._one_tool else self.previous_surface

    def visible_tool_count(self) -> int:
        return len(self.visible_tools())

    @contextmanager
    def enabled(self) -> Iterator["OneToolAdapter"]:
        """Temporarily enable one-tool mode, restoring the prior mode on exit."""
        was = self._one_tool
        self.enable()
        try:
            yield self
        finally:
            self._one_tool = was

    def inner_call(
        self, tool_id: str, *, args: Sequence[str] = ()
    ) -> dict[str, Any]:
        """Route an inner call (made from the exec plan) through the gate.

        One-tool mode changes visibility only; it never grants authority. A
        refused call raises ``DisabledToolError`` so the CLI can exit non-zero.
        Allowed and refused calls are both recorded in the in-memory audit.
        """
        allowed = self.gate(tool_id)
        record: dict[str, Any] = {
            "tool": tool_id,
            "args": list(args),
            "gate": GATE_NAME,
            "allowed": allowed,
        }
        self._calls.append(record)
        if not allowed:
            raise DisabledToolError(tool_id)
        record["status"] = "allowed"
        return record

    def report(self) -> dict[str, Any]:
        return {
            "one_tool": self._one_tool,
            "mode": "one-tool" if self._one_tool else "full",
            "exec_tool": self.exec_tool,
            "visible_tool_count": self.visible_tool_count(),
            "visible_tools": list(self.visible_tools()),
            "previous_surface": list(self.previous_surface),
            "gate": GATE_NAME,
            "host_state_written": False,
            "inner_calls": list(self._calls),
        }


def _check(name: str, ok: bool, detail: str) -> dict[str, str]:
    return {"name": name, "status": "PASS" if ok else "FAIL", "detail": detail}


def verify(adapter: OneToolAdapter | None = None) -> dict[str, Any]:
    """Run the mechanical checks in-process; return a structured report."""
    adapter = adapter or OneToolAdapter()
    original_mode = adapter.one_tool
    checks: list[dict[str, str]] = []
    digest_before = _policy_digest()

    try:
        adapter.enable()
        visible = list(adapter.visible_tools())
        count = adapter.visible_tool_count()
        checks.append(_check(
            "one_tool_count",
            count == 1 and visible == [adapter.exec_tool],
            f"enabled: {count} visible tool(s) {visible}; "
            f"want exactly [{adapter.exec_tool!r}]",
        ))

        disabled = disabled_tool_ids()
        if not disabled:
            checks.append(_check(
                "negative_control", False,
                "no disabled tool in the catalog/policy; cannot prove the gate refuses",
            ))
        else:
            target = disabled[0]
            try:
                adapter.inner_call(target)
            except DisabledToolError as exc:
                checks.append(_check(
                    "negative_control", True,
                    f"disabled tool {target!r} refused with non-zero status ({type(exc).__name__})",
                ))
            else:
                checks.append(_check(
                    "negative_control", False,
                    f"disabled tool {target!r} was NOT refused; the gate is broken",
                ))

        allowed = enabled_tool_ids()
        if not allowed:
            checks.append(_check(
                "positive_control", False,
                "no enabled tool in the catalog/policy; cannot prove the gate can pass",
            ))
        else:
            target_ok = allowed[0]
            try:
                adapter.inner_call(target_ok)
            except DisabledToolError:
                checks.append(_check(
                    "positive_control", False,
                    f"enabled tool {target_ok!r} was refused; the gate cannot pass",
                ))
            else:
                checks.append(_check(
                    "positive_control", True,
                    f"enabled tool {target_ok!r} allowed through the same gate",
                ))

        checks.append(_check(
            "enabled_state_count", adapter.visible_tool_count() == 1,
            f"visible_tool_count()={adapter.visible_tool_count()} in enabled state",
        ))

        adapter.disable()
        restored = list(adapter.visible_tools())
        checks.append(_check(
            "disabled_restores_surface",
            (not adapter.one_tool) and restored == list(adapter.previous_surface)
            and adapter.visible_tool_count() == len(adapter.previous_surface),
            f"after disable: one_tool={adapter.one_tool}, "
            f"visible_tool_count()={adapter.visible_tool_count()}, surface={restored}",
        ))
    finally:
        if original_mode:
            adapter.enable()
        else:
            adapter.disable()

    digest_after = _policy_digest()
    checks.append(_check(
        "no_host_state_change",
        digest_before == digest_after,
        f"policy.json digest unchanged: {digest_before[:12]}",
    ))

    ok = all(c["status"] == "PASS" for c in checks)
    return {"ok": ok, "checks": checks}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="one_tool_adapter",
        description="Reversible one-tool (code-exec) view of the harness surface.",
    )
    p.add_argument(
        "--one-tool", action="store_true",
        help="show only the exec tool for this invocation (default: full surface)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="print the full adapter report as JSON")
    sub.add_parser("count", help="print the currently visible tool count")
    sub.add_parser("surface", help="print the currently visible tool ids as JSON")
    inv = sub.add_parser("invoke", help="make an inner call through the enable gate")
    inv.add_argument("tool_id")
    inv.add_argument("args", nargs="*")
    sub.add_parser(
        "verify", help="run the mechanical checks (counts, negative control, restore, no host writes)",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    adapter = OneToolAdapter()
    if args.one_tool:
        adapter.enable()

    if args.cmd == "status":
        print(json.dumps(adapter.report(), indent=2))
        return 0
    if args.cmd == "count":
        print(adapter.visible_tool_count())
        return 0
    if args.cmd == "surface":
        print(json.dumps(list(adapter.visible_tools())))
        return 0
    if args.cmd == "invoke":
        try:
            record = adapter.inner_call(args.tool_id, args=args.args)
        except DisabledToolError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 3
        print(json.dumps(record))
        return 0
    if args.cmd == "verify":
        report = verify(adapter)
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
