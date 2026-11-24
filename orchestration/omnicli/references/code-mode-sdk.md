# JavaScript SDK & Code Mode Execution (`omnicli exec`)

## 🏛️ Architectural Provenance

The `omnicli` architecture unifies two foundational production AI patterns:

1. **Uber's MCP Gateway** ([Uber Engineering: Designing an MCP Gateway](https://www.uber.com/au/en/blog/designing-mcp-gateway/)):
   - **Late-Binding Discovery**: Instead of dumping hundreds of tool schemas into turn-0 model context (which triggers the Databricks tool-shadowing degradation), tools are catalogued out-of-band via AutoCrawler/builder into SQLite FTS5 + dense embeddings.
   - **Bounded Meta-Tools** (the archived gateway shape): agents once discovered tools by intent (`search`), inspected single contracts on-demand (`describe`), invoked them with strict byte caps and field projections (`invoke`), and monitored service health (`status`). The current surface keeps `describe` / `invoke` inside Code Mode and removes ranked search from the routing path.

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
| `invoke` | `invoke(toolId, argsOrArgv?, opts?)` → `Promise<InvokeEnvelope>` | Execute any catalogued tool with output bounding and projection. This is the normal call path. |
| `output` | `output(toolId, argsOrArgv?, opts?)` → `Promise<string>` | The same call, returning only `envelope.output`. |
| `describe` | `describe(toolId)` → `Promise<object>` | Optional: read one tool's usage contract, flags, parameters and help text. |
| `spec` | `spec(grepOrFilter)` → `SpecRow[]` | Synchronous query over the in-memory spec table when a tool ID is unknown. |
| `skills` | `skills()` → `Promise<unknown>` | List every registered skill; fallback for broad discovery. |
| `tools` | `tools[id](args)` → `Promise<InvokeEnvelope>` | Sleek Proxy over the generated typed functions (`TOOLS` is an alias). To enumerate a skill's tools, use `spec({ skill })` or `skills()`. |
| `parallel` | `parallel(calls, limit = 8)` → `Promise<unknown[]>` | Fan out async thunks, keeping results in input order. |
| `emitResult` | `emitResult(value)` | Hand one value back on its own channel (`emit_result` is an alias). |
| `getState` | `getState()` → `Record<string, unknown>` | Read the session's JSON object (`{}` when unset). |
| `emitState` | `emitState(value)` | Replace that object; it persists across runs sharing `--session ID`. |

Known tool IDs need no discovery or schema round-trip. Use `spec()` or the
read-only `omnicli_skills` window only when the target is unknown; use
`describe()` only when the exact contract is unclear.

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

