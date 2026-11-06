# Canvas LMS Skill

Full-featured Canvas LMS integration: fetch courses, assignments, submissions,
grades, enrollments, announcements, modules, discussions, quizzes, pages, files,
and calendar events from the command line.

| | |
|---|---|
| Script | `scripts/canvas_cli.py` |
| Requirements | Python 3.9+ (standard library only — no `pip install`) |
| Endpoint reference | `references/api_endpoints.md` |
| API docs | <https://canvas.instructure.com/doc/api/> |

## Setup

1. Get an API token: log into Canvas → **Account → Settings → + New Access Token**.
2. Create a `.env` file next to `scripts/`:

   ```
   CANVAS_API_KEY=your_canvas_api_token
   CANVAS_URL=https://your-school.instructure.com
   ```

   `CANVAS_URL` is the bare host — no `/api/v1` suffix, no trailing slash.
   Both values can also come from the environment instead of the file.

> **Keep the token safe.** A Canvas token grants full account access for as long
> as it lives. `chmod 600 .env`, and keep it out of any synced or public
> directory or git repository. Revoke it in Canvas when you no longer need it.

## Quick start

```bash
CLI=~/.gemini/config/skills/canvas-cli/scripts/canvas_cli.py

python3 $CLI courses --summary                          # compact course overview
python3 $CLI assignments 12345 --summary                # compact assignments list
python3 $CLI announcements 12345                        # what the class posted
python3 $CLI calendar --context course_12345 \
        --start-date 2026-03-01 --end-date 2026-03-31   # what's coming up
```

Output is JSON, so it pipes straight into `jq`:

```bash
# Upcoming assignments with due dates
python3 $CLI assignments 12345 | jq -r '.[] | select(.due_at) | "\(.due_at)  \(.name)"' | sort

# Announcement titles only
python3 $CLI announcements 12345 | jq -r '.[] | .title'
```

## Finding course IDs

Almost every command needs a course ID. Two ways to get it:

```bash
python3 $CLI courses | jq -r '.[] | "\(.id)  \(.name)"'
```

Or read it from the browser URL — `https://school.instructure.com/courses/12345`
means the course ID is `12345`.

## Commands

Run `python3 $CLI --help` or `python3 $CLI <command> --help` for the full
argument list of any command. `SKILL.md` is the command reference.

```
courses        enrollments     assignments     submissions
grades         gradebook       announcements   modules
discussions    files           quizzes         pages
calendar       users           outcomes        progress
```

Note that `grades`, `users`, and `progress` accept `self` in place of a user ID
to refer to your own account.

## Behaviour worth knowing

- **Pagination is automatic.** List commands walk every page and return one flat
  array, so nothing is silently cut off at 100 items.
- **Retries are automatic.** Rate limits (429) and transient server errors are
  retried with exponential backoff, honouring `Retry-After`. Requests time out
  after 30 seconds.
- **stdout is always JSON.** Errors go to stderr with a non-zero exit code, so
  `... | jq` never sees a half-written error message.
- **Creating content needs an instructor token.** The `--create` flags on
  assignments, announcements, modules, discussions, quizzes, and pages return
  403 for a student account.

## Troubleshooting

**`ERROR: Set CANVAS_API_KEY and CANVAS_URL ...`** — the `.env` file is missing
or malformed. Each line must be `KEY=value` with no `export` prefix.

**`HTTP 401`** — the token is wrong, revoked, or expired. Make a new one in
Canvas. **`HTTP 403`** — the token is valid but lacks the permission (a student
token cannot create an assignment). **`HTTP 404`** — wrong ID, or your account
isn't enrolled in that course.

**Dates look wrong by a few hours** — Canvas stores UTC. Use the `Z` suffix, or
an explicit offset like `-04:00`, when passing `--due-at`.

**A course is missing from `courses`** — the list only returns courses your
account is enrolled in and hasn't deleted.

## Tests

`scripts/test_canvas_cli.py` runs fully offline against a stubbed HTTP layer:

```bash
python3 scripts/test_canvas_cli.py
```

It covers URL encoding, `Link`-header pagination, query-parameter
construction, and that every declared command parses.

## License

MIT
