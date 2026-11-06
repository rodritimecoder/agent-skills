---
name: leasebox

description: >
  Operate the leasebox multiplayer-files service on Cloudflare: per-workspace Durable Objects
  with leases and etags, content in R2, a replayable change log, a git committer, presence
  over hibernating WebSockets, and free-tier guardrails. Use when several people or agents
  edit the same files and must not overwrite each other, to coordinate concurrent writes, to
  sync worker writes to git, or to check who is online. For parallel coding subagents in git
  worktrees on one machine, use worktree-harness.

compatibility: "Requires the deployed Worker at https://leasebox.adrielpadernilla.workers.dev (or LEASEBOX_URL) and Node for the committer."
allowed-tools: "Bash(curl:*) Bash(node:*) Read"
---

# leasebox

Smallest honest "multiplayer files" on Cloudflare: one Durable Object per
workspace, a lease that gates who may write a path, an etag that refuses stale
writes, a change log git can catch up to, presence over a hibernating
WebSocket, and bytes in R2 with the DO holding only authority.

## Endpoints (`/v1/:ws/...`)

| Method | Route | Purpose |
|---|---|---|
| GET | `/files` | list file metadata |
| GET | `/file?path=` | one file's record |
| GET | `/content?path=` | stream bytes from R2 |
| GET | `/changes?since=&limit=` | replayable change log |
| GET | `/presence` | roster over HTTP |
| WS | `/presence?name=` | live roster |
| POST | `/lease` `{path, holder, ttlMs?}` | acquire lease |
| DELETE | `/lease` `{path, holder}` | release lease |
| PUT | `/file` `{path, holder, expectedEtag, content}` | write (lease + etag) |
| DELETE | `/file` `{path, holder}` | delete (record + R2 object) |
| GET | `/__usage` | account/workspace counters and caps |

Status codes carry semantics: `409 held`/`stale`, `423 held-by-other`,
`403 no-lease`, `413 too-large`, `429 quota`/`read budget exhausted`.

## Write rule

A write needs **both**: a live lease held by `holder`, and `expectedEtag`
equal to the current etag (`null` means the file does not exist yet). On
success the DO hashes the bytes, uploads to R2 under `<workspace>/<path>`
with etag/version in `customMetadata`, then advances the record and log. If
the upload or the meter refuses, no record moves and the R2 object is deleted.

## Guardrails (free tier, enforced in code)

Account-wide `Meter` DO holds counters and caps; mutations roll back on
refusal. Defaults: `maxR2Bytes` 5 GB (of 10 GB), `maxWorkspaceBytes` 512 MB,
`maxWorkspaceFiles` 5,000, `maxDailyWrites` 20,000, `maxDailyReads` 50,000,
`maxWorkspaceDailyReads` 20,000, `maxDailyMessages` 400,000,
`maxLogEntries` 2,000, `maxFileBytes` 512 KB, `maxReadsPerMinute` 60.
Counters reset at 00:00 UTC; limits live in `vars.GUARDRAILS` (JSON).

## Git committer

A local process (not a Worker) replays the change log into a working tree:

```
WORKER_URL=https://leasebox.adrielpadernilla.workers.dev \
WORKSPACE=my-repo REPO_PATH=/path/to/repo \
node committer/committer.mjs run      # poll + commit
node committer/committer.mjs verify   # drift check, exit 1 on drift
```

Backoff 2 s→60 s when idle, jitter ±20%, daily poll budget 20,000. A cursor
that fell out of the compaction window gets `resync: true` and rebuilds.

## Usage report

```
cd /home/rodri/Projects/leasebox && npm run usage
```

Queries Cloudflare GraphQL for today's real worker/subrequest counts, prints
them against the free ceilings, exits non-zero above 80%.

## Deploy

```
cd /home/rodri/Projects/leasebox
export CLOUDFLARE_API_TOKEN=$(python3 -c "import json;print(json.load(open('$HOME/.config/cloudflare/config/default.json'))['oauth_token'])")
npx wrangler r2 bucket create leasebox-content   # one-time
npx wrangler deploy
```

Source of truth for code: `/home/rodri/Projects/leasebox`. The project is not
part of the skills repo; this skill only documents how to operate it.
