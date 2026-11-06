#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import workspace_sync

DEFAULT_BASE_URL = "https://edstem.org/api/"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

def load_env_file(filepath: Path) -> dict[str, str]:
    env_vars = {}
    if not filepath.is_file():
        return env_vars
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip().strip("\"'")
    except Exception:
        pass
    return env_vars

def get_config() -> tuple[str, str]:
    token = os.environ.get("ED_API_TOKEN")
    base_url = os.environ.get("ED_BASE_URL")

    candidates = [
        ENV_FILE,
        Path.home() / ".gemini/config/skills/edstem-cli/.env",
        Path.home() / ".pi/agent/skills/edstem-cli/.env",
        Path(".env"),
    ]

    for candidate in candidates:
        if candidate.is_file():
            file_vars = load_env_file(candidate)
            if not token:
                token = file_vars.get("ED_API_TOKEN")
            if not base_url:
                base_url = file_vars.get("ED_BASE_URL")
            if token and base_url:
                break

    if not base_url:
        base_url = DEFAULT_BASE_URL

    if not base_url.endswith("/"):
        base_url += "/"

    return token or "", base_url

def text_to_ed_xml(text: str) -> str:
    clean_text = text.strip()
    if clean_text.startswith("<document") and clean_text.endswith("</document>"):
        return clean_text

    paragraphs = clean_text.split("\n\n")
    xml_parts = ['<document version="2.0">']

    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if p.startswith("```") and p.endswith("```"):
            lines = p.split("\n")
            lang = lines[0][3:].strip()
            code_content = "\n".join(lines[1:-1])
            escaped_code = html.escape(code_content)
            if lang:
                xml_parts.append(f'<code-block language="{html.escape(lang)}">{escaped_code}</code-block>')
            else:
                xml_parts.append(f'<code-block>{escaped_code}</code-block>')
        elif p.startswith("#"):
            match = re.match(r"^(#{1,6})\s+(.*)$", p)
            if match:
                level = len(match.group(1))
                h_text = html.escape(match.group(2))
                xml_parts.append(f'<heading level="{level}">{h_text}</heading>')
            else:
                xml_parts.append(f'<paragraph>{html.escape(p)}</paragraph>')
        else:
            escaped = html.escape(p).replace("\n", "<break/>")
            xml_parts.append(f'<paragraph>{escaped}</paragraph>')

    xml_parts.append("</document>")
    return "".join(xml_parts)

def ed_xml_to_plain_text(xml_string: str) -> str:
    if not xml_string:
        return ""
    if not xml_string.startswith("<document"):
        return xml_string
    try:
        root = ET.fromstring(xml_string)
        parts = []

        def traverse(node):
            tag = node.tag.lower()
            if tag == "paragraph":
                text = "".join(node.itertext()).strip()
                if text:
                    parts.append(text)
            elif tag == "heading":
                level = node.attrib.get("level", "1")
                text = "".join(node.itertext()).strip()
                prefix = "#" * int(level) if level.isdigit() else "#"
                parts.append(f"{prefix} {text}")
            elif tag == "code-block":
                code = "".join(node.itertext())
                parts.append(f"```\n{code}\n```")
            elif tag in ("document", "list", "list-item"):
                for child in node:
                    traverse(child)
            else:
                text = "".join(node.itertext()).strip()
                if text:
                    parts.append(text)

        traverse(root)
        return "\n\n".join(parts)
    except Exception:
        return re.sub(r"<[^>]+>", " ", xml_string).strip()

class EdClient:
    def __init__(self, token: str, base_url: str):
        self.token = token
        self.base_url = base_url

    def _request(self, endpoint: str, method: str = "GET", params: dict | None = None, data: dict | None = None) -> dict:
        if not self.token:
            sys.stderr.write(
                "Error: ED_API_TOKEN is not set.\n"
                "Please generate a token from your Ed settings page:\n"
                "  - Australia / Global: https://edstem.org/settings/api-tokens\n"
                "  - US: https://edstem.org/us/settings/api-tokens\n"
                f"Then save it in {ENV_FILE} as ED_API_TOKEN=your_token\n"
            )
            sys.exit(1)

        clean_endpoint = endpoint.lstrip("/")
        full_url = urljoin(self.base_url, clean_endpoint)

        if params:
            valid_params = {k: v for k, v in params.items() if v is not None}
            if valid_params:
                full_url += ("&" if "?" in full_url else "?") + urlencode(valid_params)

        body = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "EdStem-CLI-Agent/1.0",
            "Accept": "application/json",
        }

        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = Request(full_url, data=body, headers=headers, method=method)

        try:
            with urlopen(req, timeout=30) as resp:
                raw_response = resp.read().decode("utf-8")
                if not raw_response:
                    return {"status": "ok"}
                return json.loads(raw_response)
        except HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            sys.stderr.write(f"HTTP Error {e.code} ({e.reason}) calling {full_url}\n")
            if err_body:
                sys.stderr.write(f"Server response: {err_body}\n")
            sys.exit(1)
        except URLError as e:
            sys.stderr.write(f"Network error calling {full_url}: {e.reason}\n")
            sys.exit(1)

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