Every *enabled* catalogued tool is also exposed as one async function,
generated from its extracted JSON Schema (`inputSchema`, produced by
`schema_extract.py` from the tool's own `--help`). Disabled tools are absent
from the typed `SPEC` and from the generated bindings, matching the contract
tree: a tool the policy has not opened cannot be bound to at all.

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

A tool with an empty or help-fallback `inputSchema` has no named arguments to
validate, so its generated function takes an `argv?: string[]` escape hatch
instead of rejecting every key as "unknown argument":

```js
tools["some/schema-less-tool"]({ argv: ["--flag", "value", "positional"] });
```

### 3. Zero boilerplate or ESM — same module

The VM exposes the whole module as globals, so an inline plan needs no import at
all:

```bash
omnicli exec -c 'const out = await invoke("guard-hooks/scripts/guard:check", ["echo hello", "--json"]); console.log(out.output)'
```

A plan file can import explicitly, which is what the `.d.ts` types and an editor
expect:

```js
import { invoke, spec, zoom, emitResult } from "omnicli_tools";
```

`vm_runner.mjs` links `omnicli_tools` (and `omnicli_tools.mjs`) to the same module
namespace, so both forms are the same code path.

To paste a typed surface straight into a plan, add `--plan-header`:

```bash
omnicli spec --grep zoom --stubs --plan-header
```

It prepends a short block naming the skill, tool id and `declare function`
signatures (plus the globals and an import line) above the stubs. Default
`--stubs` output stays byte-identical without the flag.

### 4. Sleek call surface

Beyond the core globals, the module exposes a few designed forms:

| Form | What it does |
|---|---|
| `tools[id](args)` | Proxy over the generated typed functions; `TOOLS` is an alias. Calls pass through the same `_callTool` validation, so behavior is identical to the named wrapper (`zoom({ ... })`). |
| `` $`cmd` `` | Claude-style tagged template returning a lazy thenable with `.text()`, `.json()` and `.nothrow()`. It throws an `Error` in `strict` **before spawning** and caches its promise — use `--sandbox write` (network) to run one. Outside `strict` it runs `guard-hooks check -- <cmd>` first; a refusal or an unavailable gate throws an `Error` before any child process starts. |
| `result({ ok, tool, proof, data })` | A designed result on the `emitResult` channel (`ok` defaults to `true`). With `exec --quiet`, plain mode prints this JSON (or stdout when no result was emitted) and drops the ⚡ status line. |

`--quiet` is inert with `--json`: reports, output caps, trace rows, the call
budget, bridge policy, and the detached 🚀 job-id line are all untouched.
`spec --plan-header` and `--quiet` are the only new CLI flags; no native tool or
tool-call verb changed.

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

### Example 1: Known tool, direct invocation

The normal Code Mode path calls the tool directly. No skill listing, body read,
or schema round-trip is required:

```js
import { invoke, result } from "omnicli_tools";

const out = await invoke(
  "guard-hooks/scripts/guard:check",
  ["echo hello", "--json"]
);
const payload = JSON.parse(String(out.output || "{}"));

result({
  ok: out.exit_code === 0 && payload.allowed === true,
  data: payload,
});
```

### Example 2: Unknown tool, discovery fallback

[`examples/discovery_and_invoke.mjs`](../examples/discovery_and_invoke.mjs)
uses the read-only skills window only because its target is not assumed:

```js
import { lsSkills, readSkill } from "omnicli_skills";
import { invoke, result } from "omnicli_tools";

const skill = lsSkills().find((s) => s.name === "guard-hooks");
if (!skill) throw new Error("skill not installed");
const body = readSkill("guard-hooks"); // only if guidance is needed

const out = await invoke(
  "guard-hooks/scripts/guard:check",
  ["echo hello", "--json"]
);
result({ ok: out.exit_code === 0, data: JSON.parse(out.output) });
```

### Example 3: In-Memory Filtering Without Context Flooding

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

All five canonical flows are collected in
[`examples/recipes.mjs`](../examples/recipes.mjs): known-tool invocation,
in-memory `spec()` dedupe, `parallel()` fan-out, a caught typed validation error,
and session state. Every recipe runs under default `strict` with no network and
exits 0.

---

## Concurrency

Every binding call is one `omnicli` CLI process, so independent calls are worth
overlapping. Every function is natively async — there are no `a*` twins to
remember, because there is nothing synchronous to twin.

```js
const parallel = (calls, limit = 8) => Promise<unknown[]>;
```

`calls` is any iterable of async thunks (`() => invoke(...)`); `[fn, args]` pairs
and bare promises work too. At most `limit` calls are in flight, and results come
back in input order even though they finish out of order. One failure rejects the
batch with `parallel[<index>]: <message>`, so the failing call is named.

### Example: independent known-tool calls

```js
import { invoke, parallel, result } from "omnicli_tools";

const commands = ["echo one", "echo two", "echo three"];
const checks = await parallel(
  commands.map((command) => () =>
    invoke("guard-hooks/scripts/guard:check", [command, "--json"])
  ),
  3
);

result({
  ok: checks.every((out) => out.exit_code === 0),
  data: checks.map((out) => JSON.parse(out.output)),
});
```

Fan out only independent calls. Dependent work should stay sequential so one
result can determine the next tool and arguments.

---

## Python plans are retired

`omnicli exec plan.py` (or `--lang py`) exits **2** with the migration text
instead of running:

```
❌ Python plans are retired in favor of JavaScript Code Mode.

  Python : omnicli exec plan.py      ← no longer supported
  JS     : omnicli exec plan.mjs
           omnicli exec -c 'const out = await invoke("guard-hooks/scripts/guard:check", ["echo hello", "--json"]); console.log(out.output)'
           omnicli spec --stubs      ← the typed surface to write against
```

The historical design record — the budget, fan-out and memory-cap run that
produced the Python surface — is preserved in
[plan-code-mode-limits.md](plan-code-mode-limits.md) and is not a usage guide.
