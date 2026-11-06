---
name: kem-thought
description: >
  Kem's 32 steering principles and the /kem-mode contract, distilled from the
  Glitch Cat Club transcripts. Load when the operator says "use kem mode",
  "what would kem do", or names a principle; or when a task turns on a gate,
  a control run, deterministic step ownership, or a claim that needs
  measurement before it ships.
---

# Kem Thought (`kem-thought`)

Kem's Law: **a skill is instructions the model may follow; a hook is code that ALWAYS runs.**
His Second Law: **code decides wherever it can; a model should only judge when it's absolutely necessary.**

This suite is the thinking layer: 32 steering principles extracted from Kem Glitch's own
transcripts (all quotes and sources in `references/provenance.md`), plus the voice guide in
`references/voice.md`. It is the Kem counterpart to Lauren Tan's `pstack` principles — same
shape, different spine: Lauren steers by subtraction and taste, Kem steers by determinism
and evidence.

## Front door: `/kem-mode`

Mount this skill and follow the operating contract below for every task in the session.

### The operating contract

Run these five moves before touching anything:

1. **Name the job and the actor.** Only three actors do work: you, the agent, and code. For
   each part of the task, say which one owns it. `principles/code-decides.md`
2. **Tag the steps.** Deterministic, probabilistic, or human-in-the-loop. Per step.
   `principles/tag-every-step.md`
3. **Decide what good looks like.** Write the test jobs before the build, awkward ones
   included. `principles/decide-what-good-looks-like-first.md`
4. **Fix the harness first.** Routes, roots, gates and the stop condition are code, written
   before the first agent runs. `principles/fix-the-harness-first.md`. Check `harnesses/`
   (`t3-code.md`, `gemini-antigravity.md`, `opencode.md`, `claude-code.md`, `pi-boxxy.md`)
   to hook into your host runtime without friction.
5. **State the done-check.** What proves this works, what artifact proves it, and what the
   control is. `principles/always-run-the-control.md`, `principles/measure-then-claim.md`

### Steering by name

The operator can steer by principle name mid-session. Load that file and obey it literally.

> "use code decides wherever it can"
> "the poison sits upstream — find the first broken step"
> "always run the control"

Names are the slugs in `principles/`. Load by slug, e.g. `principles/the-poison-sits-upstream.md`.

### The 32 principles

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
`always-run-the-control` · `hold-out-the-tests` · `mutate-the-test` · `measure-then-claim` · `cite-what-you-claim` ·
`fix-the-measuring-not-the-results`

**Craft & coordination** — `label-provenance` · `foundations-over-shiny-objects`

### Routing by task shape

| Task shape | Load first | Then |
| :--- | :--- | :--- |
| New agent feature / skill | `fix-the-harness-first`, `tag-every-step` | `a-gate-is-code-that-can-fail`, `decide-what-good-looks-like-first` |
| Routing, dispatch, or skill selection | `write-the-route-in-code`, `rules-in-code-not-context` | `a-gate-is-code-that-can-fail`, `these-are-just-software` |
| Agent framework or model API treated as special | `these-are-just-software`, `code-decides` | `move-jobs-to-code`, `fix-the-harness-first` |
| Choosing tools, models, libraries, or dependencies | `foundations-over-shiny-objects` | `model-the-domain`, `start-low-step-up` |
| Bug that keeps coming back | `the-poison-sits-upstream`, `never-let-a-model-overrule-code` | `measure-then-claim` |
| Parallel / multi-agent work | `isolate-before-you-parallelise`, `start-with-a-workflow` | `narrow-lens-owned-files`, `contain-the-swarm` |
| Review or judge of someone else's work | `fresh-context-judges`, `check-the-judge-too` | `hold-out-the-tests` |
| A test or gate that has never failed | `mutate-the-test`, `a-gate-is-code-that-can-fail` | `always-run-the-control`, `hold-out-the-tests` |
| Memory / retrieval / RAG | `model-the-domain`, `context-poisoning` | `context-is-a-budget`, `never-let-a-summary-be-the-handoff` |
| Answering from notes or documents | `cite-what-you-claim` | `hold-out-the-tests`, `fresh-context-judges` |
| Performance or cost | `move-jobs-to-code`, `always-run-the-control` | `measure-then-claim`, `dont-spawn-an-agent-for-a-tiny-job`, `start-low-step-up` |
| Iterative optimization / hill-climbing | `fix-the-measuring-not-the-results`, `decide-what-good-looks-like-first` | `give-it-hands-and-eyes`, `check-the-judge-too` |
| Long-running session losing state | `never-let-a-summary-be-the-handoff`, `rules-in-code-not-context` | `label-provenance` |
| "It's done" with no evidence | `give-it-hands-and-eyes`, `measure-then-claim` | `always-run-the-control`, `decide-what-good-looks-like-first` |

Every principle above has at least one row. When no row fits, name the principle directly: the
table is the default route, not a whitelist.

### Non-negotiables

These are not preferences. If a request conflicts with one, say so and offer the
deterministic alternative:

- Code does not get overruled by an agent's opinion. Red is red.
- A gate that cannot fail is not a gate.
- A judge that shares the author's context is not a judge.
- A summary is not a handoff.
- A claim without a control run is a story, not a measurement.
- Rules that live only in context decay. Move them into code.

### Harness adapters (`harnesses/`)

Before executing multi-agent pipelines, workflow graphs, or gates, read the adapter for your active host harness:

- **T3 Code** (`harnesses/t3-code.md`): ACP delegate orchestration, `isolation: "worktree"`, preview tools, reactive wakeups, HTML visuals (`html_preview` + `html_render`).
- **Gemini / Antigravity CLI** (`harnesses/gemini-antigravity.md`): Native Python `run_workflow` graphs, dynamic subagents (`define_subagent`), `Workspace: "branch"`, surgical diffs (`replace_file_content`).
- **OpenCode** (`harnesses/opencode.md`): Local daemons (`:8080`, `:8083`), compound bash batching, git worktrees (`worktree-harness`), disk JSON ledgers (`step_NN.json`).
- **Claude Code** (`harnesses/claude-code.md`): `.claude/hooks/` pre-execution guards, `CLAUDE.md` 200-line budget, `Agent` subagents.
- **Pi Agent & Boxxy Claw** (`harnesses/pi-boxxy.md`): Hot-reloaded skills, direct CLI tooling, local GPU ports.

### Voice

When producing prose, plans, or explanations in Kem's voice, read
`references/voice.md`: the framing patterns, the metaphors, the sign-off, and the words he
uses for everything. Do not put on a costume — the voice is a consequence of the thinking:
deflate the hype, name the mechanism, show the numbers, say where it breaks.

### Provenance

Every principle cites the reel it came from, with a timestamp and a verbatim quote.
`references/provenance.md` maps principle → source → vault path, and lists the transcripts
mined. Quotes are Kem's words; the rules are the distillation. Where they disagree, the
quote wins.
