# glitch-console · VST3 profile — layout contract

A profile is the same look on a different substrate, not a second look. This one
covers a plugin editor: a fixed window the host owns, dense parameter rows, and
mouse as the primary pointer.

Why a profile and not a new component set: the six-primitive rule below is
unchanged, and the one behaviour it bends (meters) is written down as an
exception rather than discovered at runtime.

---

## 1 · What this substrate changes

| | web terminal (default) | VST3 editor (this profile) |
| :--- | :--- | :--- |
| window | page flow, scrolls | **fixed, host-resized, never scrolls** |
| pointer | keyboard triggers only | **mouse first**, keyboard when focused |
| density | one screen, 4–8 lines | 16–28 live parameters at once |
| type floor | 12 px comfortable | **10 px caps**, readable at 100% on 1080p |
| motion | chrome stepped, 30 fps | chrome stepped · **meters interpolate** |

The "no `<button>`" rule exists because a terminal has no pointer. An editor
does. So `chip` becomes clickable here and gains `hover` / `active` / `focus`;
nothing else is added.

---

## 2 · Geometry

Three anchor sizes. The host may land anywhere between them; the layout rounds
**down** to a whole column and row count and leaves the remainder as inset.

| anchor | usable (w × h, after 8 px inset) | columns | rows | parameters |
| :--- | :--- | ---: | ---: | ---: |
| 480 × 320 (min) | 464 × 260 | 4 | 4 | 16 |
| 640 × 400 | 624 × 340 | 6 | 5 | 30 |
| 800 × 600 | 784 × 540 | 7 | 8 | 56 |

- **Chrome bands:** header 24 px (title `MIN 640` label + bot strip) · content ·
  keybar 20 px. Both bands are fixed; only content reflows.
- **Parameter cell:** 96 px wide, 56 px tall, 8 px gutter.
  `columns(n) = 96n + 8(n−1) ≤ usable_w` → 4 / 6 / 7 at the anchors above.
- **Cell stack:** label 12 px · gap 4 · control 24 px · gap 4 · value 12 px.
- No sub-8 px gaps, no 1.5 px rules. Everything sits on the 4 px ladder.

---

## 3 · Type

- **Labels:** `--fs-2xs` (10 px) caps, `--track-label` 0.12em, `--dim`.
- **Values:** `--fs-xs` (12 px) mono, right-aligned, `--text`. Units in `--dim`.
- **Title:** 12 px caps, no ellipsis — shorten the preset name instead.
- Nothing renders below 10 px. Nothing is scaled by the host: if the editor
  resizes, the *grid* changes, not the type size.
- **Fonts ship inside the plugin.** Subset FantasqueSansM Nerd Font Mono to
  ASCII + the box-drawing and dial glyphs used here (~12 KB woff2), or fall back
  to `ui-monospace`. A plugin cannot assume a system font exists.

---

## 4 · Controls — still six primitives

| primitive | VST3 role | notes |
| :--- | :--- | :--- |
| `window` | editor panel, titlebar | 1 px `--rule` + 8 px hard shadow only if the host draws no frame |
| `line` | label row, value row, log line | label + value are two `line`s in one cell |
| `chip` | toggle, button, preset selector | now clickable: `rest` · `hover` · `active` · `focus` · `disabled` |
| `rule` | section divider, cell underline | `hover` is a coral 1 px underline on the label — never a fill |
| `meter` | level, gain reduction, spectrum | the only interpolating primitive |
| `meter` | **dial**, level, gain reduction, spectrum | a dial is a rail: 11 cells, one lit |
| `sprite` | bot (header only) | one atlas family, stepped |

**A dial is a rail, not a knob.** Eleven cells (−5 … +5), one lit. A 10 px
monospace cell cannot draw a rotate-able knob without lying about the geometry,
and the pack already owns a stepped horizontal scale: the meter. So the
parameter control *is* the meter primitive with exactly one cell lit — the same
glyph the bots' `bop` uses to read a track. No new primitive, and no arc that
has to be faked at 10 px.

**One new block, no new component:** the *parameter row* = label + control +
value. A block is a composition of primitives; that is where it belongs.

Forbidden at this layer, same as the look: dropdowns, tooltips, modals, file
browsers, scrolling lists. Those become a block — a new window, or a line that
asks inline.

---

## 5 · States

Every control is drawn in all five states before it ships; none is synthesised
at runtime.

- `rest` — `--ink-700` cell, `--text-2` label.
- `hover` — label rule turns `--coral`, value brightens. **No background fill**:
  a filled cell reads as a meter at a glance.
- `active` — the lit cell turns `--yellow` and the value goes `--coral-hi`;
  one frame (33 ms), no tween.
- `focus` — 1 px `--yellow` box on the cell, keyboard path only.
- `disabled` — `--ink-600` cell, `--dim` label, value still readable (a value
  that vanishes cannot be compared).

---

## 6 · Motion — one written exception

- **Chrome stays stepped.** 30 fps, `--snap` 33 ms, no interpolation, holds from
  the measured set. This does not change.
- **Meters interpolate.** Level, gain reduction and spectrum run at the host's
  frame rate on a continuous scale. A stepped meter reads as a broken meter to
  anyone who mixes. The rule, stated once:
  > **value feedback eases; chrome never does.**
- **Bot lives in the header strip only** (24 px, left of the title). Idle `bop`
  at the measured holds; a preset change = one `flash` (90 ms). Never inside the
  content area, never behind or beside a meter.
- **Budget:** ≤ 1 chrome repaint per 33 ms; meters ≤ 1 attribute write per
  animation frame; no layout thrash inside the audio callback (editor only).

---

## 7 · The 0.1 s rule

Every pointer press answers within **100 ms** — visual state changes before the
next paint. Parameter smoothing for the DSP is a separate path and must never
gate the visual: the user sees the response immediately even when the audio
glides.

---

## 8 · Resize contract

`editorResized(w, h)` → `columns = floor((w − 8) / 104)` and
`rows = floor((h − 52) / 64)` (8 px inset + 24 px header + 20 px keybar + one
gutter of slack), then re-place cells on the grid, clamped to 4…7 columns and
4…8 rows. Never scale type, never introduce a scrollbar, never clip a label:
if the grid does not fit, drop whole cells and say so in the keybar
(`4 × 4 — 16 of 23 params`).

---

## 9 · Verification

- 480 × 320 renders 16 parameter cells with 0 clipped labels and 0 scrollbars.
- Every control exists in 5 states in `profiles/vst3-controls.html` — that plate is
  the reference, and a new control must be added there before it ships.
- A meter animating at 60 fps does not change any row height.
- Press latency ≤ 100 ms, measured, not asserted.
- No rendered type below 10 px; no `<button>` / `<input>` / `<select>` in markup.

---

## 10 · Open questions (decide before building specimens)

0. **The plate** — `profiles/vst3-controls.html` is live and passes
   `design-pack verify` (0 fail · 0 warn). Nothing in it is invented CSS: the
   buttons are chips that answer a pointer, the dial is the sprite atlas.

1. **Host framework** — JUCE (C++) vs a web-view editor. The tokens map to both;
   the dial atlas and the meter exception are C++-heavy either way.
2. **Parameter count target** — 16 is the floor this layout proves. A 60-param
   plugin needs a tab block, which is a new window, not a smaller cell.
3. **Does the keybar survive?** A DAW already has a keyboard focus model; the
   keybar may be redundant here even though it is load-bearing on the web look.
