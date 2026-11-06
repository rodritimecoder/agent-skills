---
name: glitch-orchestra

description: >
  Claude Code mods and terminal conductor architecture for multi-session agent supervision (Glitch Cat Club / Kem Glitch;
  Reel Dd_vZqINEtW), with an experimental alignment-first role workflow from Reel DeKBMCQNRXU. The conductor aligns intent,
  references and specialist panes before dispatching tasks to dedicated child sessions, tracks progress, and triggers completion chimes.

compatibility: "Requires Python 3.10+. No network access needed."
allowed-tools: "Bash(python3:*) Read Write"
---

# Glitch Orchestra (`glitch-orchestra`)

A terminal conductor architecture built on top of **Claude Code Mods** by **Kem Glitch (Glitch Cat Club)** in Reel [`Dd_vZqINEtW`](https://www.instagram.com/reel/Dd_vZqINEtW/). Its experimental alignment-first role workflow is shown in Reel [`DeKBMCQNRXU`](https://www.instagram.com/reel/DeKBMCQNRXU/) and is distinct from the runtime CLI below.

---

## 🏛️ Architecture

Instead of a single agent trying to edit every file sequentially while bloating its prompt context:
1. **The Conductor**: Leads the session, decomposes the job, and coordinates child workers.
2. **Child Terminal Sessions**: Run isolated tasks in dedicated virtual terminals.
3. **Completion Alert**: Emits an audible chime/notification upon batch completion.

### Alignment-first role workflow

Before dispatching work, the conductor gets the team in tune:

1. **Agree on intent**: Ask “Who is it for?” and “What does great mean?” before choosing tasks.
2. **Align the direction**: Discuss how it is made, how it moves, and how it should feel; bring references up front.
3. **Facilitate the Planner phase**: Planning is a responsibility of the conductor, not another model by default.
4. **Assign specialist panes**: The experimental sequence names `frontend` for the world, `sol` for motion, and `astra` for light. Use meeting and status cues to surface overlap before parallel work proceeds.
5. **Compare and test qualitatively**: Keep the prompt the same for a before/after comparison, then judge fit against the agreed audience, intent, and references rather than inventing a numeric score.

The alignment reel shows conductor-led specialist panes; it does not establish direct peer-to-peer messaging. It is an experimental workflow reference, not evidence of JEV decision-model testing.

---

## 🛠️ CLI Quickstart

```bash
ORCHESTRA="python3 /run/media/rodri/AI/skills/glitch-orchestra/glitch_orchestra.py"

# 1. Register a child worker session
$ORCHESTRA register --id worker_01 --task "Refactor authentication middleware" --term tty_01

# 2. Check live conductor status
$ORCHESTRA status

# 3. Mark session complete with the artifact that proves it
$ORCHESTRA complete --id worker_01 \
  --summary "Auth middleware refactored" \
  --evidence .verify/verify.json

# 4. Trigger completion alert
$ORCHESTRA alert --message "All 4 worker tasks successfully completed!"
```

A completion without `--evidence` is recorded as `verified: false` and reported
as `UNVERIFIED`. A path that does not exist is refused. The conductor relays
the proof; it does not invent it.

---

## AGENTS.md rule

## Conducting
Lead as a conductor, not as a worker:
glitch-orchestra register --id <worker> --task "<task>" --term <tty>
glitch-orchestra complete --id <worker> --summary "<what changed>" --evidence <artifact>
- Dispatch to a dedicated session; do not hold the work in the lead's context.
- A summary is a claim, not evidence. Completion carries the artifact a gate produced.
