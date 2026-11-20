# Core Capabilities & Multi-Machine Portability

Beyond the git-sync protocol, `github-architect` covers these.

1. **Config-Driven Fleet Management (`status-all` & `sync-all`)** — the fleet
   is defined by a JSON config at `~/.config/github-architect/fleet.json`,
   overridden by the `GITHUB_ARCHITECT_FLEET` environment variable or the
   `--config PATH` flag. Its schema is
   `{"repos": [{"name", "path", "slug", "description"}]}`. `status-all` reports
   every configured repository at a glance; `sync-all` does a safe
   `--no-rebase` merge pull, guarded commit, and push across the whole fleet.
   Both accept `[--config PATH]`, and `sync-skills publish` runs automatically
   whenever the skills repository is synced.

2. **Grounded Secret & Large-Blob Guard** — `publication_guard.py` scans
   **whole files**, including untracked ones, before committing or pushing —
   never diff-only, so a secret planted in a brand-new file cannot slip past a
   `git diff`. It checks secret filenames and token/key patterns (`ghp_*`,
   `sk-*`, `AIza*`, private keys, `.env`), applies a placeholder exemption, and
   blocks files over the 50 MB blob ceiling, preventing push rejections from
   heavy model weights, SQLite databases, or videos.

3. **Single-Command Workstation Onboarding (`bootstrap`)** — no physical
   drive required. Reads the same fleet config, clones and links the configured
   repositories, links both the `github-architect` and `git-sync` CLIs into
   `~/.local/bin/`, and propagates skills into the harness skill directories.
   Accepts `[--config PATH]`.

4. **GitHub Template Support (`publish --template`)** — creates reusable
   GitHub Template repositories via direct GitHub API integration.

5. **Self-Healing Git Identity** — auto-detects the GitHub username and handles
   missing `git config user.name` / `user.email` dynamically via a portable
   fallback, without embedding a personal username or failing the operation.
