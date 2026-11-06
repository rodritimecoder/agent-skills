#!/usr/bin/env python3
"""Offline unit checks for ed_cli.py using stubbed urllib (no network)."""
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

CLI_PATH = Path(__file__).resolve().parent / "ed_cli.py"

os.environ["ED_API_TOKEN"] = "test-token"
os.environ["ED_BASE_URL"] = "https://edstem.org/api/"

spec = importlib.util.spec_from_file_location("ed_cli", str(CLI_PATH))
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

fails = []

def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  -> {detail}" if not cond else ""))
    if not cond:
        fails.append(name)

# ── 1. Content XML Helpers ──────────────────────────────────────────────────
md_input = "# Heading 1\n\nParagraph with text.\n\n```c\nint main() { return 0; }\n```"
xml_out = cli.text_to_ed_xml(md_input)
check("text_to_ed_xml wraps in document version 2.0", '<document version="2.0">' in xml_out)
check("text_to_ed_xml extracts heading level 1", '<heading level="1">Heading 1</heading>' in xml_out)
check("text_to_ed_xml formats code-block with language", '<code-block language="c">' in xml_out)

plain_extracted = cli.ed_xml_to_plain_text(xml_out)
check("ed_xml_to_plain_text recovers heading text", "# Heading 1" in plain_extracted)
check("ed_xml_to_plain_text recovers code block", "int main() { return 0; }" in plain_extracted)

# ── 2. Deterministic Token Shielding Helpers ────────────────────────────────
sample_threads = [
    {
        "id": 101,
        "number": 1,
        "type": "question",
        "category": "Assessment 3",
        "title": "C Struct Padding",
        "author": "Alice",
        "replies": 3,
        "pinned": True,
        "created_at": "2026-10-15T10:00:00Z",
        "extra_bloat": "ignore me"
    },
    {
        "id": 102,
        "number": 2,
        "type": "post",
        "category": "General",
        "title": "Welcome to Week 5",
        "author": "Bob",
        "replies": 0,
        "pinned": False,
        "created_at": "2026-10-16T12:00:00Z",
        "extra_bloat": "ignore me"
    }
]

projected = cli.project_data(sample_threads, ["id", "title", "replies"])
check("project_data projects strictly requested keys",
      all(set(d.keys()) == {"id", "title", "replies"} for d in projected), str(projected))

tbl = cli.format_table(sample_threads)
check("format_table renders markdown pipe table",
      "| id  |" in tbl and "| C Struct Padding" in tbl and "|---" in tbl, tbl)

# ── 3. CLI Invocations with Mocked Network ──────────────────────────────────
class FakeResp:
    def __init__(self, payload):
        self.payload = payload
    def read(self):
        return json.dumps(self.payload).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

def run_cli(argv, response_payload):
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["ed_cli.py"] + argv), \
         mock.patch.object(cli, "urlopen", return_value=FakeResp(response_payload)), \
         mock.patch.object(sys, "stdout", out):
        cli.main()
    return out.getvalue()

def run_cli_responses(argv, response_payloads):
    out = io.StringIO()
    responses = [FakeResp(payload) for payload in response_payloads]
    with mock.patch.object(sys, "argv", ["ed_cli.py"] + argv), \
         mock.patch.object(cli, "urlopen", side_effect=responses), \
         mock.patch.object(sys, "stdout", out):
        cli.main()
    return out.getvalue()

mock_user_resp = {
    "user": {"id": 42, "name": "Rodrigo", "email": "rodrigo@example.com", "role": "student"},
    "realms": [{"name": "UTS"}],
    "courses": [
        {
            "course": {"id": 1001, "code": "48430", "name": "Fundamentals of C", "year": "2026", "session": "Spring", "status": "active"},
            "role": {"role": "student"}
        }
    ]
}

out_text = run_cli(["courses", "--table"], mock_user_resp)
check("courses --table renders markdown table", "| id   | code  | name" in out_text and "48430" in out_text, out_text)

mock_threads_resp = {
    "threads": [
        {
            "id": 501,
            "number": 12,
            "type": "question",
            "category": "Lab 4",
            "title": "Makefile compilation error",
            "user_id": 42,
            "reply_count": 2,
            "is_pinned": False,
            "created_at": "2026-10-15T08:00:00Z"
        }
    ],
    "users": [{"id": 42, "name": "Rodrigo"}]
}

