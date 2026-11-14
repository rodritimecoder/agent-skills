---
name: jev-decision

description: >
  Calibrated, non-generative decision engine (Glitch Cat Club / Kem Glitch; Reel DdjOqRYNZZi).
  Turns a judgement into one of four typed answers — bool (binary), choice (constrained enum),
  score (scalar 0.0-1.0) or composite (gate + action + quality) — with a probability from the
  h2o-lightning-4b local decision model on :8083, no generated tokens. Use when something must be judged,
  triaged, routed, gated, scored, or classified; for context de-duplication and superseding
  claims; or for any yes/no question about a screenshot. Fast and near-free, so it suits
  high-volume loops.

compatibility: "Requires a decision server on :8083 answering /v1/systemone (noul | choice | score). h2o-lightning-4b is the default occupant, behind the h2o-serve shim; any rotated candidate on the slot is used, and the served model is named in every result. JEV_REQUIRE_H2O=1 restores the hard h2o-only pin."
allowed-tools: "Bash(jev-decision:*) Bash(python3:*) Read Write"
---

> **Model layer:** the server behind this skill is registered in the `model-layer` skill (slot `:8083`) — launcher, weights files, health and quirks. Read it before starting, swapping or debugging the model. If it is down, `jev` starts it via `llama-rig up decision`.

# JEV Decision Engine (`jev-decision`)

A decision model, not a generative one. It never writes prose: it takes facts and a
question, and returns a probability over a closed answer set. That is why a decision
costs milliseconds and a fraction of a cent, and why the same input gives the same
answer.

**The rule:** if the answer is one of *yes/no*, *which one of these*, or *how much
0–1*, ask this — do not ask a chat model.

---

## 🏛️ The Four Primitives

| Primitive | Answer shape | Reach for it when |
| :--- | :--- | :--- |
| **`bool`** | `{decision, confidence, probabilities{true,false}}` | Gating, verifying, superseding, "did X happen?" |
| **`choice`** | `{selection, confidence, probabilities{...}}` | Routing, classifying, picking one of N |
| **`score`** | `{score, probabilities{...}}` | Grading, urgency, quality, risk on `[0,1]` |
| **`composite`** | `{gate, action, quality_score}` | One triage card carrying all three |

`--image PATH` works on every primitive: the vision projector is loaded, so a
question about a screenshot costs the same as a question about text.

---

## 🛠️ CLI

Run from this skill's directory (the harness resolves paths from the skill root).

```bash
JEV="python3 jev_decision.py"

# Is the server up?
$JEV doctor                                  # ONLINE h2o-lightning-4b http://127.0.0.1:8083

# The four primitives — one compact line each
$JEV bool    --context "Postgres was deprecated and replaced by SQLite." \
             --question "Does SQLite supersede Postgres?"
$JEV choice  --context "Tests must run in parallel across 16 cores." \
             --question "Which runner lane?" \
             --options sequential_lane parallel_worker_lane skip_tests
$JEV score   --context "100% coverage, zero failing assertions." \
             --criteria "test coverage and zero failures"
$JEV composite --context "40 new passing tests, clean diff." \
             --question "Can this merge?" --options merge_now request_changes block

# Vision: any primitive accepts a screenshot
$JEV bool --context "Order page screenshot." --question "Is the confirmation banner visible?" \
          --image /tmp/order.png
```

### Two habits that save the caller tokens

```bash
# Facts on disk, not in the transcript
$JEV bool --context-file /tmp/facts.md --question "Does the new config supersede the old one?"

# Many answers in ONE request; result to disk, one line on stdout
$JEV batch /tmp/questions.json --out /tmp/answers.json
```

```json
{"state": "facts every question shares",
 "questions": {
   "ship":   {"type": "bool",   "instructions": "Should this ship?"},
   "target": {"type": "choice", "instructions": "Which button finishes the purchase?",
              "options": ["Back to catalog", "Complete purchase"]},
   "risk":   {"type": "score",  "instructions": "How risky is this?",
              "levels": ["none", "low", "medium", "high"]}}}
```

`--json` prints the structured result. `--out FILE` writes it and prints a pointer,
which keeps stdout to one line. `--context-file` and `batch` keep bulk facts and bulk
answers off the caller's token stream.

**Exit codes:** `0` answered · `2` usage error · `3` `--require-server` and no server.

---

## ⚠️ Gotchas

- **`confidence` is not a probability.** It is the model's concentration on its answer
  (entropy-based), so a 2-way choice can show `confidence 0.31` while the winner holds
  `p=0.82`. Read `probabilities[selection]` when the actual probability matters.
- **The server has 4 slots.** More than four concurrent calls queue; sequential calls
  are bit-identical, concurrent ones differ in the last decimal. Use `batch` instead of
  fanning out.
- **There is a silent fallback.** If the server is unreachable, the CLI answers from a
  keyword heuristic and says so on **stderr** (`source: heuristic_fallback`). Pass
  `--require-server` when a guess is worse than an error.
- **`score` needs numeric levels to weight, named levels to order.** Numeric levels
  (`["0.0","0.5","1.0"]`) are averaged by value; named levels (`["none","low","high"]`)
  map to an expected level index. Both return a scalar in `[0,1]`.
- **`choice` needs at least two options, and `score` 2–10 levels.** The server rejects
  a malformed question with a 422; the CLI validates first and explains what it wanted.
  The wire dialect is `{"type": "noul", "instructions": "…"}` — `bool` + `question` is
  the retired shape that every current server rejects.

---

## 📚 Reference

`references/cli.md` — every flag, the JSON shapes, remote/Tailscale use, and the
`clean-context` recipe for pruning superseded claims.

---

---

---

## AGENTS.md rule

## Decisions: use the calibrated engine
When a question is a judgement (is this true, which option, how good, pass or fail), run:
jev bool --context "<context>" --question "<question>"   # or: choice, score, composite
- Use the returned probability, not your own confidence.
- A boolean needs a decision, not a hedge. If the probability is low, say why.
- The engine never invents facts: give it the context it needs, in the file's own words.
