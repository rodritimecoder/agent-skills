# Cloudflare free-tier limits

Verified **2026-10-21** against `developers.cloudflare.com`. These constants are
encoded in `scripts/cf_architect.py::LIMITS` — if the numbers here change, change
them there and the budget arithmetic follows.

## Free plan

| Service | Limit | Notes |
|---|---|---|
| Workers | 100,000 requests/day | 10 ms CPU per request |
| Durable Objects — requests | 100,000/day | HTTP, RPC sessions, WebSocket messages (20:1 billing ratio), alarms |
| Durable Objects — duration | 13,000 GB-s/day | 128 MB per object; hibernating objects bill nothing |
| Durable Objects — row reads | 5,000,000/day | |
| Durable Objects — row writes | 100,000/day | `setAlarm()` counts as a write |
| Durable Objects — storage | 5 GB total | **account-wide**, SQLite backend only on free |
| D1 | 5 GB, 5M reads/day, 100k writes/day | |
| KV | 100,000 reads/day, 1,000 writes/day, 1 GB | |
| R2 | 10 GB-month, 1M class A, 10M class B | egress free |
| Workers AI | 10,000 neurons/day | ≈3.5 h audio via Whisper (estimated, not published per-hour) |
| Containers | **none** | Workers Paid only |

## Paid triggers

| Trigger | Cost |
|---|---|
| Containers | Workers Paid **$5/mo**, includes 375 vCPU-min, 25 GiB-h, 200 GB-h disk |
| R2 beyond 10 GB | $0.015/GB-month |
| DO beyond 5 GB | $0.20/GB-month |
| KV beyond 1 GB | $0.50/GB-month |

## Worked example — the creator vault

1.5 GB total, 27 reels, 2,009 frames, 58 markdown files.

- Notes + transcripts + frames ≈ 9 MB/reel → ~1,000 reels fit in R2's 10 GB.
- `source.mp4` ≈ 93 MB/reel → the whole 10 GB covers ~107 reels. Keep the mp4s
  out of the replica, or in a separate prefix that gets pruned.
- One DO per reel costs one write per state transition. 100k writes/day is three
  orders of magnitude of headroom for a human-paced ingest pipeline.

## Refresh procedure

1. Fetch `developers.cloudflare.com/durable-objects/platform/pricing/`,
   `/workers/platform/pricing/`, `/r2/pricing/`, `/d1/platform/pricing/`,
   `/workers-ai/platform/pricing/`, `/containers/platform/pricing/`.
2. Diff against the tables above.
3. Update `LIMITS`, run `python3 scripts/test_cf_architect.py`, update the
   verification date here.

## Sources

- https://developers.cloudflare.com/durable-objects/platform/pricing/
- https://developers.cloudflare.com/workers/platform/pricing/
- https://developers.cloudflare.com/r2/pricing/
- https://developers.cloudflare.com/d1/platform/pricing/
- https://developers.cloudflare.com/containers/platform/pricing/
- https://developers.cloudflare.com/workers-ai/platform/pricing/
