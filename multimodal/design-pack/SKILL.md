---
name: design-pack
description: "Turn a look into a reusable pack an agent can read before it designs anything: references, a style sheet split into idea/look/feel, components drawn in every state, blocks, and one page with the code. Ships two isolated looks configured via look.json: `glitch-console` (dark terminal, 16x10 pixel sprites, Fantasque Mono, 30 fps stepped motion) and `material3-expressive` (Baseline Violet #6750a4, Light + Dark tonal surface elevation, 15-step type scale, 6 spring curves, zero-dependency `motion.js` engine for shape-morphing loaders, wavy progress, and pointer ripples). Use when a project needs an enforceable design system rather than a prompt, or when generated pages keep drifting off-style. Not a prompt library: it is tokens plus per-look policy plus gates that fail on drift."
compatibility: "Python 3.8+ for the verifier (stdlib only). Chromium/Playwright only if you want runtime checks or screenshot proofs. No server, no network."
allowed-tools: "Bash(design-pack:*) Bash(sprite-forge:*) Bash(ffmpeg:*) Bash(python3:*) Read Write"
---

# design-pack

A **pack** is the answer to "what does good look like here", written so a model can
read it in one pass and put it back down. Refined from Kem's *Design Pack* reel
(`DfPlX30teKG`): words will never cut it, references replace adjectives, and the
pack is one page you tell the model to read **before** it does any design work.

The difference from a prompt library: every value here came off a real reference,
every component is drawn in every state, and every look carries its own `look.json`
policy manifest so looks never leak rules into each other. `design-pack verify`
**fails** on token or motion drift, and `design-pack check` **fails** when an
interactive part errors or responds slowly (`> 100 ms`), or on layout overlap,
clipping, sub-floor text, or low contrast across the look's configured viewports
and theme variants.

## Available scripts

Bundled CLI scripts, referenced relative to the skill root. Run `<command> --help`
for flags and exit codes; structured data goes to stdout, diagnostics to stderr.

- `scripts/check_components.py` — check_components — the look-driven behavioural & structural gate for design-pack.
- `scripts/check_runner.mjs` — Behavioural check runner driving rendered components and Light/Dark themes in headless Chromium.
- `scripts/design_pack.py` — design-pack — the static token/motion gate and look policy loader (`look.json`).
- `scripts/sprite_forge.py` — sprite-forge — trace a pixel-art sprite out of video, in code (`glitch-console` pipeline).

## Layout

```
looks/glitch-console/     shipped look 1 — dark terminal, pixel sprites, stepped motion
  look.json               per-look policy: stepped motion, 10 px floor, >= 3:1 contrast, .win/.keybar checks
  README.md               what this look is, and where each value came from
  tokens.css              the contract: ink, paper, accents, type, space, motion
  sprites.js              ASCII pixel maps -> canvas, stepped, no easing
  pack.html               the retrieval target: 8-section spec, proportions, do/don't, blocks
  states.html             the spawn in five frames, for design review
  examples/               terminal.html · board.html · alignment.html · timing.html
  profiles/               substrate profiles (vst3.md + vst3-controls.html)
  traces/conductor_t4/    a measured pose: crop.json + grid.json + frame.png
  traces/conductor_jump_t543/   the jump: 6 rows, 300 ms, platform pinned
  traces/spawn_t18/       the spawn: 5 x 2-row steps + a 23-frame colour ramp
looks/material3-expressive/   shipped look 2 — Baseline Violet (#6750a4), Light + Dark, spring curves
  look.json               per-look policy: declared-curves, Light+Dark variants, 11 px floor, >= 4.5:1 contrast
  README.md               Zone 1 live capture provenance & Zone 2 8-section contract
  tokens.css              the contract: Light/Dark palettes, 5 tonal tiers, state layers, 6 spring tokens, 8 primitives
  motion.js               zero-dependency motion engine: spring solver, SVG shape morph, wavy progress, ripple, FAB menu
  pack.html               the retrieval target: proportions, Light/Dark contrast, state matrix, do/don't, blocks
  references/             5 live Material 3 Expressive captures (ref_01 .. ref_05)
  examples/               workspace.html · settings.html · motion.html
scripts/design_pack.py    look · tokens · sprite · verify · check
scripts/check_components.py  Playwright behaviour & layout gate (per-look viewports, themes, <=100ms, contrast)
scripts/sprite_forge.py   crop · grid · map · verify · motion · motion-verify (`glitch-console`)
references/method.md      the five zones + 8-section template, with provenance
tests/                    fail_control.html · fail_control_m3.html · test_gates.py
```

