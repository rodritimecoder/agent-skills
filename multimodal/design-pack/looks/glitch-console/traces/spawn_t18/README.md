# frontend @ 0:18.00 — the spawn

The first animation in the reel with **two channels running on different clocks**.
`motion` recovers both, and `motion-verify` proves the tracks reproduce the
measurement.

```bash
sprite-forge motion-verify .     # PASS: 0 rows, 0 rows, 5 channel units
```

Replay it from the reel:

```bash
sprite-forge motion <reel> --rect 395,780,200,170 --from 18.00 --to 18.75 --map 16x10 -o .
```

## What it found

| channel | kind | recovered |
|---|---|---|
| `height` | **stepped** | `[2, 4, 6, 8, 10]` art rows, holds `[2, 3, 3, 2, 13]`, step **2.0** |
| `tint` | **continuous** | `#f2f3f8` → `#7eb3ea`, 23 frames |
| `offset` | stepped | `[0, 2]`, holds `[15, 8]` — lifts 2 rows at the end |

Five steps of exactly two art rows, then a settle. That is the "5-step pokeball
cadence" the digest names, now with a number on each step.

The colour is **not** stepped: 23 distinct values over 23 frames, near-white to
the frontend blue. Replayed as a straight sRGB lerp it reproduces the measurement
to within **5 units per channel** — so the ramp is linear in sRGB, not perceptual,
and not a palette swap.

## Why this file exists

The jump at 0:54 and the stretch at 0:04 are pure geometry: one channel, integer
rows, one frame per change. This one is not. A recovery pass that assumes every
channel is stepped quantises the ramp into two or three colours and loses it; one
that assumes every channel is continuous smooths the five 2-row steps into a
slide and loses those. Both assumptions are wrong on this reel, and both look
plausible in isolation.

So `motion` classifies **per channel**, and refuses when a channel is neither:

```
sprite-forge: channel 'height' is not quantised to art rows (worst residual 0.46
rows at pitch 10.9). Either the pitch is wrong or this animation is not stepped.
```

That refusal is the useful part. It fires when the instrument is wrong, which on
this reel happened twice before the classifier existed.

## The isolation matters

The sprite at 0:18 is at x 395–595; by 0:19 the layout has shifted and the same
worker sits at x 141–311. A rect that spans both windows measures two different
sprites and produces a colour ramp that runs white → blue → pink. The rect must
contain **one sprite for the whole window**, or the tracks are fiction.

`spawn_strip.png` is 0:18.00 → 0:18.70 at 0.1 s per cell.
