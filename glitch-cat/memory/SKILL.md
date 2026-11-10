---
name: memory

description: >
  Four-layer agent memory over plain markdown: transcripts, notes, a linked
  wiki, and a small injected header. A second agent (observer) turns session
  logs into observations; a dreamer consolidates them offline, cross-references
  notes against the transcripts they cite, builds one wiki page per entity, and
  promotes durable facts into a budgeted header — correcting wrong notes instead
  of stacking them. Use for "remember this", "what did we decide last time",
  "recall a past session", "have you seen this bug before", "cross-reference my
  notes", "dream", "defrag memory", "update the wiki", "standing memory", or any
  request for context from earlier work. Works locally with SQLite FTS5; no
  embedding server and no cloud account required.

compatibility: "Local only. Python 3.10+ standard library and SQLite FTS5. Markdown is the source of truth; db/memory.db is a derived index you can delete. The optional `--llm` salience pass needs the local Genesis model on :8080 and falls back to the deterministic heuristic when it is offline."

allowed-tools: "Bash(memory:*) Bash(python3:*) Read Write"
---

# `memory` — Four-Layer Agent Memory

Adapted from Anthropic, *The components of agent memory* (Nov 6 2026): memory is
a hierarchy, and *dreaming* — offline consolidation — is what corrects it.

```
       ┌──────────────────────────────────────────────┐
       │ 04_context/MEMORY.md   injected every session│  ≤200 lines / 25 KB
       └───────────────▲──────────────────────────────┘
                       │ promote (details go down, links stay)
       ┌───────────────┴──────────────────────────────┐
       │ 03_wiki/   one page per entity, [[linked]]   │  dreamer writes
       └───────────────▲──────────────────────────────┘
                       │ build + merge + close gaps
       ┌───────────────┴──────────────────────────────┐
       │ 02_notes/  salient observations, verified    │  observer writes
       └───────────────▲──────────────────────────────┘
                       │ cross-reference  ↕  correct
       ┌───────────────┴──────────────────────────────┐
       │ 01_transcripts/*.jsonl   append-only log     │  hook code writes
       └──────────────────────────────────────────────┘
```

## Why this shape

| Finding (Anthropic) | Consequence here |
| :--- | :--- |
| Fixed salience rules hurt strong models (−0.234 reward) | The observer keeps a deterministic floor and offers `--llm` judgement; it never hard-codes "only record failures" |
| Several agents on one page lost 16/57 facts; one writer per page kept 57/57 | `02_notes` per session, `03_wiki` per entity, header only from the dreamer — disjoint writers |
| Wiki + search scored 61% vs 53% search-only, 48% wiki-only | Both are exposed; neither replaces the other |
| A wiki grew to 1.77× the corpus and abstracted nothing | Header budget is enforced by code; `links.py` fails red over it |
| Injected layer must stay small (Claude Code loads 200 lines / 25 KB) | `MEMORY.md` is an index of facts and links, never bodies |

## Usage

```bash
MEM="python3 _tools/mem.py"

$MEM search "auth refresh bug"          # index lines, ~50 tokens each
$MEM get <id> <id>                      # full bodies, batch only
$MEM recent --project api               # newest first
$MEM timeline <id> --window 5           # what happened around it
$MEM context                            # the budgeted injected header
$MEM save --title "Token refresh race" --type decision --project api \
          --entities auth.py,refresh_token --body "Refresh must be single-flight."
$MEM forget <id>                        # archives, never deletes
$MEM stats
```

```bash
python3 _tools/observer.py              # transcripts -> notes (heuristic)
python3 _tools/observer.py --llm        # let :8080 judge salience
python3 _tools/dreamer.py               # crossref + wiki + gaps + promote
python3 _tools/dreamer.py --only promote
python3 _tools/links.py                 # the gate: exit 1 on any finding
```

## The write contract

| Path | Sole writer | Trigger |
| :--- | :--- | :--- |
| `01_transcripts/` | harness hook | every tool call, append-only |
| `02_notes/` | `observer.py` | batch of 10 events, or `Stop` |
| `03_wiki/` | `dreamer.py` | nightly / `dream` |
| `04_context/` | `dreamer.py` | same run |
| anything | main agent | `mem save` only, `source: manual` |

The main agent is **read-only** by design. A coder that can write the wiki
pollutes memory with its own guesses; the second agent is the only consolidator.

## Dreaming is automatic, and that is safe

Every dream writes plain markdown, so a bad pass is a `git diff` away from being
reverted — not a lost fact. The guard is ownership plus a code gate, not an
approval queue:

- one writer per path, so concurrent runs cannot erase each other's lines
- `links.py` fails on dangling links, unresolved sources, duplicate ids, pages
  without provenance, and an over-budget header
- `dreamer` exits non-zero when the budget gate cannot be met, so a cron cannot
  claim success over a broken header

## Recall discipline

- Search the wiki **and** the notes; the measurements say one alone is worse.
- Quote a source line; do not paraphrase a decision into a new one.
- A note is trusted only when `verified: true`. `?` means the dreamer could not
  find its claims in the transcript — read it, do not rely on it.
- If recall returns nothing, say so. Absence is a fact worth recording.

## Files

```
memory/
├── SKILL.md            this contract
├── AGENTS.md           routing entry (<60 lines, no content)
├── CONTEXT.md          layer schema, writers, budgets
├── 01_transcripts/     *.jsonl + .observer_state.json
├── 02_notes/<project>/ one file per session
├── 03_wiki/
│   ├── _index.md       generated, never hand-edited
│   ├── entities/<kind>/<name>.md
│   └── topics/
├── 04_context/MEMORY.md
├── _tools/{mem,observer,dreamer,links}.py
├── _templates/
└── tests/
```