## Shipped looks & `look.json` policy contract

Each directory under `looks/<name>/` is isolated by `look.json`, deep-merged over
`NEUTRAL_LOOK_CONFIG` in `scripts/design_pack.py`. Cross-look rules never overlap:

| Policy axis | `glitch-console` | `material3-expressive` |
| :--- | :--- | :--- |
| `motion.mode` | `stepped` (`steps(...)`, `linear`, `--snap`/`--hold-`/`--step-`/`--spawn-`/`--scroll`) | `declared-curves` (`--ease-*` curves + `--dur-*` durations + `linear`; `allow_steps: false`) |
| `tokens.allow_color_mix_with_vars` | `false` (any `color-mix()` fails) | `true` (only `var(--...)`, `transparent`, `currentcolor`) |
| `tokens` prefixes | `--font-`, `--fs-`, `--r-` | `--font-`, `--fs-`, `--r-` |
| `sprites.enabled` | `true` (`sprites.js`) | `false` (`design-pack sprite` exits `2`) |
| `check.theme_variants` | `[]` (single dark theme, 7 viewports) | `["light", "dark"]` via `data-theme` (`7 x 2 = 14` viewport checks/page) |
| `check.viewports` | `375x812, 480x320, 640x400, 768x1024, 800x600, 1280x800, 1440x900` | `375x812, 412x915, 600x960, 840x1024, 1024x768, 1280x800, 1440x900` |
| `check.min_type_px` / `min_contrast` | `10.0 px` / `3.0:1` (`fallback_bg: [14, 17, 24]`) | `11.0 px` / `4.5:1` (`fallback_bg: null`, Light `#ffffff` default) |
| `check.forbidden_selectors` | `.win button`, `.win input`, `.win select`, `.win textarea` | `[]` (native controls allowed) |
| `check.clip_selectors` / `group_selectors` | `.win`, `.line`, `.chip`, `.ctl`, `.dial`, `.board`, `.stage`, `.keybar`, ... | `.m3-card`, `.m3-btn`, `.m3-fab`, `.m3-chip`, `.m3-field`, `.m3-toolbar`, `.m3-row`, ... |
| `check.shortcut_selector` | `.keybar .keybar__k` | `null` |

## Quick use & `--look` auto-detection

**How `--look` resolves:**
- Paths inside `looks/<name>/` automatically select `<name>` for both `verify` and `check` (mixing paths from multiple looks in one invocation exits `2`).
- Paths outside `looks/` (for example `./dist/page.html`):
  - `design-pack verify` defaults to `glitch-console` unless `--look <name>` is passed.
  - `design-pack check` runs in **neutral mode** (4 standard viewports `375x812,768x1024,1280x800,1440x900`, `10 px` floor, `3:1` contrast, `<= 100 ms` latency, no look-specific `forbidden_selectors`) unless `--look <name>` is passed.

```bash
design-pack look                                           # list shipped looks
design-pack tokens glitch-console                          # glitch-console declared tokens
design-pack tokens material3-expressive                    # M3E declared Light/Dark tokens

design-pack verify looks/glitch-console                    # auto-detects glitch-console
design-pack verify looks/material3-expressive              # auto-detects material3-expressive
design-pack verify --look material3-expressive page.html   # external page against M3E tokens & curves
design-pack verify ./dist --look glitch-console --json     # whole build against glitch-console

design-pack check looks/glitch-console                     # 7 terminal viewports, <=100ms, >=3:1 contrast
design-pack check looks/material3-expressive               # 14 viewport checks/page (7 viewports x Light+Dark)
design-pack check --look material3-expressive page.html    # external page with M3E rules (11px, >=4.5:1, Light+Dark)
design-pack check page.html                                # neutral mode check (no look-specific bans)

design-pack sprite conductor                               # glitch-console only: 16x10 ASCII map
```

## The five zones (see references/method.md)

