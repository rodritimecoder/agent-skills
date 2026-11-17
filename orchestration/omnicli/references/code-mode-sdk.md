# JavaScript SDK & Code Mode Execution (`omnicli exec`)

## 🏛️ Architectural Provenance

The `omnicli` architecture unifies two foundational production AI patterns:

1. **Uber's MCP Gateway** ([Uber Engineering: Designing an MCP Gateway](https://www.uber.com/au/en/blog/designing-mcp-gateway/)):
   - **Late-Binding Discovery**: Instead of dumping hundreds of tool schemas into turn-0 model context (which triggers the Databricks tool-shadowing degradation), tools are catalogued out-of-band via AutoCrawler/builder into SQLite FTS5 + dense embeddings.
   - **Bounded Meta-Tools**: Agents discover tools by intent (`search`), inspect single contracts on-demand (`describe`), invoke them with strict byte caps and field projections (`invoke`), and monitor service health (`status`).

2. **Cloudflare's Code Mode** ([Cloudflare Blog: Code Mode — Execute Code to Invoke Tools Instead of LLM Function Calling](https://blog.cloudflare.com/code-mode/)):
   - **One Plan, One Turn**: Instead of multiple slow, token-expensive round-trips where intermediate tool outputs flood the prompt context, the agent generates executable code (JavaScript) that calls a generated SDK.
   - **Intermediate Isolation**: Data pipelines, filtering, JSON parsing, loops, and conditional logic execute in local memory. Only the final synthesized result (`console.log()` / `emitResult()`) enters the model's context.
   - **Sandboxed Execution**: Code runs in a secure sandbox (Bubblewrap / `bwrap`) with configurable filesystem, network, and capability boundaries.

---

## 📦 The Generated SDK: `omnicli_tools.mjs`

`omnicli bindings` generates `~/.local/share/omnicli/bindings/omnicli_tools.mjs`
plus `omnicli_tools.d.ts`. The module is the runtime surface; the declaration file
is the same contract written as types, which is cheaper for a model to read than
the 500 KB module.

### 1. The Core Gateway API

| Function | Signature | What it does |
|---|---|---|
| `search` | `search(intent, limit = 6)` → `Promise<SearchResult[]>` | Full-body BM25 + dense vector search across all registered skills; ranked candidates with scores, evidence and tool IDs. |
| `skills` | `skills()` → `Promise<unknown>` | List every registered skill. |
| `tools` | `tools(skill)` → `Promise<unknown>` | List the tools registered under one skill. |
| `describe` | `describe(toolId)` → `Promise<object>` | Read one tool's usage contract, flags, parameters and help text. |
| `spec` | `spec(grepOrFilter)` → `SpecRow[]` | Synchronous query over the in-memory spec table — no subprocess. |
| `invoke` | `invoke(toolId, argsOrArgv?, opts?)` → `Promise<InvokeEnvelope>` | Execute any catalogued tool with output bounding and projection. |
| `output` | `output(toolId, argsOrArgv?, opts?)` → `Promise<string>` | The same call, returning only `envelope.output`. |
| `parallel` | `parallel(calls, limit = 8)` → `Promise<unknown[]>` | Fan out async thunks, keeping results in input order. |
| `emitResult` | `emitResult(value)` | Hand one value back on its own channel (`emit_result` is an alias). |
| `getState` | `getState()` → `Record<string, unknown>` | Read the session's JSON object (`{}` when unset). |
| `emitState` | `emitState(value)` | Replace that object; it persists across runs sharing `--session ID`. |

`spec()` takes either a grep string or one filter object:

```js
spec("zoom");                                  // /zoom/i against id and summary
spec({ skill: "zoom-recorder", limit: 2 });    // narrow by skill and cap the rows
spec({ grep: "decide|jev", kind: "cli" });     // several filters at once
```

A `SpecRow` is `{ id, fn, skill, kind, summary, sig, args, required, params,
positionalSpecs, commands, command }` — everything needed to call a tool without
invoking `describe` on it first.

