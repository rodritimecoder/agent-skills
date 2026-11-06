# glitch-console

> A dark terminal that moves in pixels. One 16×10 body per worker, one accent each,
> Fantasque Mono, 30 fps motion that snaps between held poses. No easing, no glow,
> no radius.

**Source:** Kem, *The Design Pack* (`https://www.instagram.com/p/DfPlX30teKG/`) — the
method. **Palette and sprites:** extracted from the Glitch Orchestra reels
`DeKBMCQNRXU` and `DeEyZPEtkyH`, frames `000003`, `000012`, `000014`, `000016`.

## Zone 1 · References (what to copy)

Real stills and animation sequences extracted directly from `source.mp4` (`DeKBMCQNRXU`):

| Stills | Source Time | What to copy |
| :--- | :---: | :--- |
| [ref_01_stage_orchestra.png](references/ref_01_stage_orchestra.png) | `0:19.5` | **The stage:** One shared `win--paper` terminal window with dots, path, chip, and a single floor where all workers stand together. |
| [ref_02_conductor_tuning.png](references/ref_02_conductor_tuning.png) | `0:03.0` | **The single window:** `Claude Code` header, `> /glitch-orchestra` prompt, and `conductor ★ tuning up` line. |
| [ref_03_tell_musical_notes.png](references/ref_03_tell_musical_notes.png) | `0:06.7` | **The outputting tell:** Discrete monospace `♪` → `♪♪` → `♪` held steps overhead, floating upward as they output. |
| [ref_04_tell_sparks.png](references/ref_04_tell_sparks.png) | `0:05.3` | **The thinking tell:** Discrete spark cluster progression (1 → 2 → 3 clusters, 165 ms each), then 495 ms clear. |
| [ref_05_spawn_sequence.png](references/ref_05_spawn_sequence.png) | `0:19.7`–`0:20.0` | **The pokeball spawn:** Five held steps of 90 ms (flash → oversize → squash → colour fill → settle); zero fade, zero easing. |
| [ref_06_jump_animation.png](references/ref_06_jump_animation.png) | `0:20.0`–`0:20.3` | **The jump animation:** The bot lifts off the floor (`dy: -3.5` rows / 52 px lift), holds at peak, and squashes on landing. |
| [ref_07_legs_comparison.png](references/ref_07_legs_comparison.png) | `0:20.0` | **Platform base vs leg stubs:** Conductor stands on a solid 2-row platform band (`################`); workers stand on four symmetrical leg stubs (`..#.#......#.#..`). Both share identical scale (`scale: 10`). |
| [ref_08_white_orange_sparkles.png](references/ref_08_white_orange_sparkles.png) | `0:20.3` | **White & orange sparkle cluster:** Overhead thinking sparkles use alternating white and orange/coral dots across the roster. |
| [ref_09_conductor_jump_lift.png](references/ref_09_conductor_jump_lift.png) | `0:20.5`–`0:20.9` | **Conductor lift & revealed legs:** In rest stance (left), conductor sits directly on the platform. When stretching up or jumping (middle, right), the body lifts 20 px into the air, revealing the four leg stubs (`..#.#......#.#..`) above the grounded platform. |
| [ref_10_kanban_board_particles.png](references/ref_10_kanban_board_particles.png) | `1:26.5` | **Kanban board & celebration particles:** The clean top board (`Board · 3 of 3 done`, `started · 3 tasks`, single-line status tokens `TO DO 0`, `NEEDS YOU 0`, `DOING 0`, `CHECK 0`), drifting confetti particles, divider line, and 3 passing avatars with `✓ passed`. |
| [ref_11_avatar_alignment_comm_ping.png](references/ref_11_avatar_alignment_comm_ping.png) | `0:59.0` | **Avatar alignment & communication ping:** Conductor and Frontend horizontally aligned at head level and label baseline, linked by 4 square packet dots (`■ ■ ■ ■`), with the crouch-spring jump response. |

## Zone 2 · Style sheet (idea · look · feel)

