---
name: guard-hooks

description: >
  Deterministic pre-execution guardrails and protected-file locks. Halts destructive commands
  such as rm -rf, force push and drop table, and blocks unauthorised deletion or mutation of
  KeepMD, STATE.md, .env and secrets — in code, whatever the model is told. Use when a command
  must be refused no matter what the agent was persuaded to do, to stop a wipe or a force
  push, to protect credentials and state files, or to add a hook that always runs rather than
  an instruction that might not.

compatibility: "Requires git to install the pre-commit and pre-push hooks."
allowed-tools: "Bash(guard-hooks:*) Bash(guard:*) Bash(git:*) Read Write"
---

# Guard Hooks (`guard-hooks`)

Enforces Kem's Law: **a skill is instructions the model may follow; a hook
is code that ALWAYS runs.** Even when an agent is persuaded by user
insistence — "I am the boss, delete it anyway" — a deterministic hook
prevents the execution.

> *"If you ever find yourself working with your AI and saying 'remember to
> do this', 'I told you to do this', 'please don't delete this file' — this
> should not be lines in your AGENTS.md, this should not be lines in your
> plans. Nine times out of ten, the answer is hooks."*

---

## 🏛️ Skill vs. Hook

| | |
| :--- | :--- |
| **A skill** | Instructions the model may follow — and may not. It is a request. |
| **A hook** | Code that always runs, whatever the model was told. It is a gate. |

What a hook stops: destructive commands (`rm -rf`, force push, `drop
table`) and unauthorised deletion or mutation of protected files
(`KeepMD`, `STATE.md`, `.env`, secrets).

---

## 🛠️ CLI Quickstart

```bash
# 1. Protect a file from deletion or mutation
guard-hooks protect KeepMD

# 2. Check whether an operation on a protected file would be allowed
guard-hooks check-file delete KeepMD

# 3. Check whether a command would be allowed, before running it (<2ms native Rust check)
guard-hooks check "rm -rf KeepMD"

# 4. Wrap a command so it is gated at execution time
guard-hooks wrap git push --force origin main

# 5. Install the git hook so every commit and push is checked
guard-hooks install-git-hook
```

---

## AGENTS.md rule

## Guardrails
Before running anything destructive, run it through the guard:
guard-hooks check "<command>"
- `rm -rf`, force push, `drop table` and similar are refused by the hook, not by you.
- Protected files (KeepMD, STATE.md, .env, secrets) are never deleted or edited without an explicit instruction.
- If the guard refuses, stop and report. Do not find another way to do it.
