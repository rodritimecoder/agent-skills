# glitch-console · ICM Context Specification

> **Tier:** Late-binding UI token contract for pure terminal interfaces.  
> **Source:** Kem Glitch Orchestra (`ref_01`, `ref_02`, `ref_05`, `ref_10`, `ref_11`).  
> **Gate:** `design-pack verify <target>` (strict mode, zero tolerance for drift).

---

## 1 · The Six Primitives (No Seventh)

| # | Primitive | CSS Class | Allowed States |
| :-- | :--- | :--- | :--- |
| 1 | Window | `.win` | default (`ink`), `win--paper` (cream titlebar `#fef2da` + `#0a0b10` border/8px shadow), `win--inset` (no shadow) |
| 2 | Line | `.line` | `line--cmd`, `line--tree` (`└`), event (`●`), `line--dim`, `line--alert`, `line--sm`, `.term-input`, `.keybar` |
| 3 | Chip | `.chip` | default (`--yellow`), `.chip--ink`, `.chip--coral`, `.chip--pink`, `.chip--mint` |
| 4 | Rule | `.rule` | default (1px `--rule`), `.rule--heavy` (2px), `.rule--dashed` |
| 5 | Meter | `.bar` | `.bar__cell--on`, `.bar__cell--dim`, `.bar__cell--warn`, default off (`--ink-600`) |
| 6 | Sprite | `.sprite` | `rest`, `blink`, `bop`, `squash`, `jump`, `descent`, `flash` + `outputting` / `thinking` / `absorbing` / `aligning` / `packet` moods |

No raw `<button>`, `<input>`, or `<select>` controls inside terminal windows. Interactions use keyboard triggers (`1` Hide, `2` Stop, `s` Spawn, `j` Jump, `m` Moods, `g` Ground, `c` Comm ping).

---

## 2 · Unified Sprite Grid & Baseline

- **Canvas grid**: $22 \times 18$ art cells (`PAD_X = 3`, `GRID_COLS = 22`, `GRID_ROWS = 18`).
- **Body-level alignment**: ALL bots (`conductor`, `frontend`, `copy`, `tests`) share `REST_ROW = 6` (10-row body at rows `6..15`), aligning heads, eyes, arms, torsos, and leg bottoms on identical horizontal rows.
- **Conductor platform** (`#e17c51` / `var(--coral)`): 2-row solid platform anchored at `PLAT_ROW = 16..17` directly underneath `conductor`'s feet; remains fixed during `squash` (`dy: +2`) and `jump` (`dy: -6`, `topRow = 0`, 6-row air gap).
- **Default 4-bot order (left-to-right)**: `conductor` → `frontend` → `copy` → `tests`.
- **Staggered Floor-Rise Spawn**: Canvases with `data-wait-spawn` stay blank until `Pixels.staggerSpawn(root, 330)` fires each 23-frame (`759 ms` @ 30 fps) floor-rise (`height: 2→4→6→8→10`, `floorDy: 2` for frames `0..14` then `0` for `15..22`) with linear sRGB tint lerp from `--spawn-flash` (`#f2f3f8`) to bot accent.

---

## 3 · Particle Moods, Comm Stream & Controls

- **Outputting (`outputting`)**: Dual-slot `♪` / `♫` conveyor in agent ink (`bold 2.3×px`) anchored relative to `restRow` (notes never bob on jump/bop) across 4 stepped holds (`396 + 330 + 363 + 396 ms`), clamped inside `GRID_COLS = 22` and `y >= 2.1×px`.
- **Thinking (`thinking`)**: 5-step pixel-dust cascade (`0.65×px` dots in `--paper`, `--yellow`, `--coral`; `165×3 + 198 + 495 ms`) settling into an 11-dot quantized `1.25px` horizontal band (`rowAbove = 1.3` and `2.1`).
- **Absorbing (`absorbing`)**: `0.95×px` taste blocks (`--yellow`, `--pink`, `--mint`, `--paper`) stepping diagonally up-left from lower-right into torso belly core over `6×66 + 198 ms`, drawn over the torso and triggering a `66 ms` `lerpSrgb(bodyRgb, paperRgb, 0.72)` impact flash on steps `2` and `5`.
- **Aligning (`aligning`)**: Two wrapped wave cursors stepping `-2.5 px` right-to-left (`8×132 + 396 ms`) with crisp `✶`/`✴`/`✻` glyphs (`bold 2.3×px` in `--paper`/`--text`, `y >= 2.3×px`) flanked by `0.5×px` `--coral` micro specks.
- **Packet (`packet`) & `Pixels.communicate(stage)`**: `0.65×px` `--text` hopper square over upper-left of waiting bots (`3×165 + 330 ms`), paired with `.comm-line` sequential `▪ ▪ ▪ ▪` packets (`165 ms` steps) transitioning into `■ ■ ■ ■` sync burst + 6-row jumps.
- **Pause & Mood API**: `Pixels.setPaused(bool)`, `Pixels.isPaused()`, `Pixels.setMood(canvas, mood)`, `Pixels.cycleMood(root)`, and `Pixels.pose(canvas, pose, scale, mood, step)`.

---

## 4 · Sampled Token Matrix

```css
--ink-950: #0a0b10;     /* outer window border & 8px offset shadow */
--ink-900: #0e1118;     /* outer dark page ground */
--ink-800: #12131c;     /* terminal screen body */
--ink-700: #181a26;     /* raised panel / inset bar */
--ink-600: #222433;     /* meter off-cell */
--rule:    #3a3b48;     /* 1px board box & double-ruled prompt lines */
--paper:   #fef2da;     /* cream titlebar & thinking dot highlight */
--spawn-flash: #f2f3f8; /* spawn floor-rise initial flash tint */
--text:    #e5e4eb;     /* primary bright text */
--dim:     #8c8c98;     /* muted labels, tree notes */
--coral:   #e17c51;     /* conductor, orchestrator chip, notes */
--blue:    #62a5ea;     /* frontend */
--pink:    #dd6b95;     /* copy & alert */
--mint:    #6fcbbf;     /* tests & passed checkmark */
--yellow:  #f2c94c;     /* NEEDS YOU, numbered options, attention */
--violet:  #7848f6;     /* progress cell / optional astra */
--red:     #ee3d19;     /* alarm */
--ground:  #7dabf3;     /* periwinkle halftone poster ground */
--ground-dot: #5468b8;
--font-mono: "FantasqueSansM Nerd Font Mono", "Fantasque Sans Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
```
