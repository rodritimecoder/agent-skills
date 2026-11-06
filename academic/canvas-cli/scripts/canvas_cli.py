#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

class CanvasError(Exception):
    pass

class CanvasConfigError(CanvasError):
    pass

class CanvasHTTPError(CanvasError):
    def __init__(self, code: int, body: str, url: str, method: str):
        self.code = code
        self.body = body
        self.url = url
        self.method = method
        msg = f"HTTP {code} on {method} {url}"
        if body:
            msg += f"\n{body}"
        super().__init__(msg)

class CanvasNetworkError(CanvasError):
    pass

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("CANVAS_API_KEY", "")
_canvas_url = os.environ.get("CANVAS_URL", "").rstrip("/")
API_BASE = f"{_canvas_url}/api/v1" if _canvas_url else ""

def get_headers() -> dict[str, str]:
    key = API_KEY or os.environ.get("CANVAS_API_KEY", "")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

HEADERS = get_headers()
TIMEOUT = 30
MAX_RETRIES = 4
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

def clean_okf_slug(title: str, course_code: str | None = None, week: str | int | None = None) -> str:
    s = title.strip()
    s = re.sub(r'[\U00010000-\U0010ffff]', '', s)
    s = re.sub(r'[^\x00-\x7F]+', '', s)
    s = re.sub(r'\.(md|html|pdf|docx|pptx)$', '', s, flags=re.IGNORECASE)
    s = re.sub(r'[\s_:\-\—\–\/\(\)\,\@\%\&]+', '-', s)
    s = s.strip('-').lower()

    parts = []
    if course_code:
        c_clean = str(course_code).split()[0].lower()
        parts.append(c_clean)
    if week is not None:
        try:
            w_num = int(str(week).lower().replace("week", "").replace("w", "").strip())
            parts.append(f"w{w_num:02d}")
        except ValueError:
            pass
    parts.append(s or "untitled")
    return "_".join(parts)

GENERIC_ITEM_PATTERNS = re.compile(
    r'^(?:overview|topic\s*notes|tutorial(?:\s*recording|\s*solutions|\s*questions)?|'
    r'knowledge\s*recap|lecture(?:\s*notes|\s*recording)?|slides?|ppt|solutions?|summary)$',
    re.IGNORECASE
)

def build_descriptive_title(
    item_title: str,
    module_name: str | None = None,
    course_code: str | None = None,
    week: str | int | None = None
) -> str:
    clean_item = item_title.strip()
    clean_item = re.sub(r'[\U00010000-\U0010ffff]', '', clean_item).strip()
    clean_item = re.sub(r'\.(md|html|pdf|docx|pptx)$', '', clean_item, flags=re.IGNORECASE).strip()

    week_tag = ""
    if week is not None:
        try:
            w_num = int(str(week).lower().replace("week", "").replace("w", "").strip())
            week_tag = f"W{w_num:02d}"
        except ValueError:
            pass

    c_badge = str(course_code).split()[0] if course_code else ""
    badge_parts = [c_badge, week_tag] if week_tag else [c_badge]
    badge = f"[{' '.join(p for p in badge_parts if p)}] " if any(badge_parts) else ""

    item_stripped = re.sub(r'^(?:week|w)\s*\d+[\s:_-]*', '', clean_item, flags=re.IGNORECASE).strip()
    if GENERIC_ITEM_PATTERNS.match(item_stripped) and module_name:
        mod_clean = re.sub(r'^(?:week|w)\s*\d+[\s:_-]*', '', module_name, flags=re.IGNORECASE).strip()
        if mod_clean and mod_clean.lower() not in item_stripped.lower():
            return f"{badge}{item_stripped.title()}: {mod_clean}"

    return f"{badge}{clean_item}"

def _format_param_val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return v

def build_url(url: str, params: dict | None) -> str:
    if not params:
        return url
    clean = {}
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            clean[k] = [_format_param_val(x) for x in v]
        else:
            clean[k] = _format_param_val(v)
    return f"{url}?{urlencode(clean, doseq=True)}" if clean else url

