---
name: gh-action-subagent

description: >
  Spawn isolated cloud subagents inside GitHub Actions VMs with full Linux shell,
  Git, and headless Chrome CDP browser skills. Use when delegating parallel coding tasks,
  running browser E2E checks in a sandbox, or fixing issues asynchronously via Pull Requests.

compatibility: "Requires network access to GitHub Actions, an authenticated GitHub CLI or GITHUB_TOKEN, and an OpenCode Go token in the repository secrets."
allowed-tools: "Bash(gh:*) Bash(python3:*) Read Write"
---

# GitHub Actions Cloud Subagent Skill

Use this skill to dispatch tasks to ephemeral GitHub Actions runners via a single API call. Each subagent runs in an isolated Ubuntu VM with the `playwright` skill's native client (browser daemon on :9222), the guard hooks, and the OpenCode CLI running the restricted `lane` agent.

## Prerequisites
- GitHub CLI (`gh`) authenticated, OR `GITHUB_TOKEN` exported in the environment.
- Workflow file `.github/workflows/subagent.yml` committed to the repository `main` branch — copy `assets/subagent.yml` from this skill; its `workflow_dispatch` inputs (`task`, `target_branch`, `model`) are exactly what `gh-subagent dispatch` sends.
- Repository secret `OPENCODE_GO_TOKEN` added in GitHub repo settings. The token is the OpenCode Go credential; the workflow refuses to start without it, before it creates a branch.

### Which models this runner can drive

The Go catalog serves three shapes, and the CLI speaks all of them: OpenAI `chat/completions` for DeepSeek, GLM, Kimi and MiMo; the Anthropic shape for Claude Haiku, Qwen and MiniMax M3; the Responses shape for Grok and the GPT Luna pair. That is the main reason the CLI replaced the hand-written loop, which could only call the first group.

### The runner is the OpenCode CLI

`opencode run --standalone --auto --agent lane` drives the lane. The hand-written tool loop that lived here is gone: the CLI installs in one step, speaks every protocol, and enforces permissions the loop could only pattern-match.

| | hand-written loop (removed) | `opencode run` |
| :--- | :--- | :--- |
| Tools | 5 hand-written | write, edit, patch, read, glob, grep, shell, code-mode, MCP |
| Protocols | OpenAI shape only | all of them, so Claude/Qwen/Grok become usable |
| Accounting | none | per-step cost and tokens in `--format json` |
| Safety | string matching on commands | **permission rules in the agent file** |

The safety claim is the one that matters, and it is a capability boundary rather than a filter. `assets/agents/lane.md` denies `git push*`, `rm -rf*`, `sudo*` and `git reset --hard*`, so tests run and pushes do not. Verified: `echo allowed > ok.txt` completed, `git push origin main` came back `status: error, denied`, with `--auto` on.


### Which model, now that it has been measured

The catalog has 30 ids; eight were actually driven today. Cost is from the Go
console, outcome is whether the lane produced its files.

| Job | Model | Evidence |
| :--- | :--- | :--- |
| **Tool loop, lanes, multi-file edits** | `deepseek-v4.1-flash` | 10/10 lanes completed; $1.09 for 822 requests (~$0.0013 each); 34,670 req/5h, $80 pool |
| **One-shot judgement** (read a diff, score an audit) | `deepseek-v4-pro` | the only pro that finished a multi-file edit; $0.0041/request; 1,050 req/5h, $15 pool |
| **Brief-sensitive, not unusable** | `kimi-k3.1-pro`, `glm-5.3`, `mimo-*`, `minimax-m3.1-flash` | each stalled in prose on a long brief. A control run proved the brief was the variable: `kimi-k3.1-pro` completed the identical task in 10 turns once the brief opened with "your first action should be write_file" |

### The brief is a parameter

Every stall followed the same shape: a long brief that read like a specification, after which the model composed a plan. Every completion followed the opposite: the brief named the first `write_file`, then the test, then the run. Two consequences worth keeping:

- **Open the brief with the first action.** "Your first action should be write_file X" is worth more than another paragraph of context.
- **One run is not evidence.** A model that stalled twice and then completed the same task under a corrected brief was never "broken" — the brief was. Run the control before writing a verdict into a skill.

Sizing and drift live in one script, which is also the only thing that knows the
whole catalog:

```bash
go-roster --check                 # is the plan connected, and does the roster match it
go-roster --verify                # exit 1 if a curated id is no longer served
go-roster --plan "deepseek-v4.1-flash:6,deepseek-v4-pro:2"
go-roster --tier 2 --json
```

## Commands

### 1. Dispatch a New Cloud Subagent
```bash
gh-subagent dispatch \
  --task "Start dev server, use CDP skill to inspect /login, fix the layout bug, and open a PR" \
  --branch "agent/fix-login" \
  --model "deepseek-v4.1-flash"
```

### 2. List Active / Recent Cloud Subagents
```bash
gh-subagent status
```

### 3. Fetch Logs / Output of a Subagent Run
```bash
gh-subagent logs <run_id>
```

## Parallel Delegation Pattern
You can dispatch up to 5 subagents concurrently:
1. Dispatch each independent subtask on its own `--branch` (`agent/task-1`, `agent/task-2`).
2. Poll status with `subagent_ctl.sh status`.
3. Inspect the created Pull Requests or workflow artifacts (screenshots and logs) once completed.
