# Plan — bounded Code Mode: budgets, fan-out, and a truthful surface

Status: **built and shipped 2026-11-13.** Run state: `.apiv/code-mode-limits/`
(plan, five strict briefs, per-slice evidence). Predecessor on the same files:
`.kem-loop/code-mode-catalog/plan.md` (typed signatures, invisible skills).

## Why

Three studies of the same idea — Cloudflare's origin post, UTCP's `code-mode`
packaging, and Pydantic AI Harness's `CodeMode` on Monty — agree on one thing this
skill did not do: replace N model turns with one program, then bound that program.
`omnicli exec` already had the seam (file, shell, sandbox, catalog) and none of the
bounds. Two independent studies also showed the docs had drifted: the skill
advertised an MCP face that `omnicli mcp` had retired, and the repo's own
"architectural standard" taught an import path that does not exist.

## Outcome

| Slice | Shipped | Evidence |
|---|---|---|
| MCP removal | `mcp` verb deleted, 934 lines archived to `archived/omnicli-mcp/`, every live claim removed from 9 files, `harness config opencode` emits skills-only JSON | 61+11 tests, `omnicli mcp` rc 2 |
| Async fan-out | `asearch`/`adescribe`/`ainvoke`/`aoutput`/`askills`/`atools`, `parallel(calls, limit=8)`, shared `_argv_*` helpers | 10 calls: 826 ms serial → 180 ms, 2.02× single-call |
| Call budget | `--max-calls` default 100, `0` = unlimited, reserved before dispatch, `RuntimeError` at the call site naming the count | 100 allowed, 101 trips, enforced in `strict` |
| Result | `emit_result(value)` → `exec --json .result`, stdout untouched | present/absent across runs, plain mode unchanged |
| Trace | `kind=call` (with `t`) then `kind=done` (with `ms`, `rc`) | start-without-done now marks a stalled call |
| Memory cap | `--mem-limit MiB`, opt-in, no default, via `prlimit --as` on the bwrap process | 200 MiB alloc dies at 128, survives at 512 |

## Decisions taken

| Fork | Decision | Why |
|---|---|---|
| Retire MCP or revive it | **Archive** | The server worked, which is why it kept re-entering the docs. Ranking: variables beat round-trips. |
| Kernel sandbox or interpreter subset | **Keep bubblewrap** | Monty is a Python subset in Rust (no pandas, no C extensions); a plan here gets real CPython. UTCP's Python client runs `RestrictedPython` in-process with tools at full privilege. |
| Default memory cap | **None** | The right number is a property of the plan. Below 512 MiB is unsupported and the failure is thread creation, not allocation. |
| Trace: per-run unlink or append | **Append with a row offset** | A hung call's evidence must survive the next run. A zero-call run still reports `tool_calls=0`. |
| Copy Monty's eager/speculative execution | **No** | Needs the model's token stream; this runner sees a file. |

## What the gates caught (worth keeping as practice)

- Two builder changes were made to satisfy probes that read the CLI's raw streams
  instead of the JSON payload: a stderr echo (kept, harmless) and trace appending
  (kept, but only after boundary tests). A gate must read the payload, or the
  builder reshapes the product to match the probe.
- One builder edit stripped the backticks from a doc's exit-code table to satisfy a
  literal assertion. Reverted, gate fixed. Same cause.
- `bwrap 0.12.0` has no `--rlimit-*`; the cap is `prlimit --as=N:N -- bwrap`. The
  plan assumed otherwise; the builder measured instead of following the plan.

## Open observation

1 failure in ~2,300 sandboxed tool calls (rc 1, 9 of 10 calls, 26.95 s, no
traceback). Not reproduced in 205 sandboxed runs, 400 serial calls, 400
unsandboxed fan-out calls, 25 runs under doubled load, 192 concurrent searches, or
a deliberate rebuild-collision test. A `database is locked` was seen once by a
builder; WAL with `busy_timeout=5000` is compatible with the story but does not
prove it. Next occurrence is diagnosable: the trace now records start and done
rows with elapsed time.

## Shape

```
plan.py ──▶ omnicli exec [--sandbox write|strict] [--max-calls 100] [--mem-limit N]
              │
              ├── bwrap (namespaces; strict: no net, HOME masked, UDS bridge)
              ├── OMNICLI_MAX_CALLS ──▶ bindings reserve before dispatch
              ├── OMNICLI_TRACE ──────▶ kind=call{t} / kind=done{ms,rc}
              └── OMNICLI_RESULT ─────▶ emit_result() ──▶ exec --json .result
```

Three references informed it, none adopted whole:
Cloudflare (one program beats N calls), UTCP (packaging: libs, CLI, MCP server),
Pydantic/Monty (budgets as separate failure modes). This workstation keeps the
kernel boundary and real CPython, and takes the budgets.
