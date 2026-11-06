# The Full Command Surface

Everything the quickstart does not show. The same context flags apply
throughout — `--table`, `--project`, `--out`, `--limit`, `--format`.

```bash
CLI=/run/media/rodri/AI/skills/edstem-cli/scripts/ed_cli.py
```

## Workspace files and Git sync

```bash
# List files by workspace title, author, or ID
python3 $CLI workspace-files "Assessment 3"

# Read a file directly from the container buffer, without downloading
python3 $CLI workspace-cat "Assessment 3" archive.h

# Pull the full workspace tree to a local directory
python3 $CLI workspace-pull <workspace_id> --dest ./my_assessment_3

# Live sync to Git — a continuous watch daemon with auto-commits
python3 $CLI workspace-sync <workspace_id> --dest ./my_assessment_3 --push

# Single-pass sync and git commit, then exit
python3 $CLI workspace-sync <workspace_id> --dest ./my_assessment_3 --once
```

### Safe workspace -> Git workflow

```bash
# 1. Preview against a repo: added / changed / unchanged / removed / skipped
python3 $CLI workspace-diff <workspace_id> --repo ./my_assessment_3 --diff

# 2. Apply new + changed files into a clean repo (never deletes anything)
python3 $CLI workspace-update <workspace_id> --repo ./my_assessment_3 --apply

# 3. Apply, test in an isolated sandbox, then guarded-commit and push
python3 $CLI workspace-update <workspace_id> --repo ./my_assessment_3 \
  --apply --commit --push \
  --test-command "make all" --test-command "make compress_test sort_test" \
  --message "sync latest workspace files from Ed"
```

Guarantees: preview is read-only; the destination tree must be clean; the
branch must match its remote before `--commit`; tests run in a network-isolated
`subagent-spaces` container before any file is applied; the commit goes through
`git-sync guarded-commit` (secret and 50 MB blob guard); removals from Ed are
reported via `.edstem-workspace.json` but never deleted from the repo;
`*.bak`, `.env*`, keys and generated directories are skipped and listed.

## Discovery

```bash
# The authenticated user profile and their organisation
python3 $CLI me

# List workspaces across all enrolled courses, optionally searching title/author/course
python3 $CLI workspaces --table
python3 $CLI workspaces --search "Tim" --table
```

## Reading a thread

```bash
# The full raw JSON payload
python3 $CLI thread <thread_id>
```
