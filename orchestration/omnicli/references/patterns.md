# Patterns — what a decision model is actually good for

The interface is `(state, question, options) → probability per option`. That buys three things a normal
LLM call does not give you cheaply: **one forward pass regardless of option count**, **a real
probability** instead of a vibe, and **zero generated tokens** (no formatting drift, no prompt
injection through the output channel).

## Recipes

### 1. Triage / routing — pick the queue
State is the ticket; options are your queues. Works well; the model is trained on exactly this shape
(Banking77-style intents hit 9/10 on a hand-built 10-item set, 0.96+ on clear-cut cases).

```bash
python3 $CLI "$(cat ticket.txt)" "Which queue does this ticket belong in?" \
  '{"billing":"invoices, refunds, charges","tech":"outages, bugs, access","sales":"pricing, plans"}'
```

Then act on the label. Gate on `confidence` — below ~0.5 means the ticket is ambiguous, route to
`human` rather than picking the argmax.

### 2. Gating — should the agent/tool proceed at all?
`noul` is the cheapest safety check you can run before an irreversible action: destructive shell
command, sending mail, spending money, publishing.

```bash
python3 $CLI "tool: rm -rf /home/rodri/project\nargs: ['/home/rodri/project']" \
  "Is this destructive and irreversible?" --threshold 0.9
```

Treat the probability as a score to **log and trend**, not as a guarantee — it is a classifier, not a
sandbox. Keep the real permission checks; use this as a second opinion that is cheap enough to run on
every call.

### 3. Sentiment / severity / urgency as a number
`score` gives an expected level, so "how bad" becomes sortable and thresholdable without brittle regex.

```bash
python3 $CLI "$transcript" "How escalated is this conversation?" \
  '["calm","annoyed","frustrated","angry","abusive"]'
```

### 4. Ranking when you already have the candidates
Ask for the ordering you want as the options. Useful for "which of these 5 commit messages is the
real one" and best-of-N selection with a cheap model instead of an expensive one.

### 5. Labelling at volume
Loop over files, one batch per document (`--batch` keeps the state prefilled). A 4B classifier doing
100 short documents is minutes of GPU, and the output is JSON you can join against.

### 6. Self-check loops
Ask a small model a yes/no question about your *own* output and gate on it — "does this answer contain
a commitment we did not authorise?", "is this summary faithful to the source?", "is this JSON valid for
the downstream parser?". Cheap enough to run every time; low-confidence results go back for repair.

### 7. Consistency probes
Ask the same question with the options shuffled and compare. A model that flips its argmax when the
labels move is not deciding, it is pattern-matching positionally — that difference is invisible if you
only look at one run.

## Failure modes to expect

| symptom | cause | what to do |
|---|---|---|
| flat distribution (confidence ≈ 0) | options overlap, or the state does not contain the deciding fact | rewrite the options to be mutually exclusive; add the evidence to the state |
| confident and wrong | the rule is arithmetic/date-based and it has no reasoning phase | compute it in code; use the model for routing/labelling only |
| high `p` on a plausible-sounding label | hallucinated option semantics | paste real examples in the option descriptions |
| degrades with very long states | 4-bit quantisation noise grows with context | keep the state tight, or use the Q5/BF16 quant |
| wrong for non-English text | English-first training | translate upstream, or use a multilingual model |

## Two backends, one shape

`--model jpt` (JPT-4B, 4B, llama.cpp, ~150 ms, 32k ctx, starts on demand) and `--model jev`
(Jev-Style-2B, ~60 ms, 25.6k ctx, no server but reloads per call). Identical JSON output, so the choice
never changes calling code. Public benchmarks: JPT-4B scores 0.879 on JevBench v1.4 public and 43.04
on Decision Index 0.2.1 — both ahead of every other 4B entrant listed, and behind only the closed Jev
API overall.