def render_output(data: any, args: argparse.Namespace) -> None:
    limit = getattr(args, "limit", None)
    if limit is not None and isinstance(data, list):
        data = data[:limit]

    project_arg = getattr(args, "project", None)
    if project_arg:
        fields = [f.strip() for f in project_arg.split(",") if f.strip()]
        data = project_data(data, fields)

    out_file = getattr(args, "out", None)
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

    fmt = getattr(args, "format", "json")
    if getattr(args, "table", False):
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

def cmd_user(client: EdClient, args: argparse.Namespace):
    res = client._request("user")
    user = res.get("user", {})
    realms = res.get("realms", [])
    courses = res.get("courses", [])

    if args.summary or args.table:
        render_output({
            "user_id": user.get("id"),
            "name": user.get("name"),
            "email": user.get("email"),
            "role": user.get("role"),
            "realms": [r.get("name") for r in realms],
            "enrolled_course_count": len(courses)
        }, args)
    else:
        render_output(res, args)

def cmd_courses(client: EdClient, args: argparse.Namespace):
    res = client._request("user")
    course_entries = res.get("courses", [])

    courses_out = []
    for entry in course_entries:
        course = entry.get("course", {})
        role = entry.get("role", {}).get("role", "")
        courses_out.append({
            "id": course.get("id"),
            "code": course.get("code"),
            "name": course.get("name"),
            "year": course.get("year"),
            "session": course.get("session"),
            "role": role,
            "status": course.get("status")
        })

    if getattr(args, "summary", False) or getattr(args, "table", False) or getattr(args, "project", False):
        render_output(courses_out, args)
    else:
        render_output(course_entries, args)

def cmd_threads(client: EdClient, args: argparse.Namespace):
    params = {
        "limit": getattr(args, "limit", None) or 30,
        "offset": getattr(args, "offset", 0),
        "sort": getattr(args, "sort", "new"),
    }
    if getattr(args, "filter", None):
        params["filter"] = args.filter

    res = client._request(f"courses/{args.course_id}/threads", params=params)
    threads = res.get("threads", [])
    users = {u.get("id"): u.get("name") for u in res.get("users", [])}

    search_term = getattr(args, "search", None)
    if search_term:
        term = search_term.lower()
        threads = [
            t for t in threads
            if term in t.get("title", "").lower() or term in t.get("document", "").lower()
        ]

    compact = []
    for t in threads:
        compact.append({
            "id": t.get("id"),
            "number": t.get("number"),
            "type": t.get("type"),
            "category": t.get("category"),
            "title": t.get("title"),
            "author": users.get(t.get("user_id"), "Unknown"),
            "replies": t.get("reply_count"),
            "pinned": t.get("is_pinned"),
            "created_at": t.get("created_at")
        })

    if getattr(args, "summary", False) or getattr(args, "table", False) or getattr(args, "project", False):
        render_output(compact, args)
    else:
        render_output(res, args)

