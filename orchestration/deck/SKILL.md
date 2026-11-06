---
name: deck

description: >
  Read-only homelab activity page: one dark dashboard aggregating GPUs (VRAM,
  temperature, utilisation), model servers and their ports, Tailscale devices,
  GitHub pull requests and last commit, Cloudflare account capability, the
  creator vault, and skill-hub state. Each source polls independently and
  reports its own freshness, so one dead API never blanks the page. Use when
  asked what the box is doing right now, whether a model is loaded, how much
  VRAM is free, which devices are online, or to expose a status page over
  Tailscale.

compatibility: "Python 3.10+ stdlib only. Optional: rocm-smi, tailscale, gh, cf-architect."
allowed-tools: "Bash(deck:*) Bash(systemctl:*) Bash(tailscale:*) Read"
---

# deck

A single page that answers "what is this machine doing right now", fed by
collectors that run **on the machine**. Nothing is pushed anywhere; nothing is
written back.

```bash
deck serve                     # http://127.0.0.1:7777
deck serve --port 7788
deck snapshot                  # collect once, JSON to stdout (scripting / tests)
```

## Read-Only Invariant

The collector never mutates a source. No model swaps, no CI triggers, no git
operations, no Cloudflare changes. This is deliberate: the page is reachable
over a tunnel, and a page that can evict a loaded model is one stray click away
from killing live inference. Actions belong in the CLIs that own them.

## Sources

| Source | Interval | Reads |
|---|---|---|
| `gpus` | 3s | `rocm-smi --json` — VRAM per card, temperature, busy % |
| `ports` | 5s | `GET /health` on 8080, 8081, 8083, 8084, 8085, 8090 |
| `tailscale` | 5s | `tailscale status --json` — backend, devices, online, IP |
| `vault` | 60s | reel count, newest entry, per-creator totals |
| `github` | 60s | open PRs + last commit for `DECK_REPO` |
| `cloudflare` | 300s | `cf-architect probe --json` (plan, gates, services) |
| `skills` | 120s | hub HEAD, dirty files, surface skill count |

## States

Every source carries its own `state`, `ts`, and `error`:

| State | Meaning | UI |
|---|---|---|
| `live` | Collected successfully just now | green |
| `idle` | Deliberately not available — Tailscale stopped, vault unmounted, service retired | amber |
| `stale` | Collection failed; showing the last error | red |

`idle` exists so a normally-off service (`:8084`, `:8090`) does not look like an
outage. A dashboard that cries wolf on boot gets ignored within a week.

## Endpoints

| Path | Purpose |
|---|---|
| `/` | The page (served from `assets/index.html`) |
| `/events` | SSE stream, pushes a full snapshot whenever any source publishes |
| `/snapshot.json` | One-shot JSON — the same payload the page renders |
| `/healthz` | `ok` |

## Environment

| Variable | Default |
|---|---|
| `DECK_HUB` | `~/src/my-agent-skills` |
| `DECK_VAULT` | `/run/media/rodri/AI/creator-vault` |
| `DECK_REPO` | `rodritimecoder/my-agent-skills` |
| `DECK_HOST` / `DECK_PORT` | `127.0.0.1` / `7777` |

## Install as a service

```bash
mkdir -p ~/.config/systemd/user
cp systemd/deck.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now deck
```

## Expose over Tailscale (no public IP)

```bash
tailscale up
tailscale serve --bg 7777
tailscale serve status        # -> https://<host>.<tailnet>.ts.net
```

Prefer this over `cloudflared tunnel`: the tailnet is private, and there is no
public URL pointing at a page that renders your machine's internals. Add a
Tunnel only for the case where you are off-tailnet, and put Cloudflare Access in
front of it if you do.

## Tests

```bash
python3 scripts/test_deck.py
```
