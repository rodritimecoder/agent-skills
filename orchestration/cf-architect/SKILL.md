---
name: cf-architect

description: >
  Cloudflare architecture for agents and personal infrastructure. Probe what an
  account can actually do before designing (read-only), run free-tier budget
  math on a concrete workload, and choose between Durable Objects, Containers,
  R2 and Cloudflare Tunnel. Carries the `cf` CLI papercuts: npm allow-scripts
  gating, the R2 dashboard toggle, and the beta `cf dev` config trap. Use when
  asked to deploy, host, or scale something on Cloudflare, to decide whether a
  workload fits the free plan, to expose a local GPU box or dev server, or to
  design real-time, stateful, multiplayer or per-agent infrastructure.

compatibility: "Requires the cf CLI (v0.15+). `probe` is read-only and never mutates the account."
allowed-tools: "Bash(cf-architect:*) Bash(cf:*) Bash(npm:*) Read"
---

# Cloudflare Architect (`cf-architect`)

## The Capability Law

**Never design against an assumed account.** Plans differ, services gate
independently, and a free account silently lacks the five features the article
was about. Run `probe` first, then architect.

An architecture is a claim about a specific account. Two accounts on the same
plan can differ: R2 is dashboard-gated per account and returns `10042` until
someone clicks it, regardless of plan.

```bash
cf-architect probe            # what this account can do, right now
cf-architect probe --json     # same, machine-readable
cf-architect doctor           # local toolchain + known CLI papercuts
```

## Commands

| Command | Job |
|---|---|
| `probe` | Read-only service matrix: plan, enabled services, gate reasons, Containers availability |
| `doctor` | Local `cf`/`wrangler`/`workerd`/`npm` state and the papercuts that look like failures |
| `budget` | Free-tier arithmetic for a concrete workload — per-dimension pass/fail and headroom |
| `scripts-fix` | Emit the *correct* npm allow-scripts remedy for the context (global vs project) |

```bash
cf-architect budget --r2-gb 1.5 --requests-per-day 5000 --do-writes-per-day 800
cf-architect scripts-fix --context global --package workerd
cf-architect scripts-fix --context project --package workerd
```

## The Four Products

| Product | Free? | Is for | Is NOT for |
|---|---|---|---|
| **Workers** | yes | Request handling, API, server-rendered UI, cron | Long jobs, native binaries, >128 MB memory |
| **Durable Objects** (SQLite) | yes | One authoritative stateful actor per entity; presence; WebSockets; coordination | Filesystems, blobs, anything over 5 GB or 128 MB resident |
| **R2** | yes, 10 GB | Objects, vault replicas, media, zero-egress reads | A database; a write path owned by two systems |
| **Containers** | **no — Workers Paid $5/mo** | Running a real server image at the edge | Media/transcoding against a local GPU; persistent disk |

**Tunnel is the missing fifth.** `cloudflared tunnel --url http://localhost:PORT`
exposes a machine that already exists — including one with GPUs — for free and
without a public IP. When the instinct is "put a container at the edge to run my
pipeline", the cheaper answer is almost always "tunnel to the box that already
has the hardware". Use Containers when there is no box, never as a weaker copy
of one you own.

## Durable Objects Doctrine

- **One object per entity**, keyed by that entity's identity. A vault entry, a
  task, a document, an agent session. The object *is* the lock.
- **Single-threaded by construction** — no compare-and-swap, no transaction
  retries, no race. This is the whole reason to use a DO instead of D1.
- **Billing follows wall-clock activity, not existence.** An idle object that
  can hibernate costs nothing. WebSocket Hibernation keeps long-lived
  connections free; without it, an open socket bills duration for its entire
  life.
- **5 GB SQLite is account-wide, not per object.** Documents yes, media no.

## The One-Authority Invariant

Cloudflare services multiply copies. Every copy that can be *written* is a
future disagreement.

- **Folder/git is the source of truth.** R2 is a one-way replica. A DO is a
  derived view. Both are rebuildable; neither may be edited.
- **Git is the only commit authority.** A CRDT/DO layer may carry presence and
  live cursors, but a change that matters lands as a commit, not as a document
  mutation.
- Anything that cannot be rebuilt from the source is not a replica — it is a
  second authority, and it will drift.

## Free-Tier Limits

Encoded in `budget`; see `references/free-tier-limits.md` for the dated table
and sources. Refresh that file when Cloudflare changes pricing — the arithmetic
is only as good as the constants.

## CLI Papercuts

These look like failures and are not:

1. **`npm warn install-scripts … workerd` is advisory.** npm 11 prints an
   unreviewed-scripts list; scripts still run. `workerd` ships its binary in the
   tarball, so the postinstall is a no-op.
2. **`--allow-scripts` is global-only.** On a project install it is a hard
   error (`EALLOWSCRIPTS`). Project policy lives in `package.json`
   `allowScripts` (pinned) or `.npmrc`.
3. **R2 needs one dashboard click.** No API path exists; `probe` reports it as
   a gate, not a permission error.
4. **`cf dev` is not `wrangler dev`.** It requires a dev server in the project
   (`@cloudflare/vite-plugin` or `wrangler`), then turns on
   `--experimental-new-config`, which demands `cloudflare.config.ts` with a
   schema that rejects `name`/`main`/`compatibility_date`. Use
   `npx wrangler dev` for local work on `cf` 0.15.
5. **Global npm installs are per-Node-version under nvm.** `cf` vanishes when
   you switch versions. Pin the version, or install per-version.

## Tests

```bash
python3 scripts/test_cf_architect.py
```
