---
name: edstem-cli

description: >
  Read and post on Ed Discussion and Ed Courses: list courses, browse and
  search forum threads, read a thread and its comments, post a question or
  reply, open cloud IDE workspaces, and list lessons. Use for class forums,
  threads, course announcements, and assignments.

compatibility: "Requires network access to an Ed Discussion instance, an API token (ED_API_TOKEN) and a base URL (ED_BASE_URL)."
allowed-tools: "Bash(edstem-cli:*) Bash(python3:*) Read Write"
---

# EdStem (`edstem-cli`)

A thin, deterministic client for Ed Discussion and Ed Courses. Every command
takes the same context flags — `--table`, `--project`, `--out`, `--limit` — so
you can ask a narrow question and get a small answer, not a course's worth of
JSON.

---

## 🏛️ The Command Groups

| Group | Example request |
| :--- | :--- |
| **Discovery** — `me`, `courses` | *"Which courses am I in?"* |
| **Threads** — `threads` | *"Show me the recent discussion posts"* |
| **Reading** — `thread` | *"What did people say about the sort constraint?"* |
| **Posting** — `post`, `reply` | *"Ask the class about the sort constraint"* |
| **Cloud IDE** — `workspaces`, `workspace` | *"Open the Assessment 3 workspace"* |
| **Git sync** — `workspace-diff`, `workspace-update` | *"Pull the new workspace files into GitHub safely"* |
| **Lessons** — `lessons`, `lesson` | *"What lessons are in this course?"* |

---

## 🛡️ Token Shielding

Always use these. They are what keeps the response small enough to act on.

| Flag | Effect |
| :--- | :--- |
| `--table`, `-t` | High-density Markdown table — about 98% fewer tokens on thread lists |
| `--project <keys>`, `-p` | Limit the output to a comma-separated field list |
| `--out <file>`, `-o` | Buffer bulk payloads to disk and print a one-line receipt |
| `--limit <N>`, `-n` | Cap the number of records returned (default 30) |
| `--format [table\|json\|ids]` | Exact rendering format |

---

## 🛠️ CLI Quickstart

```bash
# Run from this skill's directory; the paths are relative to it.
CLI=scripts/ed_cli.py

# 1. Discovery
python3 $CLI me
python3 $CLI courses --table
python3 $CLI courses --project id,course_code --table

# 2. Thread browsing and search
python3 $CLI threads <course_id> --table
python3 $CLI threads <course_id> --search "sorting" --table
python3 $CLI threads <course_id> --project id,title --table
python3 $CLI threads <course_id> --limit 50 --out /tmp/all_threads.json

# 3. Reading a thread and its comments
python3 $CLI thread <thread_id> --text-only
python3 $CLI thread --course-id <course_id> --number 42 --text-only
python3 $CLI thread <thread_id>

# 4. Posting and replying
python3 $CLI post <course_id> \
  --title "Question about Assignment 3 sorting constraints" \
  --content "Does sort.c need to support duplicate timestamps?" \
  --category "Assignments" \
  --type question
python3 $CLI post <course_id> \
  --title "Private feedback on rubric" \
  --content "Is the report due date firm?" \
  --private
python3 $CLI reply <thread_id> \
  --content "I tested this locally with make test and it passes all test cases."

# 5. Cloud IDE workspaces
python3 $CLI workspaces <course_id> --summary
python3 $CLI workspaces <course_id> --search "Tim" --summary
python3 $CLI workspaces --search "Tim" --table
python3 $CLI workspaces --table
python3 $CLI workspace "Assessment 3" --connect
python3 $CLI workspace-files "Assessment 3"
python3 $CLI workspace-cat "Assessment 3" main.c

# 5b. Workspace -> Git, preview first, then apply
python3 $CLI workspace-diff <workspace_id> --repo ~/path/to/repo --diff
python3 $CLI workspace-update <workspace_id> --repo ~/path/to/repo --apply \
  --test-command "make all" --test-command "make compress_test sort_test"
python3 $CLI workspace-update <workspace_id> --repo ~/path/to/repo --apply \
  --commit --push --test-command "make all" \
  --message "sync latest workspace files from Ed"

# 6. Lessons and programming challenges
python3 $CLI lessons <course_id> --summary
python3 $CLI lesson <lesson_id> --summary
```

---

## 🔁 Workspace → Git Sync

`workspace-diff` and `workspace-update` are the safe replacement for "pull
everything and `git add -A`". Both fetch into a temp directory first.

- `workspace-diff` never touches the repo: it reports added / changed /
  unchanged / removed files and (with `--diff`) bounded text diffs.
- `workspace-update` is preview-only unless `--apply`. Applying copies new and
  changed files, and **never deletes** anything Ed no longer has.
- The repo needs a clean working tree; the branch must match its remote before
  `--commit`, which runs `--test-command` entries in a network-isolated
  `subagent-spaces` sandbox first. Only then does it `git-sync guarded-commit`
  (secrets and oversized blobs are blocked), and `--push` publishes.
- Backup, credential, and generated files (`*.bak`, `.env`, `build/`, …) are
  skipped and reported. `.edstem-workspace.json` records which files this
  workspace owns, so a file that disappears from Ed is reported but kept.

---

## Reference

- `references/commands.md` — the workspace file commands
- `references/setup.md` — the API token and base URL
