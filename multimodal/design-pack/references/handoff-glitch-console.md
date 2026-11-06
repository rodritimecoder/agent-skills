# Handoff — glitch-console design pack

A brief for a fresh model. Read this, then `SKILL.md`, then `references/method.md`.
Everything below is either measured or already in the repo; nothing here is a preference.

---

## 1 · What the job is

Finish the `glitch-console` look so an agent can build terminal UI that matches the
reference reel, and so any drift is rejected by code rather than by opinion.

The design philosophy comes from Kem's *Design Pack* reel (`DfPlX30teKG`) and the
Glitch Orchestra reel it was applied to:

```
/run/media/rodri/AI/creator-vault/kem_glitch/2026-10-06_glitch_orchestra_alignment_first/source.mp4
```

The claim being implemented: **words cannot specify a design.** Images plus a
contract can. A pack is one page a model reads before it designs, and a gate that
fails when the output leaves the system.

Repo: `~/src/my-agent-skills` (this is the only source of truth; harness copies are derived).
Pack root: `multimodal/design-pack/`
Look root: `multimodal/design-pack/looks/glitch-console/`

---

## 2 · The shortcut this pack is built on

A terminal cannot render a control. It has **six primitives and no seventh**:

| # | Primitive | Class | States |
| :-- | :--- | :--- | :--- |
| 1 | window | `.win` | `ink` (default) · `paper` (the reel) · `inset` (no shadow) |
| 2 | line | `.line` | `cmd` · event (default) · `dim` · `alert` · `sm` |
| 3 | chip | `.chip` | default (yellow) · `ink` · `pink` · `mint` |
| 4 | rule | `.rule` | 1px · `heavy` (2px) · `dashed` |
| 5 | meter | `.bar` | `rest` · `on` · `warn` |
| 6 | sprite | `.sprite` | `rest` · `up` · `down` · `squash` + moods |

Everything else is a composition of those. There is no select, checkbox, slider,
modal, tooltip, menu or table-with-states in this look — a terminal has none. If a
screen appears to need one, it is a **block** (a new window, or a line that asks the
question inline), not a new component.

That is the whole design system. Do not grow it.

---

## 3 · Measured facts — do not re-derive, do not "improve"

Read off `source.mp4` at 30 fps: 210 frames of `0:02–0:09`, 90 frames of `0:18–0:21`,
tracking the coral/blue/pink blobs by colour mask.

| Fact | Value |
| :--- | :--- |
| Pose change | **one frame, 33 ms.** No interpolation anywhere. |
| Body travel | **feet never move.** bbox bottom pinned at `y=995` while the top alternated `793 ↔ 829` (third window `813 ↔ 834 ↔ 855`). It is a stretch about the feet, not a hop. |
| Hold lengths | 100, 132, 165, 198, 231, 330, 363, 396, 462, 495, 660, 726 ms — median ≈ 350 ms, irregular on purpose |
| Sprite grid | 16 × 10 art cells. Conductor 169×104 px, worker 132×105, ≈10.5 px/cell |
| Conductor vs worker | same body. Conductor ends in a solid 2-row **base plate**; worker swaps it for four 1-cell leg stubs |
| Thinking tell | spark clusters above the head: 1 → 2 → 3, 165 ms each, then 495 ms clear |
| Outputting tell | `♪` → `♪♪` → `♪`, 363 ms each, then 660 ms clear |
| Spawn | five held steps of 90 ms |

Consequence in code: `POSES` carries `flatten` and **no `dy`** —
`rest 1.0`, `up 1.2`, `down 0.85`, `squash 0.6`, scaled about the feet.
What scrolls smoothly in the reel is the transcript, never the sprite.

---

## 4 · What already exists and passes

| File | State |
| :--- | :--- |
| `looks/glitch-console/sprites.js` | 16×10 `MAPS`, `POSES`, `HOLDS`, `PROGRAMS.idle/walk/spawn`, `MOODS`, 30 fps frame gate, `prefers-reduced-motion` → static |
| `looks/glitch-console/tokens.css` | the six primitives, `win--paper`, motion tokens (`--snap`, `--hold-*`, `--scroll`), `--sprite-h: 15` |
| `looks/glitch-console/pack.html` | zones 01 palette · 02 type · 03 sprites (one terminal, four bots) · 04 components (six primitives) · 04b web layer in `<details>` · 05 blocks · 06 motion · 07 ground |
| `looks/glitch-console/examples/` | `hero` · `board` · `settings` · `terminal` · `timing` |
| `looks/glitch-console/states.html` | the spawn in five frames |
| `references/method.md` | the five zones, with provenance |
| `scripts/design_pack.py` | **strict by default**: fails on colour, font, type size, radius and easing; `--loose` demotes all but colour |
| `pages/agent-activity/index.html` | the pit is one terminal, engine inlined, 30 fps gate, reduced motion |

