# Core Capabilities & Multi-Machine Portability

Beyond the git-sync protocol, `github-architect` covers these.

1. **Fleet-Wide Synchronization (`status-all` & `sync-all`)** — manages all 5
   core workstation repositories (`my-agent-skills`, `workstation-clis`,
   `academic-agent-skills`, `agent-multiplayer-template`, `university`).
   One-command rebase, dirty-tree check, commit, and push across the whole
   machine. Automatically runs `sync-skills` whenever the skills repository
   is synced.

2. **Grounded Secret & Large-Blob Guard** — actively checks git diffs before
   committing or pushing for secret tokens (`ghp_*`, `sk-*`, `AIza*`, private
   keys). Blocks accidental commits of files over 50 MB, which prevents push
   rejections from heavy model weights, SQLite databases, or videos. Override
   with `--force` when intentional.

3. **Single-Command Workstation Onboarding (`bootstrap`)** — no physical
   drive required. Clones and links the entire 5-repository workstation
   suite, sets up symlinks in `~/.local/bin/`, and propagates all skills
   directly into the harness skill directories.

4. **GitHub Template Support (`publish --template`)** — creates reusable
   GitHub Template repositories via direct GitHub API integration.

5. **Self-Healing Git Identity** — auto-detects the GitHub username and
   handles missing `git config user.name` / `user.email` dynamically, without
   failing the operation.
