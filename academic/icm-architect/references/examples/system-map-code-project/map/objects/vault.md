---
type: object
cluster: storage
universe: illustrative
status: illustrative
entity: src/store.ts (does not exist — format example)
---

# Vault

One user's note database plus its git remote. Product word "Vault", class `Store` — both names appear in docs and errors.

## Why this shape

The Vault owns *everything durable* so commands stay stateless: a command receives a Vault, does its work, drops it. No global DB handles anywhere else.

## Shape

- Owns the SQLite connection and all migrations (src/store.ts:22)
- `path` resolved from `NOTES_VAULT` env or `./.notes` fallback (src/store.ts:31)

Citations (illustrative): `src/store.ts:15-58`

## Connected to

- **owns:** [Note](note.md) rows, migrations, FTS index
- **owned-by:** nothing
- **joins:** git remote through [sync](../processes/sync.md)
- **looks-like-but-is-not:** `VaultConfig` (src/config.ts) — that is only the TOML file; the Store is the live object

## If you change this

- **Hits:** every command entrypoint, [Note](note.md) persistence, [sync](../processes/sync.md)
- **Does not hit:** markdown rendering (pure functions over Note bodies)

## Surfaces

| Surface | Role |
|---|---|
| All CLI commands | read/write through it |
| Tests | construct in-memory Stores |

## See

- Source: `src/store.ts`
