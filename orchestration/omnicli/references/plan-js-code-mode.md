# Plan — JSON-Schema-driven, JavaScript-first Code Mode

Status: **built and verified 2026-11-17.** Run state: `.apiv/js-code-mode/`
(plan, six strict briefs, per-slice & 5-level evidence). Predecessor on the same
files: [plan-code-mode-limits.md](plan-code-mode-limits.md) (budgets, fan-out,
sandbox, bridge, trace).

## Why

1. **Scraper drift:** `omnicli` scraped `--help` text with regexes (`registry.py`
   + `argspec.py`), discarding `argparse` types (`type=int`, `type=float`,
   required flags, subparser splits) and failing 11 `typing`/`declared` gates in
   `scripts/verify_code_mode.py` (such as `--mem-limit MiB`).
2. **Double-nested Python overhead:** Running `plan.py` inside Node/JS harnesses
   forced extra boilerplate and broke `strict` mode whenever `.venv/bin/python`
   lived under `$HOME` (`bwrap --tmpfs $HOME` hid the interpreter).
3. **Interface vs. Execution split:** Following Claude Code Code Mode and
   Cloudflare Code Mode, split the two roles cleanly: extract real JSON Schemas
   (`inputSchema`) from live `argparse` parsers, generate **TypeScript `.d.ts`
   declarations** (`omnicli_tools.d.ts`, `omnicli spec --stubs`) for LLM context,
   and run **plain JavaScript** (`omnicli_tools.mjs`) inside `node:vm` +
   Bubblewrap (`bwrap`) with zero runtime `tsc` compilation overhead.

## Outcome

| Slice | Shipped | Evidence |
|---|---|---|
| **1 — JSON Schema extraction** | `catalog/schema_extract.py` (`argparse.ArgumentParser.print_help` probe hook + `contract_to_input_schema` fallback + `merge_parent_schema`), `CONTRACT_PARSER_VERSION = 8` | 25 tests in `test_schema_extract.py`; `551/577` tools carry `inputSchema`; `verify_code_mode --tier b1` reports `clean: true` (`0` `typing`/`declared` violations across 577 tools) |
| **2 — JS bindings & `.d.ts` stubs** | `argspec.py` prefers `inputSchema` + emits TS `.ts_sig()`/`ts_decl()`/`ts_stub()`; `bindings.py` (`BINDINGS_VERSION = "5"`) generates `omnicli_tools.mjs` (555,940 B) + `omnicli_tools.d.ts` (156,099 B) with pre-dispatch schema validation, `parallel()`, `node:net` UDS bridge path, budget, and trace parity | `node --check omnicli_tools.mjs` rc 0; `test_usage.py` `JsBindings` parity passes; `TestBindings` schema validation rejects unknown/missing/enum/type with `TypeError` before dispatch |
| **3 — `node:vm` runner, CLI & gate** | `catalog/vm_runner.mjs` (ESM `SourceTextModule` + classic async-IIFE `vm.runInContext`), `catalog/exec_runner.py` extracted (`omnicli.py` shrunk 2,079 → 1,853 lines), host `node` `--ro-bind` into `/tmp/omnicli/node`, `--mem-limit` via `--max-old-space-size` + `RLIMIT_AS` floor, `.py`/`--lang py` retired at exit 2 | `omnicli.py` 1,853 ≤ 2,079 ceiling; `--sandbox strict` `bridge_calls=1`, `bridge_denied=['exec']`, `rc=126`; `--max-calls 2` trips; `--mem-limit 64` trips (rc 134); `plan.py` exits 2 |
| **4A — Hook & OpenCode plugin** | `plugin/omnicli-route.js` & `hooks/agy_omnicli_hook.py` teach JS-first Code Mode (`omnicli exec -c` / `plan.mjs`), `spec --stubs`, and gate 3+ inline `python3 -c` or `node -e` probes | `node --check omnicli-route.js` rc 0; `test_agy_hook.py` passes (triggered live during verification when 3+ `python3 -c` probes fired!) |
| **4B — Harness & docs** | `catalog/harness.py`, `SKILL.md`, `README.md`, `references/code-mode-sdk.md`, `harnesses/*.md`, `examples/{discovery_and_invoke,in_memory_filter}.mjs` (old `.py` examples deleted) | `omnicli harness verify` **PASS** 5/5 (`t3-code` 6/6, `agy` 6/6, `opencode` 6/6, `pi` 5/5, `boxxy` 5/5); both `.mjs` examples exit 0 cleanly |
| **5 — Read-only DB bind (`write` mode)** | `builder.connect()` (`timeout=30.0`, `OMNICLI_DB_RO=1` opens `?immutable=1` without `executescript`); `exec_runner.py` checkpoints WAL (`PRAGMA wal_checkpoint(TRUNCATE)`) and `--ro-bind`s `catalog.db` + `policy.json` into `/tmp/omnicli/data/` in `write` mode | 10-call `parallel()` fan-out in empty workspace under `--sandbox write` dropped from 31.2s + `database is locked` to **0.283s, rc 0**, `tool_calls=10`, zero `.local/` created (`TestCatalogReadOnly` + `TestExec`) |

