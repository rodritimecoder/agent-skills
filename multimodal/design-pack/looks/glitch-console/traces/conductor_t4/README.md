# conductor @ 0:04 — the first trace

Proof that the grid is recovered from the pixels, not read off them.

**Source:** `kem_glitch/2026-10-06_glitch_orchestra_alignment_first/source.mp4`,
frame 120 (`--at 4.0`), `1080×1920 @ 30 fps`, crop `140,760,340,360`.

```bash
sprite-forge verify .            # PASS, 0.00% of cells wrong
sprite-forge verify . --mutate 3 # FAIL, 10.00% — the gate can fail
```

`overlay.png` is `frame.png` with the recovered pitch drawn on it: every green line
lands on an art-pixel boundary, which is the visual form of "aspect drift 0.27%".

## What it recovered

```
..############..
..############..
..##.######.##..
..##.######.##..
################
################
..############..
..############..
################
################
```

Measured pitch **18.25 × 18.20 px** (aspect drift 0.27%), palette exactly two
colours: `#12131c` paper, `#e17c51` coral. The render error is 5.55% of pixels,
all of it H.264 blur on cell boundaries; the cell vote is exact.

## Why this pose is not in `sprites.js`

The shipped `conductor` map has four leg stubs at rows 8–9. This frame has a
solid two-row platform bar instead. That is not a contradiction: `sprites.js`
was transcribed from 0:18–0:21, and `01_digest/CONTEXT.md` records that in
segment 1 (0:01–0:09) the *"platform bar (solid 2 rows) remains anchored to
baseline"*. Two timestamps, two poses — which is exactly the reason a pose
table needs a timestamp per row rather than one hand-drawn map per character.

`sprites.js` is unchanged. Adding this pose needs a name and a `PALETTES`
entry, and that is an art decision, not a measurement.
