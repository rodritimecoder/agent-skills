---
name: design-system

description: >
  One token layer and one renderer, so pages stop being one-off HTML. tokens.css
  declares three named looks — house, paper, terminal — as CSS custom properties
  (colour, font stack, radius, border, shadow) plus base styles for h1/h2/p/pre/
  table/blockquote, and scripts/render.py (stdlib only) inlines the base rules and
  the one look you pick into a single standalone page with no external requests.
  Use when a report, note, README or generated document needs consistent
  typography and colour without inventing styling per page.

compatibility: "Python 3.8+. No dependencies, no network, no build step."
allowed-tools: "Bash(python3:*) Read Write Edit"
---

# Design System (`design-system`)

Two files do the work: `tokens.css` holds the decisions, `scripts/render.py`
applies one of them to content you already wrote.

## What the token layer is for

Every page used to hardcode its own colours, sizes and spacing, so two pages
never agreed and every new page was a fresh set of one-off decisions. The token
layer moves those decisions into **one place** and names them:

| Group | Tokens | Controls |
| :--- | :--- | :--- |
| colour | `--ink` `--ink-soft` `--paper` `--paper-sunk` `--accent` `--rule` | text, muted text, page, sunk panels, links/rules, hairlines |
| font stack | `--font-body` `--font-display` `--font-mono` | running text, headings, code |
| radius | `--radius` | corners on code blocks and panels |
| border | `--border` | hairlines on `h2`, tables, `pre` |
| shadow | `--shadow` | depth on `pre` (or `none`) |

Base rules style `h1`, `h2`, `p`, `pre`, `table`, `blockquote` — and they never
hardcode a colour. They only read the tokens, so a look is **one block** and
nothing else.

## The three looks

| Look | Feels like | Type | Accent |
| :--- | :--- | :--- | :--- |
| `house` | default product page, light and quiet | system sans | teal `#0f766e` |
| `paper` | printed page, cream stock | serif (Iowan/Palatino/Georgia) | burnt orange `#8a3b12` |
| `terminal` | dark screen, phosphor | monospace throughout | green `#38e07b` |

Each is a single `[data-look="<name>"]` block in `tokens.css`. Adding a fourth
look means adding one block and one entry in `render.LOOKS` — the renderer picks
blocks up by selector, so no other code changes.

## The command

```bash
python3 scripts/render.py --title T --body file.html --look house --out page.html
```

`--body -` reads stdin; omitting `--out` prints to stdout. From Python:

```python
import sys; sys.path.insert(0, "scripts")
from render import render, write

html = render("Coffee, measured", body_html, look="paper")   # -> str
write("page.html", "Coffee, measured", body_html, look="house")  # -> Path
```

The output is a full document (`<!DOCTYPE html>`, `<html data-look="…">`, one
`<style>` block). The base rules and **exactly one** look block are inlined, so
the page makes no external requests: no `<link>`, no `<script>`, no font fetch.
An unknown look raises `RenderError` (a `ValueError`) naming the valid looks, and
the CLI exits `2` with the same message.

## Boundary

It renders content you already wrote. It does not design for you.

- **Copy, structure and meaning are yours.** The body HTML is inserted
  unchanged — no rewriting, no Markdown parsing, no layout inference. If you
  wrote a bad page, you get a well-typeset bad page.
- **Trusted input only.** The body is raw markup and is not sanitised. Point it
  at a file you or your agent wrote, not at third-party HTML.
- **No site, no components, no interactions.** There is no nav, grid, hero,
  theme switcher or dark-mode toggle. It styles prose and tables, not an app.
- **Three looks, not a design system in the Figma sense.** Tokens are a contract
  for consistency; they are not a brand exploration tool.

Tests: `python3 tests/test_render.py` — 13 unittest cases covering title,
unchanged body, per-look isolation (only the chosen look is inlined), one
`<style>` block, no `<link>`/remote URLs, and the unknown-look error.