def request(method: str, url: str, data: dict | None = None) -> tuple:
    if not API_KEY or not API_BASE:
        raise CanvasConfigError("Set CANVAS_API_KEY and CANVAS_URL in .env file or environment.")

    headers = HEADERS if HEADERS.get("Authorization") != "Bearer " else get_headers()
    body = json.dumps(data).encode() if data is not None else None

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = urlopen(Request(url, data=body, headers=headers, method=method), timeout=TIMEOUT)
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None), resp.headers
        except HTTPError as e:
            if e.code in RETRY_STATUSES and attempt < MAX_RETRIES:
                wait = float(e.headers.get("Retry-After") or 2 ** attempt)
                time.sleep(wait)
                continue
            err_body = e.read().decode(errors="replace")
            raise CanvasHTTPError(e.code, err_body, url, method)
        except (URLError, TimeoutError, OSError) as e:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise CanvasNetworkError(f"{method} {url} failed: {e}")

    raise CanvasNetworkError(f"{method} {url} failed after {MAX_RETRIES} retries")

def get(path: str, params: dict | None = None) -> dict:
    return request("GET", build_url(f"{API_BASE}{path}", params))[1]

def post(path: str, data: dict) -> dict:
    return request("POST", f"{API_BASE}{path}", data)[1]

def next_page_url(link_header: str, current_url: str) -> str | None:
    for part in link_header.split(","):
        segs = part.split(";")
        if len(segs) < 2 or not segs[0].strip().startswith("<"):
            continue
        if any(s.strip().lower().replace(" ", "") == 'rel="next"' for s in segs[1:]):
            url = segs[0].strip()[1:-1]
            return url if url.startswith("http") else urljoin(current_url, url)
    return None

def paginate(path: str, params: dict | None = None) -> list:
    url = build_url(f"{API_BASE}{path}", {**(params or {}), "per_page": 100})
    items: list = []

    while url:
        _status, payload, headers = request("GET", url)
        if not isinstance(payload, list):
            break
        items.extend(payload)
        url = next_page_url(headers.get("Link", ""), url)

    return items

def resource(ns, path: str, id_attr: str, body=None, id_param: str | None = None):
    ident = getattr(ns, id_attr, None)
    if ident is not None:
        return get(path, {id_param: ident}) if id_param else get(f"{path}/{quote(str(ident), safe='')}")
    if getattr(ns, "create", False):
        return post(path, body(ns))
    return paginate(path)

def summarize_course(c: dict) -> dict:
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "course_code": c.get("course_code"),
        "workflow_state": c.get("workflow_state"),
        "start_at": c.get("start_at"),
        "end_at": c.get("end_at"),
    }

def summarize_assignment(a: dict) -> dict:
    return {
        "id": a.get("id"),
        "name": a.get("name"),
        "due_at": a.get("due_at"),
        "points_possible": a.get("points_possible"),
        "submission_types": a.get("submission_types"),
    }

def summarize_announcement(an: dict) -> dict:
    author = an.get("author") or {}
    return {
        "id": an.get("id"),
        "title": an.get("title"),
        "posted_at": an.get("posted_at"),
        "author": author.get("display_name") if isinstance(author, dict) else str(author),
    }

def summarize_module(m: dict) -> dict:
    return {
        "id": m.get("id"),
        "name": m.get("name"),
        "position": m.get("position"),
        "items_count": m.get("items_count"),
        "state": m.get("state"),
    }

def title_message(ns) -> dict:
    return {"title": ns.title, "message": ns.message}

def cmd_courses(ns):
    if ns.course_id is None:
        params = {}
        if getattr(ns, "enrollment_state", None):
            params["enrollment_state"] = ns.enrollment_state
        res = paginate("/courses", params if params else None)
        if (getattr(ns, "summary", False) or getattr(ns, "compact", False)) and isinstance(res, list):
            return [summarize_course(c) for c in res]
        return res
    if ns.syllabus:
        return get(f"/courses/{ns.course_id}", {"include": ["syllabus_body"]}).get("syllabus_body", "")
    res = get(f"/courses/{ns.course_id}", {"include": ns.include})
    if (getattr(ns, "summary", False) or getattr(ns, "compact", False)) and isinstance(res, dict):
        return summarize_course(res)
    return res

def cmd_enrollments(ns):
    return paginate(f"/courses/{ns.course_id}/enrollments", {"type": ns.type, "state": ns.state})

