# v1 render source (port reference)

Provenance: extracted from the retired v1 renderer, `University/notes/viz.html`
(2026-10-23), when it was 1.5 MB.

| File | What it is |
| :--- | :--- |
| `viz_app.js` | the application code: constellation render, week chips, node selection, Cornell toggle, math/callout rendering (~58 KB) |
| `viz_style.css` | the stylesheet for the same page (~14 KB) |

**Deliberately not included:** the injected graph payload and the
`WORKED_SOLUTIONS_DB`. Those are course data — module names, lecture titles,
Zoom links — not code. A port needs the functions, not the student's notes.

**Also not included:** d3 v7.8.5, which the original embedded. The port may
inline a minified d3 or replace the force layout; either way `graph.html` must
open offline, with no network requests.

Use this as the source for stage 4 (`scripts/render_graph.py`,
`render_anki.py`, `render_cornell.py`). Do not copy the data model: stage 4
reads `meta.json` and `02_sift/`, not a baked-in payload.
