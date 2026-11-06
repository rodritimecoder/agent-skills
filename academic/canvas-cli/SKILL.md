---
name: canvas-cli

description: >
  Read Canvas LMS data: courses, assignments, submissions, grades, the gradebook, files,
  pages, announcements and the calendar. Use for anything school, university or class related
  — the course portal, student portal, learning management system (LMS) or gradebook —
  assignments, homework, what is due this week or next, deadlines, marks and results,
  readings, lecture material a teacher posted, or course announcements.

compatibility: "Requires network access to a Canvas LMS instance and a Canvas API token (CANVAS_API_KEY)."
allowed-tools: "Bash(canvas-cli:*) Bash(python3:*) Read"
---

# Canvas LMS (`canvas-cli`)

A thin, deterministic client for the Canvas LMS API. Every command takes the
same context flags — `--table`, `--project`, `--out`, `--limit` — so you can
ask a narrow question and get a small answer instead of a course's worth of
JSON.

---

## 🏛️ The Command Groups

| Group | Example request |
| :--- | :--- |
| **Urgent** — `todo`, `upcoming` | *"What do I have due this week?"* |
| **Courses** — `courses` | *"List my active courses"* |
| **Assignments** — `assignments` | *"What is assigned in course 12345?"* |
| **Submissions & grades** — `submissions`, `grades`, `gradebook` | *"What are my grades?"* |
| **Content** — `modules`, `files`, `pages`, `quizzes`, `discussions` | *"Get the files for course 12345"* |
| **Announcements** — `announcements` | *"Any new announcements?"* |
| **Calendar** — `calendar` | *"What's on the calendar this month?"* |
| **Users** — `users`, `progress` | *"Which courses am I enrolled in?"* |
| **OCR** — `pdf_ocr.py` | *"Transcribe these scanned tutorial solutions"* |

---

## 🛡️ Token Shielding

Always use these. They are what keeps the response small enough to act on.

| Flag | Effect |
| :--- | :--- |
| `--table`, `-t` | High-density Markdown table — about 95% fewer tokens than raw JSON |
| `--project <keys>`, `-p` | Limit the output to a comma-separated field list |
| `--out <file>`, `-o` | Buffer bulk JSON to disk and print a one-line receipt |
| `--limit <N>`, `-n` | Cap the number of records returned |
| `--format [table\|json\|ids]` | Exact rendering format |

---

## 🛠️ CLI Quickstart

```bash
# Run from this skill's directory; the paths are relative to it.
CLI=scripts/canvas_cli.py

# 1. What needs doing, across every enrolled course
python3 $CLI todo --table
python3 $CLI upcoming --days 7 --table

# 2. Courses
python3 $CLI courses --enrollment-state active --summary --table
python3 $CLI courses --project id,course_code --table
python3 $CLI courses --out /tmp/all_courses.json
python3 $CLI courses --course-id 12345 --syllabus

# 3. Assignments
python3 $CLI assignments 12345 --summary
python3 $CLI assignments 12345
python3 $CLI assignments 12345 --assignment-id 99

# 4. Submissions and grades
python3 $CLI submissions 12345 --student-id 456 --assignment-id 99
python3 $CLI grades 12345 self
python3 $CLI gradebook 12345

# 5. Course content
python3 $CLI modules 12345
python3 $CLI files 12345
python3 $CLI pages 12345
python3 $CLI announcements 12345

# 6. Calendar
python3 $CLI calendar --context course_12345 --start-date 2026-03-01 --end-date 2026-03-31

# 7. Handwritten and scanned PDFs
OCR_CLI=scripts/pdf_ocr.py
python3 $OCR_CLI "path/to/Tutorial Solutions.pdf" -o "markdown/Tutorial_Solutions.md"
```

---

## Reference

- `references/commands.md` — the full command surface, including the specialised ones
- `references/setup.md` — the API token and URL the client needs
- `references/notes.md` — write operations, permissions, and known limits
