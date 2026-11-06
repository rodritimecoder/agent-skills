---
name: notes-index

description: >
  Local ranked search over a Markdown notes folder — one SQLite FTS5 index, fingerprint-based refresh, Haiku-class
  summaries, and an AGENTS.md rule so the agent searches the index instead of grepping (Glitch Cat Club / Kem Glitch;
  Reel DezGALzNCuf, artifact MdwChkFxkCKwwnToGVJXGX). Cuts memory-search token spend by up to half on a large notes
  vault. Also a `cite` gate that proves an answer's citations before it ships: paths resolve, `:lines` exist, and
  every quoted span is verbatim in the cited file or transcript. Use when answering questions about past work,
  decisions or notes, when a folder of Markdown keeps growing, or when a claim needs to be traced back to its source.

compatibility: "Python 3.10+ with sqlite3 FTS5. Summaries use a hosted model over plain HTTPS; a local OpenAI-compatible endpoint is an optional fallback."
allowed-tools: "Bash(python3:*) Bash(notes-index:*) Read Write Edit"
---

# Notes Index (`notes-index`)

One ranked search instead of many greps. Derived from **Kem Glitch (Glitch Cat Club)**'s *"Half the Tokens"* artifact
([`MdwChkFxkCKwwnToGVJXGX`](https://claude.ai/artifact/MdwChkFxkCKwwnToGVJXGX)) and reel
[`DezGALzNCuf`](https://www.instagram.com/reel/DezGALzNCuf/), both vaulted at
`/run/media/rodri/AI/creator-vault/kem_glitch/2026-10-22_sqlite_fts_index_for_native_memory_search/`.

---

## 🏛️ The Problem

When the model answers a question about your past work it **greps, reads, then greps again**. Every file it opens
lands in the context window, and the context window is the token bill. On one person's ~3,000-note vault, plain
Claude Code on Opus opened **9 files** for a single prompt.

## 🛠️ The Fix

A local SQLite FTS5 index over your Markdown notes, and a rule in `CLAUDE.md` that makes the agent search the index
first. One ranked query opens the one file that matters.

| Part | What it does |
| :--- | :--- |
| `notes.db` | One SQLite file, FTS5 index (porter stemming) over raw, summary and fact rows |
| `index.py update` | Fingerprints every note, touches only what changed, drops deleted notes |
| Summariser | A hosted frontier model writes topic + fact rows beside the raw text (see below) |
| `index.py search` | One ranked query, reciprocal rank fusion, recency bonus, health line first |
| `AGENTS.md` rule | Tells the agent to search the index before answering (write `CLAUDE.md` with `--target claude`) |
| Timer | Refreshes every 6 hours, silently, no window |

## 🖥️ CLI Quickstart

```bash
NI="notes-index"        # installed on PATH by sync-skills
# or, straight from the checkout:
# NI="python3 /run/media/rodri/AI/skills/notes-index/notes_index.py"

# 1. What would the one-off first pass cost?
$NI --folder ~/notes plan

# 2. Scaffold: index, CLAUDE.md rule, 6-hour timer (asks before the first ingest)
$NI --folder ~/notes init --timer

# 3. Refresh (safe to run any time; unchanged notes cost nothing)
$NI --folder ~/notes update

# 4. Search — the health line prints first, then ranked pointers
$NI --folder ~/notes search "decision about the worktree harness"
```

`search` prints the health line first, exactly as the artifact prescribes:

```
2883 rows | last refreshed 2026-10-22T12:42:43 | last error: none
- 2026-10-17 | topic | claude_projects_beta_architecture/notes.md  (score 0.01647)
    »multi-agent coordination CLI three-way routing«
    /home/rodri/notes/claude_projects_beta_architecture/notes.md
```

Results are **pointers**. Open the file before stating a fact from it.

## 🧩 Commands

| Command | Purpose |
| :--- | :--- |
| `plan` | Count notes, notes needing summaries, estimated minutes |
| `init` | Create the index, write the `AGENTS.md` rule, optionally install the timer (`--yes` to ingest now); `--target agents\|claude` chooses the rule file |
| `update` | Re-index new/changed/removed notes (`--strict` treats summary failures as run failures) |
| `search` | Ranked search; `--after YYYY-MM-DD`, `--limit N` (default 5) |
| `status` | Files, rows by kind, freshness, last error, last log line |
| `rule` | Print the `AGENTS.md` block, or `--apply` it; `--variant full\|lean\|trust-snippet`, `--target agents\|claude` |
| `timer` | `install` / `status` / `uninstall` the 6-hour refresh |
| `cite` | Prove an answer's citations: paths resolve, `:lines` exist, quotes are verbatim. `--strict-lines`, `--transcript`, `--fail-on-warn` |

## 🔗 `cite` — prove the answer's citations

Search finds the note; `cite` proves the answer used it. It reads a Markdown answer and checks
every citation in it:

- **`path` or `path:line`** — the file resolves (relative to the answer, then `--root`) and the
  line exists. A path with an explicit line that does not resolve is a violation; a bare
  reference like `karpathy/llm-wiki.md` is a warning, because not every name is a local file.
- **`[MM:SS]`** — resolved against `transcript.md` beside the answer (or `--transcript`), and
  matched against the surrounding transcript blocks, so a coarse ASR block does not produce a
  false failure.
- **Quotes** — every `"…"` in a paragraph that carries a citation must appear in the cited
  text. `[editorial insertions]` and `…` elisions are tolerated; paraphrase is not. Punctuation
  and case are ignored, words are not.

```bash
# Did the answer actually quote what it cited?
notes-index --folder /run/media/rodri/AI/creator-vault cite path/to/answer.md

# Require the quote to sit inside the cited line range
notes-index cite answer.md --strict-lines

# Fail on uncited prose too, not just on false citations
notes-index cite answer.md --fail-on-warn
```

Exit `1` when a citation is false. Uncited paragraphs are warnings by default: a synthesis
paragraph legitimately has no single source, and the gate should not pretend otherwise.

**What it cannot do:** a quote can be real and still not support the claim. That is a judge's
job with fresh context (`kem-thought` → `fresh-context-judges`), not a substring's. This gate
proves the citation exists; it does not prove the argument.

The measured case for it: plain Claude Code verified 70% of its answers on a 200-file test;
with one cite-your-source instruction, 92.5% (Glitch Cat Club, `DfFSZDvN6oV`).

## ⚖️ The Levers (change one at a time, compare)

| Lever | What it does |
| :--- | :--- |
| `--lever no-grep` | Adds *"If the search found it, don't also grep"* — the biggest waste in Kem's testing |
| `--lever trust-snippet` | Swaps *"Open the file before you state a fact"* for *"Open the file only if the snippet doesn't hold the answer"* |
| `--lever fewer-results` | Acts only on the top few hits; the search default is already 5, not 10 |
| `--lever check-newer` | Adds *"Before answering, search once more for anything newer on the same topic"* — the accuracy lever |

The artifact's section 09 lists these four. Each is selectable on its own and they compose:

```bash
notes-index rule --lever no-grep                       # one lever
notes-index rule --lever no-grep --lever check-newer   # two
notes-index rule --variant trust-snippet               # shipped bundle: trust-snippet + no-grep + check-newer
```

| Other flag | What it does |
| :--- | :--- |
| `--limit N` | Hits per search (default 5, not 10) |
| `--target claude` | Writes the rule to `CLAUDE.md` instead of `AGENTS.md` |
| `--no-summaries` | Skip the summary pass: fewer tokens spent indexing, weaker recall on long notes |
| `--workers N` | Parallel summary calls (default 6) |

## 🧠 Which model writes the summaries

Providers are tried in order, and the first that answers wins:

| # | Provider | Configured by |
| :---: | :--- | :--- |
| 1 | Any command you choose | `NOTES_INDEX_SUMMARIZER_CMD` — prompt on stdin, JSON on stdout |
| 2 | `claude -p --model haiku` | used only if the `claude` CLI is installed |
| 3 | **A hosted OpenAI-compatible endpoint** | `NOTES_INDEX_API_URL`, `NOTES_INDEX_MODEL`, `NOTES_INDEX_API_KEY`; defaults to NVIDIA NIM `z-ai/glm-5.3-flash` |
| 4 | A local OpenAI-compatible endpoint | `NOTES_INDEX_LOCAL_URL` (default `http://127.0.0.1:8080/v1/chat/completions`), `NOTES_INDEX_LOCAL_MODEL` |

Keys are read from the environment **and** from `~/.agent_keys.env`, because the 6-hour refresh runs from a systemd user unit that never loads a shell profile. A key exported only in `.bashrc` fails there silently.

`NOTES_INDEX_MAX_TOKENS` defaults to **6000**, not 1600: the default model reasons before it answers, and at 1600 the whole budget went on thinking and the reply came back empty. It scales to half a token per input character and caps at 16k, so a 20k-character note gets a bigger answer budget than a short one.

`NOTES_INDEX_TIMEOUT` defaults to **300 seconds**. Large notes take minutes on a reasoning model, and the previous 180s limit is what lost two writes in the 2026-10-25 run.

Failures are retried across the key pool: a 5xx, a timeout, or an empty reply moves to the next key. Only 400/404/422 fail fast, because a different key cannot fix a bad request. The error line reports what actually happened (`HTTP 502 Bad Gateway`, `empty content (finish_reason=length)`, `TimeoutError`) instead of `no answer`.

`notes-index status` prints the resolved provider, so a failure names the thing that died:

```
summarizer    : z-ai/glm-5.3-flash @ https://integrate.api.nvidia.com/v1/chat/completions (2 keys)
```

To send summaries through your own agent instead: `NOTES_INDEX_SUMMARIZER_CMD='opencode run -m opencode-go/deepseek-v4.1-flash'`.


## ⚠️ What It Does Not Do

- **It is not a lock.** The `CLAUDE.md` rule is an instruction; in Kem's testing Claude ran the search in 91 of 92 runs.
- **It does not improve accuracy**, it makes finding cheaper. Same accuracy, fewer tokens.
- **It is keyword search.** It depends on the words you use; the summaries add the words you would have searched with.
- **It pays off on large vaults.** A few hundred notes: one grep already finds the answer and the index adds a step.
- **The first pass costs once** — summarising long notes is a one-off.

## 🔒 Safety

- API keys, tokens and passwords are **masked before they reach the database**.
- Note contents are treated as data, never as instructions, by the summariser.
- A lock file stores the process id; a lock left by a killed run is ignored, not a blocker.
- A failed update keeps the old `last refreshed` time and records `last error` instead.

## 🧪 Tests

```bash
python3 tests/test_notes_index.py
```

## 📚 Reference

- `references/field-notes.md` — the full "Half the Tokens" field notes, as published
- `references/agents-blurbs.md` — paste-ready `AGENTS.md` rule blocks for the whole Glitch Cat suite, with a shortlist that does not overlap
- `references/build-prompt.md` — the copy-paste build prompt from section 08

---

---

---

## AGENTS.md rule

## Notes index: search it first
Before you answer about my past work, decisions or notes, run:
notes-index --folder <notes-folder> search "distinctive words"
- Use the words the note itself would use. If nothing fits, search once more with different words.
- Results are pointers. Open the file before you state a fact from it.
- If the first line shows an error, or says the index is more than a day old, run: notes-index --folder <notes-folder> update
