# Memory — Routing (`AGENTS.md`)

Where am I: a four-layer agent memory store. State is files; nothing here is a
service. Read `CONTEXT.md` for the layer contract.

## Where everything lives

| Need | Go to |
| :--- | :--- |
| Find something from earlier work | `_tools/mem.py search "<intent>"` |
| Read a hit | `_tools/mem.py get <id...>` |
| What happened around it | `_tools/mem.py timeline <id>` |
| The session-start header | `04_context/MEMORY.md` (via `mem.py context`) |
| Record something deliberately | `_tools/mem.py save ...` |
| Raw event log | `01_transcripts/**/*.jsonl` |
| Observations | `02_notes/<project>/*.md` |
| Linked knowledge | `03_wiki/entities/<kind>/*.md` |
| Consolidate / correct | `_tools/dreamer.py` |
| Gate before believing a pass | `_tools/links.py` |

## Rules

- Markdown is the truth. `db/memory.db` is derived; delete it freely.
- The main agent is read-only except `mem.py save`. Never hand-edit `03_wiki/`
  or `04_context/`: the dreamer owns them.
- `04_context/MEMORY.md` is an index, never a body dump. Over budget is a bug.
- A note with `verified: false` is a lead, not a fact.
- Archived, never deleted: `mem.py forget <id>` moves to `_archive/`.

## Checks

```bash
python3 _tools/links.py            # exit 0 clean, 1 on any finding
python3 tests/test_gates.py        # gates must fail on their negative control
node _tools/test_capture.mjs       # the transcript hook must not leak secrets
```