def cmd_assignments(ns):
    c, a = ns.course_id, ns.assignment_id
    if a and ns.overrides:
        return paginate(f"/courses/{c}/assignments/{a}/overrides")
    if ns.create:
        return post(f"/courses/{c}/assignments", {
            "name": ns.name, "description": ns.description or "",
            "points_possible": ns.points, "due_at": ns.due_at,
            "submission_types": ["online_text_entry"],
        })
    res = resource(ns, f"/courses/{c}/assignments", "assignment_id")
    if getattr(ns, "summary", False) or getattr(ns, "compact", False):
        if isinstance(res, list):
            return [summarize_assignment(x) for x in res]
        if isinstance(res, dict):
            return summarize_assignment(res)
    return res

def cmd_announcements(ns):
    res = resource(ns, f"/courses/{ns.course_id}/announcements", "announcement_id", title_message)
    if getattr(ns, "summary", False) or getattr(ns, "compact", False):
        if isinstance(res, list):
            return [summarize_announcement(x) for x in res]
        if isinstance(res, dict):
            return summarize_announcement(res)
    return res

def cmd_submissions(ns):
    c = ns.course_id
    ids = ns.assignment_ids or ([ns.assignment_id] if ns.assignment_id else None)
    if ns.student_id and ns.assignment_id:
        return get(f"/courses/{c}/students/{ns.student_id}/submissions/{ns.assignment_id}")
    if ns.student_id:
        return paginate(f"/courses/{c}/students/{ns.student_id}/submissions",
                         {"assignment_ids": ids, "graded": ns.graded})
    return paginate(f"/courses/{c}/students/submissions", {"assignment_ids": ids, "graded": ns.graded})

def cmd_modules(ns):
    c, m = ns.course_id, ns.module_id
    if m is None:
        if ns.create:
            return post(f"/courses/{c}/modules", {"name": ns.name, "position": ns.position})
        res = paginate(f"/courses/{c}/modules")
        if (getattr(ns, "summary", False) or getattr(ns, "compact", False)) and isinstance(res, list):
            return [summarize_module(x) for x in res]
        return res
    if ns.items:
        return paginate(f"/courses/{c}/modules/{m}/items", {"include": ["content_details"]})
    if ns.add_item:
        return post(f"/courses/{c}/modules/{m}/items",
                    {"title": ns.title, "type": ns.item_type, "content_id": ns.content_id})
    res = get(f"/courses/{c}/modules/{m}")
    if (getattr(ns, "summary", False) or getattr(ns, "compact", False)) and isinstance(res, dict):
        return summarize_module(res)
    return res

def cmd_calendar(ns):
    return paginate("/calendar_events", {
        "context_codes[]": ns.context, "start_date": ns.start_date, "end_date": ns.end_date,
    })

def cmd_todo(_ns):
    items = paginate("/users/self/todo")
    compact_items = []
    for it in items:
        assignment = it.get("assignment") or {}
        quiz = it.get("quiz") or {}
        target = assignment or quiz
        compact_items.append({
            "type": it.get("type", "assignment"),
            "context_name": it.get("context_name", ""),
            "title": target.get("name") or target.get("title") or it.get("type", "Item"),
            "due_at": target.get("due_at") or it.get("date"),
            "points": target.get("points_possible"),
            "html_url": it.get("html_url") or target.get("html_url"),
        })
    return compact_items

def cmd_upcoming(ns):
    courses = paginate("/courses", {"enrollment_state": "active"})
    limit_days = getattr(ns, "days", 14) or 14
    now = datetime.utcnow()
    all_upcoming = []

    for c in courses:
        cid = c.get("id")
        cname = c.get("course_code") or c.get("name") or str(cid)
        if not cid:
            continue
        try:
            assignments = paginate(f"/courses/{cid}/assignments")
            for a in assignments:
                due_str = a.get("due_at")
                if not due_str:
                    continue
                try:
                    due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    delta = (due_dt - now).total_seconds() / 86400.0
                    if 0 <= delta <= limit_days:
                        all_upcoming.append({
                            "course": cname,
                            "assignment": a.get("name"),
                            "due_at": due_str,
                            "days_left": round(delta, 1),
                            "points": a.get("points_possible"),
                            "id": a.get("id"),
                        })
                except Exception:
                    continue
        except Exception:
            continue

    all_upcoming.sort(key=lambda x: x.get("due_at", ""))
    return all_upcoming

def project_data(data: any, fields: list[str]) -> any:
    if isinstance(data, list):
        return [project_data(x, fields) for x in data]
    if isinstance(data, dict):
        return {k: data[k] for k in fields if k in data}
    return data

