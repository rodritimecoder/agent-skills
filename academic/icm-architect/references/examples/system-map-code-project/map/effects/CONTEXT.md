# Change-impact index

"If you are changing X, open these cards first." First-order hits only; each card's own *Hits / Does not hit* is authoritative — fix the card if they disagree here.

| You are changing… | Open |
|---|---|
| `src/note.ts` (schema, revision rule) | [objects/note.md](objects/note.md), [processes/sync.md](processes/sync.md) |
| `src/store.ts` (connection, migrations) | [objects/vault.md](objects/vault.md), every command entrypoint |
| `src/sync.ts` | [processes/sync.md](processes/sync.md), [objects/note.md](objects/note.md) |
| Anything in `src/legacy/` | nothing — leftover; do not extend, propose deletion instead |
