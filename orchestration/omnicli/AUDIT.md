# omnicli audit — 2026-10-23 (historical)

> **Status: historical snapshot.** This audit was taken before the legacy
> retrieval/ranking layer was removed. Findings about that layer and its
> evaluation are retained only as history, not as current policy. omnicli now
> uses exec-only discovery: one `omnicli exec` plan reads skills through
> `omnicli_skills` (`lsSkills` / `readSkill` / `readResource`), calls
> `describe()` for the tool schema, then `invoke()` — never a search tool.
> The engineering findings below that are still true (cap exactness, unified
> invoke, enable gate, health probe, concurrency, flag handling, doc drift)
> are kept; the ranking-specific findings are not.

Scope: `orchestration/omnicli` at commit `3268926`, both faces (CLI and MCP), the
catalog, the tests, and the documentation. Every finding below was reproduced
with a command before it was fixed, and every fix was re-measured afterwards.

The reference architecture is Uber's MCP Gateway (AutoCrawler → registry →
bounded invoke). The audit asked one question: where does this implementation
claim that contract and not hold it?

---

## What was wrong

### 1. The MCP cap was exceeded by the elision banner

`tool_invoke` sliced the payload to `max_bytes` and then *appended* a banner,
so `max_bytes: 400` returned 429 bytes. The CLI had the opposite failure: it
reserved 300 bytes for its banner, so every cap below 300 returned the notice
and no payload.

**Fix.** `catalog.invoke.cap` measures the banner first, splits the remaining
budget head/tail, and clamps the final encode — the ceiling is a guarantee at
any size. `invoke.fit_envelope` then measures the JSON envelope's real
overhead and reshapes, so `--omni-json` cannot smuggle bytes past the cap.

```
cap    plain reply   json reply
250    249           248
400    399           396
1000   999           989
```

Small caps now return payload, not a banner-only reply.

### 2. Two invoke implementations had drifted apart

The CLI and the MCP face each owned projection, capping and subprocess
handling. The consequences were all real:

| | CLI | MCP |
|---|---|---|
| projection | dicts and lists | dicts only |
| nested paths (`a.b`) | `{}` | `{}` |
| cap | banner counted, preview under-filled | banner appended past the cap |
| stderr | merged into stdout | merged into stdout |
| buffer | wrote the *filtered* payload | n/a |

Merging stderr into stdout is the worst of these: any tool that logs progress
produces invalid JSON, so projection silently fails and the agent receives
the unfiltered payload believing it was filtered.

**Fix.** `catalog/invoke.py` owns projection, capping, envelope fitting and
execution; both faces call it. Projection supports dotted paths and maps over
lists, reports `applied: false` when nothing matched (instead of returning
`{}`), and keeps stderr separate.

```
project {"a":{"b":1,"c":2}} ["a.b"]        -> {"a":{"b":1}}        applied
project [{"x":1,"y":2},...] ["x"]          -> [{"x":1},{"x":3}]     applied
project {"a":1} ["nope"]                   -> {"a":1}  applied=false
```

`--omni-buffer` now writes the full **unfiltered** stdout, which is what the
buffer exists to preserve, and says so when the preview is filtered:

```
💾 Full stdout buffered to: /tmp/omni_buf.txt  (3215 bytes)
📊 The preview below is filtered; the buffer is not.
```

### 3. Discovery rungs returned more context than the skill they pointed at

The old discovery rungs were dumping archives:

```
the retired intent-lookup verb (--json)   25,278 bytes  (~6.3k tok)
the retired MCP discovery verb            12,966 bytes  (~3.2k tok)
```

**Fix (as of that audit).** The compact view returned skill, score, matched
terms and one line of evidence instead of the full body; `--chunks` returned
the full shape. MCP discovery returned skill, score, a 100-char reason, tool
count and the two most relevant tool ids.

```
the retired intent-lookup verb (--json)    2,323 bytes  (10.9x smaller)
the retired MCP discovery verb             1,805 bytes  (7.2x smaller)
```

This class of problem is now solved structurally: the exec plan reads skill
files into VM variables and emits one bounded `result()`, so a full body never
enters the context at all.