Session state is a plain JSON object, not variable persistence: `getState()` reads
the value saved for `--session ID` (default: the trace session identity) and
`emitState(value)` replaces it. It lives at
`~/.local/share/omnicli/sessions/<safe-id>.json` (8 KB bound on load) and holds
only plan data.

### 2. Typed Surface Functions

Every catalogued tool is also exposed as one async function, generated from its
extracted JSON Schema (`inputSchema`, produced by `schema_extract.py` from the
tool's own `--help`):

```js
zoom({ url: "https://zoom.us/rec/share/example", format: "md" });
```

Arguments are validated against that schema **before dispatch**: an unknown key,
a missing required argument, or a mistyped value throws `TypeError` naming the
function and the argument, at the call site rather than at call forty.

```js
zoom({ url: "...", fromat: "md" });   // TypeError: zoom_download: unknown argument "fromat"
zoom({ format: "md" });               // TypeError: zoom_download: missing required argument "url"
zoom({ url: "...", video: "yes" });   // TypeError: zoom_download: "video" must be boolean, got string
```

The same call accepts the invoke envelope knobs inline — `project`, `grep`,
`maxBytes`, `timeout` — which map onto the CLI's `--omni-*` flags. An array where
the tool expects positionals is passed through in order:

```js
invoke("audiocpp/scripts/audiocpp_cli", ["asr", "talk.wav"], { maxBytes: 4000 });
```

### 3. Zero boilerplate or ESM — same module

The VM exposes the whole module as globals, so an inline plan needs no import at
all:

```bash
omnicli exec -c 'const rows = await search("audio", 2); console.log(rows)'
```

A plan file can import explicitly, which is what the `.d.ts` types and an editor
expect:

```js
import { search, spec, zoom, emitResult } from "omnicli_tools";
```

`vm_runner.mjs` links `omnicli_tools` (and `omnicli_tools.mjs`) to the same module
namespace, so both forms are the same code path.

---

## 🔒 Sandboxing & Execution Modes

`omnicli exec <plan.mjs>` runs the plan with `node:vm` (via `vm_runner.mjs`) in
one of three containment tiers:

| Mode | Filesystem | Network | Tool Dispatch | Use Case |
|---|---|---|---|---|
| `write` | `/` is read-only; only current workspace and `/tmp` writable. | Unrestricted. | Direct subprocess execution. | Standard multi-step data pipelines and local tool orchestration. |
| `strict` (default) | Home directory masked (`~/.ssh`, `~/.env` unreadable); only workspace writable. | **Disabled** (no outbound sockets). | Every tool call crosses a UNIX domain socket bridge to the parent process. | Running untrusted code, external scripts, or high-security evaluation suites. |
| `none` | Unconfined host filesystem. | Unrestricted. | Direct subprocess execution. | Tasks requiring broad machine access (system admin, global package installs). |

Node lives under `$HOME` on this workstation (nvm), which `strict` masks, so the
host `node` binary, `vm_runner.mjs` and the bindings directory are re-bound into
`/tmp/omnicli` before the plan starts.

---

## 🧠 Memory cap (`--mem-limit`)

Address space is uncapped by default. `--mem-limit MiB` is a positive integer
that caps the plan in two places at once:

- **JS heap:** Node runs with `--max-old-space-size=<MiB>`, so V8 collects
  instead of growing past the number you asked for.
- **Address space:** the bubblewrap process is wrapped in
  `prlimit --as=<cap>`, so the plan and every process it spawns inherit a hard
  ceiling and cannot raise it.

The `RLIMIT_AS` value is floored: `max(MiB, 2048)` MiB. V8 reserves roughly
1.5 GiB of virtual address space for its CodeRange before any plan code runs, so
a smaller rlimit aborts Node at startup — the failure would be the runner's, not
the plan's. The JS heap itself is still capped exactly by
`--max-old-space-size`.

`--sandbox none` rejects the flag instead of ignoring it, because an unsandboxed
run has no rlimit to set. On a heap out-of-memory the error report says so
explicitly, so a capped allocation is not mistaken for a logic bug.

---

## 💡 Practical Examples

### Example 1: Dynamic Discovery & Chained Execution

[`examples/discovery_and_invoke.mjs`](../examples/discovery_and_invoke.mjs):

```js
import { search, spec } from "omnicli_tools";

const results = await search("transcribe recorded audio", 3);
for (const row of results) {
  console.log(`Skill: ${row.skill} (Score: ${Number(row.score ?? 0).toFixed(2)})`);
}

for (const row of spec({ grep: "zoom", limit: 2 })) {
  console.log(`Tool ID: ${row.id}`);
  console.log(`Summary: ${row.summary}`);
}
```

Run via:

```bash
omnicli exec examples/discovery_and_invoke.mjs
```

### Example 2: In-Memory Filtering Without Context Flooding

[`examples/in_memory_filter.mjs`](../examples/in_memory_filter.mjs) collects
every decision-related contract, collapses it per skill in JS memory, prints
five lines, and hands the structured summary back on the result channel:

```js
import { spec, emitResult } from "omnicli_tools";

const rows = spec({ grep: "decide|jev" });
const bySkill = new Map();
for (const row of rows) if (!bySkill.has(row.skill)) bySkill.set(row.skill, row);

console.log(`Found ${rows.length} decision tools across ${bySkill.size} skills:`);
for (const row of [...bySkill.values()].slice(0, 5)) {
  console.log(`  - ${row.id}: ${row.summary.slice(0, 80)}`);
}

emitResult({ count: rows.length, skills: [...bySkill.keys()] });
```

`exec --json` reports that value under `result` while `stdout` keeps the printed
lines.

---

## Concurrency

Every binding call is one `omnicli` CLI process, so independent calls are worth
overlapping. Every function is natively async — there are no `a*` twins to
remember, because there is nothing synchronous to twin.

```js
const parallel = (calls, limit = 8) => Promise<unknown[]>;
```

`calls` is any iterable of async thunks (`() => search(...)`); `[fn, args]` pairs
and bare promises work too. At most `limit` calls are in flight, and results come
back in input order even though they finish out of order. One failure rejects the
batch with `parallel[<index>]: <message>`, so the failing call is named.

### Example: ten independent lookups

```js
import { search, parallel } from "omnicli_tools";

const INTENTS = [
  "transcribe audio", "ocr a slide", "search notes", "zoom recording",
  "git worktree", "review a diff", "run tests", "summarize a paper",
  "check model status", "convert pdf",
];

const hits = await parallel(INTENTS.map((intent) => () => search(intent, 2)), 8);
for (const [i, rows] of hits.entries()) {
  const top = rows[0] ?? {};
  console.log(`${INTENTS[i].padEnd(22)} ${String(top.score ?? 0).padStart(6)} ${top.skill ?? "none"}`);
}
```

Measured on this workstation (`--sandbox write`, three runs per cell, ten
`search(intent, 2)` calls):

| Shape | Wall clock |
|---|---|
| one `search()` | ~80 ms |
| ten sequential | 1672–1710 ms |
| `parallel(…, 8)` | 808–929 ms |
| `parallel(…, 10)` | 805–893 ms |

Fan-out roughly halves the wall clock rather than dividing it by eight: the cost
is the CLI's own catalog work, not waiting on the network, so wider fan-out buys
little past the point where the machine is saturated.

---

## Python plans are retired

`omnicli exec plan.py` (or `--lang py`) exits **2** with the migration text
instead of running:

```
❌ Python plans are retired in favor of JavaScript Code Mode.

  Python : omnicli exec plan.py      ← no longer supported
  JS     : omnicli exec plan.mjs
           omnicli exec -c 'const r = await search("intent")'
           omnicli spec --stubs      ← the typed surface to write against
```

The historical design record — the budget, fan-out and memory-cap run that
produced the Python surface — is preserved in
[plan-code-mode-limits.md](plan-code-mode-limits.md) and is not a usage guide.
