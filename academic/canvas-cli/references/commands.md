# The Full Command Surface

Everything the quickstart does not show. The same context flags apply
throughout — `--table`, `--project`, `--out`, `--limit`, `--format`.

```bash
CLI=/run/media/rodri/AI/skills/canvas-cli/scripts/canvas_cli.py
```

## Urgent action items and deadlines

```bash
# Actionable student todo items across all enrolled courses (ultra-compact)
python3 $CLI todo --table

# Upcoming deadlines in the next 14 days across all active courses
python3 $CLI upcoming --table
```

## Assignments

```bash
# Per-student due-date extensions
python3 $CLI assignments 12345 --assignment-id 99 --overrides

# Create (instructor tokens only)
python3 $CLI assignments 12345 --create \
  --name "Chapter 5 Quiz" --points 50 --due-at "2026-03-30T23:59:00Z"
```

## Submissions and grades

```bash
# One student's submissions, filtered
python3 $CLI submissions 12345 --student-id 456 \
  --assignment-ids 99 --assignment-ids 100 --graded true

# Everything submitted in a course
python3 $CLI submissions 12345
```

## Course content

```bash
# Readings, files and pages inside one module
python3 $CLI modules 12345 --module-id 5 --items

# One file, one page
python3 $CLI files 12345 --file-id 77
python3 $CLI pages 12345 --url "lecture-notes"

# Quizzes, discussions, enrollments, outcomes
python3 $CLI quizzes 12345
python3 $CLI discussions 12345
python3 $CLI enrollments 12345 --type Student --state active
python3 $CLI outcomes 12345
```

## Announcements

```bash
# One announcement
python3 $CLI announcements 12345 --announcement-id 12
```

## Calendar

```bash
# Several courses at once
python3 $CLI calendar --context course_12345 --context course_67890
```

## Users and async operations

```bash
# The requesting user, with their enrolments
python3 $CLI users self --include enrollments

# Status of an async operation
python3 $CLI progress 999
```

## OCR and document conversion

```bash
OCR_CLI=/run/media/rodri/AI/skills/canvas-cli/scripts/pdf_ocr.py

# Transcribe specific pages
python3 $OCR_CLI "path/to/Tutorial Solutions.pdf" --pages 1 2 3 -o "markdown/Tutorial_P1-3.md"

# Force OCR even if the document contains digital text
python3 $OCR_CLI "path/to/Tutorial Solutions.pdf" --force-ocr
```