### 4. Discovery implied exposure

AutoCrawler catalogues anything it finds; the gateway's registry then holds
every tool **disabled** until an owner enables it. omnicli catalogued
everything and exposed all of it.

**Fix.** `tools.enabled` (schema v3) plus `catalog/policy.py`:

* a tool new relative to the previous catalog starts disabled;
* tools that already existed are grandfathered, so installing the gate does
  not turn a working workstation into a dead one;
* `omnicli enable|disable|policy` record the decision in `policy.json` and
  append it to `policy.log.jsonl` with the contract hash it was made against;
* `invoke` refuses a disabled tool and names the command that opens the gate;
  `describe` still works, so the contract can be reviewed first.

```
❌ Error: tool 'local/decide' is disabled.
   Review it:  omnicli describe local/decide
   Enable it:  omnicli enable local/decide
```

### 5. `omni_status` hardcoded a tailnet IP and trusted TCP

The MCP face probed `127.0.0.1` and a literal `100.83.178.106`, treating any
accepted socket as "online". On a port where `tailscale serve` owns the
listener, that reports a dead backend as healthy. It also omitted :8084,
:8086 and :9222, and included the retired :8090. <!-- ports:ignore -->

**Fix.** `catalog/health.py` is the single probe for both faces: HTTP on
loopback is authoritative, TCP alone is `DEGRADED`, the tailnet address is
discovered rather than hardcoded, and the port list matches the machine
(`:8086` reranker added, `:8090` retired). <!-- ports:ignore -->

### 6. The MCP loop was serial

A tool taking minutes blocked `ping` and every other request, because
`serve()` handled each line inline.

**Fix.** Requests run on a four-worker pool and replies are written under a
single stdout lock. JSON-RPC correlates by `id`, so out-of-order completion is
legal. Verified with six concurrent requests: all six replied, `ping`
included.

### 7. Unknown gateway flags were silently dropped

`omnicli invoke tool --omni-max-byte 100` (typo) was swallowed, and the agent
got an unfiltered 8 KB payload believing it had asked for 100 bytes. Bad
integers raised a bare `ValueError` traceback.

**Fix.** Unknown `--omni-*` flags are reported on stderr with the known set;
non-numeric values fail with a clean message and exit 1.

### 8. Documentation drift

`README.md` and `SKILL.md` claimed stale tool counts, a different library
size, and that `uber`/`local-hub`/`skills-hub` remained as aliases. `SKILL.md`
also documented a command that does not exist — gateway mode is a state file
(`~/.config/skills-frontline`) read by `sync-skills`, not a CLI.

**Fix.** Counts, the cap and buffer semantics and the enable gate are now
measured facts. The archived note says plainly that no switch is installed
and no harness routes through the binary automatically. The live authority is
`tests/doc_drift_check.py`.

---

## What the audit did not change

* The enable gate and the `--omni-*` flag namespace.
* The 8 KB default cap.
* The decision to keep the skill archived. Retiring it as a front line was
  deliberate; the audit made the docs say so instead of pretending otherwise.

The old retrieval design and its evaluation are deliberately omitted here:
that layer has since been removed. See the historical note in
[README.md](README.md) and the current flow in
[SKILL.md](SKILL.md).

---

## Verification (as of the audit)

```
tests/test_catalog.py   54 tests   OK        (was 39)
tests/test_mcp.py       28 checks  28/28     (was 17)
```

Live checks at the time: cap exactness at 250/400/1000/8000 in both faces,
nested and list projection, buffer-vs-preview byte counts, disabled-tool
refusal and re-enable, six concurrent MCP requests, and a full catalog rebuild
through the schema-v3 migration (392 tools grandfathered, new tools default
disabled).

Current verification is the three hard legs of `tests/routing_gate.py`
(`exec_only_flow`, `skills_bridge_flow`, `doc_drift`) with their real mutants in
`tests/discovery_mutant.py` and `tests/leg_mutants.py`. `tests/overfit_check.py`
is a standalone diagnostic of the curated routing metadata, not a gate leg.
