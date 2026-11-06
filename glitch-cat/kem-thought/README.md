# 🐱 Kem Thought (`kem-thought`)

Kem Glitch's **thought skills** — 32 steering principles distilled from the Glitch Cat Club
transcripts, plus the `/kem-mode` front door that dispatches them.

Lineage: Lauren Tan's `pstack` packages 24 principles as skills and routes them from
`/poteto-mode`. This is the same shape, a different spine. Lauren steers by subtraction and
taste (*subtract before you add*, *minimize reader load*). Kem steers by determinism and
evidence (*code decides wherever it can*, *always run the control*, *the poison sits
upstream*). Both are "thought skills": named principles you steer an agent by.

## Layout

```
kem-thought/
├── SKILL.md                  # /kem-mode — dispatcher, contract, routing table
├── principles/               # 32 principles, one file each
│   ├── code-decides.md
│   ├── ...
└── references/
    ├── voice.md              # how Kem speaks: structure, metaphors, sign-off
    └── provenance.md         # principle → reel → timestamp → vault entry
```

## The principles

**The law** — `code-decides` · `move-jobs-to-code` · `these-are-just-software`

**Harness & gates** — `fix-the-harness-first` · `tag-every-step` ·
`a-gate-is-code-that-can-fail` · `never-let-a-model-overrule-code` ·
`rules-in-code-not-context` · `write-the-route-in-code` · `start-low-step-up`

**Parallelism & state** — `isolate-before-you-parallelise` · `fresh-context-judges` ·
`check-the-judge-too` · `narrow-lens-owned-files` ·
`dont-spawn-an-agent-for-a-tiny-job` · `contain-the-swarm` · `start-with-a-workflow`

**Context & memory** — `context-is-a-budget` · `never-let-a-summary-be-the-handoff` ·
`context-poisoning` · `the-poison-sits-upstream` · `model-the-domain`

**Evidence** — `decide-what-good-looks-like-first` · `give-it-hands-and-eyes` ·
`always-run-the-control` · `hold-out-the-tests` · `mutate-the-test` · `measure-then-claim` ·
`cite-what-you-claim` · `fix-the-measuring-not-the-results`

**Craft & coordination** — `label-provenance` · `foundations-over-shiny-objects`

## Use

```
/kem-mode
```

Or steer mid-session by name:

```
use code decides wherever it can
the poison sits upstream — find the first broken step
always run the control
```

Each principle file is short enough to load on demand. `SKILL.md` holds the routing table
for picking them by task shape: all 32 have at least one row, and the table is a default
route rather than a whitelist, so naming a principle always works.

## How this was derived

1. The 25 mined vault entries under `/run/media/rodri/AI/creator-vault/kem_glitch/` were
   read in full (transcript + analysis notes).
2. Doctrine was extracted per talk: candidate rules, metaphors, anti-patterns, vocabulary,
   verbal tics.
3. Candidates were merged across talks by frequency and by whether the point was
   load-bearing in Kem's own argument.
4. Each surviving rule was rewritten as an imperative with a mechanism, and pinned to a
   verbatim quote with a timestamp.

Full mapping in `references/provenance.md`. Quotes are Kem's; the rules are the
distillation. Where the two disagree, the quote wins.

## Extending it

Seven catalogued reels are not yet mined
(`creator-vault/kem_glitch/REELS_LEDGER.md`), and his YouTube mirror
(`@glitchcatclub/shorts`) lags Instagram. When a new talk is mined:

1. Add the vault entry to the "Talks mined" table.
2. Add or revise principles — prefer revising an existing rule over stacking a new one.
3. Update the principle → source table with reel ID and timestamp.
4. Keep the file shape: **Rule / Why / In practice / Kem quote.**
5. Re-run `sync-skills --push`.

Guard rail: no principle without a quote from a transcript. If it cannot be quoted, it is
not Kem's thinking yet — it is a guess, and guesses belong in a different file.

---

*Kem at Glitch Cat Club signing out.*
