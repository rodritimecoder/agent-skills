---
name: isolate-run
description: >
  Run untrusted JS/TS in a capability-gated V8 isolate (Deno) with an allow-list,
  heap cap and wall-clock timeout. Use for model-generated snippets, policy/routing
  scripts, scoring functions, JSON transforms and pure-JS test shards when you want
  millisecond startup without a container. Not for native builds, git, browsers or
  arbitrary shell work — use subagent-spaces (local Podman) or gh-action-subagent
  (cloud VM) for those.
metadata:
  bins: isolate-run
compatibility: "Requires Deno 2.x (DENO_BIN overrides discovery). Python 3.10+ for the wrapper. No third-party packages. No workerd needed."
allowed-tools: "Bash(deno:*) Bash(python3:*) Read Write"
---

# Isolate Run (`isolate-run`)

A cheap inner sandbox for JavaScript. The outer boundary is still
`subagent-spaces` (Podman) or `gh-action-subagent` (GitHub VM) — this skill covers
the case where the untrusted thing is *JS itself* and a container is overkill.

## Why an isolate, and what it cannot do

A V8 isolate is a separate JS heap inside one process. It gives ~10–20 ms cold
starts and tiny memory, but **it is not an OS boundary**: no fork/exec, no mounts,
no cgroups, no native toolchains. Deno's capability layer is the actual gate.

| Need | Use |
| :--- | :--- |
| Pure JS/TS, untrusted snippets, transforms, scoring, policy scripts | **this skill** |
| `pytest` / `cargo check` / `npm test`, workspace mounts, CPU pinning | `subagent-spaces` |
| git, headless Chrome, branches/PRs | `gh-action-subagent` |
| Per-request Workers semantics, durable objects | `cf-architect` (`workerd`) |

## Profiles

| Profile | Grants | Denies |
| :--- | :--- | :--- |
| `pure` | computation only (JSON, math, regex, `Intl`, `crypto.subtle`) | read, write, net, env, sys, run, ffi |
| `read` | read of exactly `--allow-path` | write, net, env, sys, run, ffi |
| `net` | network to exactly `--allow-host` | read, write, env, sys, run, ffi |

Every profile always passes `--no-prompt`, `--no-remote`, `--no-npm`, a V8 heap
cap (`--mem`, default 128 MiB) and a wall-clock timeout (`--timeout`, default 10 s).

> **Never use `deno eval` for sandboxing.** In Deno 2.x, `eval` grants all
> permissions by default — a probe reading `/etc/hostname` with zero flags
> succeeds. The wrapper always uses `deno run --no-prompt` with explicit flags.

## Quick commands

```bash
# Pure computation: no permissions at all
isolate-run --profile pure --json scripts/transform.js

# Read exactly one file
isolate-run --profile read --allow-path /etc/hostname --json scripts/reader.js /etc/hostname

# Fetch exactly one host:port
isolate-run --profile net --allow-host 127.0.0.1:8080 --json scripts/fetcher.js http://127.0.0.1:8080/data

# Tighten resources for an untrusted snippet
isolate-run --profile pure --mem 32 --timeout 2 --json untrusted.js
```

Exit codes: `0` script succeeded · child's code on failure (e.g. `1` `NotCapable`) ·
`124` timed out · `2` usage error. `--json` emits
`{profile, flags, exit, timed_out, duration_ms, stdout, stderr}` so the result can
feed a gate.

## Prove the gate can fail

```bash
python3 tests/test_isolate_run.py
```

The suite runs 3 positive cases and 10 negative controls: file read/write, env,
network, subprocess, FFI, allow-list escapes, a busy loop (timeout) and an
allocation bomb (heap cap). A control that unexpectedly succeeds fails the suite.
