# conductor @ 0:54.3 — the jump

The counter-example to `conductor_t4`. At 0:04 the bot stretches in place; at
0:54.3 it is **airborne**, and the map does not change at all.

```bash
sprite-forge verify .            # PASS, 0.00% of cells wrong
```

`jump_strip.png` is 0:53.8 → 0:54.7 at 0.1 s per cell: the 5th and 6th cells
(0:54.2, 0:54.3) are the ones in the air.

## The measurement

Two bands, tracked per frame across 0:53–0:56 at 30 fps. "Band" = a row whose
longest continuous run of non-background is ≥100 px, which finds the solid body
and the platform bar and ignores the thin leg stubs and the `♪` particles.

| | rest (0:54.133) | airborne (0:54.167 – 0:54.433) |
|---|---|---|
| sprite bbox top | y 824 | y 718 |
| sprite bbox bottom | y 1001 | y 896 |
| platform bar | y 964 – 1000 | y 964 – 1001 |

- **Hold: 9 frames = 300 ms**, one frame in and one frame out. No tween.
- **Rise: 106 px = 5.96 art rows** at pitch 17.8 — exactly **6 rows**.
- **The platform does not move** — 964 → 964 across the whole window. The jump
  is the body leaving a fixed floor, not the floor following it.

`motion.json` in this folder is the same window as a track:

```
sprite-forge motion-verify .
  offset  stepped  [0, 6, 0]  holds [17, 9, 16]   max error 0 art rows
  tint    stepped  ['#e17c51', '#df7d51', '#e17c51']  max error 0
```

The bbox at rest includes the platform bar (the legs touch it, so they form one
connected component); airborne it does not, which is why the bottom moves 105 px
and the top 106 px. An earlier pass measured the solid body's bottom edge instead
of the sprite bbox and reported 3.9 rows. The bbox is the right instrument: it
gives an integer, and integer is the law this animation obeys.

## The map is identical

```
..############..
..############..
..##.######.##..
..##.######.##..
################
################
..############..
..############..
..#.#......#.#..
..#.#......#.#..
```

Same 16×10, same rows, at rest and at peak. So the jump is **pure translation**:
`translateY(-3.9 art rows)`, held 300 ms, with no pose change. Nothing to
interpolate and nothing to redraw — which is why it reads as a jump rather than
a squash.

## Why this file exists

An earlier measurement of 0:03.5 – 0:09.5 found a 2-row stretch with the feet
planted, and that was generalised to "the bot does not jump". That was true of
one six-second window and false of the reel. Two windows, two motions:

| window | motion | feet |
|---|---|---|
| 0:03.5 – 0:09.5 | 2-row vertical stretch, legs compress | in contact |
| 0:53 – 0:56 | 6-row translation, 300 ms | leave the floor |

Both are held poses, both are one frame in and out, and neither eases. The
difference is contact: a stretch keeps the legs on the platform, a jump does not.
