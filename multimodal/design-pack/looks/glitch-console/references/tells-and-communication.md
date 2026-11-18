# Tells & Inter-Agent Communication Logic

> **Look:** `glitch-console`  
> **Source Evidence:** `ref_01_stage_orchestra.png`, `ref_02_conductor_tuning.png`, `ref_05_spawn_sequence.png`, `ref_10_kanban_board_particles.png`, `ref_11_avatar_alignment_comm_ping.png` (`sprites.js` + `tokens.css`)  
> **Key Principle:** Pure discrete 30 fps stepped frames (`FRAME_MS = 33.33 ms`). Zero easing curves (`transition: none`, `steps(...)`).

---

## 1. Canvas Grid & Sampled Palette

All mood tells render inside `drawMood()` in `sprites.js` on the unified `22×18` art-cell canvas (`PAD_X = 3`, `GRID_COLS = 22`, `GRID_ROWS = 18`):

- **Shared baseline:** All 4 bots (`conductor`, `frontend`, `copy`, `tests`) rest at `REST_ROW = 6` (16×10 body on rows `6..15`).
- **Conductor platform:** 2-row solid plate anchored at `PLAT_ROW = 16..17` directly beneath `conductor`'s feet; stays fixed during `squash` (`dy: +2`) and 6-row `jump` (`dy: -6`, `topRow = 0`).
- **Sampled tokens:**
  - `--coral`: `#e17c51` (conductor, orchestrator chip, outputting notes, aligning micro specks)
  - `--blue`: `#62a5ea` (frontend)
  - `--pink`: `#dd6b95` (copy & alert)
  - `--mint`: `#6fcbbf` (tests, passed checkmark, active meter cell)
  - `--yellow`: `#f2c94c` (`NEEDS YOU`, numbered options, thinking/absorbing highlight)
  - `--paper`: `#fef2da` (cream titlebar, thinking/aligning/absorbing highlight, `72%` absorb flash)
  - `--text`: `#e5e4eb` (primary terminal text, packet hopper, active packet dot)

---

## 2. Five Canvas-Rendered 30 fps Mood Systems (`Pixels.moods`)

### A. `outputting` — Dual-Slot `♪` / `♫` Conveyor

```text
          ♪/♫   (upper slot, baseRow - 3.5)
    ♪/♫         (lower slot, baseRow - 0.5 / -0.4)
  ┌─────────┐
  │ 16 × 10 │   Anchored to restRow (never bobs on jump/bop)
  │  BODY   │
  └─────────┘
```

- **Medium & font:** Canvas `ctx.fillText`, `bold ${Math.round(px * 2.3)}px` `--font-mono`, in agent `ink` (`--coral` `#e17c51`, `--pink` `#dd6b95`, etc.).
- **Anchoring & clamping:** Uses `baseRow = restRow ?? topRow` so notes never bounce when the sprite bops or jumps; clamped inside `GRID_COLS = 22` (`rightPad = max(2, round(px * 0.25))`) and `y >= 2.1 * px`.
- **Measured cadence (`396 + 330 + 363 + 396 = 1,485 ms`):**
  - **Step 0 (`396 ms`):** `♪` at lower slot `(PAD_X + cols - 1.4, baseRow - 0.5)`.
  - **Step 1 (`330 ms`):** `♪` at upper slot `(PAD_X + cols + 0.1, baseRow - 3.5)` + `♫` at lower slot `(PAD_X + cols - 1.6, baseRow - 0.4)`.
  - **Step 2 (`363 ms`):** `♫` at upper slot `(PAD_X + cols - 0.3, baseRow - 3.5)`.
  - **Step 3 (`396 ms`):** Hold clear before next cycle.

### B. `thinking` — 5-Step Pixel-Dust Cascade

```text
  ▪ ▪ ▪ ▪ ▪ ▪   (step 3: 11-dot 1.25px quantized band at rowAbove 1.3 & 2.1)
  ┌─────────┐
  │ 16 × 10 │
  │  BODY   │
  └─────────┘
```

- **Medium & geometry:** Canvas `ctx.fillRect` `0.65×px` square dots (`max(2, round(px * 0.65))`) in `[--paper, --yellow, --coral]` above `topRow` (`THINKING_STEPS[0..3]`).
- **Stagger:** Steps `0..2` apply per-bot horizontal `dustShiftFor(name)` (`conductor: 0`, `frontend: 0`, `copy: +0.35`, `tests: -0.35`); step `3` locks to `shift = 0`.
- **Measured cadence (`165×3 + 198 + 495 = 1,188 ms`):**
  - **Steps 0–2 (`165 ms` each):** 5 → 6 → 7 scattered dust pixels descending toward the crown.
  - **Step 3 (`198 ms`):** Settles into an 11-dot quantized `1.25px` horizontal band (`dx = 1.25..13.75` alternating `rowAbove = 1.3` and `2.1`).
  - **Step 4 (`495 ms`):** Clear hold.

