# System map — `notes-cli`

Walkable map of this repo for agents editing it later. The source tree is the truth; this map cites it.

**Where am I:** a ~2k-line TypeScript CLI (`src/`) that stores markdown notes in SQLite and syncs them to a git remote.

## Catalog

| You want… | Go to |
|---|---|
| What a Note is | [objects/note.md](objects/note.md) |
| What a Vault is | [objects/vault.md](objects/vault.md) |
| How sync works | [processes/sync.md](processes/sync.md) |
| What a change hits | [effects/CONTEXT.md](effects/CONTEXT.md) |

## Name collisions

- Product word **Vault** = class `Store` in `src/store.ts`. Same thing.
- **Index** means two different things: the SQLite FTS index and `src/commands/index.ts` (the command registry). Neither maps to the other.

## Universes

In a real map, state what is **live** (cite commit), **leftover**, and **ghost**. This illustrative example marks everything `illustrative` — see [_meta/schema.md](_meta/schema.md). In the imagined subject, `src/legacy/import-evernote.ts` would be **leftover**.
