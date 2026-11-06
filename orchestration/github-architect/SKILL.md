---
name: github-architect

description: >
  Synchronize, audit, and bootstrap GitHub repositories across a fleet of
  machines. Disciplined git-sync protocol (Look, Guard, Commit, Gate, Pull,
  Push, Report), secret and blob shielding, and zero-drive workstation
  onboarding. Use when committing or pushing work, syncing repositories
  between machines, making a repo private, shielding secrets before a push, or
  bootstrapping a fresh workstation from GitHub.

compatibility: "Requires git and an authenticated GitHub CLI."
allowed-tools: "Bash(git:*) Bash(gh:*) Bash(github-architect:*) Read Write"
---

# GitHub Architect (`github-architect`)

Turns local workspaces into clean, secret-shielded GitHub repositories,
synchronizes a fleet of repositories across machines, and bootstraps a whole
agent workstation from GitHub with no physical drive. Repositories it creates
are **strictly private** by default.

---

## 🏛️ The Git-Sync Protocol

| Stage | What it does | What it prevents |
| :--- | :--- | :--- |
| **Look** | Validates branch, upstream tracking, rebase/merge locks, uncommitted changes | Pushing from a broken state |
| **Guard** | Scans dirty files for secret patterns (`ghp_*`, `sk-*`, `AIza*`, private keys, `.env`) and blocks files over 50 MB | Leaking a token, or a rejected push |
| **Commit** | Stages only validated files, explicitly — never a blanket `git add -A` | Sweeping an unrelated file into the commit |
| **Gate** | Detects and runs the project's own quality gate (`npm test`, `pytest`, `cargo test`, `go test`) | Pushing code that does not pass |
| **Pull** | Safe merge pull (`--no-rebase`), preserving local commit topology | Rewriting published history |
| **Push** | Pushes upstream, confirming before touching a protected default branch (`main`/`master`); `-y` overrides | Force-pushing over someone else's work |
| **Report** | Emits a 5-line receipt: commits, pull/push status, files left out | Not knowing what actually happened |

### Commit messages

`-m` is the description, and how it is used depends on how you write it:

| You write | The commit becomes |
| :--- | :--- |
| `type(scopes): what changed`, then body paragraphs | your message, verbatim |
| `type(scopes): what changed` alone | your header, then a generated file manifest |
| plain prose | diff-derived subject, your prose underneath |
| nothing | diff-derived subject, then a generated file manifest |

**Every commit carries a body.** A subject is a receipt; the body is the
description. When you do not write one, the manifest names every staged path
with its delta, so `git log` answers "which files" without `--stat`. This is
enforced, not requested: `guarded-commit` refuses to write a bodyless message,
and the push gate refuses to publish a bodyless commit.

The header form is the one to use, because the subject is what `git log
--oneline` shows and it should say what changed:

```
fix(window,terminal,command-palette): guard the palette against a stale index

Strip apostrophes and treat hyphens, underscores and dots as spaces while
normalizing queries, so typing "whats new" matches "What's New".
```

Name components in the scope, not file paths; comma-separate several with no
spaces. One prose paragraph per concern, no bullets, no diffstat, no manifest —
`git show --stat` already answers "which files". The manifest exists only for
commits you did not describe yourself. The full standard, with a worked
example, is `references/commit-messages.md`.

`-m` is what a person (or an agent) should use whenever the change has an intent a
diff cannot express:

```bash
git-sync -m "refactor(github-architect): derive commit subjects from the diff"
sync-skills --push -m "feat(kem-thought): add the scribe principle"
```

Timestamps are not written into the subject. The commit object already stores
one (`git log --format=%cI`), so a stamped subject duplicates metadata and
leaves every entry identical.

---

## 🛠️ CLI Quickstart

