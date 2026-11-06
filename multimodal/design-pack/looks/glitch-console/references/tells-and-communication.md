# Tells & Inter-Agent Communication Logic

> **Look:** `glitch-console`  
> **Source Evidence:** `source.mp4` (`0:01–0:09`, `0:24–0:26`, `0:52–1:05`)  
> **Key Principle:** Pure discrete 30 fps stepped frames. Zero easing curves (`transition: none`, `steps(N, end)`).

---

## 1. ASCII Music Note Logic (`♫ ♪` Outputting Tell)

```
       ♫ ♪
   ┌─────────┐
   │ 16 × 10 │  Outputting / Conducting State
   │  BODY   │  Emits while the conductor drafts briefs or streams tokens
   └─────────┘
```

- **Semantics**: Indicates active generation/synthesis (conductor dispatching tasks, streaming code).
- **Typography & Medium**: Monospace text typography (`--font-mono`: Fantasque Sans Mono, monospace), **not** canvas pixel art. Uses Unicode glyphs:
  - `♫` (U+266B, Beamed Eighth Notes)
  - `♪` (U+266A, Eighth Note)
- **Palette**: `--coral` (`#d87653` / `#e17c51`), bold weight `700`, font size `--fs-xl`.
- **Timing & Discrete Rhythm (Measured at 0:01–0:09)**:
  - Total duration: **1,749 ms** cycle before repeating or holding.
  - **Step 0 (0–363 ms)**: Hidden (`opacity: 0`).
  - **Step 1 (363–726 ms)**: Single beamed note `♫` appears directly overhead (`top: -24px`, `opacity: 1`).
  - **Step 2 (726–1089 ms)**: Beamed pair + single note `♫ ♪` holds position.
  - **Step 3 (1089–1452 ms)**: Drifts up and rightward (`translate(18px, -20px)`, `opacity: 0.8`).
  - **Step 4 (1452–1749 ms)**: Clears out (`opacity: 0`, 660 ms quiet gap).
- **CSS Stepped Rule**:
  ```css
  .comm-notes[data-active="conducting"] {
    animation: comm-notes-float 2.0s steps(6, end) infinite;
  }
  @keyframes comm-notes-float {
    0%   { opacity: 0; transform: translate(0, 0); }
    20%  { opacity: 1; transform: translate(4px, -6px); }
    50%  { opacity: 1; transform: translate(12px, -14px); }
    80%  { opacity: 0.8; transform: translate(18px, -20px); }
    100% { opacity: 0; transform: translate(22px, -24px); }
  }
  ```

---

## 2. Dot Neurons / Communication Channel (`• • •` / `■ ■ ■ ■`)

```
   ┌───────────┐         • • •         ┌───────────┐
   │ Conductor │ ────────────────────> │ Frontend  │
   │  --coral  │ <──────────────────── │   --blue  │
   └───────────┘    Inter-Agent Pings  └───────────┘
```

- **Semantics**: Mid-stage packet transmission between agents (Conductor handing briefs to Worker; Worker reporting `✓ passed` to Conductor).
- **Typography & Medium**: Monospace glyphs (`•` U+2022 Bullet or `■` U+25A0 Black Square).
- **Color**:
  - `--blue` (`#62a5ea` / `#68a8e6`) for Worker → Conductor status signals.
  - `--coral` (`#d87653` / `#e17c51`) for Conductor → Worker briefs.
- **Physical Geometry**: Centered vertically in the mid-stage gap between avatar slots (`align-self: center`, gap `min-width: 64px`).
- **Timing & Stepped Propagation (Measured at 0:24–0:26 & 0:59–1:05)**:
  - Firing sequence: 4 discrete packet dots or 3 firing dots (`1 → 2 → 3`).
  - Step duration: **165 ms** (5 frames @ 30 fps) per dot, or **132 ms** stagger.
  - Total traversal: **660 ms** (20 frames).
  - Traversal translation: `translateX(20px)` → `translateX(4px)` → `translateX(-14px)` → `translateX(-24px)` using `steps(4, end)`.