### C. `absorbing` — Diagonal Taste Blocks + Impact Flash

- **Medium & geometry:** Canvas `ctx.fillRect` `0.95×px` blocks (`max(2, round(px * 0.95))`) in `[--yellow, --pink, --mint, --paper]` stepping diagonally up-left along `ABSORB_PATH` (`(19.2, 9.4)` → `(16.0, 7.6)` → `(12.8, 6.2)` → `(10.0, 5.2)` → `(8.0, 4.8)` relative to `baseRow = restRow ?? topRow`).
- **Impact flash:** On **step 2** and **step 5**, blocks arrive in the torso core and trigger a `66 ms` torso (and conductor platform) tint lerp `lerpSrgb(bodyRgb, paperRgb, 0.72)` toward `--paper` (`#fef2da`).
- **Measured cadence (`6×66 + 198 = 594 ms`):** Steps `0..5` (`66 ms` each, `ABSORB_FRAMES[0..5]`), followed by step `6` (`198 ms` clear hold).

### D. `aligning` — `-2.5 px` Right-to-Left Star Wave

- **Medium & geometry:** Two wrapped wave cursors stepping `-2.5 px` right-to-left across `ALIGN_COLS = [18.5, 16.0, 13.5, 11.0, 8.5, 6.0, 3.5, 1.5]` (`y = max(2.3 * px, (topRow - 0.9) * px)`).
- **Glyphs & specks:** Cycles `["✶", "✴", "✻"]` (`bold 2.3×px`) alternating `--paper` (`#fef2da`) and `--text` (`#e5e4eb`). On odd steps (`step % 2 === 1`), draws `0.5×px` `--coral` (`#e17c51`) dust specks flanking `col ± 1.6` at `topRow - 1.4`.
- **Measured cadence (`8×132 + 396 = 1,452 ms`):** Steps `0..7` (`132 ms` each) + step `8` (`396 ms` clear hold).

### E. `packet` — Waiting Hopper & `Pixels.communicate(stage)`

```text
  ♪ conductor      ▪ ▪ ▪ ▪  -->  ■ ■ ■ ■      frontend (packet hopper)
```

- **Canvas hopper (`packet`):** `0.65×px` `--text` (`#e5e4eb`) square hopping over the upper-left corner of waiting bots along `PACKET_HOPS` (`(PAD_X - 0.5, 1.5)` → `(PAD_X + 0.5, 2.6)` → `(PAD_X + 1.5, 1.8)` above `topRow`). Cadence: `3×165 + 330 = 825 ms`.
- **DOM `.comm-line` (`Pixels.communicate(stage)`):** Two-phase mid-stage channel anchored at `margin-top: calc(10 * var(--sprite-scale, 7px))`:
  1. **Packet stream:** Switches `.comm-dot` to `▪` (`.comm-dot--packet`, `--ink-500` → `--text` `.is-active`) stepping every `165 ms` across all dots.
  2. **Sync burst + 6-row jumps:** At `syncStart = dots.length * 165 ms`, switches dots back to `■` (`--dim` → `--paper` `.is-active`), triggers `Pixels.jump(conductor)` (`dy: -6`), triggers `Pixels.jump(frontend)` at `syncStart + 462 ms`, cascades `.is-active` across `■ ■ ■ ■` every `132 ms` starting at `syncStart + 660 ms`, and clears `495 ms` after the final dot.

*(Optional alert mood `attention`: bold `2.6×px` `--red` `#ee3d19` `!` toggling at `2×250 ms`.)*

---

## 3. Eye & Cursor Blinking Logic

### A. Sprite Eye Slit Blink (`pose: "blink"`)

```text
  EYES OPEN (Rest)         EYES CLOSED (Blink)
  Col:  4       11         Col:  4       11
  Row 2: .       .         Row 2: #       #
  Row 3: .       .         Row 3: #       #
```

- **Pixel anatomy:** The `16×10` body map (`..##.######.##..` on rows `2` and `3`) leaves transparent eye slits at columns `4` and `11`. In `blink`, `draw()` fills those 4 cells with the body fill colour.
- **Timing & anti-unison:** Each blink holds for `132 ms` (4 frames @ 30 fps). `idleProgram(seed)` computes `restHold = 1320 + ((seed * 330) % 990)` and `mount()` assigns `offset = i * 170` ms so bots never blink in unison.

### B. Terminal Caret Blink

- **Rule in `tokens.css`:** `.term-input__caret` runs `animation: caret-blink 1000ms steps(2, start) infinite;` (hard 50/50 snap, zero ease).
