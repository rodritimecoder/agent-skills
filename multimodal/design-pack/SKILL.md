---
name: design-pack
description: "Turn a look into a reusable pack an agent can read before it designs anything: references, a style sheet split into idea/look/feel, components drawn in every state, blocks, and one page with the code. Ships a `glitch-console` look — dark terminal, 16×10 pixel sprites, Fantasque Mono, 30 fps pixel-snapped motion. Use when building a UI that should feel like a terminal, a GBA, or a retro pixel system, when a project needs a design system rather than a prompt, or when generated pages keep drifting off-style. Not a prompt library: it is tokens plus sprites plus a gate that fails on drift."
compatibility: "Python 3.8+ for the verifier (stdlib only). Chromium/Playwright only if you want a screenshot proof. No server, no network."
allowed-tools: "Bash(design-pack:*) Bash(sprite-forge:*) Bash(ffmpeg:*) Bash(python3:*) Read Write"
---

# design-pack

A **pack** is the answer to "what does good look like here", written so a model can
read it in one pass and put it back down. Refined from Kem's *Design Pack* reel
(`DfPlX30teKG`): words will never cut it, references replace adjectives, and the
pack is one page you tell the model to read **before** it does any design work.

The difference from a prompt library: every value here came off a real image, every
component is drawn in every state, and `design-pack verify` **fails** when a page
steps outside the pack.

## Layout

```
looks/glitch-console/     the shipped look — dark terminal, pixel sprites
  README.md               what this look is, and where each value came from
  tokens.css              the contract: ink, paper, accents, type, space, motion
  sprites.js              ASCII pixel maps -> canvas, stepped, no easing
  pack.html               the retrieval target: everything on one page
  states.html             the spawn in five frames, for design review
  examples/               terminal.html · board.html · alignment.html · timing.html
  traces/conductor_t4/    a measured pose: crop.json + grid.json + frame.png
  traces/conductor_jump_t543/   the jump: 6 rows, 300 ms, platform pinned
  traces/spawn_t18/       the spawn: 5 x 2-row steps + a 23-frame colour ramp
scripts/design_pack.py    look · tokens · sprite · verify
scripts/sprite_forge.py   crop · grid · map · verify · motion · motion-verify
references/method.md      the five zones, with provenance
```

## Quick use

```bash
design-pack look                          # what looks exist
design-pack tokens glitch-console         # the declared values
design-pack verify page.html              # the gate (exit 1 on drift)
design-pack verify ./dist --json          # whole builds
design-pack sprite conductor              # the 16x10 map, for debugging
```

## The five zones (see references/method.md)

| Zone | What goes in it | Cost |
| :--- | :--- | :--- |
| 1 references | real images of one style, each with a note on what you like | minutes |
| 2 style sheet | **idea** (concept, voice, rules) → **look** (what each colour/font is *for*) → **feel** (surface, texture, line, shape, spacing) | one borrowed format, filled in |
| 3 components | every piece in **every** state, then its motion | the real work |
| 4 blocks | full screens assembled from 3 | cheap once 3 exists |
| 5 design pack | one page with swatches, type, states, snippets | assembly |

**Zone 2 is load-bearing.** Do not author a style sheet from nothing: find one you
like, hand it over *as the format*, and fill it from the references. Format transfers,
content must be yours.

### A terminal has six primitives, not sixty components

The shortcut for this whole look: a terminal cannot render a control. It has a window,
a line, a chip, a rule, a meter and a sprite — and every screen is a composition of
those six. That is why zone 3 is small here and zone 4 is nearly free.

| Primitive | Class | States |
| :--- | :--- | :--- |
| window | `.win` | default (`ink`) · `win--paper` · `win--inset` |
| line | `.line` | `cmd` · `tree` · `event` · `dim` · `alert` · `sm` · `.term-input` · `.keybar` |
| chip | `.chip` | `default` · `ink` · `coral` · `pink` · `mint` |
| rule | `.rule` | `1px` · `heavy` · `dashed` |
| meter | `.bar` | `rest` · `on` · `dim` · `warn` |
| sprite | `.sprite` | `rest` · `blink` · `bop` · `squash` · `jump` · `descent` · `flash` + moods |