### The Idea
A deadpan terminal UI that moves in discrete pixels, never continuous tweens. The voice is a deadpan site surveyor: states what was measured, never apologises or says "oops". A terminal has **six primitives and no seventh** (`.win`, `.line`, `.chip`, `.rule`, `.bar`, `.sprite`). Every bot stands inside one terminal window; heads are aligned horizontally across the stage (`align-items: flex-start`). When dipping (`dy: +2`, `flatten: 0.75`), the body sinks down 2 rows, submerging conductor's legs into the platform (`image_5ff87c81-4625-47fb-9436-4f14dd9e1325`) and worker below its standing line, before springing up (`dy: -2`, `flatten: 1.25`) into the air. Full contract: [context.md](context.md).

### The Look — what each colour and font is *for*
- `--coral` (`#d87653`): Conductor / planner (the master plan, orchestration).
- `--blue` (`#68a8e6`): Frontend worker ("the world", layout, chrome).
- `--pink` (`#f02e75`): Copy worker ("the words") and alert/destructive signals.
- `--mint` (`#54c693`): Tests worker ("the holdout"), passing assertions, terminal carets.
- `--yellow` (`#f7d140`): Attention chip (`orchestrator`), pending actions, input focus rings.
- `--paper` (`#fdf6e3`): Window frame border, paper title bar (`win--paper`), flash frames.
- `--ink-900` / `--ink-800` / `--ink-700` (`#0e1118` / `#12151c` / `#171b24`): Screen ground, terminal body, raised panel surface.
- `--font-mono` (`Fantasque Sans Mono, monospace`): All commands, logs, agent states, and glyphs.

### The Feel — surface, texture, line, shape, spacing
- **Surface**: Flat ink planes (`--ink-800` body, `--ink-700` panels). Zero gradients; meters use discrete cellular segments (`.bar__cell`).
- **Texture & Shadow**: One hard offset shadow (`6px 6px 0 var(--paper-2)` or `--shadow-hard`), zero blur.
- **Line & Shape**: 1px/2px hard borders, 0px border radius (corners stay square like pixel art; 50% only for the 7px window dots).
- **Spacing**: Discrete 4px grid steps (`--s-1` to `--s-10`).
- **Motion**: 30 fps pixel-snapped frame gate, 33 ms single-frame pose swaps, irregular holds (100–726 ms).

## Where every value came from

| Token | Value | How it was measured |
| :--- | :--- | :--- |
| `--ink-800` | `#12151c` | mode colour of the terminal body, 71–90% of every screen frame |
| `--ink-700` | `#171b24` | title strip and raised panels |
| `--paper` | `#fdf6e3` | the window border, sampled on a clean row (`y=352`) |
| `--coral` | `#d87653` | conductor body fill |
| `--coral-hi` | `#f39f7e` | conductor highlight, sampled at 1,121 px |
| `--blue` | `#68a8e6` | frontend body fill |
| `--pink` | `#f02e75` | copy body fill and the caption highlight |
| `--mint` | `#54c693` | tests body fill |
| `--yellow` | `#f7d140` | the `orchestrator` chip and every attention label |
| `--violet` | `#7848f6` | astra body fill |
| `--red` | `#de301c` | sol's head band |
| sprite grid | 16×10 | conductor bbox 169×104 px; five bands of ~21 px, ~10.5 px per art pixel. Read off `0:18–0:21` |

Nothing above is a preference. If you change one, say which image you measured instead.

## The sprite body

```
worker (16×10)
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

conductor (16×10) — same body, stands on a solid platform base band
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

Two slit eyes, arms that break the silhouette, and a 16-cell footprint:
- **Workers**: Four one-cell leg stubs: outer leg on edge (col 2), skip a pixel (col 3), inner leg stub (col 4), 6-pixel centered opening, inner leg stub (col 11), skip a pixel (col 12), outer leg on edge (col 13) — `..#.#......#.#..`. Perfectly centered and symmetric.
- **Conductor**: Stands on a solid 2-row platform base band (`################`) across the bottom.
Both share identical scale (`scale: 10`), identical canvas dimensions ($160 \times 170$ px), and a unified floor line (row 17) where conductor's platform and workers' feet meet, keeping all text captions (`conductor`, `frontend`, `copy`, `tests`) completely inline horizontally.

