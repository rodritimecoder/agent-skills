# Memory — Layer Contract (`CONTEXT.md`)

## Reading (inputs)

- `01_transcripts/**/*.jsonl` — append-only events written by the harness
- `02_notes/**/*.md` — observations written by the observer
- `03_wiki/**/*.md` — representations written by the dreamer

## Process

| Layer | Folder | Writer | Shape | Lifetime |
| :--- | :--- | :--- | :--- | :--- |
| transcript | `01_transcripts/` | hook code | one JSON object per line | append-only, never edited |
| note | `02_notes/<project>/` | `observer.py` | one file per session, frontmatter + Files/Commands/Failures/Discoveries | until promoted or archived |
| wiki | `03_wiki/` | `dreamer.py` | one page per entity, `[[links]]`, `_index.md` generated | rewritten whole, merged |
| context | `04_context/MEMORY.md` | `dreamer.py` | index of facts + `mem get` pointers | ≤200 lines / 25 600 bytes |

Disjoint writers are the safety mechanism. Two processes never write one path:
notes are per session, pages are per entity, the header has a single author.

## Frontmatter

```yaml
id: api-1a2b3c4d          # stable, derived from the path unless set
title: Refresh race
type: decision            # note | session | entity | decision | invariant | rule
project: api
ts: 2026-11-10T05:04:00
source: manual            # manual | observer | dreamer
entities: [auth.py, refresh_token]
sources: [01_transcripts/api/s1.jsonl]
confidence: 0.9
verified: true            # the dreamer found the claims in the transcript
```

`type` in `{decision, invariant, rule, policy, preference}` is what the dreamer
promotes to the header. Everything else stays searchable one layer down.

## Outputs

- `db/memory.db` — derived FTS5 index (`docs`, `docs_fts`, `meta`)
- `04_context/MEMORY.md` — the injected header
- `03_wiki/_index.md` — generated catalog, never hand-edited

## Check

```bash
python3 _tools/links.py
```

Fails on: dangling wikilink, unresolved `sources:` path, duplicate id across
layers, entity page with no provenance and no stub marker, header over budget.
`dreamer.py` exits 1 when the header cannot be brought back under budget, so a
cron cannot report success over a broken header.

A pass recorded before an upstream edit is stale: re-run the dreamer after new
notes land, do not trust yesterday's header.

## Budgets

| Thing | Cap | Why |
| :--- | :--- | :--- |
| `MEMORY.md` | 200 lines / 25 600 bytes | paid every session; long instruction files lose adherence |
| one note | 6 KB | notes are pointers, not transcripts |
| one wiki page | 4 KB | a page larger than its subject abstracts nothing |
| `mem search` result | 8 lines | index first, bodies on request |

## Anti-patterns

- Hand-editing `03_wiki/` or `04_context/` — the next dream overwrites it.
- Letting the coder write standing memory — hallucinated self-poisoning.
- Stacking a correction beside the old note — rewrite it in place, keep the id.
- Promoting a `verified: false` note to the header — mark it `?` or leave it down.