If a screen needs a seventh, it is not a component — it is a **block**: a new window,
or a line that asks the question inline. Do not add a `<button>`, `<input>`, select,
modal or tooltip to a terminal look; drive actions via keyboard triggers (`1` Hide,
`2` Stop, `s` Spawn, `j` Jump, `m` Moods, `g` Ground, `c` Comm ping).

## Build a new look

1. **Collect references.** One style only. Public domain, or your own work. Write down
   what you actually like about each image — that note is the annotation.
2. **Copy the closest look.** `cp -r looks/glitch-console looks/<name>`.
3. **Sample the references, do not guess.** Pull real hexes out of the frames:
   ```bash
   python3 - <<'PY'
   from PIL import Image; from collections import Counter
   im = Image.open("ref.png").convert("RGB")
   for c,k in Counter(im.getdata()).most_common(12):
       print("#%02x%02x%02x" % c, k)
   PY
   ```
4. **Fill tokens.css, then pack.html.** Every state of every component. If a state
   has no drawing, the model will invent one.
5. **Gate it.** `design-pack verify looks/<name>/pack.html`, then verify a page you
   generated with it. A pack that cannot fail is not a pack.

## Use the pack when writing UI

- Read `pack.html` (or at least `tokens.css` + `README.md`) **before** designing.
- Use `var(--token)` for every colour, size and radius. A raw hex is a drift.
- Take components from zone 3 rather than inventing a control. In a terminal look
  there are six primitives and no seventh — see the table above.
- Motion is stepped: quantise to `floor(t / (1000/fps))`, never an eased property.
- Run `design-pack verify <file>` on what you produced. It fails on an undeclared
  colour, an off-ladder font or size, a radius, and any eased curve; `--loose` only
  demotes the last three to warnings. Treat FAIL as a build error, not a suggestion.

## Sprite pipeline (this look)

Sprites are ASCII maps on a 16×10 body inside a 22×18 grid (`PAD_X = 3`), drawn to
`<canvas>` at an integer scale with `imageSmoothingEnabled = false`. All four bots
(`conductor`, `frontend`, `copy`, `tests`) share `REST_ROW = 6` (rows 6–15) so their
feet land on the same baseline; `conductor`'s 2-row solid platform sits fixed at
`PLAT_ROW = 16..17`, leaving 6 rows of overhead headroom (`rows 0..5`) for jumps and tells.

```html
<canvas data-sprite="conductor" data-mood="outputting"></canvas>
<canvas data-sprite="frontend" data-mood="thinking" data-wait-spawn data-stagger-spawn></canvas>
```

```js
Pixels.staggerSpawn(stage, 330); // staggered 23-frame floor-rise spawn across workers
Pixels.setPaused(true);          // freeze/resume 30 fps loop (2 Stop)
Pixels.cycleMood(root);          // cycle measured particle moods (m Moods)
```

### Motion: the bot never eases

Everything below was measured off the reference reel at 30 fps, one frame at a time.
Do not soften it back into a tween.

- **Unified floor baseline.** All 4 bots rest at rows 6–15 with `conductor`'s fixed
  2-row coral platform directly beneath at rows 16–17, sharing one floor and label row.
- **A pose change takes one frame, 33 ms.** There is no interpolation anywhere. What
  looks smooth in the video is the *terminal transcript scrolling*, not the sprite.
- **Holds are irregular.** Measured set: 66, 99, 132, 165, 198, 231, 264, 297, 330,
  363, 396, 495, 660 ms. `PROGRAMS.idle` picks from it with a seeded hash, so a
  roster drifts apart instead of pulsing in unison.
