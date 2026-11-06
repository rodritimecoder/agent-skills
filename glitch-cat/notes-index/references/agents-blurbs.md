# AGENTS.md blurbs — the Glitch Cat suite

Paste-ready rule blocks for `AGENTS.md`, one per skill. Every block is written the way the
["Half the Tokens" artifact](https://claude.ai/artifact/MdwChkFxkCKwwnToGVJXGX) writes its own rule:
imperative, two to five lines, and the **exact command** the agent should run.

They are also mirrored into each skill's own `SKILL.md` under `## AGENTS.md rule`, so a block
travels with its skill even if the suite catalogue is not installed.

---

## 🏛️ Why a shortlist

Most of these skills govern the *same* moment: "the agent is about to look something up, or spend
tokens, or spawn help." Installed together they argue with each other — a rule that says *search the
index* and a rule that says *run the graph* send the agent in two directions, and it will do both,
paying twice.

So: **pick one per group.** The groups below are mutually exclusive by design.

| Group | Skills | Choose one when |
| :--- | :--- | :--- |
| **Retrieval** | `notes-index`, `graph-memory`, `semantic-cache`, `state-compactor` | the question is "where is that thing I wrote" |
| **Multi-agent** | `worktree-harness`, `projects-harness`, `glitch-orchestra`, `agentic-engineering` | the job is too big for one agent |
| **Judgement** | `jev-decision`, `eval-router`, `eval-pipeline` | something must be scored, gated or routed |
| **Verification** | `verification`, `frontend-uat`, `parallel-test-lane` | the work has to be proven, not asserted |
| **Safety** | `guard-hooks` | always safe, never conflicts |
| **Principles** | `kem-thought` | always safe, never conflicts |

### Recommended starting shortlist (5 blocks, no overlap)

1. **`notes-index`** — find things in your notes
2. **`state-compactor`** — keep long sessions from rotting
3. **`guard-hooks`** — never let a destructive command through
4. **`jev-decision`** — decide, don't guess
5. **`kem-thought`** — the principles underneath the rest

Add one from **Multi-agent** when you actually fan out, and one from **Verification** when you
actually ship. Everything else waits until it earns its place.

---

## 📋 The blocks

### `notes-index` — find things in your notes

```markdown
## Notes index: search it first
Before you answer about my past work, decisions or notes, run:
notes-index --folder <notes-folder> search "distinctive words"
- Use the words the note itself would use. If nothing fits, search once more with different words.
- Results are pointers. Open the file before you state a fact from it.
- If the first line shows an error, or says the index is more than a day old, run: notes-index --folder <notes-folder> update
```

*Sharper variant:* add `- If the search found it, don't also grep.`
*Cheaper variant:* `- Results are pointers. Open the file only if the snippet doesn't hold the answer.`
plus `- Before answering, search once more for anything newer on the same topic.`

All four of the artifact's section 09 levers are individually selectable with
`notes-index rule --lever no-grep --lever trust-snippet --lever fewer-results --lever check-newer`.

### `graph-memory` — hybrid graph + RAG over a corpus

```markdown
## Memory: query the graph before you search
When a question is about people, owners, decisions or relationships in this repo's knowledge graph, run:
graph-memory recall "<question>" --hops 2 --top-k 8
- The answer is a pointer to a source line. Quote it exactly, do not paraphrase it.
- If the recall returns nothing, fall back to `graph-memory search "<words>" --table`.
```

### `semantic-cache` — bypass repeat questions

```markdown
## Semantic cache: ask it first
Before sending a question that resembles one already answered, run:
semantic-cache query "<question>"
- On a hit, use the cached answer as-is and say it came from the cache.
- On a miss, answer normally, then `semantic-cache store "<question>" "<verified answer>"`.
- Only store answers you have verified, never a guess.
```

### `state-compactor` — context rot shield

```markdown
## State: read the ledger, not the pile
When you need the current state of a long-running task, run:
cgate outline <file>            # symbols and shape
cgate view <file> --symbol <Name>   # one symbol
- Do not read whole files into context. Slice them.
- The authoritative state is `.agent_state.json` and `STATE.md`; update them one fact per line.
- Never let an old summary overwrite a newer fact. Supersede in place.
```

### `guard-hooks` — destructive command protection

```markdown
## Guardrails
Before running anything destructive, run it through the guard:
python3 <path>/guard_hooks.py check "<command>"
- `rm -rf`, force push, `drop table` and similar are refused by the hook, not by you.
- Protected files (KeepMD, STATE.md, .env, secrets) are never deleted or edited without an explicit instruction.
- If the guard refuses, stop and report. Do not find another way to do it.
```

### `jev-decision` — decide, don't guess

```markdown
## Decisions: use the calibrated engine
When a question is a judgement (is this true, which option, how good, pass or fail), run:
jev bool --context "<context>" --question "<question>"   # or: choice, score, composite
- Use the returned probability, not your own confidence.
- A boolean needs a decision, not a hedge. If the probability is low, say why.
- The engine never invents facts: give it the context it needs, in the file's own words.
```

### `eval-router` — route by complexity

```markdown
## Routing: let the router pick the model
Before answering, classify the request:
eval-router route "<request>"
- Easy requests go to local zero-cost models; hard ones escalate.
- If the shadow verification fails, the router falls back to a frontier model automatically.
- Never route a task that needs a tool call through the free tier without verifying the output.
```

### `eval-pipeline` — step-level gates

```markdown
## Pipeline: tag every step and gate it
When a task has more than one step, tag each step [D] (deterministic), [P] (probabilistic) or [H] (human).
- Serialize every step's output to disk before the next step reads it.
- A [P] step needs a deterministic assertion after it. A gate that cannot fail is not a gate.
- Stop at the first failed gate. Do not compound downstream on an unverified result.
```

### `worktree-harness` — parallel agents, isolated files

```markdown
## Parallel edits: worktrees and file ranges
When more than one agent will edit this repository, run:
worktree-harness start ...
worktree-harness claim --run-id <run> --worker <agent> --file "<path>" --lines "<range>"
- Two agents never write the same file range. Claims are enforced, not trusted.
- Every branch is gated on the project's own tests before it is integrated.
```

### `projects-harness` — multi-agent coordination

```markdown
## Coordination
Route work through the harness, not through ad-hoc messages:
projects-harness route "<question or task>"
- Every worker gets one brief (intent) and one owner instruction (verbatim), and they never mix.
- Memory is one fact per line, capped at 200 lines; supersede in place, never append a duplicate.
- A static rule and a memory entry that clash is a stop-and-ask, not a judgement call.
```

### `glitch-orchestra` — terminal conductor

```markdown
## Conducting
Lead as a conductor, not as a worker:
glitch-orchestra register --id <worker> --task "<task>" --term <tty>
glitch-orchestra complete --id <worker> --summary "<what changed>" --evidence <artifact>
- Dispatch to a dedicated session; do not hold the work in the lead's context.
- A summary is a claim, not evidence. Completion carries the artifact a gate produced.
```

### `agentic-engineering` — the 7-step factory

```markdown
## Software factory
Work moves through the board, not through chat:
agentic kanban add "<task>" --req "<requirement>"
agentic kanban move <card-id> done
- One card, one verifiable requirement. No card without a done condition.
- Gates run as commands (`--lint`, `--test`, `--evidence`); a skipped gate is reported, never passed.
- A fresh-context judge decides whether the work is done; the author does not grade itself.
- `agentic run` stops in review. The human moves the card to done.
```

### `swarm-contract` — goals, scorecards, budget ceiling

```markdown
## Swarm contract
Before spending, write the contract:
swarm init --goal "<hit list>" --budget <dollars> --tokens <n>
swarm check --est-cost <c> --est-tokens <n>
- Every worker returns a scorecard with the schema, not a markdown summary.
- The budget ceiling is enforced in code. If the check says no, stop — do not find another way.
```

### `verification` — hands and eyes

```markdown
## Verify, don't claim
When an agent says a UI change is done, prove it:
verify-app run --pass .verify/pass.json
- "Done" without a tool call is a claim. Open the app on the real viewport first.
- Assert the text AND the request behind it: a healthy screen can hide a failed order.
- A skipped layer is not a pass. Report which questions are still open.
- Keep the check as a command, so the next agent replays it instead of re-improving it.
```

### `frontend-uat` — model-backed browser UAT

```markdown
## Frontend UAT
When a UI change must be proven, drive it:
frontend-uat run --url <url> --intent "<goal>" --expect-text "<assertion>"
- The decision model picks the target from the DOM's indexed clickables; it never guesses coordinates.
- A run without an assertion is not a result. Assert the text or the URL.
```

### `parallel-test-lane` — blast radius contained test runs

```markdown
## Test lanes
Run the suite through the lane planner:
parallel-test-lane run --dir tests/ --lanes 8
- Tests marked serial run alone, in isolation, one at a time.
- Output is buffered per lane; read the aggregated report, not interleaved streams.
- A lane failure is a failure. Do not re-run until it passes.
```

### `kem-thought` — the principles

```markdown
## Principles
- Code decides wherever it can. Red is red.
- The poison sits upstream: fix the source of the bad context, not the symptom.
- Always run the control.
- A skill is instructions the model may follow; a hook is code that ALWAYS runs.
- A gate that cannot fail is not a gate; when a classifier is unsure, it routes to the human, not past it.
- A judge that shares the author's context is not a judge.
```

---

## 🧩 Assembling a file

1. Copy the blocks you want, keep the headings.
2. Replace `<path>` with the real absolute path of the script.
3. One blank line between blocks; the file stays under ~150 lines so it loads in every session cheaply.
4. If two blocks in the same group disagree, you have picked wrong — delete one.