```bash
# 1. Disciplined branch synchronization
git-sync [-m "commit message"] [-y] [--dry-run] [--no-pull] [--no-gate] [--table] [--json]

# 2. Fleet dashboard — every workstation repository at a glance
github-architect status-all [--table] [--json] [--project repository branch worktree remote_sync] [--limit 5]

# 3. Fleet sync — pull rebase, commit, and push across every repository
github-architect sync-all [-m "sync fleet updates"]

# 4. Audit one repository — status, auth, secret scan, oversized blob guard
github-architect audit [path] [--table] [--json]

# 5. Sync one repository — pull rebase, auto-commit, push
github-architect sync [path] [-m "commit message"]

# 6. Scaffold documentation, .gitignore, and LICENSE without committing
github-architect scaffold [path] [--name repo-name]

# 7. Publish to GitHub — private by default; --template, --public
github-architect publish [path] [--name repo-name] [--template] [--public]

# 8. Bootstrap a whole agent environment on a new machine
github-architect bootstrap [--dest ~/workspace]

# 9. Clone any GitHub repository via the gh CLI
github-architect clone <repo-name> [dest]

# 10. Gate a public bundle publication — secrets, oversized blobs, archived status markers
github-architect guard --source DIR [--source DIR ...] [--published PATH] [--exclude PATTERN] [--label NAME] [--json]

# 11. Guarded commit — stage by path and refuse to commit a file carrying a credential
git-sync guarded-commit --repo PATH -m "message" [--exclude PATTERN] [--json]

# 12. Description gate — fail if any outgoing commit has no body (merge commits exempt)
git-sync check-messages --repo PATH [--upstream ORIGIN/BRANCH]

# 13. Install the pre-push description gate so no bare `git push` can bypass it
git-sync install-hook --repo PATH [--force]
```

---

## 🛡️ Publication Guard

The hub (`my-agent-skills`) is private; the spokes (`workstation-clis`,
`glitch-cat-skills`, `academic-agent-skills`, `free-frontier-skills`) are
public. Everything the bundle sync copies from a hub into a spoke is a
one-way trip, so a mistake made in the hub becomes permanent and public on
the next push.

`github-architect guard` runs before each spoke publication and **blocks** the
bundle when it finds:

- a secret-shaped filename (`.env`, `*.pem`, `*.key`, `id_rsa`, `credentials.json`)
- credential content in a text file (GitHub, OpenAI, Anthropic, Google, HuggingFace,
  Slack and AWS token shapes, plus generic `api_key = "..."` assignments)
- a file above the 50 MB blob ceiling
- a skill published from an `archived/` path whose `SKILL.md` declares no
  archived status — so a retired tool cannot read as a supported one

The guard takes the same `--exclude` list the publishing rsync uses, so it
models exactly what will be published. A drifted exclude set is a hole
straight through the gate.

The same module reaps what a spoke used to publish and no longer does. The
bundle sync records the managed directories in `.bundle-managed.json` at the
spoke root, and any directory that leaves the manifest is removed on the next
sync instead of freezing in place.

### Two layers, both fail-closed

The private hub is guarded too. `git-sync guarded-commit` replaces the raw
`git add -A` in the bundle sync: it stages by path and refuses to commit a
file that carries a credential or an oversized blob. Its content scan reads
**whole files**, not diffs — a brand-new file is untracked, so `git diff HEAD`
shows nothing for it and a secret planted in a new file would sail through a
diff-based guard.

A planted secret is caught twice, independently:

```
🛡️  [guard] Blocked files from staging:
   ❌ academic/canvas-cli/planted-leak.py — GitHub Personal Access Token: ghp_AA...AAAA
🛑 [guard] 1 file(s) blocked; nothing committed.
🛡️  [publication-guard] academic-agent-skills: 1 blocked file(s)
🛑 [bundle-sync] BLOCKED: academic-agent-skills not published.
🛑 One or more bundles were blocked and left untouched.
```

The hub commit is refused, the spoke is never copied, and the sync reports
the block instead of claiming success.

---

## Reference

- `references/capabilities.md` — fleet sync, secret guard, onboarding, templates, git identity
- `references/commit-messages.md` — the commit description standard (header, prose body, worked example)
