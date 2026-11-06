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
| 1 | **References** | real images, one style only, each annotated with what you like | 0 m |
| 2 | **Style sheet** | idea · look · feel, plus components and behaviour | 105 m |
| 3 | **Components** | every piece drawn in every state, then animated | 1,000 m |
| 4 | **Blocks** | full screens built from those pieces | 4,000 m |
| 5 | **Design pack** | one web page with swatches, type, states, snippets | 6,000 m |

### 1 · References

Find real images. One style only — *"mixing styles just confuses the model."* Say what
you like in each one; that note is what aligns the model to you. Public domain or your
own, and *"always respect people's creative work. We're here to be inspired not to
steal."*

### 2 · Style sheet — foundations, components, behaviour

Foundations is three questions in order:

- **The idea** — the overall concept, its voice, and the rules your references follow.
- **The look** — *what each colour is for* and *what each font does*. Roles, not swatches.
- **The feel** — surface, texture, line, shape, spacing.

Components is *"every piece you'll need, like buttons, sliders, forms — each one drawn
in all of its states."* Behaviour is *"simply how things move."*

> *"Find one style sheet you like, give it to the model as the format and ask it to fill
> it in from your references. Once you've done one, it is reusable and the model sticks
> to it."* — 01:56

**This is the load-bearing instruction.** Format transfers between projects; content
must be yours. The model is not remembering taste, it is reading a contract.

### 3 · Components

Every state, then motion. *"The animations are all entirely custom, and that's honestly
where the real fun is."* In the source look this means `AT REST · HOVER · PRESSED ·
DISABLED` per control, with the disabled state getting art direction rather than grey.

### 4 · Blocks

Landing page, dashboard, settings — *"because it's a system. Every new screen looks
like it belongs."* Cheap once zone 3 exists; the reel shows the same block inventory in
several unrelated aesthetics to make that point.

### 5 · The design pack

> *"Everything lands in one web page with reusable code snippets, and you tell the model
> to read it before it does any design work for you, whatever you're building."* — 02:35

A retrieval target, not documentation. Cheapest RAG corpus you will ever build.

## What the reel leaves open, and what this skill adds

| Gap in the reel | What `design-pack` does |
| :--- | :--- |
| never renders the same brief twice, prose vs pack | `pack.html` is the honest half: one page, every state, rendered |
| no verifier — "the model sticks to it" is asserted | `design-pack verify` fails on an undeclared colour, font, radius or eased curve |
| zone 1 has no artefact in the reel | the look's `README.md` records which image every value came from |
| no cost model for zone 3 | the gate makes the cheap path the correct path: copy a token, never a hex |

The last row is the point. A pack that only documents is obeyed until it is
inconvenient. A pack with a failing gate is obeyed because the build breaks otherwise.
