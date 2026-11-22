# One-tool harness adapter

`orchestration/omnicli/catalog/one_tool_adapter.py` is a reversible view over
the tool surface the harness sees. Normally the harness front line
(`plugin/omnicli-route.js`, mirrored by the MCP face) registers the native
omnicli tools `omnicli_search`, `omnicli_invoke` and `omnicli_exec`. The adapter
can collapse that surface to exactly one visible tool — the code-exec surface
`omnicli_exec` — and switch back to the previous surface on demand.

The adapter is a *client-side view*. It is not an install step and it writes no
host state: no checkout file, no harness config, no `ports.json`, no policy
file. Enabling and disabling flip an in-memory flag, so the switch is always
reversible and there is nothing persistent to undo or commit.

## How to enable and disable it

Per invocation (the `--one-tool` flag applies only to that process):

```bash
# One-tool state: the harness sees exactly one visible tool.
python3 orchestration/omnicli/catalog/one_tool_adapter.py --one-tool count
# -> 1

# Disabled state: the previous (full) surface is back.
python3 orchestration/omnicli/catalog/one_tool_adapter.py count
# -> 3

# Machine-readable detail, including the count and both surfaces.
python3 orchestration/omnicli/catalog/one_tool_adapter.py --one-tool status
```

In process, the same switch plus a guarded form that restores the prior mode
even when the body raises:

```python
from catalog.one_tool_adapter import OneToolAdapter

adapter = OneToolAdapter()
adapter.enable()                 # visible_tool_count() == 1
adapter.disable()                # visible_tool_count() == 3 (previous surface restored)

with adapter.enabled():          # temporarily one-tool, always restored on exit
    assert adapter.visible_tool_count() == 1
assert adapter.visible_tool_count() == 3
```

`previous_surface` is snapshotted when the adapter is constructed, so
`disable()` always restores that exact surface (`omnicli_search`,
`omnicli_invoke`, `omnicli_exec`) rather than whatever happens to be around
later.

## Relation to the front-line state file

This machine already runs gateway mode: `~/.config/skills-frontline` selects
the `gateway` front line, so `surface/` exposes only the `omnicli` skill and
`sync-skills` keeps the harness copies in step. The adapter works one layer
below that, on the native tools the gateway registers: it narrows the
gateway's visible surface from those tools down to `omnicli_exec`.

It deliberately does **not** write `~/.config/skills-frontline`, does not call
`sync-skills propagate`, and does not edit the plugin or `opencode.json`. The
front-line state file is read by `sync-skills` and is shared host state;
touching it would make the switch a committed host-state change. The adapter
never does.

## Every inner call still passes the enable/disable gate

The one visible tool is the exec surface. Everything a plan does from inside
that surface is an *inner call*, and each one is checked against the existing
gate before it can run. One-tool mode changes **visibility only, never
authorization** — it cannot be used to reach a tool the gate has refused.

The gate evaluation is deliberately the same decision `omnicli invoke`
enforces, read-only:

1. An explicit decision in `policy.json` wins. `omnicli enable <tool_id>` and
   `omnicli disable <tool_id>` write that file, so its verdict is authoritative.
2. Otherwise the catalog's `enabled` column decides. That is the flag
   `omnicli invoke` checks at execution time; the catalog rebuild re-applies
   `policy.json` on top of it.
3. A tool absent from both is refused (fail-closed).

No inner call bypasses this, whether the adapter is in one-tool mode or full
mode. `inner_call()` returns a structured allow/refuse record; a refusal raises
`DisabledToolError` so the command exits non-zero. The in-process `verify`
check proves both directions: a disabled tool is refused (negative control)
and an enabled tool is still allowed (positive control). A gate that only ever
refused would be useless, so both are required.

## The claim is observable

- `visible_tool_count()` returns `1` in the enabled state and the size of the
  previous surface in the disabled state.
- `status` prints `visible_tool_count`, `visible_tools`, `previous_surface`,
  the gate name, and an in-memory audit of inner calls as JSON.
- `verify` runs the mechanical checks in one process and exits 0 only if every
  check passes; its JSON report gives a PASS/FAIL line per check.

## Mechanical checks

Buffer verbose output to a file; only exit codes and the compact verdict are
reported. From the checkout root:

| Check | Command | Expected |
| :--- | :--- | :--- |
| Enabled state reports one visible tool | `python3 orchestration/omnicli/catalog/one_tool_adapter.py --one-tool count` | prints `1`, exit 0 |
| Disabled state restores previous surface | `python3 orchestration/omnicli/catalog/one_tool_adapter.py count` | prints `3`, exit 0 |
| Negative control — disabled tool refused | `python3 orchestration/omnicli/catalog/one_tool_adapter.py --one-tool invoke "$DISABLED"` where `$DISABLED` is an id from `omnicli policy --json` | `REFUSED: ...`, exit 3 |
| Positive control — enabled tool allowed | `python3 orchestration/omnicli/catalog/one_tool_adapter.py --one-tool invoke "$ENABLED"` | allow record, exit 0 |
| All checks in one process | `python3 orchestration/omnicli/catalog/one_tool_adapter.py --one-tool verify` | `"ok": true`, exit 0 |
| Distribution stays clean | `sync-skills verify` | clean, exit 0 |

The negative control is mandatory. If a disabled tool is ever allowed through
the adapter, or if the enabled count is not exactly one, `verify` fails.