## Decisions taken

| Fork | Decision | Why |
|---|---|---|
| Runtime: `workerd`, Deno, Monty, or host `node` | **Host `node` (`v26.10.0`) + `node:vm` inside `bwrap`** | Zero new runtime install, native ESM + `node:net` UDS bridge, real OS isolation via `bwrap`, `--ro-bind` host `node` binary bypasses `$HOME` masking |
| Script language: TypeScript vs. JS + `.d.ts` | **Plain JS executed, TS `.d.ts` in prompt** | Zero `tsc`/transpile latency and zero type-check false failures on throwaway orchestration scripts while keeping full typed schema hints (`omnicli spec --stubs`) |
| Dual-stack Python `exec` vs. deprecate | **Retire `.py` / `--lang py` at exit 2** | One SDK generator, one sandbox runner, clear migration message pointing to `plan.mjs` and `spec --stubs` |
| Scope | **Scope A (gateway only)** | `orchestration/omnicli/` + `.apiv/js-code-mode/` only; downstream skill `--fields`/`--project` (`b2b: 10`) and repo-root `AGENTS.md` left for dedicated passes |

## Measured workstation gotchas

- **V8 CodeRange vs `RLIMIT_AS`:** Node 26 reserves ~1.5 GiB virtual address space; `prlimit --as <= 1024 MiB` aborts Node before JS starts. `--mem-limit <MiB>` therefore sets `node --max-old-space-size=<MiB>` (enforcing the JS heap cap cleanly down to 64 MiB) plus `prlimit --as=<max(MiB, 2048) MiB>`.
- **Empty-workspace rebuild lock (`write` mode):** Because `exec_runner` points `HOME` at `<workspace>`, parallel child `omnicli` invocations saw no `<workspace>/.local/share/omnicli/catalog.db` and raced to rebuild the 577-tool catalog inside `<workspace>` (explaining the 26–31s `database is locked` failure also noted in [plan-code-mode-limits.md](plan-code-mode-limits.md)). Checkpointing WAL and `--ro-bind`ing `catalog.db` + `policy.json` with `OMNICLI_DB_RO=1` (`?immutable=1`) eliminates rebuilds and locking in `write` mode.
- **Line-count ratchet (`9dce5a3`):** Extracting `exec_runner.py` dropped `omnicli.py` from 2,079 → 1,853 lines while keeping every new module well below 1,000 lines.

## Shape

```
plan.mjs / -c ──▶ omnicli exec [--sandbox write|strict|none] [--max-calls 100] [--mem-limit N]
                    │
                    ├── bwrap (--ro-bind node, vm_runner.mjs, bindings/; write: --ro-bind catalog.db RO)
                    ├── node:vm (ESM SourceTextModule + classic async-IIFE with omnicli_tools globals)
                    ├── OMNICLI_MAX_CALLS ──▶ bindings reserve before dispatch
                    ├── OMNICLI_BRIDGE ─────▶ node:net UNIX socket fast-path (strict) / execFile (write)
                    ├── OMNICLI_TRACE ──────▶ kind=call{t} / kind=done{ms,rc}
                    └── OMNICLI_RESULT ─────▶ emitResult() ──▶ exec --json .result
```
