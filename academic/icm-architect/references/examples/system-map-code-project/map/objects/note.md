---
type: object
cluster: storage
universe: illustrative
status: illustrative
entity: src/note.ts (does not exist — format example)
---

# Note

A single markdown note with metadata; product word "note", class `Note` in `src/note.ts`. Stored as one row in SQLite, rendered as one markdown file on export.

## Why this shape

Notes are immutable once synced — edits create a new revision row rather than updating in place, so git sync can diff rows instead of guessing. That is why `rev` exists and why nothing ever `UPDATE`s a note body.

## Shape

- Primary key `(id)` UUID; `rev` monotonic integer per id
- Body stored raw markdown; frontmatter parsed lazily (`parseFrontmatter`, src/note.ts:41)
- FTS index maintained by trigger, not application code (migrations/0002_fts.sql:12)

Citations (illustrative): `src/note.ts:18-64`

## Connected to

- **owns:** nothing
- **owned-by:** [Vault](vault.md) (a Vault contains Notes)
- **joins:** [Vault](vault.md) via `vault_id`
- **looks-like-but-is-not:** `NoteRevision` in the same file — that is the history row, do not edit notes through it

## If you change this

- **Hits:** [Vault](vault.md) serialization, sync row hashing (src/sync.ts:77), FTS triggers
- **Does not hit:** command registry — commands construct Notes only through `Note.create()`

## Surfaces

| Surface | Role |
|---|---|
| CLI commands | reads/writes via repository |
| Sync engine | reads |
| Human | writes via editor after `notes open` |

## See

- Source: `src/note.ts`