- **Particles are 30 fps stepped tells, not eased emitters.** Measured `Pixels.moods`:
  `outputting` (dual-slot `♪`/`♫` conveyor anchored to `restRow`, `396+330+363+396 ms`),
  `thinking` (5-step `0.65×px` pixel-dust cascade into a 1.25px horizontal band),
  `absorbing` (diagonal taste blocks + `66 ms` 72% paper torso flash),
  `aligning` (`-2.5 px` right-to-left `✶`/`✴`/`✻` sparkle wave + coral micro specks),
  and `packet` (`0.65×px` waiting hopper + 2-phase packet→ping stream).
- **The stage is one window.** Every bot stands on the same floor inside a single
  `win--paper` terminal. Never a card per bot.

`examples/terminal.html`, `examples/board.html`, and `examples/alignment.html` are the
1-to-1 reference screens; `examples/timing.html` renders the live programs, so none
can drift from `sprites.js`. `prefers-reduced-motion` keeps the sprites at rest.

## Adding a sprite

A sprite comes out of a frame, not out of an imagination. `sprite-forge` measures
the grid, the palette and the map, then proves the result reproduces the frame:

```bash
sprite-forge crop reel.mp4 --at 4.0 --rect 140,760,340,360 -o stage/
sprite-forge grid stage/ --map 16x10        # pitch, palette, ASCII rows
sprite-forge map  stage/ --name conductor   # the MAPS entry
sprite-forge verify stage/                  # gate: every cell must reproduce
sprite-forge verify stage/ --mutate 3       # control: the gate must fail
```

Crop from the **source video at native resolution**, never from a screenshot of it.
A screenshot is a downscale, so the art pixel lands on a fractional pitch and the
map shears. The tracer absorbs a fractional pitch by deriving it from the sprite's
own bounding box over the *declared* map size — which is also why a wrong `--map`
is caught rather than silently rounded.

Then append the printed entry to `MAPS` and add a `PALETTES` line; `design-pack
sprite <name>` confirms the grid is rectangular. `traces/conductor_t4/` is a
worked example you can re-run. Transcribe from the reference; never hand-draw a
shape you have not measured.

## Motion: tracks, not poses

A pose is not the unit of animation. A jump, a bop and a stretch are the same
primitive at different amplitudes, and the spawn runs two channels on two clocks.
So `motion` recovers **per-channel tracks** and classifies each one:

```bash
sprite-forge motion reel.mp4 --rect 395,780,200,170 --from 18.00 --to 18.75 --map 16x10 -o stage/
sprite-forge motion-verify stage/          # replay the tracks against the measurement
```

| channel | what it is | what it caught |
| :--- | :--- | :--- |
| `height` | visible rows | the spawn: `[2,4,6,8,10]`, step **2.0**, five steps |
| `offset` | rows above the resting bottom | the jump: **6 rows**, held 9 frames |
| `tint` | modal colour | the spawn: `#f2f3f8` → `#7eb3ea`, **continuous**, 23 frames |

The rule that makes this work: **geometry is quantised to art rows, colour is
not.** `motion` snaps every geometry channel to whole rows before classifying,
and refuses when the residual is too large:

```
sprite-forge: channel 'height' is not quantised to art rows (worst residual 0.46
rows at pitch 10.9). Either the pitch is wrong or this animation is not stepped.
```

That refusal fires when the *instrument* is wrong — wrong rect, wrong pitch,
two sprites in one crop. On this reel it fired twice before the classifier
existed, and both times the animation was fine and the measurement was not.

**One sprite per rect, for the whole window.** The frontend spawns at x 395–595
and then the layout shifts it to x 141–311; a rect spanning both measures two
different sprites and reports a colour ramp that runs white → blue → pink.

`motion-verify` replays each track against the stored measurement and fails when
the quantisation lost something. It is a gate on the model, not on the reel:
`PASS` means integer rows and run-lengths reproduce every frame; `FAIL` means the
tracks are a lossy summary and should not be trusted.

## What this skill does not do

- It does not generate a page for you. It gives the model the corpus to do it well.
- It does not judge taste. It only proves the output stayed inside the declared system.
- It does not ship webfonts. `--font-mono` resolves through `local()` to the installed
  Fantasque Nerd Font Mono, and degrades to a system mono elsewhere.
