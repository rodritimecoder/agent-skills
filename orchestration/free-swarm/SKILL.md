---
name: free-swarm

description: >
  Nine zero-cost OpenCode models, each published as a named read-only subagent so a session
  can fan a task out to all of them at once. Use when a question deserves several independent
  answers, when one model's blind spot should be covered by another, for a second opinion, a
  panel or ensemble of different models, majority votes, long-context reads, or cheap parallel
  review — while the main session keeps its own model. Not for coordinating file edits across
  agents (worktree-harness) or for choosing the cheapest model for one prompt (eval-router).

compatibility: "OpenCode v2 with the opencode provider. No API keys, no GPU, no network beyond OpenCode's own free tier."
allowed-tools: "Bash(python3:*) Bash(opencode:*) Read"
---

# free-swarm

One session, many models, no bill. Each free model on the `opencode` provider is
installed as a `mode: subagent` agent with its own model binding, so the parent
session can launch any of them — or all of them — without changing its own model.

They are deliberately **read-only**: `edit`, `shell`, `subagent` and `question`
are denied. That is what makes running nine of them at once safe, and it is why
they answer instead of acting.

## Roster

| Agent | Model | Context / output | Use it for |
|---|---|---|---|
| `free-flint` | `flint-40b-free` | 262k / 65k | one long file, sustained reasoning |
| `free-minimax` | `minimax-m3.1-flash-free` | 1M / 512k | the biggest single writer |
| `free-vl` | `nemotron-3.5-super-vl-free` | 1M / 131k | screenshots and images |
| `free-lightning` | `nemotron-3.5-lightning-free` | 262k / 262k | fastest of the roster |
| `free-ultra` | `nemotron-3-ultra-free` | 1M / 128k | depth when speed does not matter |
| `free-beam` | `beam-free` | 1M / 131k | long-context reading |
| `free-mimo` | `mimo-v2.6-flash-free` | 200k / 32k | quick short answers |
| `free-glm` | `glm-5.3-flash-free` | 200k / 32k | code and structured review |
| `free-pickle` | `big-pickle` | 200k / 32k | generalist second opinion |

## Install

```bash
python3 scripts/install.py            # symlink agents into ~/.config/opencode/agents
python3 scripts/install.py --check    # every link present?
opencode api get /api/agent | grep -o '"id":"free-[^"]*"'
```

The installer only ever touches `free-*.md`, and it symlinks rather than copies,
so editing `agents/free-glm.md` in the checkout changes what OpenCode loads.
Remove them again with `--remove`.

## Two ways to call it

### In a session — native subagents

Launch several in one turn, each with `background: true`, and they run
concurrently while the parent keeps working:

```text
subagent(agent: "free-glm",      description: "review",  prompt: "<task>", background: true)
subagent(agent: "free-minimax",  description: "rewrite", prompt: "<task>", background: true)
subagent(agent: "free-lightning",description: "check",   prompt: "<task>", background: true)
```

Use this for two to four workers you want to talk to, follow up with, or whose
answers you will read in the conversation. `sessionID` comes back with each
result, so a worker can be continued instead of restarted.

### Outside the loop — deterministic fan-out

```bash
python3 scripts/fanout.py --models glm,minimax,flint "Which of these two APIs is simpler to extend?"
python3 scripts/fanout.py --file src/deck.py "Find correctness bugs. Severity order."
python3 scripts/fanout.py --check
```

Every worker gets the identical prompt and its own fresh context. Answers land in
`<out>/<agent>.md`, metadata in `summary.json` (status, seconds, characters,
output tokens, error), and only a one-line-per-agent table reaches the caller.
Default `--out` is `/tmp/opencode/free-swarm/<timestamp>`; `--strict` exits 1
unless every worker answered.

Use this when you want the full text on disk instead of in context, more than
four workers, or a reproducible run you can diff.

## They inherit MCP servers

Subagents are not sandboxed away from MCP: every worker sees the same servers the
parent session does. With `rea` registered, a fan-out can put several models on
one binary from different angles — one reads build info, one traces strings, one
reviews the decompiled function — and each answer carries REA's own Evidence.

Verified 2026-10-22: `free-glm` called `rea.inspect_go_binary` on `/usr/bin/gh`
and returned `go1.25.0`, `github.com/cli/cli/v2/cmd/gh`, and the same sha256 the
parent session got from the same tool.

## Getting something out of the disagreement

- **Compare** — same prompt everywhere, then diff the answers. Agreement across
  different families is the strongest signal this skill produces; a lone answer
  that contradicts five others is worth reading, not trusting.
- **Vote** — three workers, take the majority; use `free-glm` and `free-beam` as
  the two that are least likely to share the same failure.
- **Route by size** — a 300k-token dump goes to `free-minimax`, `free-beam` or
  `free-vl` (1M context), not to the 200k models.
- **Cross-examine** — one worker drafts, attach its draft with `--file` and send
  it to three others to attack. Cheaper and blunter than one model reviewing
  itself.

## Failure policy

- `error.type == "provider.quota"` with HTTP 402 means the endpoint is down, not
  that the task is wrong. Skip it, say which model was skipped, retry at most once.
- One slow worker sets the wall time of the whole batch. Drop it with `--models`
  rather than waiting; `free-ultra` is the usual culprit.
- Free tiers share upstream rate limits. Do not wrap fan-out in a per-file loop;
  batch the files into one prompt instead.

## Measured

2026-10-22, this machine, `opencode` v2.1.1:

| Check | Result |
|---|---|
| `--check` across the roster | 9/9 answered `READY` in 2.1–3.8 s each |
| 3 workers, real task, parallel | 20–82 s; wall time was the slowest worker, not the sum |
| 8 workers, parallel, cold | 15.6 s wall |
| custom agent binding | `/api/agent` reports `model: opencode/…` per agent, and both `free-glm` and `free-lightning` returned their probe text from real subagent calls |

Two things worth re-checking after an OpenCode upgrade:

- If `/api/agent` stops showing `model` on `free-*`, the subagents silently fall
  back to the parent's model.
- Newly linked agents appeared in `/api/agent` a few seconds after
  `install.py` — no service restart, and therefore no risk of killing a live
  session.
