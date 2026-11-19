# The method — five zones, references first

From Kem, *The Design Pack* (`DfPlX30teKG`, 2026-11-02, 2:59). The reel is the
superscription of an older written artefact of his (`insta-glitch`, the design-system
skill: `SKILL.md` + `tokens.css` + `style-guide.html` + `reel.py`). The reel adds what
the artefact buried: **why it must be images.**

## The claim

> *"Your job is to give the model the tools to understand what good looks like. And
> when it comes to design, words will never cut it. Let me say that again. Words will
> never cut it. You have to use images themselves."* — 00:22

He demonstrates it with a counter: a design brief of *"make it look retro and premium,
warm but clean, a bit playful, not too busy"* scores **WORDS 15 · IMAGES 0**, and the
render that follows is generic. Adjectives are lossy compression of visual decisions.

## The five zones

| # | Zone | Contents | Depth label in the reel |
| :-- | :--- | :--- | ---: |
| 1 | **References** | real images, one style only + full-fidelity side-by-side candidates (`AVOID` with reason), annotated with what you like | 0 m |
| 2 | **Style sheet** | production constraint + `NEVER` block + 8 sections (idea, domain voice, mark, colour, type, layout, imagery, texture & motion) | 105 m |
| 3 | **Components** | closed inventory (`N` parts, `M` timings, `K` marks), every piece drawn in every state, then animated | 1,000 m |
| 4 | **Blocks** | full screens built from those pieces | 4,000 m |
| 5 | **Design pack** | one web page with swatches, type, states, snippets | 6,000 m |

### 1 · References

Find real images. One style only — *"mixing styles just confuses the model."* Say what
you like in each one; that note is what aligns the model to you. When exploring
directions, render at least two candidates to full fidelity on the same subject and
level of finish (a sketch is not comparable), place them side by side, choose by
looking, and tag each rejected candidate `AVOID` with one concrete reason. Public
domain or your own, and *"always respect people's creative work. We're here to be
inspired not to steal."*

### 2 · Style sheet — the 8-section book skeleton

From Kem's *Design Lab* follow-up (`DfudeDMtl2P`), the concrete Zone 2 content template is an **8-section skeleton**, preceded by a named production constraint and an explicit `NEVER` block of patterns banned by that constraint (for example: two-ink press, zero-pointer terminal, or fixed DAW host window; banning smooth gradients, pure black or white ink, soft shadows, or perfect register), with two structural conventions:

1. **Idea** — the overall concept and the press/substrate constraint that enforces it.
2. **Voice** — copy tone, length rules, and real UI states mapped to domain vocabulary (for a print shop: loading is `"inking up"`, error is `"a misprint"`, done is `"dry"`).
3. **Mark** — signature sprites/icons and their placement.
4. **Colour** — specified **by proportion** (ink budget, e.g. 78% ink / 12% type / 5% paper / 5% accent), not a flat swatch list, paired with **contrast, measured**.
5. **Type** — font stack, discrete size ladder, tracking.
6. **Layout** — grid/window geometry, spacing steps, target viewports.
7. **Imagery** — sprites, halftones, or illustration rules.
8. **Texture & Motion** — surfaces, borders, shadows, and an enumerated table of timing tokens.

Two rules carry it: **every section terminates in drawn `do, don't` pairs** (not prose warnings alone), and **comparisons beat descriptions** (put rejected candidates tagged `AVOID` beside the chosen direction).

> *"Find one style sheet you like, give it to the model as the format and ask it to fill
> it in from your references. Once you've done one, it is reusable and the model sticks
> to it."* — 01:56

**This is the load-bearing instruction.** Format transfers between projects; content
must be yours. The model is not remembering taste, it is reading a contract.

### 3 · Components

Every state, then motion. *"The animations are all entirely custom, and that's honestly
where the real fun is."* Declare closed inventory counts (`N` parts, `M` timings, `K`
marks) so completeness is auditable. In the source look this means `AT REST · HOVER ·
PRESSED · DISABLED` per control, with the disabled state getting art direction rather
than grey.

### 4 · Blocks

Landing page, dashboard, settings — *"because it's a system. Every new screen looks
like it belongs."* Cheap once zone 3 exists; the reel shows the same block inventory in
several unrelated aesthetics to make that point.

### 5 · The design pack

> *"Everything lands in one web page with reusable code snippets, and you tell the model
> to read it before it does any design work for you, whatever you're building."* — 02:35

A retrieval target, not documentation. Cheapest RAG corpus you will ever build.

## What the reels leave open, and what this skill adds

| Gap in the reels | What `design-pack` does |
| :--- | :--- |
| never renders the same brief twice, prose vs pack | `pack.html` is the honest half: one page, every state, rendered |
| no static token gate | `design-pack verify` fails on an undeclared colour, font, radius or eased curve |
| `check_components.py` shown only as a passing clip | `design-pack check` (`check_components.py`) runs headless Chromium across 7 viewports: verifies declared `.keybar` triggers and clickable controls respond within ≤100 ms with zero console or page errors, plus overlap, clipping, 10 px floor, and contrast (with a failing control test) |
| reel prints tiered WCAG contrast (`4.5` AA body, `3.0` LARGE at `24 px` / `19 px` heavy, `< 3` `FAIL` decoration only) | **Known scope boundary (not parity):** `design-pack check` enforces a single `>= 3:1` floor (`--min-contrast 3.0`) across visible text rather than size-tiered AA/Large rules |
| zone 1 has no artefact in the reel | the look's `README.md` records which image every value came from |
| no cost model for zone 3 | the gates make the cheap path the correct path: copy a token, never a hex |

The last row is the point. A pack that only documents is obeyed until it is
inconvenient. A pack with failing conformance and behaviour gates is obeyed because
the build breaks otherwise — ending with human sign-off for taste.

## Provenance

| Reel / Frames | Observation / Quote | What the skill adds |
| :--- | :--- | :--- |
| `DfudeDMtl2P` (`t026`, `t040`, `t052`, `t064`, `t068`, `t132`, `t144`) | `t040` puts `SECOND PASS` (`AVOID`) beside `OVERPRINT` (chosen) as two complete foundation sheets, and notes *"White is not an ink. Neither is black."* `t052` shows six surface tiles badged `ONE MORE PROMPT`. `t064` shows struck-off `do, don't` pairs. `t068` declares `"NINE SHOP MARKS"` and prints WCAG tiers (`AA 4.5` body, `LARGE 3.0` at `24 px` / `19 px` heavy, `< 3` `FAIL` decoration only). `t132` declares `"THIRTY-SEVEN PARTS"`; `t144` declares `"SEVENTEEN TIMINGS"`. | Full-fidelity side-by-side candidate comparison before choosing, closed inventory counts (`N` parts, `M` timings, `K` marks), one-prompt surface reuse after both gates pass, and recording the single `>= 3:1` check floor as a known scope boundary vs tiered WCAG. |
| `Df417DaNz4r` (`t048`, `t062`, `t066`, `t070`, `t072`) | `t062` prints an explicit `NEVER` block of constraint-banned patterns. `t066` defines `THE VOICE`: *"A printer talking shop. Short, practical, dry. Loading is inking up. An error is a misprint..."* | Requiring a named production constraint and derived `NEVER` block before the 8-section skeleton, plus mapping UI states (loading, error, done) to domain vocabulary in Voice. |