def cmd_thread(client: EdClient, args: argparse.Namespace):
    if args.course_id and args.number:
        endpoint = f"courses/{args.course_id}/threads/{args.number}"
    elif args.thread_id:
        endpoint = f"threads/{args.thread_id}"
    else:
        sys.stderr.write("Error: Must provide either <thread_id> or --course-id <id> with --number <num>\n")
        sys.exit(1)

    res = client._request(endpoint)
    thread = res.get("thread", {})

    if args.text_only:
        title = thread.get("title", "")
        category = thread.get("category", "")
        num = thread.get("number", "")
        body_text = ed_xml_to_plain_text(thread.get("content", ""))

        output = [
            f"=== [Thread #{num}] {title} ({category}) ===",
            f"Author ID: {thread.get('user_id')} | Date: {thread.get('created_at')}",
            "",
            body_text,
            "",
            f"--- Comments & Answers ({thread.get('reply_count', 0)}) ---"
        ]

        def dump_comments(comments_list, depth=0):
            indent = "  " * depth
            for c in comments_list:
                c_text = ed_xml_to_plain_text(c.get("content", ""))
                output.append(f"{indent}[Comment #{c.get('number')}] User {c.get('user_id')} ({c.get('created_at')}):")
                for line in c_text.splitlines():
                    output.append(f"{indent}  {line}")
                output.append("")
                if c.get("comments"):
                    dump_comments(c.get("comments"), depth + 1)

        dump_comments(thread.get("answers", []))
        dump_comments(thread.get("comments", []))
        print("\n".join(output))
    else:
        render_output(res, args)

def cmd_post(client: EdClient, args: argparse.Namespace):
    xml_content = text_to_ed_xml(args.content)
    payload = {
        "thread": {
            "type": args.type,
            "title": args.title,
            "category": args.category,
            "subcategory": args.subcategory or "",
            "subsubcategory": args.subsubcategory or "",
            "content": xml_content,
            "is_pinned": args.pinned,
            "is_private": args.private,
            "is_anonymous": args.anonymous,
            "is_megathread": False,
            "anonymous_comments": False,
        }
    }
    res = client._request(f"courses/{args.course_id}/threads", method="POST", data=payload)
    render_output(res, args)

def cmd_reply(client: EdClient, args: argparse.Namespace):
    xml_content = text_to_ed_xml(args.content)
    payload = {
        "comment": {
            "content": xml_content,
            "parent_id": args.parent_id,
            "is_anonymous": args.anonymous,
            "is_private": args.private
        }
    }
    res = client._request(f"threads/{args.thread_id}/comments", method="POST", data=payload)
    render_output(res, args)

def cmd_lock(client: EdClient, args: argparse.Namespace):
    res = client._request(f"threads/{args.thread_id}/lock", method="POST")
    render_output(res, args)

def cmd_unlock(client: EdClient, args: argparse.Namespace):
    res = client._request(f"threads/{args.thread_id}/unlock", method="POST")
    render_output(res, args)

def _workspace_rows(client: EdClient, course_id: int | None = None) -> tuple[list[dict], list[dict]]:
    if course_id is None:
        user = client._request("user")
        courses = [entry.get("course", {}) for entry in user.get("courses", [])]
        course_entries = [course for course in courses if course.get("id") is not None]
    else:
        course_entries = [{"id": course_id}]

    out = []
    raw_responses = []
    for course in course_entries:
        course_res = client._request(f"courses/{course['id']}/workspaces")
        raw_responses.append(course_res)
        users = {u.get("id"): u.get("name") for u in course_res.get("users", [])}
        for ws in course_res.get("workspaces", []):
            uid = ws.get("user_id")
            row = {
                "id": ws.get("id"),
                "title": ws.get("title"),
                "type": ws.get("type"),
                "author": users.get(uid, f"User {uid}"),
                "created_at": ws.get("created_at"),
                "opened_at": ws.get("opened_at"),
                "shared_at": ws.get("shared_at"),
            }
            if course_id is None:
                row["course_id"] = course.get("id")
                row["course_code"] = course.get("code")
                row["course"] = course.get("name")
            out.append(row)
    return out, raw_responses


def _resolve_workspace_id(client: EdClient, selector: str) -> str:
    selector = selector.strip()
    if not selector:
        raise SystemExit("Workspace selector cannot be empty.")

    rows, _ = _workspace_rows(client)
    by_id = [row for row in rows if str(row.get("id", "")).casefold() == selector.casefold()]
    if by_id:
        return str(by_id[0]["id"])

    term = selector.casefold()
    exact_title = [row for row in rows if str(row.get("title") or "").casefold() == term]
    exact_author = [row for row in rows if str(row.get("author") or "").casefold() == term]
    title_matches = exact_title or [
        row for row in rows if term in str(row.get("title") or "").casefold()
    ]
    matches = title_matches or exact_author or [
        row for row in rows if term in str(row.get("author") or "").casefold()
    ]
    if len(matches) == 1:
        return str(matches[0]["id"])
    if not matches:
        raise SystemExit(f"No workspace matched {selector!r}. Run 'workspaces --table' to browse.")

    choices = "\n".join(
        f"  {row.get('title')} — {row.get('course')} ({row.get('course_code')}) [ID: {row.get('id')}]"
        for row in matches
    )
    raise SystemExit(f"Workspace selector {selector!r} is ambiguous; choose one:\n{choices}")