| Zone | What goes in it | Cost |
| :--- | :--- | :--- |
| 1 references | real images of one style + at least two full-fidelity candidates side by side (chosen vs `AVOID` with one concrete reason), each with a note on what you like | minutes |
| 2 style sheet | named production constraint + explicit `NEVER` block + **8 sections** (Idea / Voice mapped to domain UI states / Mark / Colour by proportion & contrast / Type / Layout / Imagery / Texture & Motion) + drawn `do, don't` pairs | one borrowed format, filled in |
| 3 components | closed inventory (`N` parts, `M` timings, `K` marks), every piece in **every** state, then its motion | the real work |
| 4 blocks | full screens assembled from 3 | cheap once 3 exists |
| 5 design pack | one page with proportions, contrast, type, states, `do/don't`, snippets | assembly |

**Zone 2 is load-bearing.** Do not author a style sheet from nothing: find one you
like, hand it over *as the format*, and fill it from the references. Before filling
the 8 sections, name the production constraint the look must obey (two-ink press,
zero-pointer terminal, tonal-surface spring UI, fixed DAW host window) and write an
explicit `NEVER` block of patterns banned by that constraint. Map real UI states in
**Voice** to the domain's own vocabulary (for a print shop: loading -> "inking up",
error -> "a misprint", done -> "dry"), specify colour **by proportion** (not just
a flat hex list), and end sections in **drawn `do, don't` pairs**. Format transfers,
content must be yours.

### `glitch-console`: six primitives, not sixty components

The shortcut for `glitch-console`: a terminal cannot render a web control. It has
a window, a line, a chip, a rule, a meter and a sprite — and every screen is a
composition of those six. That is why zone 3 is small here and zone 4 is nearly free.

| Primitive | Class | States |
| :--- | :--- | :--- |
| window | `.win` | default (`ink`) · `win--paper` · `win--inset` |
| line | `.line` | `cmd` · `tree` · `event` · `dim` · `alert` · `sm` · `.term-input` · `.keybar` |
| chip | `.chip` | `default` · `ink` · `coral` · `pink` · `mint` |
| rule | `.rule` | `1px` · `heavy` · `dashed` |
| meter | `.bar` | `rest` · `on` · `dim` · `warn` |
| sprite | `.sprite` | `rest` · `blink` · `bop` · `squash` · `jump` · `descent` · `flash` + moods |

If a `glitch-console` screen needs a seventh, it is not a component — it is a
**block**: a new window, or a line that asks the question inline. Do not add a
`<button>`, `<input>`, select, modal or tooltip inside `.win` in this terminal look;
drive actions via keyboard triggers (`1` Hide, `2` Stop, `s` Spawn, `j` Jump, `m` Moods,
`g` Ground, `c` Comm ping).

**Base look vs substrate profiles (`glitch-console`).** The core `glitch-console` look
stays strictly zero-pointer terminal. When targeting a non-terminal substrate (like
a DAW plugin), add a **profile** that inherits all tokens and writes down its exact
exceptions rather than mutating the core look:
[`profiles/vst3.md`](looks/glitch-console/profiles/vst3.md) is the plugin-editor
contract (fixed host window, 4 / 6 / 7 column anchors, 10 px type floor, clickable
`.ctl` chips, the dial as a detent rail borrowed from the meter primitive, and the
single motion exception — *value feedback eases, chrome never does* — measured
against `profiles/vst3-controls.html`).

### `material3-expressive`: tonal surfaces, eight primitives, and spring physics

`material3-expressive` targets modern web/app UIs built around Google's **Baseline
Violet (`#6750a4`)** Light + Dark themes (`[data-theme="light"]` / `[data-theme="dark"]`),
a **5-tier tonal surface container ladder** (`lowest` -> `low` -> `default` -> `high` -> `highest`),
interactive **state layers** via `color-mix(in srgb, var(--md-on-*) <pct>, <surface>)`
(`8%` hover, `10%` focus, `10–12%` pressed, `12%` disabled container / `38%` disabled ink),
and **spring-physics spatial feedback** (pill-to-square corner morphing on press).