## Files

| File | What it is |
| :--- | :--- |
| `tokens.css` | the contract — ink, paper, accents, type, space, motion |
| `sprites.js` | ASCII maps → canvas; `Pixels.mount`, `Pixels.spawn`, `Pixels.pose` |
| `pack.html` | the retrieval target: palette, type, sprites, every component state, blocks, motion |
| `states.html` | the spawn in five frames, for design review |
| `examples/` | reference pages built from the pack: `hero.html`, `settings.html`, `terminal.html`, `timing.html` (the cadence as a diagram) |

`data-static` on a canvas means "I will draw this myself with `Pixels.pose`" — the
auto-loop leaves it alone. That is how `states.html` renders five frames at once.

## Motion — measured, not guessed

Read off `DeKBMCQNRXU` at 30 fps, frame by frame: 210 frames of `0:02–0:09` and 195 of
`0:17.5–0:24.0`, tracking the coral/blue/pink blobs by colour mask. The window is static
throughout, so every number below is the sprite itself.

| What | Measurement |
| :--- | :--- |
| Pose change | **one frame, 33 ms.** There is no interpolation anywhere. |
| Hold length | irregular: 100, 132, 165, 198, 231, 330, 363, 396, 462, 495, 660, 726 ms — median ≈ 350 ms |
| Stretch vs Jump | **Stretch:** feet stay pinned while top alternates `793 ↔ 829` (`rest 1.0`, `up 1.2`, `down 0.85`).<br>**Jump:** discrete lift off floor (`dy: -2.5` to `-3.5` rows / 20–52 px lift), peak hold (165–330 ms), squash landing. In the conductor, stretching up or jumping lifts the body off the platform, revealing the four leg stubs above the grounded base. |
| Thinking | spark clusters above head: 1 → 2 → 3 clusters with **alternating white & orange/coral dots**, 165 ms each, then 495 ms clear |
| Outputting | `♪` → `♪♪` → `♪`, 363 ms each, **floating upward** as steps advance, then 660 ms clear |
| Spawn | five held steps of 90 ms |
| Step cycle | 84 ms per pose (12 fps), only for the walk program |

**Nothing eases and nothing interpolates.** The earlier `sink` program — 667 ms of
accelerating descent, then a spring — was an artefact of reading the *transcript
scroll* as sprite motion. The sprite never sinks. What scrolls in the reel is the text;
the bot swaps pose inside a single frame and holds.

`POSES` uses discrete row displacement (`dy`) on a 16-row discrete ladder (no flattening stretch):
`rest` (`dy: 0`, Row 3 tall idle), `squash` (`dy: +2`, Row 5 compressed squat), `jump` (`dy: -3`, Row 0 peak airborne with clear 4-row air gap), and `descent` (`dy: -1`, Row 2 drop). `PROGRAMS.jump` and `PROGRAMS.workerJump` execute the frame-accurate 5-step cadence from the 30 fps stream. `PROGRAMS.idle` picks the next hold from the measured set with a seeded hash, so a roster drifts apart instead of pulsing in unison. `examples/timing.html` draws all of it from `Pixels.programs`, so the diagram and the code cannot disagree.

The stage is **one window**: every bot stands on the same floor inside a single
`win--paper` terminal, never one card each. `examples/terminal.html` is that layout.

## Voice

The reel's voice rule, borrowed verbatim because it is the personality:

> *"A deadpan site surveyor. States what was measured. Never says sorry or 'oops'."*

Applied here: the UI reports, it does not apologise. `It stopped. I watched.` — not
`Oops, something went wrong!`. An error keeps the same type, the same tokens, and the
same flatness as a success.

## What is not in this look, on purpose

- **No blurred shadows.** One hard offset shadow, `6px 6px 0`.
- **No border radius above 2px.** Pixel art has corners.
- **No gradients.** Progress is discrete cells.
- **No icon set.** Sprites, glyphs from the Nerd Font, and text.
- **No hover tween.** Hover is one step up the ink ladder, applied instantly.
