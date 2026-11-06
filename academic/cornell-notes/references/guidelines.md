# Content & Active Recall Guidelines

Rules for writing the cue–note pairs. The formatter handles most of this
automatically; these are the things it cannot infer.

- **LaTeX Math Escaping** — always use standard LaTeX syntax inside math
  delimiters (`$\\omega$`, `$\\frac{A}{B}$`). In JSON strings, use standard
  JSON escaping (`"\\omega"`). The formatter automatically sanitizes
  accidental double-escaped backslashes (`\\\\omega` $\\to$ `\\omega`).
- **Cognitive Question Badges** — the formatter detects cognitive types
  (`definition`, `mechanism`, `comparison`, `formula`, `pitfall`) from the
  cue wording, so write cues that name the relationship.
- **Spaced Repetition Checkboxes** — each cue row gets three review
  checkboxes for Leitner-style tracking across review sessions.
- **Obsidian Callouts** — notes may contain Obsidian-style callouts
  (`> [!NOTE]`, `> [!TIP]`, `> [!WARNING]`, `> [!DANGER]`), rendered as
  distinct accent boxes.
- **Handling Large Files** — for documents over 3,000 words, process
  section by section, combining them into a single coherent JSON document in
  source order without duplicating boundary headings.
