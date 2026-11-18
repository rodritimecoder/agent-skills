#!/usr/bin/env python3
"""Offline checks for canvas_cli.py using a stubbed urlopen (no network)."""
import importlib.util, io, json, os, sys, types
from pathlib import Path
from unittest import mock

# Resolve the CLI relative to this file so the skill can be moved anywhere.
CLI_PATH = Path(__file__).resolve().parent / "canvas_cli.py"

os.environ["CANVAS_API_KEY"] = "test-key"
os.environ["CANVAS_URL"] = "https://example.instructure.com"

spec = importlib.util.spec_from_file_location(
    "cli", str(CLI_PATH))
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  -> {detail}" if not cond else ""))
    if not cond:
        fails.append(name)

# ── 1. URL building: list values + special chars ─────────────────────────────
u = cli.build_url("https://x/api/v1/courses", {"include": ["total_scores", "syllabus_body"]})
check("include list expands to repeated keys",
      u == "https://x/api/v1/courses?include=total_scores&include=syllabus_body", u)
u = cli.build_url("https://x/api/v1/pages", {"url": "week 3/notes&more"})
check("special chars are percent-encoded (space as +, / and & escaped)",
      "+" in u and "%2F" in u and "%26" in u, u)
check("None values dropped", cli.build_url("https://x", {"a": None, "b": 1}) == "https://x?b=1")

# ── 2. Link header parsing ───────────────────────────────────────────────────
link = ('<https://x/api/v1/courses?page=2&per_page=100>; rel="next", '
        '<https://x/api/v1/courses?page=3&per_page=100>; rel="last"')
check("next page found", cli.next_page_url(link, "https://x/api/v1/courses?page=1")
      == "https://x/api/v1/courses?page=2&per_page=100")
check("no next on last page", cli.next_page_url(
    '<https://x?page=1>; rel="prev"', "https://x?page=1") is None)
check("relative next resolved", cli.next_page_url(
    '<?page=2>; rel="next"', "https://x/api/v1/courses") == "https://x/api/v1/courses?page=2")

# ── 3. Pagination across 3 pages (the page-2+ bug) ───────────────────────────
class FakeResp:
    def __init__(self, payload, link=None):
        self.status, self.read_val = 200, json.dumps(payload).encode()
        self.headers = {"Link": link} if link else {}
    def read(self): return self.read_val

pages = {
    "https://x/api/v1/courses?per_page=100": (
        [{"id": 1}, {"id": 2}],
        '<https://x/api/v1/courses?page=2&per_page=100>; rel="next"'),
    "https://x/api/v1/courses?page=2&per_page=100": (
        [{"id": 3}],
        '<https://x/api/v1/courses?page=3&per_page=100>; rel="next"'),
    "https://x/api/v1/courses?page=3&per_page=100": ([{"id": 4}], None),
}
cli.API_BASE = "https://x/api/v1"
seen = []
def fake_urlopen(req, timeout=None):
    url = req.full_url
    seen.append(url)
    if url not in pages:
        raise AssertionError(f"unexpected URL: {url}")
    payload, link = pages[url]
    return FakeResp(payload, link)

with mock.patch.object(cli, "urlopen", fake_urlopen):
    out = cli.paginate("/courses")
check("paginate returns all 3 pages", out == [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}], out)
check("page-2 URL is not double-suffixed with params",
      all(u.count("?") == 1 and "?" in u or "per_page" in u for u in seen), seen)

# ── 4. End-to-end CLI invocations (URL assertions) ───────────────────────────
def run_cli(argv, responses):
    calls = []
    def stub(req, timeout=None):
        calls.append((req.get_method(), req.full_url, req.data))
        payload, link = responses.get(req.full_url, ({}, None))
        return FakeResp(payload, link)
    out = io.StringIO()
    with mock.patch.object(cli, "urlopen", stub), \
         mock.patch.object(sys, "argv", ["canvas_cli.py"] + argv), \
         mock.patch.object(sys, "stdout", out):
        cli.main()
    return calls, out.getvalue()

calls, _ = run_cli(["courses", "--course-id", "7", "--include", "total_scores"],
                   {"https://x/api/v1/courses/7?include=total_scores": ({"id": 7}, None)})
check("courses --include sends a clean query",
      calls[0][1] == "https://x/api/v1/courses/7?include=total_scores", calls[0][1])

calls, _ = run_cli(["submissions", "5", "--student-id", "9", "--assignment-ids", "3", "--assignment-ids", "4", "--graded", "true"],
                   {"https://x/api/v1/courses/5/students/9/submissions?assignment_ids=3&assignment_ids=4&graded=true&per_page=100": ([], None)})
check("submissions --assignment-ids maps to assignment_ids and keeps --graded",
      "assignment_ids=3" in calls[0][1] and "assignment_ids=4" in calls[0][1]
      and "graded=true" in calls[0][1], calls[0][1])

calls, _ = run_cli(["submissions", "5", "--student-id", "9", "--assignment-id", "3"],
                   {"https://x/api/v1/courses/5/students/9/submissions/3": ({"id": 3}, None)})
check("submissions student+assignment hits the single-submission endpoint",
      calls[0][1].endswith("/students/9/submissions/3"), calls[0][1])