| Primitive | Class | Key variants / states |
| :--- | :--- | :--- |
| card | `.m3-card` | `filled` · `elevated` · `outlined` + `is-interactive` (`hover` / `focus` / `pressed` / `disabled`) |
| button | `.m3-btn` | `filled` · `tonal` · `outlined` · `text` · sizes `xs`/`sm`/`md`/`lg` + pill-to-square press morph |
| split & group | `.m3-split-btn`, `.m3-btn-group` | connected `lead`/`trail`/`item` shapes + `is-selected` morph |
| fab | `.m3-fab` | standard `56px` · `lg` (`96px`) · `extended` · `vibrant` (`--md-tertiary-container`) |
| toolbar | `.m3-toolbar` | `standard` · `vibrant` floating pill bar with `.m3-toolbar__btn` |
| chip | `.m3-chip` | `assist` · `filter` · `input` + `is-selected` pill morph |
| text field | `.m3-field` | `outlined` · `filled` + `hover` / `focus` / `pressed` / `is-error` / `is-disabled` |
| switch & loader | `.m3-switch`, `.m3-loader` | thumb expand on press/checked + shape-morphing `--dur-spin`/`--dur-spatial-slow` loader |

Navigation and layout primitives (`--md-surface*`, `.m3-app-bar`, `.m3-nav-rail`,
`.m3-nav-bar`, `.m3-nav-item`, `.m3-snackbar`) compose screens across Compact,
Medium, Expanded, and Large window classes. Motion uses only the 6 declared spring
tokens (`--ease-spatial-{fast,default,slow}` with overshoot for geometry/morphs and
`--ease-effects-{fast,default,slow}` critically damped for colour/opacity) paired
with `--dur-*` tokens; `steps(...)`, `ease`, and `ease-in-out` fail `verify`.
Runtime `check` enforces the `11 px` type floor (`Label Small`) and `>= 4.5:1`
WCAG contrast across all 14 Light + Dark viewport checks (`7` M3 viewports × `2` themes).

#### Runtime motion engine (`motion.js`)

`looks/material3-expressive/motion.js` is the zero-dependency companion to `tokens.css`.
CSS owns the declared curves and hover/focus/pressed state layers; the engine owns what
CSS cannot express: interrupted spring state, pointer-origin ripples, the 7-shape SVG
polygon loader, the wavy progress indicator, neighbour-push button groups, and the
staggered FAB menu. Load it once per page, before your own script:

```html
<script src="motion.js"></script>       <!-- page at the look root -->
<script src="../motion.js"></script>    <!-- page under examples/ -->
```

| API | Use |
| :--- | :--- |
| `mount(root)` | Bind loaders, wavy bars, ripples, groups, and FAB menus under `root`. Runs automatically on `DOMContentLoaded`. |
| `setProgress(el, 0..1)` | Drive a `.m3-progress-wavy` bar (also updates `aria-valuenow` and `data-value`). |
| `setPaused(bool)` / `isPaused()` | Pause/resume the shared loader + wavy RAF loop. |
| `evalSpring(name, tSec)` / `sampleLinearCss(name)` | Sample the declared spring at time `t`, or emit its 17-stop `linear(...)` CSS. |
| `SPRINGS` / `SHAPE_NAMES` / `SHAPES` | Inspect the 6 frozen spring specs and 7 morph shapes (`(damping, stiffness)` from Compose `MotionScheme.expressive()`). |
| `morphPoints` / `pointsToSvgPath` / `loaderFrame` | Reuse the polygon morph geometry directly. |

Markup contract: `.m3-loader > .m3-loader__morph` gets the engine SVG on mount (CSS
keeps the pre-JS fallback); `.m3-progress-wavy` needs only `data-value`; ripples attach
to the closed interactive inventory automatically. `data-dont` opts a subtree out,
`data-static` freezes one loader/bar, `data-engine="off"` leaves one loader/bar to
its CSS fallback, and `prefers-reduced-motion: reduce` disables
every animation while leaving state changes instant.

## Build a new look

1. **Collect references.** One style only. Public domain, or your own work (or live
   official spec captures). Write down what you actually like about each image:
   that note is the annotation.
2. **Compare candidates at full fidelity.** Render at least two candidate directions
   on the same subject to the same level of finish (a sketch is not comparable). Put
   them side by side, choose by looking, and tag each rejected sheet `AVOID` with
   one concrete reason.
3. **Copy the closest look.** `cp -r looks/<closest> looks/<name>` and inspect its
   `look.json`.
