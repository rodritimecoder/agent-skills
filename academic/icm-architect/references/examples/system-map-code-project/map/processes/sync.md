---
type: process
status: illustrative
consumes: ["../objects/note.md", "../objects/vault.md"]
produces: ["git push to vault remote"]
---

# Sync

Push committed note revisions from the local Vault to its git remote and pull remote changes. One sentence version: rows become commits, commits become pushes.

## Input → Movement → Output

Input: dirty Note rows in the Vault. Movement: hash rows, write a snapshot commit, fast-forward or rebase against the remote. Output: an up-to-date remote ref, or a conflict report the human resolves.

## Why this shape

Sync diffs **rows**, not files — that only works because notes are immutable (see note.md "Why this shape"). If notes ever became mutable in place, this whole process needs a redesign, not a patch.

## Steps

1. Collect rows where `max(rev)` changed since last sync hash (`src/sync.ts:44`).
2. Serialize each changed Note to markdown under `.notes/objects/` (`src/sync.ts:88`).
3. Commit via isomorphic-git with a deterministic message `sync@<hash>` (`src/sync.ts:112`).
4. Push; on non-fast-forward, stop and emit a conflict report for the human (`src/sync.ts:131`). Never auto-merge.

## If you change this

- **Hits:** [Note](../objects/note.md) immutability rule, [Vault](../objects/vault.md) migration history
- **Does not hit:** FTS index (query-time only)

## Surfaces

| Surface | Role |
|---|---|
| `notes sync` command | triggers |
| Human | resolves conflicts |

## See

- Objects: [note.md](../objects/note.md), [vault.md](../objects/vault.md)
- Source: `src/sync.ts`