Verified, not asserted:

```
design-pack verify looks/glitch-console/            → PASS · 8 files · 0 fail · 0 warn
design-pack verify looks/glitch-console/examples    → PASS · 5 files · 0 fail · 0 warn
```

Gate control (a file that must fail):

```
font-size:17px · font-family:Inter · border-radius:7px · transition: .2s ease-in-out
strict → FAIL 4 · loose → PASS 4 warn
```

Motion control (30 fps harness, 122 ticks):

```
distinctRenders 3 · transitions 11 · holds 100–957 ms
top rows 33 / 55 / 72 (art rows 3 / 5 / 6.5) · feet row pinned at 164 · canvas 176×165
```

---

## 5 · What is not done — the actual TODO

Do these in order. Each one is small; do not start a redesign.

1. **Zone 1 is empty.** The look ships no reference images. Extract 3–4 stills from
   `source.mp4` (`0:18–0:21` for the terminal + stage, `0:02–0:09` for the particle
   tells), save under `looks/glitch-console/references/`, annotate each with one line
   saying what to copy, and link them from `README.md`. This is zone 1 of the method.
2. **Zone 2 is missing its shape.** `README.md` has provenance, motion, voice and
   exclusions, but not the method's **idea → look → feel**. Add three short sections.
   "Look" is what each colour and font is *for* (coral = conductor, blue = frontend,
   pink = copy + destructive, mint = tests + pass, yellow = attention, paper = chrome).
   "Feel" is surface, texture, line, shape, spacing.
3. **Zone 3 states are drawn but thin.** The kit renders; check every state in
   `pack.html` zone 04 has a matching declared class in `tokens.css` — no inline
   `style="background:…"` faking a hover or pressed state.
4. **Zone 4 has only a board block.** Add a landing/hero block and a settings/table
   block built **only** from the six primitives. The existing `examples/settings.html`
   uses the web layer — that is the difference to demonstrate.
5. **Zone 5 snippets are stale.** The "copy this" panel in `pack.html` still shows
   `data-spawn` alone. It should show `data-mood`, `data-pose`/`Pixels.pose`, the
   `.line` vocabulary and `design-pack verify`.
6. **The web layer is parked, not resolved.** `btn/input/tab/badge/toast/tbl` still
   live in `tokens.css` and are used by `hero.html`/`settings.html`. Decide once:
   keep as an explicit non-terminal appendix (current state), or delete and rewrite
   those two examples from primitives. Do not leave it ambiguous.
7. **`pages/agent-activity` duplicates `sprites.js` inline.** This is a drift risk.
   Either add a static route to `server.mjs` so the page can load the real file, or
   write a check that the inlined copy matches. Do not let the two diverge silently.
8. Evidence currently lives in `/tmp` and will vanish. Anything you want the next
   person to see belongs in the repo.

---

## 6 · Hard rules

- **Edit the checkout**: `~/src/my-agent-skills/<domain>/<skill>/`. Never edit the
  harness copies under `~/.config/opencode`, `~/.gemini`, `~/.pi`.
- **Publish once per task**: `sync-skills` while iterating, `sync-skills --push` at
  the end. Not per edit.
- **No hex outside `tokens.css`.** No font outside `--font-*`. No size outside
  `--fs-*`. Radius `0–2px` (or `50%` for the one disc). No easing.
- **Never add `dy` back to a pose.** The feet are pinned; the body stretches.
- **Never "tidy" a sprite row.** They are transcriptions, not drawings.
- **Prove, do not claim.** `design-pack verify` plus the 30 fps harness, or it did
  not happen.

### Traps

- The `:7320` server (`pages/agent-activity/server.mjs`) serves **only** `/` and
  `/index.html`. Any script must be inlined.
- Headless Chrome never settles on `:7320` because of the SSE stream. For a
  screenshot: `curl /api/snapshot`, inline it, strip `EventSource`, then shoot.
- `--sprite-scale` must be set **inline on the canvas**. A value inherited from
  `:root` is ignored by design.
- `design-pack verify` is strict now. `--loose` exists for a first pass on old pages;
  do not use it to make a new page pass.

---

## 7 · Definition of done for this milestone

- `design-pack verify looks/glitch-console/` → PASS with 0 fail **and 0 warn**.
- Zone 1 has real stills; zone 2 has idea/look/feel; zones 3–5 are built only from
  the six primitives.
- `pack.html` contains no inline style that fakes a component state.
- The gate still fails on a deliberate drift file (keep the control).
- One `sync-skills --push` at the end, and `sync-skills verify` green.

If a step seems to need a seventh primitive, stop and re-read section 2.