calls, _ = run_cli(["submissions", "5", "--graded", "false"],
                   {"https://x/api/v1/courses/5/students/submissions?graded=false&per_page=100": ([], None)})
check("submissions --graded false is sent, not dropped", "graded=false" in calls[0][1], calls[0][1])

calls, _ = run_cli(["pages", "5", "--url", "week 3"],
                   {"https://x/api/v1/courses/5/pages?url=week+3": ({"url": "week-3"}, None)})
check("pages --url is encoded and sent as a query param",
      calls[0][1] == "https://x/api/v1/courses/5/pages?url=week+3", calls[0][1])

calls, _ = run_cli(["calendar", "--context", "course_5", "--start-date", "2026-03-01"],
                   {"https://x/api/v1/calendar_events?context_codes%5B%5D=course_5&start_date=2026-03-01&per_page=100": ([], None)})
check("calendar uses context_codes[] encoding",
      "context_codes%5B%5D=course_5" in calls[0][1], calls[0][1])

calls, _ = run_cli(["assignments", "5", "--create", "--name", "Q1", "--points", "50"],
                   {"https://x/api/v1/courses/5/assignments": ({"id": 1}, None)})
check("create sends points as a number, not a string",
      json.loads(calls[0][2])["points_possible"] == 50.0, calls[0][2])

calls, _ = run_cli(["grades", "5", "self"],
                   {"https://x/api/v1/courses/5/grades/self": ({"current_score": 90}, None)})
check("grades accepts 'self'", calls[0][1].endswith("/grades/self"), calls[0][1])

# ── 5. New features: --summary, --enrollment-state, and exceptions ───────────
calls, out = run_cli(["courses", "--enrollment-state", "active", "--summary"],
                     {"https://x/api/v1/courses?enrollment_state=active&per_page=100": ([{
                         "id": 12, "name": "Algorithms", "course_code": "ALG101",
                         "workflow_state": "available", "extra_field": "ignore_me"
                     }], None)})
check("courses --enrollment-state query param sent", "enrollment_state=active" in calls[0][1], calls[0][1])
parsed_out = json.loads(out)
check("courses --summary strips verbose fields",
      parsed_out == [{"id": 12, "name": "Algorithms", "course_code": "ALG101",
                      "workflow_state": "available", "start_at": None, "end_at": None}], out)

# Exception checking
check("CanvasError classes defined",
      issubclass(cli.CanvasConfigError, cli.CanvasError) and
      issubclass(cli.CanvasHTTPError, cli.CanvasError) and
      issubclass(cli.CanvasNetworkError, cli.CanvasError))

# ── 6. Every declared command builds a working parser ────────────────────────
parser = cli.build_parser()
for name, description, argspec, _ in cli.COMMANDS:
    argv = [name]
    for line in argspec.strip().splitlines():
        tok = line.split()
        if not tok:
            continue
        if not tok[0].startswith("-"):          # supply a plausible value for positionals
            argv.append("self" if tok[0].endswith("user_id") else "5")
    try:
        ns = parser.parse_args(argv)
        ok, err = callable(ns.func), "no handler bound"
    except SystemExit as e:
        ok, err = False, f"exit {e.code}"
    check(f"parser accepts '{name}' and binds a handler", ok, err)

# ── 7. No dead code left behind ──────────────────────────────────────────────
src = open(str(CLI_PATH)).read()
for dead in ("def put(", "def delete(", "resp.status != 204", "time.sleep(0"):
    check(f"removed dead code: {dead!r}", dead not in src)

# ── 8. Deterministic Token Reduction (table, project, out, limit) ───────────
sample_data = [
    {"id": 101, "name": "Assignment 1", "due_at": "2026-03-30T23:59:00Z", "points": 100, "extra": "bloat"},
    {"id": 102, "name": "Assignment 2", "due_at": "2026-04-15T23:59:00Z", "points": 50, "extra": "bloat"}
]

projected = cli.project_data(sample_data, ["id", "name", "points"])
check("project_data filters strictly to requested keys",
      all(set(d.keys()) == {"id", "name", "points"} for d in projected), str(projected))

tbl = cli.format_table(sample_data)
check("format_table renders markdown pipe table",
      "| id  |" in tbl and "| Assignment 1" in tbl and "|---" in tbl, tbl)

tmp_out = "/tmp/test_canvas_out.json"
if os.path.exists(tmp_out):
    os.remove(tmp_out)
calls, out_text = run_cli(["--out", tmp_out, "courses"],
                          {"https://x/api/v1/courses?per_page=100": (sample_data, None)})
check("--out writes response to disk", os.path.exists(tmp_out))
check("--out prints concise receipt with preview", "saved_to" in out_text and "count" in out_text, out_text)
if os.path.exists(tmp_out):
    os.remove(tmp_out)

calls, out_text = run_cli(["--table", "--project", "id,name", "courses"],
                          {"https://x/api/v1/courses?per_page=100": (sample_data, None)})
check("--table with --project prints clean markdown table",
      "| id  | name         |" in out_text and "extra" not in out_text, out_text)

calls, out_text = run_cli(["--limit", "1", "courses"],
                          {"https://x/api/v1/courses?per_page=100": (sample_data, None)})
parsed = json.loads(out_text)
check("--limit truncates output records", len(parsed) == 1 and parsed[0]["id"] == 101, out_text)

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)
