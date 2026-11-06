# Glitch Cat Skills — Agent Invariants (`glitch-cat/AGENTS.md`)

Governs all AI coding assistants, delegates, and subagents operating on skills inside `glitch-cat/`.

---

## 🏛️ Kem's Prime Laws

1. **A skill is instructions the model may follow; a hook is code that ALWAYS runs.**
2. **Code decides wherever it can; a model should only judge when it's absolutely necessary.**
3. **Never let a model overrule code. Red is red.**
4. **A gate that cannot fail is not a gate.** Always run the negative control (`always-run-the-control`).
5. **A judge that shares the author's context is not a judge.** Use fresh-context unbiased evaluators (`fresh-context-judges`).

---

## 🛠️ Editing & Sync Protocol

- **Source of truth:** All edits MUST happen in `~/src/my-agent-skills/glitch-cat/<skill>/`.
- **Derived views:** Do NOT edit directly inside `~/.gemini/config/skills/`, `~/.pi/agent/skills/`, or OpenCode directories.
- **Publishing:** Run `sync-skills` to propagate locally across harnesses. Run `sync-skills --push` once at the very end of a verified task.
- **Provenance on additions:** Every principle added to `kem-thought` or new Glitch Cat tool MUST trace back to an explicit reel or artifact in `/run/media/rodri/AI/creator-vault/kem_glitch/` with timestamps and verbatim quotes.

---

## 🧭 Skill Routing by Capability

| If the task is... | Use this skill | Invariant |
| :--- | :--- | :--- |
| Steering principles / architectural alignment | `kem-thought` | Load principle by name from `principles/<slug>.md`. |
| Fast typed binary / scoring gates | `jev-decision` | Sub-second, non-generative decisions via `:8083`. |
| Hands-and-eyes browser verification | `verification` / `playwright` | Drive real DOM / CDP; never claim UI works without eyes. |
| Multi-step deterministic / probabilistic pipelines | `eval-pipeline` | Tag every step `[D]`, `[P]`, or `[H]` and serialize `step_NN.json`. |
| Routing to free / local models | `eval-router` | Speculative shadow evaluation with automatic frontier fallback. |
| Blast radius containment / test partitioning | `parallel-test-lane` | Partition sequential vs parallel worker lanes; run mutants. |
| State preservation across long sessions | `state-compactor` | Maintain `.agent_state.json` and `STATE.md` with fact parity. |
| Parallel subagents in git worktrees | `worktree-harness` | Reserve file ranges before write; gate branches on project tests. |
| Swarm governance & ceilings | `swarm-contract` | Immutable token/financial spend ceilings; validate scorecards. |
| Notes search without token rot | `notes-index` | Search SQLite FTS5 database; never recursive grep. |
