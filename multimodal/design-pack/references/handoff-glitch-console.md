# Handoff — glitch-console design pack

Read this, then [SKILL.md](../SKILL.md), then [method.md](method.md).
Everything below is measured off the source stills/frames or implemented in the repo.

---

## 1 · What the job is

Keep `glitch-console` faithful to Kem's Glitch Orchestra stills and enforce it with automated static and runtime gates so drift fails at build time rather than in review.

```text
Repo:      ~/src/my-agent-skills  (canonical; symlinked at /run/media/rodri/AI/skills)
Pack root: multimodal/design-pack/
Look root: multimodal/design-pack/looks/glitch-console/
```

Harness copies under `~/.pi/`, `~/.gemini/`, `~/.config/`, etc. are derived — edit the canonical repo and propagate via `sync-skills`.

---

## 2 · The six primitives (no seventh)

A terminal cannot render web controls. Every screen in the core `glitch-console` look is composed strictly from **six primitives**:

| # | Primitive | Class | States |
| :--- | :--- | :--- | :--- |
| 1 | Window | `.win` | default (`ink`) · `win--paper` (cream titlebar `#fef2da`) · `win--inset` (no shadow) |
| 2 | Line | `.line` | `line--cmd` · `line--tree` (`└`) · event (`●`) · `line--dim` · `line--alert` · `line--sm` · `.term-input` · `.keybar` |
| 3 | Chip | `.chip` | default (`--yellow`) · `chip--ink` · `chip--coral` · `chip--pink` · `chip--mint` |
| 4 | Rule | `.rule` | `1px` (`--rule`) · `rule--heavy` (`2px`) · `rule--dashed` |
| 5 | Meter | `.bar` | off (`--ink-600`) · `bar__cell--on` (`--mint`) · `bar__cell--dim` (`--dim`) · `bar__cell--warn` (`--yellow`) |
| 6 | Sprite | `.sprite` | `rest` · `blink` · `bop` · `squash` · `jump` · `descent` · `flash` + 5 `Pixels.moods` |

There is no `<button>`, `<input>`, `<select>`, modal, tooltip, or `04b` web-control layer in the core look. Actions are keyboard triggers (`1` Hide, `2` Stop, `s` Spawn, `j` Jump, `m` Moods, `g` Ground, `c` Comm ping).

**Substrate profile exception:** Non-terminal targets inherit all tokens and document their exact exceptions in a profile — [`profiles/vst3.md`](../looks/glitch-console/profiles/vst3.md) + [`profiles/vst3-controls.html`](../looks/glitch-console/profiles/vst3-controls.html) cover fixed host windows (4 / 6 / 7 columns), clickable `.ctl` chips, 11-cell dial rails, and the single motion exception (*value feedback eases; chrome never does*).

---

## 3 · Measured facts & `sprites.js` architecture

Measured at 30 fps (`FRAME_MS = 33.33 ms`) from the Glitch Orchestra source video and stills (`ref_01`, `ref_02`, `ref_05`, `ref_10`, `ref_11`, and `traces/`):

| Fact | Value |
| :--- | :--- |
| Canvas grid | **22 × 18 art cells** (`PAD_X = 3`, `GRID_COLS = 22`, `GRID_ROWS = 18`), integer-scaled (`imageSmoothingEnabled = false`) |
| Sprite body | **16 × 10** ASCII `MAPS` (`conductor`, `worker`, plus optional `sol`, `astra`); default roster `conductor` → `frontend` → `copy` → `tests` |
| Shared baseline | All 4 bots rest at **`REST_ROW = 6`** (body rows `6..15`); 6 rows of overhead headroom (`rows 0..5`) |
| Conductor platform | 2-row solid `--coral` plate anchored at **`PLAT_ROW = 16..17`** directly below `conductor`'s feet (never moves on `squash` or `jump`) |
| Jump | **6-row jump** (`dy: -6`, `topRow = 0`, 6-row air gap over fixed platform): `squash (231) → jump (297/264) → descent (66) → squash (264/297) → rest (396 ms)` |
| Floor-rise spawn | **23 frames (`759 ms` @ 30 fps)**: `SPAWN_HEIGHTS` steps `2→4→6→8→10` (`[2, 3, 3, 2, 13]` frames), `floorDy = 2` for frames `0..14` then `0`, with linear sRGB lerp from `--spawn-flash` (`#f2f3f8`) to bot accent |
| 13 measured holds | `[66, 99, 132, 165, 198, 231, 264, 297, 330, 363, 396, 495, 660]` ms (`--hold-min: 66ms`, `--hold-max: 660ms`), irregular on purpose |
| 5 `Pixels.moods` | `outputting` (dual-slot `♪`/`♫` conveyor anchored to `restRow`), `thinking` (5-step `0.65×px` dust cascade → `1.25px` band), `absorbing` (`0.95×px` diagonal taste blocks + `66 ms` 72% `--paper` flash), `aligning` (`-2.5px` right-to-left `✶`/`✴`/`✻` wave + coral specks), `packet` (`0.65×px` hopper + `.comm-line` `▪ ▪ ▪ ▪` → `■ ■ ■ ■` ping) |
| Reduced motion | `prefers-reduced-motion: reduce` freezes sprites at `rest` and disables CSS animations/transitions |