def cmd_workspaces(client: EdClient, args: argparse.Namespace):
    course_id = getattr(args, "course_id", None)
    out, raw_responses = _workspace_rows(client, course_id)

    search_term = getattr(args, "search", None)
    if search_term:
        term = search_term.casefold()
        out = [
            row for row in out
            if any(term in str(row.get(key) or "").casefold() for key in ("title", "author", "course"))
        ]

    if course_id is None or getattr(args, "summary", False) or getattr(args, "table", False) or getattr(args, "project", False):
        render_output(out, args)
    else:
        render_output(raw_responses[0], args)

def cmd_workspace(client: EdClient, args: argparse.Namespace):
    workspace_id = _resolve_workspace_id(client, args.workspace_id)
    res = client._request(f"workspaces/{workspace_id}")
    if getattr(args, "connect", False):
        try:
            ticket_res = client._request(f"workspaces/{workspace_id}/connect", method="POST")
            res["ticket"] = ticket_res.get("ticket")
        except Exception as e:
            res["ticket_error"] = str(e)
    render_output(res, args)


def _workspace_helper_path() -> Path:
    return Path(__file__).resolve().parent / "ed_ws.js"


def _pull_workspace_snapshot(workspace_id: str):
    """Fetch the live workspace into an automatically cleaned temp directory."""
    node = shutil.which("node")
    if not node:
        raise workspace_sync.WorkspaceSyncError("node is required for workspace file access")
    helper = _workspace_helper_path()
    if not helper.is_file():
        raise workspace_sync.WorkspaceSyncError(f"workspace helper not found: {helper}")
    temporary = tempfile.TemporaryDirectory(prefix="ed-workspace-")
    result = subprocess.run(
        [node, str(helper), "pull", workspace_id, temporary.name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        temporary.cleanup()
        detail = (result.stderr or result.stdout).strip()
        raise workspace_sync.WorkspaceSyncError(detail or "workspace pull failed")
    return temporary, Path(temporary.name)


def _render_workspace_report(report: dict, repo: Path, show_diff: bool = False) -> None:
    print(f"Ed workspace: {report.get('workspace_id') or '(not recorded yet)'}")
    print(f"Repository: {repo}")
    for key, label in (("added", "Added"), ("changed", "Changed"), ("unchanged", "Unchanged"), ("removed", "Removed from Ed (not deleted)")):
        paths = report.get(key, [])
        print(f"{label}: {len(paths)}")
        for relative in paths:
            print(f"  {relative}")
    skipped = report.get("skipped", [])
    print(f"Skipped: {len(skipped)}")
    for item in skipped:
        print(f"  {item['path']} ({item['reason']})")
    if show_diff and report.get("changed"):
        diff = workspace_sync.unified_diff(report["snapshot"], repo, report)
        if diff:
            print("--- diff ---")
            print(diff, end="" if diff.endswith("\n") else "\n")


def cmd_workspace_diff(client: EdClient, args: argparse.Namespace):
    workspace_id = _resolve_workspace_id(client, args.workspace_id)
    repo = Path(args.repo).expanduser().resolve()
    try:
        temporary, snapshot = _pull_workspace_snapshot(workspace_id)
        try:
            report = workspace_sync.compare_snapshot(snapshot, repo)
            report["workspace_id"] = workspace_id
            report["snapshot"] = snapshot
            _render_workspace_report(report, repo, args.diff)
        finally:
            temporary.cleanup()
    except workspace_sync.WorkspaceSyncError as exc:
        raise SystemExit(f"workspace-diff: {exc}") from exc


def _git_sync_preflight(repo: Path) -> None:
    """Require an up-to-date tracking branch before a commit or push."""
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True, check=False
    )
    if branch.returncode != 0 or not branch.stdout.strip():
        raise workspace_sync.WorkspaceSyncError("repo must be on a named Git branch")
    upstream = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if upstream.returncode != 0:
        raise workspace_sync.WorkspaceSyncError("repo branch must track a remote before commit/push")
    fetched = subprocess.run(["git", "fetch", "--quiet"], cwd=repo, check=False)
    if fetched.returncode != 0:
        raise workspace_sync.WorkspaceSyncError("git fetch failed; refusing commit/push")
    divergence = subprocess.run(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...{upstream.stdout.strip()}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if divergence.returncode != 0:
        raise workspace_sync.WorkspaceSyncError("cannot compare local branch with its upstream")
    counts = divergence.stdout.split()
    if len(counts) != 2 or counts != ["0", "0"]:
        raise workspace_sync.WorkspaceSyncError(
            "local branch is ahead of or behind its remote; sync it before workspace update"
        )


def _run_sandbox_tests(repo: Path, snapshot: Path, workspace_id: str, commands: list[str]) -> None:
    """Test an applied copy in a network-isolated subagent-space."""
    sandbox = shutil.which("subagent-spaces")
    if not sandbox:
        raise workspace_sync.WorkspaceSyncError(
            "subagent-spaces is required to run workspace tests safely; apply without --commit instead"
        )
    with tempfile.TemporaryDirectory(prefix="ed-workspace-test-") as temporary:
        test_root = Path(temporary)
        workspace_sync.copy_tracked_repo(repo, test_root)
        workspace_sync.apply_snapshot(snapshot, test_root, workspace_id)
        for command in commands:
            result = subprocess.run(
                [
                    sandbox,
                    "run",
                    "--cpus",
                    "2",
                    "--memory",
                    "2g",
                    "--network",
                    "none",
                    "--workspace",
                    str(test_root),
                    "--",
                    "bash",
                    "-lc",
                    f"cd /workspace && {command}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            output = (result.stdout or "") + (result.stderr or "")
            print(f"Test command: {command}")
            if output:
                print(output[-6000:], end="" if output.endswith("\n") else "\n")
            if result.returncode != 0:
                raise workspace_sync.WorkspaceSyncError(
                    f"sandbox test failed ({result.returncode}); repository was not changed"
                )


def _guarded_commit(repo: Path, message: str) -> None:
    command = shutil.which("git-sync")
    if not command:
        raise workspace_sync.WorkspaceSyncError("git-sync is required for guarded commits")
    result = subprocess.run(
        [command, "guarded-commit", "--repo", str(repo), "-m", message, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        raise workspace_sync.WorkspaceSyncError("guarded commit failed; changes remain for review")
    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError as exc:
        raise workspace_sync.WorkspaceSyncError("git-sync returned invalid JSON") from exc
    if not payload.get("committed"):
        raise workspace_sync.WorkspaceSyncError("no changes were committed")


def _guarded_push(repo: Path) -> None:
    command = shutil.which("git-sync")
    if not command:
        raise workspace_sync.WorkspaceSyncError("git-sync is required for guarded pushes")
    result = subprocess.run(
        [command, "--yes", "--no-pull", "--no-gate", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        raise workspace_sync.WorkspaceSyncError("push failed; local commit remains")


def cmd_workspace_update(client: EdClient, args: argparse.Namespace):
    workspace_id = _resolve_workspace_id(client, args.workspace_id)
    repo = Path(args.repo).expanduser().resolve()
    if args.push and not args.commit:
        raise SystemExit("workspace-update: --push requires --commit")
    if args.commit and not args.apply:
        raise SystemExit("workspace-update: --commit requires --apply")
    if args.commit and not args.test_command:
        raise SystemExit("workspace-update: --commit requires at least one --test-command")

    try:
        temporary, snapshot = _pull_workspace_snapshot(workspace_id)
        try:
            report = workspace_sync.compare_snapshot(snapshot, repo)
            report["workspace_id"] = workspace_id
            report["snapshot"] = snapshot
            _render_workspace_report(report, repo, args.diff)
            if not args.apply:
                print("Preview only: no repository files changed. Re-run with --apply to proceed.")
                return
            workspace_sync.require_clean_git_repo(repo)
            if args.commit:
                _git_sync_preflight(repo)
                _run_sandbox_tests(repo, snapshot, workspace_id, args.test_command)
            result = workspace_sync.apply_snapshot(snapshot, repo, workspace_id)
            print(f"Applied {len(result['applied'])} file(s); removed files were not deleted.")
            print(f"Manifest: {result['manifest']}")
            if args.commit:
                _guarded_commit(repo, args.message)
                if args.push:
                    _guarded_push(repo)
        finally:
            temporary.cleanup()
    except workspace_sync.WorkspaceSyncError as exc:
        raise SystemExit(f"workspace-update: {exc}") from exc

def _run_workspace_helper(args: list[str], *, capture_output: bool = True) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if not node:
        raise SystemExit("node is required for workspace file access")
    return subprocess.run(
        [node, str(_workspace_helper_path())] + args,
        check=False,
        capture_output=capture_output,
        text=True,
    )


def cmd_workspace_files(client: EdClient, args: argparse.Namespace):
    workspace_id = _resolve_workspace_id(client, args.workspace_id)
    res = _run_workspace_helper(["files", workspace_id])
    if res.returncode != 0:
        sys.stderr.write(res.stderr or "Workspace file listing failed.\n")
        sys.exit(res.returncode)
    print((res.stdout or "").strip())


def cmd_workspace_cat(client: EdClient, args: argparse.Namespace):
    workspace_id = _resolve_workspace_id(client, args.workspace_id)
    res = _run_workspace_helper(["cat", workspace_id, args.file_path])
    if res.returncode != 0:
        sys.stderr.write(res.stderr or "Workspace file read failed.\n")
        sys.exit(res.returncode)
    sys.stdout.write(res.stdout or "")


def cmd_workspace_pull(client: EdClient, args: argparse.Namespace):
    workspace_id = _resolve_workspace_id(client, args.workspace_id)
    cmd = ["pull", workspace_id]
    if getattr(args, "dest", None):
        cmd.append(args.dest)
    res = _run_workspace_helper(cmd)
    if res.returncode != 0:
        sys.stderr.write(res.stderr or "Workspace pull failed.\n")
        sys.exit(res.returncode)
    print((res.stdout or "").strip())


def cmd_workspace_sync(client: EdClient, args: argparse.Namespace):
    workspace_id = _resolve_workspace_id(client, args.workspace_id)
    dest = getattr(args, "dest", None) or f"workspace_{workspace_id}"
    cmd = ["sync", workspace_id, dest]
    if getattr(args, "push", False):
        cmd.append("--push")
    if getattr(args, "once", False):
        cmd.append("--once")
    try:
        _run_workspace_helper(cmd, capture_output=False)
    except KeyboardInterrupt:
        print("\n[ed-sync] Watcher stopped.")

def cmd_lessons(client: EdClient, args: argparse.Namespace):
    res = client._request(f"courses/{args.course_id}/lessons")
    modules = {m.get("id"): m.get("name") for m in res.get("modules", [])}
    lessons = res.get("lessons", [])

    out = []
    for l in lessons:
        mid = l.get("module_id")
        out.append({
            "id": l.get("id"),
            "title": l.get("title"),
            "module": modules.get(mid, f"Module {mid}"),
            "kind": l.get("kind"),
            "due_at": l.get("due_at"),
            "slide_count": l.get("slide_count"),
        })

    search_term = getattr(args, "search", None)
    if search_term:
        term = search_term.lower()
        out = [x for x in out if term in x["title"].lower() or term in x["module"].lower()]

    if getattr(args, "summary", False) or getattr(args, "table", False) or getattr(args, "project", False):
        render_output(out, args)
    else:
        render_output(res, args)

def cmd_lesson(client: EdClient, args: argparse.Namespace):
    res = client._request(f"lessons/{args.lesson_id}")
    lesson = res.get("lesson", {})
    slides = lesson.get("slides", [])

    if getattr(args, "summary", False) or getattr(args, "table", False):
        slides_summary = []
        for s in slides:
            slides_summary.append({
                "id": s.get("id"),
                "title": s.get("title"),
                "type": s.get("type"),
                "challenge_id": s.get("challenge_id"),
                "content": ed_xml_to_plain_text(s.get("content", ""))[:300],
            })
        render_output({
            "id": lesson.get("id"),
            "title": lesson.get("title"),
            "due_at": lesson.get("due_at"),
            "slides": slides_summary,
        }, args)
    else:
        render_output(res, args)

def main():
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--format", "-f", choices=["json", "table", "ids"], default=argparse.SUPPRESS, help="Output format")
    common_parser.add_argument("--table", "-t", action="store_true", default=argparse.SUPPRESS, help="Shorthand for --format table")
    common_parser.add_argument("--project", "-p", default=argparse.SUPPRESS, help="Comma-separated keys to project (e.g. id,title,category)")
    common_parser.add_argument("--out", "-o", default=argparse.SUPPRESS, help="Buffer full response to disk file and return concise receipt")
    common_parser.add_argument("--limit", "-n", type=int, default=argparse.SUPPRESS, help="Limit number of returned records")

    parser = argparse.ArgumentParser(
        prog="ed_cli.py",
        description="EdStem CLI - High Performance Deterministic Discussion & Course Gateway",
        epilog="Default output is JSON. Use --table, --project, or --out to shield context tokens.",
        parents=[common_parser]
    )
    parser.add_argument("--token", help="Override ED_API_TOKEN")
    parser.add_argument("--base-url", help="Override ED_BASE_URL (default: https://edstem.org/api/)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_user = subparsers.add_parser("user", help="Get authenticated user info", parents=[common_parser])
    p_user.add_argument("--summary", action="store_true", help="Print compact summary")

    p_courses = subparsers.add_parser("courses", help="List enrolled courses", parents=[common_parser])
    p_courses.add_argument("--summary", action="store_true", help="Print clean course list")

    p_threads = subparsers.add_parser("threads", help="List threads in a course", parents=[common_parser])
    p_threads.add_argument("course_id", type=int, help="Course ID")
    p_threads.add_argument("--offset", type=int, default=0, help="Pagination offset")
    p_threads.add_argument("--sort", default="new", choices=["new", "top", "unanswered"], help="Sort order")
    p_threads.add_argument("--filter", help="Thread filter (e.g. unread, starred)")
    p_threads.add_argument("--search", help="Search keyword in titles and content")
    p_threads.add_argument("--summary", action="store_true", help="Compact listing")

    p_thread = subparsers.add_parser("thread", help="View thread and its replies", parents=[common_parser])
    p_thread.add_argument("thread_id", type=int, nargs="?", help="Global thread ID")
    p_thread.add_argument("--course-id", type=int, help="Course ID (when using with --number)")
    p_thread.add_argument("--number", type=int, help="Course-relative thread number")
    p_thread.add_argument("--text-only", action="store_true", help="Render as clean plain text")

    p_post = subparsers.add_parser("post", help="Create a new thread")
    p_post.add_argument("course_id", type=int, help="Course ID")
    p_post.add_argument("--title", required=True, help="Thread title")
    p_post.add_argument("--content", required=True, help="Thread body (markdown or plain text)")
    p_post.add_argument("--category", default="General", help="Category name (default: General)")
    p_post.add_argument("--subcategory", help="Subcategory name")
    p_post.add_argument("--subsubcategory", help="Sub-subcategory name")
    p_post.add_argument("--type", default="post", choices=["post", "question", "announcement"], help="Thread type")
    p_post.add_argument("--private", action="store_true", help="Make thread private (staff-only)")
    p_post.add_argument("--anonymous", action="store_true", help="Post anonymously to peers")
    p_post.add_argument("--pinned", action="store_true", help="Pin thread (staff only)")

    p_reply = subparsers.add_parser("reply", help="Reply to a thread")
    p_reply.add_argument("thread_id", type=int, help="Thread ID")
    p_reply.add_argument("--content", required=True, help="Reply body text")
    p_reply.add_argument("--parent-id", type=int, help="Parent comment ID for nested replies")
    p_reply.add_argument("--anonymous", action="store_true", help="Post anonymously")
    p_reply.add_argument("--private", action="store_true", help="Make comment private")

    p_lock = subparsers.add_parser("lock", help="Lock a thread")
    p_lock.add_argument("thread_id", type=int, help="Thread ID")

    p_unlock = subparsers.add_parser("unlock", help="Unlock a thread")
    p_unlock.add_argument("thread_id", type=int, help="Thread ID")

    p_workspaces = subparsers.add_parser("workspaces", help="List workspaces in one or all courses", parents=[common_parser])
    p_workspaces.add_argument("course_id", type=int, nargs="?", help="Course ID (omit to search all enrolled courses)")
    p_workspaces.add_argument("--search", help="Search by workspace title or author")
    p_workspaces.add_argument("--summary", action="store_true", help="Print summary list")

    p_workspace = subparsers.add_parser("workspace", help="Inspect workspace details")
    p_workspace.add_argument("workspace_id", metavar="workspace", help="Workspace ID, title, or author selector")
    p_workspace.add_argument("--connect", action="store_true", help="Fetch connection ticket")

    p_ws_files = subparsers.add_parser("workspace-files", help="List live files inside workspace container")
    p_ws_files.add_argument("workspace_id", metavar="workspace", help="Workspace ID, title, or author selector")

    p_ws_cat = subparsers.add_parser("workspace-cat", help="Print file buffer from live workspace container")
    p_ws_cat.add_argument("workspace_id", metavar="workspace", help="Workspace ID, title, or author selector")
    p_ws_cat.add_argument("file_path", help="File path inside container (e.g. Makefile, archive.h)")

    p_ws_pull = subparsers.add_parser("workspace-pull", help="Download all files from workspace container")
    p_ws_pull.add_argument("workspace_id", metavar="workspace", help="Workspace ID, title, or author selector")
    p_ws_pull.add_argument("--dest", help="Destination directory path (default: ./workspace_<id>)")

    p_ws_diff = subparsers.add_parser(
        "workspace-diff",
        help="Preview a workspace snapshot against a Git repo without changing files",
    )
    p_ws_diff.add_argument("workspace_id", metavar="workspace", help="Workspace ID, title, or author selector")
    p_ws_diff.add_argument("--repo", required=True, help="Local Git repository path")
    p_ws_diff.add_argument("--diff", action="store_true", help="Print unified text diffs for changed files")

    p_ws_update = subparsers.add_parser(
        "workspace-update",
        help="Safely apply a workspace snapshot to a clean Git repo",
    )
    p_ws_update.add_argument("workspace_id", metavar="workspace", help="Workspace ID, title, or author selector")
    p_ws_update.add_argument("--repo", required=True, help="Local Git repository path")
    p_ws_update.add_argument("--apply", action="store_true", help="Apply new and changed files (default: preview only)")
    p_ws_update.add_argument("--diff", action="store_true", help="Print unified text diffs before applying")
    p_ws_update.add_argument(
        "--test-command",
        action="append",
        default=[],
        help="Command to run in an isolated sandbox before commit (repeatable)",
    )
    p_ws_update.add_argument("--commit", action="store_true", help="Run tests, then guarded-commit (requires --apply)")
    p_ws_update.add_argument("--push", action="store_true", help="Push the guarded commit (requires --commit)")
    p_ws_update.add_argument("--message", default="edstem-cli: sync workspace snapshot", help="Commit message")

    p_ws_sync = subparsers.add_parser("workspace-sync", help="Sync workspace with a local git repo (watch or single pass)")
    p_ws_sync.add_argument("workspace_id", metavar="workspace", help="Workspace ID, title, or author selector")
    p_ws_sync.add_argument("--dest", help="Destination directory path (default: ./workspace_<id>)")
    p_ws_sync.add_argument("--push", action="store_true", help="Auto git push on new commits")
    p_ws_sync.add_argument("--once", action="store_true", help="Run once and exit instead of continuous watcher")

    p_lessons = subparsers.add_parser("lessons", help="List modules and lessons in a course", parents=[common_parser])
    p_lessons.add_argument("course_id", type=int, help="Course ID")
    p_lessons.add_argument("--search", help="Search by lesson or module name")
    p_lessons.add_argument("--summary", action="store_true", help="Print summary list")

    p_lesson = subparsers.add_parser("lesson", help="Inspect lesson and challenge content", parents=[common_parser])
    p_lesson.add_argument("lesson_id", type=int, help="Lesson ID")
    p_lesson.add_argument("--summary", action="store_true", help="Print clean summary of slides")

    args = parser.parse_args()

    default_token, default_url = get_config()
    token = args.token or default_token
    base_url = args.base_url or default_url

    client = EdClient(token=token, base_url=base_url)

    cmd_map = {
        "user": cmd_user,
        "courses": cmd_courses,
        "threads": cmd_threads,
        "thread": cmd_thread,
        "post": cmd_post,
        "reply": cmd_reply,
        "lock": cmd_lock,
        "unlock": cmd_unlock,
        "workspaces": cmd_workspaces,
        "workspace": cmd_workspace,
        "workspace-files": cmd_workspace_files,
        "workspace-cat": cmd_workspace_cat,
        "workspace-pull": cmd_workspace_pull,
        "workspace-diff": cmd_workspace_diff,
        "workspace-update": cmd_workspace_update,
        "workspace-sync": cmd_workspace_sync,
        "lessons": cmd_lessons,
        "lesson": cmd_lesson,
    }

    handler = cmd_map.get(args.command)
    if handler:
        handler(client, args)

if __name__ == "__main__":
    main()
