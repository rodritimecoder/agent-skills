---
name: reply-meter

description: >
  Deterministic output scorer for agent replies, modelled on the STE field test:
  measure replies, not vibes. Returns words, sentences, longest sentence, faults
  per 100 words and a line-located list of named faults (sentence over 25 words,
  banned modals, contractions, semicolons, Latin abbreviations, slop words,
  -ing clause openers, check/verify/confirm rotation, em dashes). Regex only, no
  model, no network. Wire it to a Stop hook and print the failures at the top of
  the next turn.

compatibility: "Python 3.8+. No dependencies, no network, no model, no API key."
allowed-tools: "Bash(python3:*) Read Write"
---

# Reply Meter (`reply-meter`)

A field test for prose. The subject is not a paragraph someone wrote once — it
is the reply your agent is about to send. The meter counts the words, splits
the sentences, runs eleven regex rules, and returns every fault with the line
that carries it.

**A rule is a regex. There is no judge model, no score from a language model,
and no network call.** The same text scores the same on every machine, so a
fault is something you can fix rather than something you can argue with.

---

## 🛠️ The One Command

```bash
python3 scripts/meter.py --file reply.md
```

```bash
python3 scripts/meter.py --file reply.md --json     # machine-readable score
python3 scripts/meter.py --file - < reply.md        # read the reply from stdin
```

```
words 63  sentences 4  longest 20w  faults/100w 34.9
  L1    banned_modal           We should leverage a robust, seamless p…
  L1    slop_word              We should leverage a robust, seamless pipeline t…
  L1    contraction            …across the entire landscape. It's crucial that we delve into th…
  L1    semicolon              …e into the tapestry of options; the team can't ignore this. B…
  L1    ing_clause_start       …; the team can't ignore this. Building on that, we might streamline…
  L1    em_dash                …firm the queue before we ship — which is absolutely vital.
  … 16 more faults, all on line 1
```

`score(text)` is the same engine in-process:

```python
from meter import score
score("Open the config file and set the port to 8080.")
# {"words": 10, "sentences": 1, "longest_sentence": 10,
#  "faults_per_100w": 0.0, "faults": []}
```

| Key | Meaning |
| :--- | :--- |
| `words` | alphanumeric tokens |
| `sentences` | sentences, split on terminal punctuation and newlines |
| `longest_sentence` | word count of the longest sentence (the >25 check) |
| `faults_per_100w` | `faults * 100 / words`, rounded to one decimal |
| `faults` | `[{rule, line, excerpt}]`, sorted by line |

---

## 📏 The Rules

| Rule | Fires on |
| :--- | :--- |
| `sentence_over_25_words` | any sentence longer than 25 words |
| `banned_modal` | `should`, `must`, `might` in instructions |
| `contraction` | `don't`, `can't`, `it's`, `we'll`, `I've`, `let's` … |
| `semicolon` | `;` anywhere |
| `latin_abbrev` | `e.g.`, `i.e.`, `etc.` |
| `slop_word` | 30 words (`leverage`, `robust`, `seamless`, `delve`, `unlock`, `streamline`, `holistic`, `crucial`, `myriad` …) |
| `ing_clause_start` | a sentence opening with an `-ing` clause: `Building on that, …` |
| `synonym_rotation` | two or more of `check` / `verify` / `confirm` / `validate` in one text |
| `em_dash` | `—`, or a spaced `--` |
| `exclamation_mark` | `!` |
| `summary_boilerplate` | `In summary`, `In conclusion`, `To sum up`, `All in all` |

The rules as a 20-line paste-in card, written as instructions for the writer,
live in [`scripts/card.md`](scripts/card.md). Drop it at the top of a system
prompt and the reply arrives closer to clean before the meter ever runs.

Exit code is `0` whether or not faults are found — the meter reports, it never
blocks a turn. A missing file is `2`.

---

## 🔁 How It Feeds the Next Prompt

The point is not the score. The point is that the next turn starts with the
failures instead of the model's opinion of itself.

A Stop hook writes the assistant's last message to a file, runs the meter, and
the next turn opens with the fault block:

```bash
# Stop hook: capture, then measure. Never block the turn.
python3 scripts/meter.py --file last_reply.md | head -20 >> .reply-meter.log
```

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command",
        "command": "python3 ~/src/my-agent-skills/glitch-cat/reply-meter/scripts/meter.py --file last_reply.md --json > .reply-meter.json" } ] }
    ]
  }
}
```

```
REPLY METER — fix these before replying (34.9 faults/100w):
  L3 banned_modal     "should" → imperative
  L7 semicolon        split into two sentences
  L9 slop_word        "streamline" → name the action
```

Then the rewrite loop: reply → meter → prepend the failures → rewrite → meter
again. Stop at zero faults, or at the faults you can name a reason for. The
loop is short because the output is a list, not a critique.

---

## 🚫 Where It Does Not Fit

- **Creative writing.** Fiction, dialogue, marketing copy, speeches and any
  deliberate voice. The meter would flag rhythm as a fault: a 30-word sentence
  can be the best sentence in a story, and an em dash can be the point.
- **Non-English text.** Every rule is an English regex.
- **Code, logs and quoted output.** Measure the prose around them, not them.
- **Truth.** The meter measures form. A zero score means clean writing, not a
  correct answer, and it never replaces a test.

If a rule fires on prose that must keep that shape, say so in one line and
move on. The meter is a checklist, not a veto.

---

## 🧪 Tests

```bash
python3 tests/test_meter.py
```

Stdlib `unittest`, no network. Asserts that a clean paragraph scores zero
faults, that a slop-heavy paragraph trips its named rules, and that
`faults_per_100w` stays proportional as the reply grows.

---

## AGENTS.md rule

```markdown
## Reply meter
- Before sending a technical reply, run:
  `python3 ~/src/my-agent-skills/glitch-cat/reply-meter/scripts/meter.py --file <reply>`
- Print the faults at the top of the next turn, then rewrite until they clear.
- Never meter creative writing, code, logs or quoted output.
```