- **CSS Stepped Rule**:
  ```css
  .comm-dots[data-from="worker"] {
    animation: comm-dots-fire 660ms steps(4, end) 1;
  }
  @keyframes comm-dots-fire {
    0%   { opacity: 1; transform: translateX(20px); }
    33%  { opacity: 1; transform: translateX(4px); }
    66%  { opacity: 1; transform: translateX(-14px); }
    100% { opacity: 0; transform: translateX(-24px); }
  }
  ```

---

## 3. Thinking Sparkles (Reasoning Tell)

```
     ✦  ✦  ✦   (1 → 2 → 3 spark clusters)
   ┌─────────┐
   │ 16 × 10 │  Thinking / Inference State
   │  BODY   │  Active model thinking latency
   └─────────┘
```

- **Semantics**: Active model reasoning, test verification, or context ingestion.
- **Medium**: Rendered directly in `<canvas>` above the sprite head (rows 0–2 of the 16-row ladder).
- **Cluster Anatomy**:
  - Each sparkle is a $2 \times 2$ pixel art motif drawn at integer scale.
  - Divided into a dim quadrant and a bright quadrant:
    ```js
    function spark(ctx, x, y, h, dim, bright) {
      ctx.fillStyle = dim;
      ctx.fillRect(x, y, h, h);
      ctx.fillStyle = bright;
      ctx.fillRect(x + h, y, h, h);
      ctx.fillRect(x + h, y + h, h, h);
      ctx.fillRect(x, y + h, h, h * 0.5);
    }
    ```
- **Palette Alternation**:
  - Sparkle clusters alternate between White/Paper (`--paper`, `#fdf6e3`) and Orange/Coral (`--coral`, `#d87653`).
  - Worker thinking sparkles alternate between White/Paper and Accent Blue (`--blue`).
- **Timing & Discrete Progression (Measured at 0:05.3 & 0:20.3)**:
  - Total cycle: **990 ms** (snapped to exactly 30 frames @ 30 fps).
  - **Step 0 (0–165 ms / 5 frames)**: 1 spark cluster above center-left.
  - **Step 1 (165–330 ms / 5 frames)**: 2 spark clusters side-by-side.
  - **Step 2 (330–495 ms / 5 frames)**: 3 spark clusters side-by-side (left to right).
  - **Step 3 (495–990 ms / 15 frames)**: Clear. All sparkles vanish for 495 ms before the next burst.

---

## 4. Eye & Cursor Blinking Logic

### A. Sprite Eye Slit Blink (`pose: "blink"`)

```
   EYES OPEN (Rest)         EYES CLOSED (Blink)
   Col:  4       11         Col:  4       11
   Row 2: .       .         Row 2: #       #
   Row 3: .       .         Row 3: #       #
   (dark terminal slit)     (filled with body fill)
```

- **Semantics**: Natural organic aliveness during resting idle.
- **Pixel Anatomy**:
  - The $16 \times 10$ ASCII body map has vertical slit pupils at **Column 4** and **Column 11** spanning **Rows 2 and 3** (`..##.######.##..`).
  - In `rest`, these cells are empty (`.`), rendering as transparent cuts through which the dark terminal background shows.
  - In `blink`, these 4 cells are filled with the body's primary fill color (`#`), temporarily sealing the slit pupils shut.
- **Timing & Rhythm (Measured from 30 fps stream)**:
  - Duration: Exactly **132 ms** (4 frames @ 30 fps: $4 \times 33\text{ ms} = 132\text{ ms}$).
  - Cadence: Triggered every 1.5s to 3.0s between resting holds and subtle 1-row head bops (`bop: dy +1`).
- **De-synchronization & Anti-Unison Seed**:
  - In a multi-worker terminal, each bot computes an individualized hold offset:
    ```js
    const restHold = 1320 + ((seed * 330) % 990);
    const offset = i * 170; // ms stagger per roster slot
    ```
  - This guarantees that Conductor, Frontend, Copy, and Tests **never blink at the same time**.

### B. Terminal Caret / Prompt Cursor Blink

- **Medium**: Pure CSS text cursor on `.prompt__caret` (`❯` or `_`).
- **Cadence**: 2 fps (500 ms visible, 500 ms hidden).
- **Stepped Rule**: Snaps with `steps(2, start)`—never a soft opacity pulse or fade.