out_text = run_cli(["threads", "1001", "--table"], mock_threads_resp)
check("threads --table renders clean markdown table", "| id  | number |" in out_text and "Makefile compilation error" in out_text, out_text)

out_text = run_cli(["threads", "1001", "--project", "id,title"], mock_threads_resp)
check("threads --project id,title projects keys", '"id": 501' in out_text and '"title": "Makefile compilation error"' in out_text and "category" not in out_text, out_text)

tmp_out = "/tmp/test_ed_out.json"
if os.path.exists(tmp_out):
    os.remove(tmp_out)
out_text = run_cli(["--out", tmp_out, "threads", "1001"], mock_threads_resp)
check("--out writes to disk file", os.path.exists(tmp_out))
check("--out returns concise 1-line receipt with count", "saved_to" in out_text and '"count": 1' in out_text, out_text)
if os.path.exists(tmp_out):
    os.remove(tmp_out)

mock_ws_resp = {
    "workspaces": [{"id": "workspace-1", "title": "Assessment 3", "type": "c", "user_id": 7}],
    "users": [{"id": 7, "name": "Timothy Perry"}],
}
lookup_client = SimpleNamespace(
    _request=mock.Mock(side_effect=[
        {"courses": [{"course": {"id": 1001, "code": "48430", "name": "Fundamentals of C"}}]},
        mock_ws_resp,
    ])
)
resolved = cli._resolve_workspace_id(lookup_client, "assessment 3")
check("workspace title resolves to its ID", resolved == "workspace-1", resolved)

ambiguous_client = SimpleNamespace(
    _request=mock.Mock(side_effect=[
        {"courses": [
            {"course": {"id": 1001, "code": "48430", "name": "Fundamentals of C"}},
            {"course": {"id": 1002, "code": "48441", "name": "Digital Systems"}},
        ]},
        mock_ws_resp,
        mock_ws_resp,
    ])
)
try:
    cli._resolve_workspace_id(ambiguous_client, "Assessment 3")
    ambiguous = False
except SystemExit as exc:
    ambiguous = "ambiguous" in str(exc) and "48430" in str(exc) and "48441" in str(exc)
check("duplicate workspace titles require an explicit choice", ambiguous)

mock_user_two_courses = {
    "courses": [
        {"course": {"id": 1001, "code": "48430", "name": "Fundamentals of C"}},
        {"course": {"id": 1002, "code": "48441", "name": "Digital Systems"}},
    ]
}
out_text = run_cli_responses(
    ["workspaces", "--search", "Tim", "--table"],
    [mock_user_two_courses, mock_ws_resp, {"workspaces": [], "users": []}],
)
check(
    "workspaces without course ID searches all enrolled courses",
    "Assessment 3" in out_text and "Timothy Perry" in out_text and "Fundamentals of C" in out_text,
    out_text,
)

helper_result = SimpleNamespace(returncode=0, stdout='[{"path":"/home/main.c"}]\n', stderr="")
with mock.patch.object(cli, "_resolve_workspace_id", side_effect=lambda client, selector: selector), \
     mock.patch.object(cli, "_run_workspace_helper", return_value=helper_result):
    out_text = run_cli(["workspace-files", "workspace-1"], {})
check("workspace-files prints captured helper output without crashing", '"/home/main.c"' in out_text, out_text)

helper_result = SimpleNamespace(returncode=0, stdout="int main(void) { return 0; }\n", stderr="")
with mock.patch.object(cli, "_resolve_workspace_id", side_effect=lambda client, selector: selector), \
     mock.patch.object(cli, "_run_workspace_helper", return_value=helper_result):
    out_text = run_cli(["workspace-cat", "workspace-1", "main.c"], {})
check("workspace-cat prints the captured workspace file contents", "int main(void)" in out_text, out_text)

with mock.patch.object(cli.shutil, "which", return_value="node"), \
     mock.patch.object(cli, "_workspace_helper_path", return_value=Path("ed_ws.js")), \
     mock.patch.object(cli.subprocess, "run", return_value=helper_result) as run_helper:
    cli._run_workspace_helper(["files", "workspace-1"])
check(
    "workspace helper captures text output for file commands",
    run_helper.call_args.kwargs.get("capture_output") is True and run_helper.call_args.kwargs.get("text") is True,
)

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURES: {fails}"))
sys.exit(1 if fails else 0)
