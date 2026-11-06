# glitch-console · ICM Context Specification

> **Tier:** Late-binding UI token contract for terminal-style interfaces.  
> **Source:** Kem Glitch (`source.mp4`, `DeKBMCQNRXU`, `DeEyZPEtkyH`).  
> **Gate:** `design-pack verify <target>` (zero tolerance for undeclared tokens).

---

## 1 · The Six Primitives (No Seventh)

| # | Primitive | CSS Class | Allowed States |
| :-- | :--- | :--- | :--- |
| 1 | Window | `.win` | `ink` (default), `win--paper` (cream bar), `win--inset` (no shadow) |
| 2 | Line | `.line` | `line--cmd` (user), event (default), `line--dim`, `line--alert`, `line--sm` |
| 3 | Chip | `.chip` | default (`--yellow`), `.chip--ink`, `.chip--pink`, `.chip--mint` |
| 4 | Rule | `.rule` | default (1px), `.rule--heavy` (2px), `.rule--dashed` |
| 5 | Meter | `.bar` | `.bar__cell--on`, `.bar__cell--warn`, default (off) |
| 6 | Sprite | `.sprite` | `rest`, `squash`, `dip`, `up`, `jump`, `flash` |

---

## 2 · Sprite Grid & Jump Engine

### Dimensions
- **Art cell**: $16 \times 10$ body matrix ($10$ px per cell at scale 10).
- **16-row vertical ladder**: $16 \times 16$ grid canvas.
  - **Row 0**: Jump Peak Top (`dy: -3`, peak airborne with 4-row clear air gap).
  - **Row 2**: Descent Top (`dy: -1`, mid-air drop).
  - **Row 3**: Tall Idle Top (`dy: 0`, default standing baseline).
  - **Row 5**: Squash / Compress Top (`dy: +2`, 2-row pre-jump squat).
  - **Rows 11–12**: Leg stubs in Tall Idle (rest baseline).
  - **Rows 13–14**: Conductor Platform Bar (strictly 2 rows deep, anchored to baseline).

### Footing & Jump Mechanics (Calibrated to 30 fps stream)
- **Shared Anatomy**: Both Conductor (`#e17c51` / `var(--coral)`) and Frontend (`#62a5ea` / `var(--blue)`) use the exact same 16×10 pixel body (`MAPS.conductor` = `MAPS.worker`). No flattening stretch—discrete row displacement only.
- **Conductor High Jump (0:01–0:03)**:
  - Anchored base bar (rows 13–14) stays pinned.
  - In `squash` (`dy: +2`), torso touches platform directly and legs submerge behind the platform bar.
  - In `jump` (`dy: -3`), body launches to Row 0, creating a clear 4-row air gap (36 px) over the anchored base bar with 4 leg stubs dangling in mid-air.
  - Timing: rest 660 ms → squash 231 ms → jump peak 366 ms → descent 233 ms → settle rest 400 ms.
- **Frontend Squat-and-Jump (0:24–0:26)**:
  - Starts at identical Tall Idle baseline (Row 3).
  - Compresses down 2 rows into pre-jump squat (`dy: +2`, Row 5) before launching high into air (`dy: -3`, Row 0).

---

## 3 · Tells & Inter-Agent Communication (0:24–0:26)

- **Conductor Floating Music Notes (`♫`, `♪`)**: Standard terminal monospace font glyphs (`--font-mono`), NOT canvas pixel blocks. Color is coral (`var(--coral)`). Emits at Frame 37 (~1.23s), pair of beamed double note (`♫`) and single note (`♪`) drifting up and rightward toward worker over ~930 ms (`.comm-notes[data-active="conducting"]`).
- **Frontend Communication Dots (`•`, `•••`)**: Blue monospace characters (`var(--blue)`). Triggers at Frame 48 (~1.60s) during Frontend's pre-jump squat and launch: $1 \rightarrow 2 \rightarrow 3$ dots (`•` $\rightarrow$ `••` $\rightarrow$ `•••`), 165 ms per step, firing leftward across the mid-space channel toward the Conductor (`.comm-dots[data-from="worker"]`).
- **Thinking Tell (`thinking`)**: Overhead square pixel dot/spark clusters (1 $\rightarrow$ 2 $\rightarrow$ 3 clusters, 165 ms each, 495 ms clear).
- **Celebration Confetti**: $2 \times 1$ pixel rectangles (`--yellow`, `--blue`, `--mint`, `--coral`, `--paper`) drifting at 30 fps without easing (`steps(12, end)`).

---

## 4 · Token Matrix

```css
--ink-900: #0e1118;  /* frame ground */
--ink-800: #12151c;  /* terminal body */
--ink-700: #171b24;  /* raised panels */
--paper:   #fdf6e3;  /* paper bar, borders */
--coral:   #d87653;  /* conductor */
--blue:    #68a8e6;  /* frontend */
--pink:    #f02e75;  /* copy / alert */
--mint:    #54c693;  /* tests / passed */
--yellow:  #f7d140;  /* attention chip */
--font-mono: Fantasque Sans Mono, monospace;
```
