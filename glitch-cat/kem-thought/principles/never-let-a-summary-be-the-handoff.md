# Never Let a Summary Be the Handoff

**Rule:** State lives in a file — one line per fact, superseded in place. Compaction hands back the state file, never a summary of it.

**Why:** Handover documents, manual clears, and custom compaction systems cost more, are slow, and magnify the very problems you are trying to solve. A summary is a lossy copy of a thing that did not need copying.

**In practice:**
- Facts get written down while the agent is still sharp.
- Compaction happens at a limit you set, not at one the harness picks for you deep into the session.
- A changed fact replaces its old line. The corpus never carries both the old and the new version.
- Treat the context as three artifacts, not one blob: state (what is true), a task board (what is left, who owns it, what is blocked), and a cache (what is warm). When a conductor's context fills, open a fresh pane, let the old conductor walk off, and have the new one read the same state. No compaction, no handover document.
- Every save overwrites the whole file. Nothing fancy, just simple, but it works.

**Kem:** *"The facts go into a state file... after that every compaction is just handing the state file back, so it never has to go through some weird summary."* — Autonomous State File Compaction [01:39]

*"So when the conductor's context fills up, a new pane opens and it walks off and a fresh conductor can walk back on ... No compaction, no giant hand-off document."* — Glitch Orchestra: conductor rotation [00:34–00:51]
