# Plan: native omnicli tools for OpenCode / T3 Code

**Run:** `.apiv/t3-omnicli-route` · **Date:** 2026-11-13 · **Status:** VERIFIED

## Problem

T3 Code drives a provider; this workstation uses OpenCode. T3's own bundle has
zero omnicli references, and omnicli reached the session only as prose in a
skill (`surface/omnicli` → `orchestration/omnicli`). The agent's native tools —
`read`, `grep`, `glob`, `bash`, and OpenCode's own `execute` — were always one
call away, while `omnicli` was a subprocess behind a shell. The documented
anti-pattern ("never cat/grep skill directories") had no enforcement.

`omnicli harness verify t3-code` returned 5/5 PASS while nothing was wired: it
checked the binary, catalog, doc path, config dirs, and Python bindings.

## Decision

Do not revive MCP (retired in `.apiv/code-mode-limits` slice 1) and do not fork
T3. Put the catalogue in OpenCode's tool registry, where T3 already reads tools,
and let OpenCode's Code Mode call the same functions as `tools.omnicli.*`.

Rejected: an MCP shim; a T3 driver; a blanket native-tool ban; registering all
555 tools; a fifth instruction-only document.

## What shipped

`orchestration/omnicli/plugin/omnicli-route.js`, symlinked to
`~/.config/opencode/plugins/omnicli-route.js`:

| Piece | Behaviour |
|---|---|
| Tools | `omnicli_search`, `describe`, `invoke`, `exec`; `codemode: true`; argv arrays; 8 KB default cap. |
| Routing | `session.hook("context")` appends `[omnicli route]` with the exact Code Mode names. |
| Gate | `tool.hook("execute.before")` denies `read`/`grep`/`glob`/`list` and read-only shell verbs under `~/src/my-agent-skills/**` until a catalogue call primes the session. Exempt: project root inside the skills repo, or `.omnicli-route-exempt`. |
| Log | `~/.local/share/omnicli/route.jsonl`; `scripts/route_stats.py` reports the skill-dir bypass rate. |

Harness truth: `catalog/harness.py` now emits the install block and verifies a
`native_tool_plugin` check; `harnesses/t3-code.md`, `harnesses/opencode.md`, and
`SKILL.md` describe native tools as the default path.

## Evidence

- Spike in OpenCode 2.2.6: transform tool called as `tools.spike.echo`; a throw
  in `execute.before` reached the model as `SPIKE_DENIED`.
- Integration, standalone project outside the skills repo:
  - `tools.omnicli.search({query:"transcribe a zoom lecture"})` returned the
    real BM25 result for `video-miner`;
  - `read` of `orchestration/omnicli/SKILL.md` without a prior catalogue call
    was denied with the gate message.
- Live T3 Code catalog after the symlink: `omnicli (4 tools)` with
  `tools.omnicli.describe|exec|invoke|search`.
- `omnicli harness verify t3-code` → 6/6 PASS, `native_tool_plugin: source=True
  link=True node_check=True`.
- `node --test plugin/omnicli-route.test.mjs` → 7/7.
- `python3 tests/test_harness.py` → 11/11.

## Known limits

- The gate is heuristic: `bash` is checked only for read-like verbs plus the
  skills path; a determined agent can read via an arbitrary interpreter.
  The metric makes that visible rather than pretending it is impossible.
- The plugin is global, so it applies to every OpenCode project. The project
  exemption and the marker are the escape hatches.
- `exec` plans are kept under `~/.local/share/omnicli/plans/` for audit; they
  are not deleted automatically.
