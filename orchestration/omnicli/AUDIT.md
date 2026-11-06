# omnicli audit — 2026-10-23

Scope: `orchestration/omnicli` at commit `3268926`, both faces (CLI and MCP), the
catalog, the tests, and the documentation. Every finding below was reproduced
with a command before it was fixed, and every fix was re-measured afterwards.

The reference architecture is Uber's MCP Gateway (AutoCrawler → registry →
four meta-tools → bounded invoke). The audit asked one question: where does
this implementation claim that contract and not hold it?

---

## What was wrong

### 1. `--rerank always` silently behaved like `never`

`cmd_search` passed the *string* `"always"` into `search()`, which tested
`if rerank_enabled and results:` (true) and then `wants = rerank_enabled is
True or ...` (false, because `"always" is not True`). The re-ranker was never
consulted in that mode, and `tier` still said `bm25`.

Evidence before the fix:

```
--rerank always  -> tier=bm25        1.4 ms
--rerank True    -> tier=bm25+rerank 68 ms
```

The MCP face had the mirror-image bug: it ignored its own `rerank` argument
and passed `not args.get("no_rerank")`, so `rerank:"never"` still re-ranked.

**Fix.** One normaliser (`search.normalize_rerank`) maps `never/auto/always`
and booleans onto the tri-state, and `search()` calls it before doing
anything. Both faces pass the mode through unchanged.

```
--rerank never   -> bm25             4.0 ms   0/61 queries
--rerank auto    -> bm25+rerank     24.0 ms   9/61 queries
--rerank always  -> bm25+rerank    126.0 ms  61/61 queries
```

### 2. The MCP cap was exceeded by the elision banner

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

### 3. Two invoke implementations had drifted apart

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

### 4. Every rung returned more context than the skill it pointed at

The gateway is supposed to be a late-binding control plane, but the two
discovery rungs were dumping archives:

```
omnicli search --json            25,278 bytes  (~6.3k tok)
omni_discover (MCP)              12,966 bytes  (~3.2k tok)
```

**Fix.** `search --json` returns the compact routing view (skill, score,
matched terms, one line, top hit); `--chunks` returns the full shape. MCP
discovery returns skill, score, 100-char reason, tool count and the two most
relevant tool ids.

```
omnicli search --json             2,323 bytes  (10.9x smaller)
omni_discover                     1,805 bytes  (7.2x smaller)
```

### 5. Discovery implied exposure

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

### 6. `omni_status` hardcoded a tailnet IP and trusted TCP

The MCP face probed `127.0.0.1` and a literal `100.83.178.106`, treating any
accepted socket as "online". On a port where `tailscale serve` owns the
listener, that reports a dead backend as healthy. It also omitted :8084,
:8086 and :9222, and included the retired :8090.

**Fix.** `catalog/health.py` is the single probe for both faces: HTTP on
loopback is authoritative, TCP alone is `DEGRADED`, the tailnet address is
discovered rather than hardcoded, and the port list matches the machine
(`:8086` reranker added, `:8090` retired).

### 7. The MCP loop was serial

A tool taking minutes blocked `ping` and every other request, because
`serve()` handled each line inline.

**Fix.** Requests run on a four-worker pool and replies are written under a
single stdout lock. JSON-RPC correlates by `id`, so out-of-order completion is
legal. Verified with six concurrent requests: all six replied, `ping`
included.

### 8. Unknown gateway flags were silently dropped

`omnicli invoke tool --omni-max-byte 100` (typo) was swallowed, and the agent
got an unfiltered 8 KB payload believing it had asked for 100 bytes. Bad
integers raised a bare `ValueError` traceback.

**Fix.** Unknown `--omni-*` flags are reported on stderr with the known set;
non-numeric values fail with a clean message and exit 1.

### 9. The evaluation was partly measuring the answer key

`tests/overfit_check.py` found three aliases that were verbatim fragments of
golden queries:

```
guard-hooks     'protect the state file from being edited'
eval-router     'which model should handle this prompt'
swarm-contract  'stop the workers before they overspend'
```

Removing them dropped the score from 61/61 to **60/61** — which is the honest
number. The remaining miss is a genuine lexical ambiguity:

```
"decide which model should handle this prompt before answering"
  pplx-decider  matched all 6 terms   score 18.17
  eval-router   matched 4 terms       score 10.41  (ranked 5th)
```

`pplx-decider` is a calibrated decision model; `eval-router` is the request
router. A human routes to the router. BM25 cannot separate them, and the
embedding re-ranker does not either. The case is recorded, not excluded.

One golden case was also corrected: it expected `omnicli`, which is archived
and excluded from the index, so the expectation was unreachable. It now
expects `local-llm`, the skill that actually owns `llm_client.py`.

### 10. Documentation drift

`README.md` and `SKILL.md` claimed 210 tools, a 38-skill library, 52/53 and
40/61 eval numbers, and that `uber`/`local-hub`/`skills-hub` remained as
aliases. None of that was true. `SKILL.md` also documented a
`skills-frontline` command that does not exist — gateway mode is a state file
(`~/.config/skills-frontline`) read by `sync-skills`, not a CLI.

**Fix.** Counts, eval numbers, the re-ranker table, the cap and buffer
semantics and the enable gate are now measured facts. The archived note says
plainly that no switch is installed and no harness routes through the binary
automatically.

---

## What the audit did not change

* The retrieval design: BM25 over full skill bodies, curated aliases in a
  weighted column, coordination by distinct IDF-weighted terms, gated
  re-ranker. It is the part that works.
* The four meta-tools and the `--omni-*` flag namespace.
* The 8 KB default cap.
* The decision to keep the skill archived. Retiring it as a front line was
  deliberate; the audit made the docs say so instead of pretending otherwise.

---

## Verification

```
tests/test_catalog.py   54 tests   OK        (was 39)
tests/test_mcp.py       28 checks  28/28     (was 17)
tests/eval_runner.py    top1 60/61, top3 60/61
tests/overfit_check.py  0 query echoes
```

Live checks: cap exactness at 250/400/1000/8000 in both faces, nested and list
projection, buffer-vs-preview byte counts, disabled-tool refusal and
re-enable, `rerank` passthrough, six concurrent MCP requests, and a
full catalog rebuild through the schema-v3 migration (392 tools grandfathered,
new tools default disabled).