---

## 4 · What ships & passes

| Path | Role |
| :--- | :--- |
| `looks/glitch-console/tokens.css` | Sampled palette (`78%` ink / `12%` type & rules / `5%` paper / `5%` accent), `--ground-dot: #709ee3`, `.bar__cell--on: var(--mint)`, `--violet` scoped to optional `astra` & timing chart, `FantasqueSansM` mono scale (`10px–36px`), 4px space ladder, `0px`/`2px` radii, 30 fps stepped motion tokens |
| `looks/glitch-console/sprites.js` | `22×18` grid engine, `MAPS`, `POSES`, `HOLDS`, `PROGRAMS`, `MOODS`, `drawMood()`, `Pixels.{mount,spawn,spawnFrame,staggerSpawn,jump,crouch,setPaused,isPaused,setMood,cycleMood,communicate,pose,moodStep}` |
| `looks/glitch-console/pack.html` | 5-zone design pack: Zone 1 references, Zone 2 8-section spec + ink proportion bar + measured WCAG contrast grid + swatches, Zone 3 six primitives + `03b` drawn `DO / DON'T` pairs, Zone 4 assembled stage / 5 particles / alignment / board blocks, Zone 5 copy snippets + countable inventory |
| `looks/glitch-console/examples/` | `terminal.html` · `board.html` · `alignment.html` · `timing.html` (all 1-to-1 reference screens + live timing diagrams from `Pixels.*`) |
| `looks/glitch-console/states.html` | Deterministic 23-frame `spawn` keyframes and step-by-step frames for all 5 `Pixels.moods` |
| `looks/glitch-console/profiles/` | `vst3.md` contract + `vst3-controls.html` 5-state comparison plate |
| `looks/glitch-console/traces/` | `conductor_t4/`, `conductor_jump_t543/`, `spawn_t18/` measured crops, grids, and `motion.json` |
| `scripts/design_pack.py` | Strict static gate (`verify`), Playwright wrapper (`check`), `look`, `tokens`, `sprite` (parses `const MAPS` block only) |
| `scripts/check_components.py` | Playwright 7-viewport behaviour gate (overlap, clipping, primitive discipline, keyboard reachability, `≤100 ms` press latency, `≥3:1` contrast) |
| `tests/test_gates.py` | Unit tests covering `verify`, `check`, negative controls (`fail_control.html`, `border-radius: 3px`, implicit ease), and `sprite all` |

---

## 5 · Hard rules & traps

- **No hex outside `tokens.css`.** Always copy `var(--token)` — never hardcode colours, fonts, sizes, or radii.
- **Radius gate is strict (`--r-*` only):** Only `0px` (`--r-0`) and `2px` (`--r-1`), or `50%` for a disc. Border widths (`--b-*`) are excluded from `radii`.
- **Chrome never eases:** Any `transition:` or `animation:` declaration without `steps(...)`, `linear`, or `none`/`0s` fails `design-pack verify` (including implicit-ease shorthands like `transition: opacity 200ms;`).
- **Set `--sprite-scale` on `<canvas class="sprite">`:** `sizeCanvas()` reads inline `style="--sprite-scale:..."` or computed CSS `--sprite-scale` on the canvas element.
- **Verification commands:**
  - `python3 multimodal/design-pack/scripts/design_pack.py verify multimodal/design-pack/looks/glitch-console/`
  - `python3 multimodal/design-pack/scripts/design_pack.py check multimodal/design-pack/looks/glitch-console/`
  - `python3 multimodal/design-pack/scripts/design_pack.py sprite all`
  - `python3 -m unittest discover -s multimodal/design-pack/tests -v`