def format_table(data: list[dict], max_col_width: int = 40) -> str:
    if not data:
        return "No records found."
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        return json.dumps(data, indent=2)

    keys = list(data[0].keys())
    for item in data[1:]:
        for k in item.keys():
            if k not in keys:
                keys.append(k)

    headers = [str(k) for k in keys]
    rows = []
    for item in data:
        row = []
        for k in keys:
            val = item.get(k, "")
            if val is None:
                val = ""
            elif isinstance(val, (dict, list)):
                val = json.dumps(val)
            else:
                val = str(val).strip().replace("\n", " ")
            if len(val) > max_col_width:
                val = val[:max_col_width - 3] + "..."
            row.append(val)
        rows.append(row)

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "|-" + "-|-".join("-" * col_widths[i] for i in range(len(headers))) + "-|"
    row_lines = ["| " + " | ".join(r[i].ljust(col_widths[i]) for i in range(len(headers))) + " |" for r in rows]

    return "\n".join([header_line, sep_line] + row_lines)

def render_output(data: any, ns: argparse.Namespace) -> None:
    limit = getattr(ns, "limit", None)
    if limit is not None and isinstance(data, list):
        data = data[:limit]

    project_arg = getattr(ns, "project", None)
    if project_arg:
        fields = [f.strip() for f in project_arg.split(",") if f.strip()]
        data = project_data(data, fields)

    out_file = getattr(ns, "out", None)
    if out_file:
        p = Path(out_file)
        if p.parent:
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))
        receipt = {
            "status": "ok",
            "saved_to": str(p.resolve()),
            "count": len(data) if isinstance(data, list) else 1,
            "preview": data[:3] if isinstance(data, list) else data
        }
        print(json.dumps(receipt, indent=2))
        return

    fmt = getattr(ns, "format", "json")
    if getattr(ns, "table", False):
        fmt = "table"

    if fmt == "table" and isinstance(data, list) and data and isinstance(data[0], dict):
        print(format_table(data))
    elif fmt == "ids" and isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "id" in item:
                print(item["id"])
    elif isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, indent=2))

TYPES = {"int": int, "float": float, "str": str}

def str2bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "y", "on")

def build_args(spec: str) -> tuple:
    positionals, optionals = [], []
    for line in spec.strip().splitlines():
        tokens = line.split()
        if not tokens:
            continue
        name, mods = tokens[0], set(tokens[1:])
        kind = next((t for t in tokens[1:] if t in TYPES or t in ("flag", "bool")), "str")

        opts = {"help": name.lstrip("-").replace("-", " ")}
        if kind in TYPES:
            opts["type"] = TYPES[kind]
        elif kind == "bool":
            opts.update(type=str2bool, nargs="?", const=True, metavar="true|false")
        elif kind == "flag":
            opts["action"] = "store_true"
        if "rep" in mods:
            opts["action"] = "append"

        if name.startswith("-"):
            optionals.append((tuple(name.split("|")), opts))
        else:
            positionals.append((name, opts))
    return positionals, optionals