4. **Sample the references, do not guess.** Pull real hexes out of the frames:
   ```bash
   python3 - <<'PY'
   from PIL import Image; from collections import Counter
   im = Image.open("ref.png").convert("RGB")
   for c,k in Counter(im.getdata()).most_common(12):
       print("#%02x%02x%02x" % c, k)
   PY
   ```
5. **Fill `look.json`, `tokens.css`, then `pack.html`.** Declare the look's motion
   policy (`stepped` vs `declared-curves`), token prefixes, `color-mix()` policy,
   optional `theme_variants`, and runtime `check` thresholds/selectors in `look.json`.
   Name the production constraint and write its explicit `NEVER` block first, then
   fill the 8-section skeleton: map real UI states in Voice to domain vocabulary,
   specify ink/surface proportions and measured contrast, declare closed inventory
   counts (`N` parts, `M` timings, `K` marks), draw every component state, and add
   `do / don't` pairs.
6. **Gate it with a negative control.** Run both `design-pack verify looks/<name>`
   and `design-pack check looks/<name>`, then pair them with a `fail_control*.html`
   fixture that triggers every static and runtime check (`verify` + `check`). A pack
   that cannot fail is not a pack.

## Use the pack when writing UI

- Read `looks/<look>/pack.html` (or at least `tokens.css` + `README.md` + `look.json`)
  **before** designing.
- Once a pack passes both gates, treat each new surface (brand guidelines, slide
  deck, documents, social kit, merch, landing page) as one more prompt that reads
  `pack.html` and inherits the locked tokens, voice, and motion rather than a fresh
  design brief.
- Use `var(--token)` for every colour, size, radius, and declared motion curve/duration.
  Keep the look's colour proportion (`glitch-console`: `~78%` dark ink ground/body,
  `~12%` type/rules, `~5%` paper chrome, `~5%` semantic accents; `material3-expressive`:
  `~72%` tonal surfaces, `~14%` ink & hairline outlines, `~8%` tonal containers,
  `~6%` primary/tertiary/error accents).
- Take components from zone 3 rather than inventing ad-hoc controls (six primitives
  in `glitch-console`, eight `.m3-*` primitives in `material3-expressive`).
- Follow the look's motion contract:
  - In `glitch-console`, motion is stepped (`floor(t / (1000/fps))` / `steps(...)`), never eased.
  - In `material3-expressive`, motion uses the 6 declared `--ease-*` + `--dur-*` tokens (overshoot on spatial geometry, critically damped on effects), never `steps(...)` or bare `ease*`.
- Run **both** gates with the target look on what you produced:
  - `design-pack verify --look <look> <file>` (static conformance: undeclared colour, `color-mix()` policy, off-ladder font/size/radius, disallowed motion).
  - `design-pack check --look <look> <file>` (runtime behaviour across the look's configured viewports and `theme_variants`: verifies controls/shortcuts respond within `<= 100 ms` with zero console/page errors, plus overlap, clipping, type floor, and contrast, then waits for human sign-off).
  Treat FAIL as a build error, not a suggestion.

## Sprite pipeline (`glitch-console`)

> Specific to `glitch-console` (`sprites.enabled: true` in `looks/glitch-console/look.json`).
> Looks with `sprites.enabled: false` (such as `material3-expressive`) reject `design-pack sprite` with exit `2`.

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

### Motion: the bot never eases (`glitch-console`)

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

`looks/glitch-console/examples/terminal.html`, `board.html`, and `alignment.html` are
the 1-to-1 reference screens; `timing.html` renders the live programs, so none can
drift from `sprites.js`. `prefers-reduced-motion` keeps the sprites at rest.

## Adding a sprite (`glitch-console`)

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

## Motion: tracks, not poses (`glitch-console`)

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
  Once a pack passes both gates, each new surface (brand guidelines, slide deck,
  documents, social kit, merch, landing page) is one more prompt inheriting the
  locked tokens, voice, and motion rather than a fresh design brief.
- It does not judge taste. It only proves the output stayed inside the declared system.
- It does not ship webfonts. `glitch-console`'s `--font-mono` resolves through `local()`
  to Fantasque Nerd Font Mono (degrading to system mono), and `material3-expressive`'s
  `--font-brand`/`--font-plain`/`--font-mono` resolve through installed Roboto Flex /
  Google Sans / Roboto / Roboto Mono or system UI fallbacks.
