# Sources — `glitch-orchestra`

**Two reels. One architecture, one experimental workflow.**

## The sources

| | Architecture reel | Alignment reel |
| :--- | :--- | :--- |
| Creator | Kem Glitch (`kem_glitch`, Glitch Cat Club) | Kem Glitch (`kem_glitch`, Glitch Cat Club) |
| Instagram reel | [`Dd_vZqINEtW`](https://www.instagram.com/reel/Dd_vZqINEtW/) | [`DeKBMCQNRXU`](https://www.instagram.com/reel/DeKBMCQNRXU/) |
| Vault entry | `kem_glitch/2026-10-17_claude_code_mods_and_glitch_orchestra/` | `kem_glitch/2026-10-06_glitch_orchestra_alignment_first/` |
| Uploaded | 2026-10-02 | 2026-10-06 |
| Mined | 2026-10-17 | 2026-11-02 |
| Media | `source.mp4`, `transcript.md`, 30 frames | `source.mp4`, `transcript.md`, 41 frames |
| Verified | 2026-11-02 — media byte-identical; fresh ASR vs transcript **0.875** | 2026-11-02 — media byte-identical; fresh ASR vs transcript **0.955** |
| Caption | *"Claude Mods came out and it's super cool!"* | *"Just having fun 🫶 - testing the experimental alignment system for glitch orch."* |

The alignment reel pairs with the architecture reel and with
[`DeEyZPEtkyH`](https://www.instagram.com/reel/DeEyZPEtkyH/) (conductor rotation update). The
current orchestration page lives at `pages/kem-orchestra/`.

## Shown in the architecture reel

Excerpts from `transcript.md`; ellipses mark omitted words. The ASR misspells "Claude" as
"clawed"; the quotes are left exactly as transcribed.

| Claim | Quote | Time |
| :--- | :--- | :---: |
| Mods reshape Claude Code itself — live panels, commands, behaviour in the terminal | "They let you reshape Claude code itself, like your own live panels, commands and behavior right inside the terminal." | 00:00 |
| Orchestra is built on his own orchestration experience, **not** stacked on the Mods API | "I built Glitch Orchestra where the session becomes the conductor [UM] it's built on everything I've learned really, running my own orchestration." | 00:00 |
| A harness spinning up its own sessions, each in its own terminal | "It's an entire kind of agentic harness. It spins up its own cloud sessions, each in their own terminal" | 00:25 |
| State on a visible Kanban board, conductor manages its own context resets | "manages the conductor's own context for resets and tracks the whole state on a visible Kanban board and much, much, much more." | 00:25 |
| A preview, not a release | "It's experimental, but it's already working great, and I can't wait to share it with you all soon." | 00:42 |

## Shown in the alignment reel

| Claim | Quote | Time |
| :--- | :--- | :---: |
| Intent is the interface between human and AI | "Intent is really how to work with AI." | 00:51 |
| An alignment phase runs before anything is built | "Orchestra now starts with this experimental alignment phase before any single thing is built." | 00:51 |
| References are hunted up front, as the alignment tool | "It hunts for references all up front using my AI design methodology because references are the best and most powerful tool for alignment when it comes to design." | 00:51 |
| More models are not the answer | "More models are never the answer. They all just kind of converge, especially with knowledge and design work." | 00:31 |
| The differentiator is his design stack and taste | "Could I take my own design stack, my own taste and build it into orchestra?" | 00:31 |
| Same prompt, before and after; still experimental | "Here are some befores and here are some afters, all with the same prompt. Now, sure, it's still experimental" | 01:09 |

On-screen only — no spoken line, checked against captured frames:

| Shown | Frames |
| :--- | :--- |
| The intent questions: "What is this for? / Who is it for? / What does great mean?" and "1. How is it made? 2. How does it move? 3. How should it feel?" | 000022, 000024 |
| Role cues: `frontend` "the world", `sol` "the motion", `astra` "the light" | 000010, 000028, 000039 |

## What the reels do not establish

- **Pane view ≠ peer-to-peer messaging.** The alignment reel shows workers as separate panes
  with meeting and status cues. That supports a shared orchestration view; it does not show
  whether workers message each other directly or the conductor relays every message.
- **The alignment reel is not JEV evidence.** It shows a design/role workflow, not a
  decision-model test.
- **The `planner` role is inferred.** The reel does not visibly name a separate planner agent;
  the visible conductor currently leads that phase. The planner/conductor split is our useful
  boundary, not his claim.

## Modeled by this skill

| Choice | Why it is not attributed to the reels |
| :--- | :--- |
| The CLI surface (`register --term`, chime behaviour, session bookkeeping) | Implementation shape for agents; the reels show a live demo, not a CLI. |
| `Completion Alert` as an audible chime | The reels show a completion cue; the exact mechanism is ours. |
| The alignment-first workflow as a numbered procedure | Distilled from the reel's questions and role cues, then ordered by us. |
| The `.kanban/` path and stream-event vocabulary | Appears in our diagram; the reel shows only a board view. |

## Attribution history

`DeKBMCQNRXU` was previously credited to `frontend-uat`. That was wrong: the URL resolves to
this alignment reel, and the `frontend-uat` attribution was retracted on 2026-11-02. The
`frontend-uat` capture is now vaulted without a reel claim. See
[`../frontend-uat/SOURCES.md`](../frontend-uat/SOURCES.md).

## Rule

If a claim about Kem's method is not in a "Shown" table, it is modeled. Do not present it as
his.