COMMANDS = [
    ("courses", "List or get courses", """
        --course-id int   List all courses if omitted
        --enrollment-state str  active | invited_or_pending | completed
        --include rep     e.g. total_scores, syllabus_body
        --syllabus flag   Return just the syllabus body
        --summary flag    Compact summary (id, name, code, state, dates)
        --compact flag    Shorthand for compact summary
    """, cmd_courses),

    ("enrollments", "List course enrollments", """
        course_id int
        --type str        StudentEnrollment | TeacherEnrollment | TaEnrollment
        --state str       active | invited | completed | ...
    """, cmd_enrollments),

    ("assignments", "List, get, or create assignments", """
        course_id int
        --assignment-id int   Get one assignment
        --overrides flag      Per-student due-date extensions
        --create flag
        --name str
        --description str
        --points float
        --due-at str          ISO 8601, e.g. 2026-03-30T23:59:00Z
        --summary flag        Compact summary (id, name, due_at, points, types)
        --compact flag        Shorthand for compact summary
    """, cmd_assignments),

    ("submissions", "Get submissions", """
        course_id int
        --student-id int      Limit to one student
        --assignment-id int   One assignment
        --assignment-ids int rep   Filter by several assignment IDs
        --graded bool         true | false
    """, cmd_submissions),

    ("grades", "Get a user's grades in a course", """
        course_id int
        user_id str       Canvas user ID, or 'self'
    """, lambda ns: get(f"/courses/{ns.course_id}/grades/{quote(ns.user_id, safe='')}")),

    ("gradebook", "Get the full course gradebook", """
        course_id int
    """, lambda ns: get(f"/courses/{ns.course_id}/gradebook")),

    ("announcements", "List, get, or create announcements", """
        course_id int
        --announcement-id int
        --create flag
        --title str
        --message str
        --summary flag        Compact summary (id, title, posted_at, author)
        --compact flag        Shorthand for compact summary
    """, cmd_announcements),

    ("modules", "List, get, or create modules and their items", """
        course_id int
        --module-id int      Target one module
        --items flag         List the module's items
        --add-item flag      Add an item to the module
        --title str          Item title (with --add-item)
        --item-type str      SubHeader | File | Page | Assignment | ExternalUrl
        --content-id int     Content object ID for the item
        --create flag
        --name str
        --position int
        --summary flag       Compact summary (id, name, position, items_count, state)
        --compact flag       Shorthand for compact summary
    """, cmd_modules),

    ("discussions", "List, get, or create discussion topics", """
        course_id int
        --topic-id int
        --create flag
        --title str
        --message str
    """, lambda ns: resource(ns, f"/courses/{ns.course_id}/discussion_topics", "topic_id", title_message)),

    ("files", "List course files or get file metadata", """
        course_id int
        --file-id int
    """, lambda ns: resource(ns, f"/courses/{ns.course_id}/files", "file_id")),

    ("quizzes", "List, get, or create quizzes", """
        course_id int
        --quiz-id int
        --create flag
        --title str
        --description str
    """, lambda ns: resource(ns, f"/courses/{ns.course_id}/quizzes", "quiz_id",
                             lambda a: {"title": a.title, "description": a.description or ""})),

    ("pages", "List, get, or create wiki pages", """
        course_id int
        --url str       Page slug, e.g. lecture-notes-week-3
        --create flag
        --title str
        --body str      HTML
    """, lambda ns: resource(ns, f"/courses/{ns.course_id}/pages", "url",
                             lambda a: {"title": a.title, "body": a.body or ""}, id_param="url")),

    ("calendar", "List calendar events", """
        --context str rep    e.g. course_12345 (repeat for several)
        --start-date str     YYYY-MM-DD
        --end-date str       YYYY-MM-DD
    """, cmd_calendar),

    ("todo", "List active student todo items across all enrolled courses", """
    """, cmd_todo),

    ("upcoming", "List upcoming assignments across active courses (default 14 days)", """
        --days int      Number of days ahead to look (default: 14)
    """, cmd_upcoming),

    ("users", "Get user info", """
        user_id str       Canvas user ID, or 'self'
        --include rep     e.g. avatar, enrollments
    """, lambda ns: get(f"/users/{quote(ns.user_id, safe='')}", {"include": ns.include})),

    ("outcomes", "List course outcomes", """
        course_id int
    """, lambda ns: paginate(f"/courses/{ns.course_id}/outcomes")),

    ("progress", "Check an async operation's progress", """
        progress_id int
    """, lambda ns: get(f"/progress/{ns.progress_id}")),
]

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canvas_cli.py",
        description="Canvas LMS CLI - High Performance Deterministic LMS Gateway",
        epilog="Default output is JSON. Use --table, --project, or --out to shield context tokens.",
    )
    parser.add_argument("--format", "-f", choices=["json", "table", "ids"], default="json", help="Output format")
    parser.add_argument("--table", "-t", action="store_true", help="Shorthand for --format table")
    parser.add_argument("--project", "-p", help="Comma-separated keys to project (e.g. id,name,due_at)")
    parser.add_argument("--out", "-o", help="Buffer full response to disk file and return concise receipt")
    parser.add_argument("--limit", "-n", type=int, metavar="LIMIT", help="Limit number of returned records")

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for name, description, spec, handler in COMMANDS:
        p = sub.add_parser(name, help=description, description=description)
        positionals, optionals = build_args(spec)
        for arg_name, opts in positionals:
            p.add_argument(arg_name, **opts)
        for flags, opts in optionals:
            p.add_argument(*flags, **opts)
        p.set_defaults(func=handler)
    return parser

def main() -> None:
    parser = build_parser()
    ns = parser.parse_args()
    if not getattr(ns, "func", None):
        parser.print_help()
        return

    try:
        data = ns.func(ns)
        render_output(data, ns)
    except CanvasHTTPError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except CanvasError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
