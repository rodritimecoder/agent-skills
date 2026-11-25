#!/usr/bin/env python3
"""
git_sync.py - Disciplined 6-Stage Git Branch Synchronization Engine
Adapted from EricTechPro/super-board git-sync specification with deterministic security gates.

Stages:
  1. Look    - Verify working tree, upstream tracking, ahead/behind status.
  2. Guard   - Shield secrets (.env, keys, API tokens) and oversized blobs (>50MB).
  3. Commit  - Atomic path-specific staging (never 'git add -A').
  4. Gate    - Auto-discover & run fast repository checks (lint/typecheck/tests).
  5. Pull    - Safe merge pull (--no-rebase) with conflict shielding.
  6. Push    - Safe non-force push (with protected branch confirmation).
  7. Report  - Clean structured receipt of all actions.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def render_table(rows: list[dict], columns: list[str] | None = None, headers: list[str] | None = None) -> str:
    if not rows:
        return "*(no records)*\n"
    if columns is None:
        columns = list(rows[0].keys())
    if headers is None:
        headers = [col.replace("_", " ").title() for col in columns]

    col_widths = [len(h) for h in headers]
    for r in rows:
        for idx, col in enumerate(columns):
            val_str = str(r.get(col, "")).replace("\n", " ").strip()
            if len(val_str) > col_widths[idx]:
                col_widths[idx] = len(val_str)

    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * col_widths[i] for i in range(len(headers))) + " |"
    row_lines = []
    for r in rows:
        row_str = "| " + " | ".join(str(r.get(col, "")).replace("\n", " ").strip().ljust(col_widths[i]) for i, col in enumerate(columns)) + " |"
        row_lines.append(row_str)
    return "\n".join([header_line, sep_line] + row_lines) + "\n"

def run_git(args: list[str], check: bool = True, capture: bool = True, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, check=check, text=True, capture_output=capture, cwd=cwd)


GROUPING_DIRS = {
    "glitch-cat", "orchestration", "engineering", "hardware",
    "multimodal", "academic", "archived",
}

MAX_SUBJECT = 72


def _scope_of(path: str) -> str:
    """The unit a reader cares about: the skill, not the domain holding it."""
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return "(root)"
    if parts[0] in GROUPING_DIRS and len(parts) >= 3:
        return parts[1]
    return parts[0]


def _delta(added: int, removed: int, binary: bool) -> str:
    return "binary" if binary else f"+{added}/-{removed}"


def staged_changes(repo: str = None) -> list[dict]:
    """Staged files with their line counts and the scope each belongs to."""
    res = run_git(["diff", "--cached", "--numstat", "-z", "--no-renames"], check=False, cwd=repo)
    changes = []
    for record in res.stdout.split("\0"):
        fields = record.split("\t")
        if len(fields) < 3 or not fields[2].strip():
            continue
        added, removed, path = fields[0], fields[1], fields[2]
        changes.append({
            "path": path,
            "added": int(added) if added.isdigit() else 0,
            "removed": int(removed) if removed.isdigit() else 0,
            "binary": added == "-",
            "scope": _scope_of(path),
        })
    return changes


def _group(changes: list[dict]) -> dict:
    scopes = {}
    for c in changes:
        entry = scopes.setdefault(c["scope"], {"files": [], "added": 0, "removed": 0, "binary": False})
        entry["files"].append(c["path"])
        entry["added"] += c["added"]
        entry["removed"] += c["removed"]
        entry["binary"] = entry["binary"] or c["binary"]
    return scopes


def _rank(scopes: dict) -> list[str]:
    return sorted(scopes, key=lambda s: (s == "(root)", -len(scopes[s]["files"]), s))


def _build_subject(prefix: str, scopes: dict, total: int, delta: str) -> str:
    ranked = _rank(scopes)
    primary, others = ranked[0], ranked[1:]

    if total == 1:
        name = Path(scopes[primary]["files"][0]).name
        where = "" if primary == "(root)" else f"({primary})"
        return f"{prefix}{where}: {name} ({delta})"

    noun = f"{total} file{'' if total == 1 else 's'}"
    candidates = []
    for names in ([primary] + others[:1], [primary], []):
        more = len(ranked) - len(names)
        shown = ["root" if n == "(root)" else n for n in names]
        where = ""
        if shown:
            where = "(" + ", ".join(shown) + (f" +{more}" if more else "") + ")"
        candidates.append(f"{prefix}{where}: {noun} ({delta})")
        candidates.append(f"{prefix}{where}: {noun}")

    for candidate in candidates:
        if len(candidate) <= MAX_SUBJECT:
            return candidate
    return candidates[-1][:MAX_SUBJECT - 1] + "…"


def staged_subject(repo: str = None, prefix: str = "chore") -> str:
    """A subject naming what moved.

    Derived from the diff rather than from a clock: a timestamp already lives
    in the commit object, and a fixed template leaves `git log` unsearchable.
    The subject carries the scope, the file count and the delta; the paths
    themselves go in the body written by `compose_message`.
    """
    changes = staged_changes(repo)
    if not changes:
        return f"{prefix}: sync working tree"

    scopes = _group(changes)
    added = sum(c["added"] for c in changes)
    removed = sum(c["removed"] for c in changes)
    binary = any(c["binary"] for c in changes)
    return _build_subject(prefix, scopes, len(changes), _delta(added, removed, binary))


CONVENTIONAL_SUBJECT = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(\([^)]+\))?!?: \S"
)

JARGON_TERMS = frozenset("wip todo fixme tmp asdf foo bar baz xxx".split())
_JARGON_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in sorted(JARGON_TERMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_MANIFEST_BULLET_RE = re.compile(r"^[-*] .+ \((?:\+\d+/-\d+|binary)\)$")
_MANIFEST_TOKEN_RE = re.compile(r"\(\+\d+/-\d+\)")
_GENERATED_DELTA_RE = re.compile(r" \(\+\d+/-\d+\)$| \(binary\)$")
_GENERATED_FILES_RE = re.compile(r"\d+ files?(?: \(\+\d+/-\d+\))?")

DEFAULT_WRAP_WIDTH = 80
DEFAULT_MAX_TITLE = 120
DEFAULT_TINY_DIFF_LINES = 3
DEFAULT_TINY_DIFF_FILES = 1
DEFAULT_TINY_BODY_CHARS = 600
DEFAULT_LARGE_DIFF_LINES = 100
DEFAULT_LARGE_BODY_CHARS = 80


def _manifest(changes: list[dict]) -> str:
    """The paths the subject only counted, one bullet each.

    A subject says "6 files (+19/-5)"; it never says which six. The manifest
    is the part `git log --oneline` compresses away and a reader needs when
    scanning history outside GitHub's changed-files view. It is also the body
    of last resort: a generated commit with no author prose still has to
    describe itself.
    """
    if not changes:
        return ""
    return "\n".join(
        f"- {c['path']} ({_delta(c['added'], c['removed'], c['binary'])})"
        for c in sorted(changes, key=lambda c: c["path"])
    )


def compose_message(repo: str = None, message: str = None, prefix: str = "chore") -> str:
    """The one commit shape every entry point emits.

    Every commit gets a body, because a subject is a receipt and the body is
    the description. Who supplies it depends on the message:

    - a conventional header with prose: the author's message, verbatim;
    - a conventional header alone: the header, then the manifest;
    - prose without a header: the derived subject, then the prose;
    - no message: the derived subject, then the manifest.

    Only the generated cases get a manifest. An author who wrote paragraphs
    has already described the change, and `git show --stat` still answers
    "which files" for them.
    """
    prose = (message or "").strip()
    subject = staged_subject(repo, prefix)
    manifest = _manifest(staged_changes(repo))

    if prose and CONVENTIONAL_SUBJECT.match(prose):
        if estimate_body(prose):
            return prose
        return prose + "\n\n" + manifest if manifest else prose

    parts = [subject]
    if prose:
        parts.append(prose)
    elif manifest:
        parts.append(manifest)
    return "\n\n".join(parts)


def estimate_body(message: str) -> bool:
    """Does this commit message already carry a body below its subject?"""
    _, _, body = message.partition("\n\n")
    return bool(body.strip())


def commits_without_body(upstream: str | None = None, repo: str = None) -> list[tuple[str, str]]:
    """Commits about to be pushed whose body is empty.

    The composer cannot reach a commit made outside its entry points, so this
    is the gate that makes "every commit has a description" true rather than
    aspirational. Merge commits are exempt: git writes their message.
    """
    args = ["log", "--format=%H%x1f%s%x1f%b%x1e"]
    if upstream:
        args.append(f"{upstream}..HEAD")
    else:
        args += ["HEAD", "--not", "--remotes"]
    res = run_git(args, check=False, cwd=repo)
    missing = []
    for record in res.stdout.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, rest = record.partition("\x1f")
        subject, _, body = rest.partition("\x1f")
        if subject.startswith("Merge "):
            continue
        if not body.strip():
            missing.append((sha[:7], subject))
    return missing


def read_commit_records(repo: str = None, upstream: str | None = None, limit: int = 20) -> list[dict]:
    """One bounded git log plus one diff-tree per commit.

    The framing and range match `commits_without_body()` so every gate reads
    the same set of outgoing commits. Merge subjects stay in the result marked
    `is_merge` for reporting, but the audit skips them: git writes their text.
    """
    if repo is not None and not Path(repo).is_dir():
        raise RuntimeError(f"repository not found: {repo}")
    args = ["log", "--no-merges", "--format=%H%x1f%s%x1f%b%x1e", "-n", str(limit)]
    if upstream:
        args.append(f"{upstream}..HEAD")
    else:
        args += ["HEAD", "--not", "--remotes"]
    res = run_git(args, check=False, cwd=repo)
    if res.returncode != 0:
        raise RuntimeError(f"git log failed: {res.stderr.strip() or res.stdout.strip()}")

    records = []
    for chunk in res.stdout.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        sha, _, rest = chunk.partition("\x1f")
        subject, _, body = rest.partition("\x1f")
        sha, subject = sha.strip(), subject.strip()
        files = added = removed = 0
        diff = run_git(
            ["diff-tree", "--no-commit-id", "--numstat", "-r", sha],
            check=False, cwd=repo,
        )
        if diff.returncode == 0:
            for line in diff.stdout.splitlines():
                fields = line.split("\t")
                if len(fields) < 3:
                    continue
                a, r, _path = fields[0], fields[1], fields[2]
                files += 1
                added += int(a) if a.isdigit() else 0
                removed += int(r) if r.isdigit() else 0
        records.append({
            "sha": sha,
            "subject": subject,
            "body": body.strip("\n"),
            "files": files,
            "added": added,
            "removed": removed,
            "is_merge": subject.startswith("Merge "),
        })
    return records


def _subject_parts(subject: str):
    """Return (scope, summary) from a subject, whether or not it is conventional."""
    head, _, tail = subject.partition(": ")
    open_i, close_i = head.find("("), head.rfind(")")
    scope = head[open_i + 1:close_i] if open_i != -1 and close_i > open_i else None
    return scope or None, tail


def _looks_generated_subject(subject: str) -> bool:
    if not CONVENTIONAL_SUBJECT.match(subject):
        return False
    tail = subject.partition(": ")[2].strip()
    return (tail == "sync working tree"
            or bool(_GENERATED_FILES_RE.fullmatch(tail))
            or bool(_GENERATED_DELTA_RE.search(tail)))


def _commit_kind(record: dict) -> str:
    """Composer fallback is a manifest; anything else is author prose."""
    override = record.get("kind")
    if override in ("author-written", "generated-manifest"):
        return override
    lines = [ln.strip() for ln in (record.get("body") or "").splitlines() if ln.strip()]
    if lines and all(_MANIFEST_BULLET_RE.fullmatch(ln) for ln in lines):
        return "generated-manifest"
    return "author-written"


def _paragraphs(body: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]


def audit_commit_messages(records: list[dict], *,
                          wrap_width: int = DEFAULT_WRAP_WIDTH,
                          max_title: int = DEFAULT_MAX_TITLE,
                          tiny_diff_lines: int = DEFAULT_TINY_DIFF_LINES,
                          tiny_diff_files: int = DEFAULT_TINY_DIFF_FILES,
                          tiny_body_chars: int = DEFAULT_TINY_BODY_CHARS,
                          large_diff_lines: int = DEFAULT_LARGE_DIFF_LINES,
                          large_body_chars: int = DEFAULT_LARGE_BODY_CHARS) -> list[dict]:
    """PURE: regex/length/threshold checks, no subprocess, model or clock."""
    findings = []
    for record in records:
        if record.get("is_merge"):
            continue
        sha = record.get("sha", "")
        subject = (record.get("subject") or "").strip()
        body = record.get("body") or ""
        kind = _commit_kind(record)
        author = kind == "author-written"
        conventional = bool(CONVENTIONAL_SUBJECT.match(subject))
        scope, tail = _subject_parts(subject)
        paragraphs = _paragraphs(body)
        body_chars = len(body.strip())

        def add(rule: str, field: str, line: int, message: str, severity: str = "block"):
            findings.append({
                "sha": sha, "rule": rule, "severity": severity,
                "field": field, "line": line, "message": message,
            })

        if not conventional:
            add("title-not-conventional", "title", 1,
                "title must use '<type>(<scope>): <lowercase summary>'")
        if not estimate_body(subject + "\n\n" + body):
            add("body-missing", "body", 1, "commit has no description body")
        if len(subject) > max_title:
            add("title-too-long", "title", 1,
                f"title is {len(subject)} chars (max {max_title})")

        if author:
            if scope is None:
                add("scope-missing", "title", 1, "title has no (scope)")
            else:
                scopes = scope.split(",")
                if len(scopes) > 4:
                    add("too-many-scopes", "title", 1,
                        f"scope lists {len(scopes)} components (max 4)")
                if any(not s or "/" in s or any(ch.isspace() for ch in s) for s in scopes):
                    add("scope-is-path", "title", 1,
                        "scope must be comma-separated component names, no paths or spaces")
            if tail and tail[0].isupper():
                add("title-capitalized", "title", 1,
                    "summary after ': ' must start lowercase")
            if subject.endswith("."):
                add("title-trailing-period", "title", 1, "title must not end with a period")

            head_jargon = _JARGON_RE.search(tail)
            body_jargon = _JARGON_RE.search(body)
            if head_jargon or body_jargon:
                hit = head_jargon or body_jargon
                add("internal-jargon", "title" if head_jargon else "body", 1,
                    f"mechanism-only word {hit.group(0)!r} is not user-facing copy")

            if "/" in tail or tail.lower().endswith((".py", ".md", ".toml")):
                add("subject-is-path", "title", 1, "summary must not be a bare file path")

            for line_no, line in enumerate(body.splitlines(), 1):
                if re.match(r"^[-*] ", line):
                    add("body-has-bullets", "body", line_no,
                        "user-facing body must be prose, not bullets")
                    break
            if _MANIFEST_TOKEN_RE.search(body):
                add("body-is-manifest", "body", 1,
                    "user-facing body contains a (+N/-M) manifest token")

            lower = max(40, wrap_width // 2)
            for para_no, para in enumerate(paragraphs, 1):
                lines = [ln.strip() for ln in para.splitlines() if ln.strip()]
                if len(lines) < 2:
                    continue
                lengths = [len(ln) for ln in lines]
                longest, last = max(lengths), lengths[-1]
                mean = sum(lengths) / len(lengths)
                joined = " ".join(lines)
                if (lower <= longest <= wrap_width and mean >= 0.8 * longest
                        and last < longest - 10 and len(joined) > wrap_width):
                    add("hard-wrapped", "body", para_no,
                        f"paragraph hard-wrapped near {longest} cols within a {wrap_width}-col gate")
                    break
        else:
            add("generated-manifest", "body", 1,
                "body is the generated file manifest, not user-facing prose", severity="warning")

        diff_lines = int(record.get("added", 0)) + int(record.get("removed", 0))
        file_count = int(record.get("files", 0))
        if (diff_lines <= tiny_diff_lines and file_count <= tiny_diff_files
                and (body_chars > tiny_body_chars or len(paragraphs) > 3)):
            add("message-too-long-for-change", "diff", 0,
                f"{body_chars} chars of message for a {diff_lines}-line, {file_count}-file change")
        if diff_lines >= large_diff_lines and body_chars < large_body_chars:
            add("message-too-short-for-change", "diff", 0,
                f"{body_chars} chars of message for a {diff_lines}-line change")
    return findings


def audit_report(records: list[dict], *, repo: str = None, upstream: str | None = None,
                 limit: int = 20, strict: bool = False) -> dict:
    """The shared JSON payload for both check-messages and audit --commits."""
    findings = audit_commit_messages(records)
    by_sha = {}
    for finding in findings:
        by_sha.setdefault(finding["sha"], []).append(
            {k: v for k, v in finding.items() if k != "sha"}
        )

    commits = []
    for record in records:
        if record.get("is_merge"):
            continue
        body = record.get("body") or ""
        commits.append({
            "sha": record.get("sha", ""),
            "title": record.get("subject") or "",
            "kind": _commit_kind(record),
            "body_chars": len(body.strip()),
            "paragraphs": len(_paragraphs(body)),
            "diff": {
                "files": int(record.get("files", 0)),
                "added": int(record.get("added", 0)),
                "removed": int(record.get("removed", 0)),
            },
            "findings": by_sha.get(record.get("sha", ""), []),
        })

    counts = {"block": 0, "warning": 0}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1

    return {
        "repo": str(Path(repo).resolve()) if repo else str(Path.cwd().resolve()),
        "range": f"{upstream}..HEAD" if upstream else "HEAD --not --remotes",
        "limit": limit,
        "strict": strict,
        "checked": len(commits),
        "skipped": {"merge": sum(1 for r in records if r.get("is_merge"))},
        "passed": counts["block"] == 0,
        "counts": counts,
        "thresholds": {
            "wrap_width": DEFAULT_WRAP_WIDTH,
            "max_title": DEFAULT_MAX_TITLE,
            "tiny_diff_lines": DEFAULT_TINY_DIFF_LINES,
            "tiny_diff_files": DEFAULT_TINY_DIFF_FILES,
            "tiny_body_chars": DEFAULT_TINY_BODY_CHARS,
            "large_diff_lines": DEFAULT_LARGE_DIFF_LINES,
            "large_body_chars": DEFAULT_LARGE_BODY_CHARS,
        },
        "commits": commits,
    }


def _parse_porcelain_paths(stdout: str) -> list[str]:
    """Extract paths from `git status --porcelain --untracked-files=all`.

    Git quotes paths containing spaces (or other special characters) with
    surrounding double quotes, and renders renames as ``old -> new``. Return
    the destination of a rename with any quote wrapper stripped.
    """
    paths = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ")[-1].strip()
        if len(path) >= 2 and path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if path:
            paths.append(path)
    return paths


def stage1_look() -> dict:
    # 1. Branch name
    res = run_git(["branch", "--show-current"])
    branch = res.stdout.strip()
    if not branch:
        sys.exit("❌ Error: Detached HEAD state. Please switch to a branch before syncing.")

    # 2. Check for active rebase/merge/cherry-pick
    git_dir = Path(run_git(["rev-parse", "--git-dir"]).stdout.strip())
    if (git_dir / "MERGE_HEAD").is_file():
        sys.exit("❌ Error: A merge is currently in progress. Resolve or abort before running git-sync.")
    if (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir():
        sys.exit("❌ Error: A rebase is currently in progress. Complete or abort before running git-sync.")
    if (git_dir / "CHERRY_PICK_HEAD").is_file():
        sys.exit("❌ Error: A cherry-pick is currently in progress.")

    # 3. Check upstream tracking
    has_upstream = False
    ahead, behind = 0, 0
    try:
        up_res = run_git(["rev-parse", "--abbrev-ref", "@{upstream}"])
        upstream = up_res.stdout.strip()
        has_upstream = bool(upstream)
        run_git(["fetch"], check=False)
        count_res = run_git(["rev-list", "--left-right", "--count", "HEAD...@{upstream}"])
        parts = count_res.stdout.strip().split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])
    except subprocess.CalledProcessError:
        upstream = None

    # 4. Check status
    # --untracked-files=all: git collapses a new directory to one "dir/"
    # entry, and a directory is not a file, so the guard would scan nothing
    # while `git add dir/` stages everything inside it.
    status_res = run_git(["status", "--porcelain", "--untracked-files=all"])
    changed_files = _parse_porcelain_paths(status_res.stdout)

    return {
        "branch": branch,
        "upstream": upstream,
        "has_upstream": has_upstream,
        "ahead": ahead,
        "behind": behind,
        "changed_files": changed_files,
    }


def stage2_guard(changed_files: list[str], repo: str = None) -> list[str]:
    scan_file = _load_publication_guard()
    safe_files = []
    blocked_files = []

    for f_str in changed_files:
        target = Path(f_str) if repo is None else Path(repo) / f_str
        if not target.is_file():
            # A deleted path has nothing to scan; treating it as missing from
            # disk is the whole point of staging its removal.
            safe_files.append(f_str)
            continue
        findings = scan_file(target, "git-sync")
        if findings:
            blocked_files.append((f_str, findings[0]["detail"]))
        else:
            safe_files.append(f_str)

    if blocked_files:
        print("\n🛡️  [Security Guard] Blocked files from staging:")
        for bf, reason in blocked_files:
            print(f"   ❌ {bf} — {reason}")

    return safe_files, blocked_files


def stage3_commit(safe_files: list[str], message: str = None, repo: str = None) -> list[str]:
    committed_shas = []
    if not safe_files:
        return committed_shas

    # Stage explicitly by path (NEVER git add -A or git add .)
    for f in safe_files:
        target = Path(f) if repo is None else Path(repo) / f
        if not target.exists():
            run_git(["rm", "--cached", "--", f], check=False, cwd=repo)
        elif run_git(["check-ignore", "-q", "--", f], check=False, cwd=repo).returncode == 0:
            # Ignored on purpose (e.g. .apiv snapshots untracked from the index).
            # `git add` would either abort on the ignore rule or resurrect the
            # file; the staged deletion is already the whole intent.
            continue
        else:
            run_git(["add", "--", f], cwd=repo)

    commit_msg = compose_message(repo, message)
    if not estimate_body(commit_msg):
        raise RuntimeError(
            f"refusing to commit without a description: {commit_msg.splitlines()[0]!r}"
        )

    res = run_git(["commit", "-m", commit_msg], cwd=repo)
    # Extract SHA
    sha_res = run_git(["rev-parse", "--short", "HEAD"], cwd=repo)
    committed_shas.append((sha_res.stdout.strip(), commit_msg))
    return committed_shas


def stage4_gate():
    """Run fast repository quality checks before pulling/pushing."""
    root = Path.cwd()
    checks_run = []

    # 1. Node / TypeScript checks
    if (root / "package.json").is_file():
        # Check typecheck
        pkg_content = (root / "package.json").read_text(encoding="utf-8", errors="replace")
        if '"typecheck"' in pkg_content:
            checks_run.append("npm run typecheck")
            subprocess.run(["npm", "run", "typecheck"], check=True)
        elif '"test"' in pkg_content and '"test": "echo' not in pkg_content:
            checks_run.append("npm test")
            subprocess.run(["npm", "test"], check=True)

    # 2. Python checks
    elif (root / "pytest.ini").is_file() or (root / "pyproject.toml").is_file():
        if shutil.which("pytest") and (root / "tests").is_dir():
            checks_run.append("pytest")
            subprocess.run(["pytest", "-q"], check=True)

    # 3. Rust checks
    elif (root / "Cargo.toml").is_file():
        if shutil.which("cargo"):
            checks_run.append("cargo test")
            subprocess.run(["cargo", "test", "--quiet"], check=True)

    # 4. Go checks
    elif (root / "go.mod").is_file():
        if shutil.which("go"):
            checks_run.append("go test")
            subprocess.run(["go", "test", "./..."], check=True)

    return checks_run


def stage5_pull(upstream: str):
    if not upstream:
        return "No upstream tracking branch"

    # Merge pull (--no-rebase per super-board specification)
    res = run_git(["pull", "--no-rebase"], check=False)
    if res.returncode != 0:
        sys.exit(f"❌ Error: Merge conflict detected during pull:\n{res.stdout}\n{res.stderr}\nPlease resolve conflicts manually.")
    return "Clean merge (up to date)"


def stage6_push(branch: str, has_upstream: bool, auto_yes: bool = False):
    upstream = None
    if has_upstream:
        up = run_git(["rev-parse", "--abbrev-ref", "@{upstream}"], check=False)
        upstream = up.stdout.strip() or None

    missing = commits_without_body(upstream)
    if missing:
        listing = "\n".join(f"   {sha} {subject}" for sha, subject in missing)
        sys.exit(
            f"❌ Refusing to push {len(missing)} commit(s) with no description:\n"
            f"{listing}\n"
            f"   Amend each message (`git commit --amend`), then retry."
        )

    is_protected = branch in ("main", "master", "production")
    if is_protected and not auto_yes:
        # Structural contract: confirmation comes from --yes/-y, never stdin.
        sys.exit(
            f"❌ Refusing to push to protected branch '{branch}' without confirmation.\n"
            f"   Re-run with -y/--yes to confirm, or push manually."
        )

    if not has_upstream:
        run_git(["push", "-u", "origin", branch])
    else:
        run_git(["push"])


def _load_publication_guard():
    try:
        from publication_guard import scan_file
        return scan_file
    except ImportError:
        import importlib.util
        script_path = Path(__file__).resolve().parent / "publication_guard.py"
        spec = importlib.util.spec_from_file_location("publication_guard", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.scan_file


def _load_exclude_matcher():
    try:
        from publication_guard import is_excluded
        return is_excluded
    except ImportError:
        import importlib.util
        script_path = Path(__file__).resolve().parent / "publication_guard.py"
        spec = importlib.util.spec_from_file_location("publication_guard", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.is_excluded


def changed_files_in(repo: str) -> list[str]:
    """Every path the working tree differs on, including untracked files."""
    res = run_git(["status", "--porcelain", "--untracked-files=all"], check=False, cwd=repo)
    return _parse_porcelain_paths(res.stdout)


def _matches_patterns(rel_path: Path, patterns: list, is_excluded) -> bool:
    if is_excluded(rel_path, patterns):
        return True
    rel_str = str(rel_path)
    for pattern in patterns:
        norm = pattern.rstrip("/")
        if not norm:
            continue
        if "/" in norm:
            if rel_str == norm or rel_str.startswith(norm + "/"):
                return True
        elif pattern.endswith("/"):
            if norm in rel_path.parts[:-1]:
                return True
        elif norm in rel_path.parts:
            return True
    return False


def guarded_commit(repo: str, message: str, excludes: list = None, includes: list = None) -> dict:
    """Stage and commit only the files that pass the secret guard.

    The content scan reads whole files rather than diffs: a brand-new file is
    untracked, so `git diff HEAD` shows nothing for it and a secret planted
    in a new file would sail straight through a diff-based guard.
    """
    scan_file = _load_publication_guard()
    is_excluded = _load_exclude_matcher()
    excludes = excludes or []
    includes = includes or []
    files = changed_files_in(repo)
    safe, blocked = [], []
    for rel in files:
        rel_path = Path(rel)
        if excludes and _matches_patterns(rel_path, excludes, is_excluded):
            continue
        if includes and not _matches_patterns(rel_path, includes, is_excluded):
            continue
        target = Path(repo) / rel
        if not target.is_file():
            # A deletion or a rename source: nothing to scan, and its absence
            # is the point.
            safe.append(rel)
            continue
        findings = scan_file(target, "hub")
        if findings:
            blocked.append((rel, findings[0]["detail"]))
        else:
            safe.append(rel)

    if blocked:
        print("🛡️  [guard] Blocked files from staging:", file=sys.stderr)
        for rel, reason in blocked:
            print(f"   ❌ {rel} — {reason}", file=sys.stderr)
        return {"committed": [], "blocked": blocked, "safe": safe}

    committed = stage3_commit(safe, message=message, repo=repo) if safe else []
    return {"committed": committed, "blocked": [], "safe": safe}


def cmd_guarded_commit(args) -> int:
    result = guarded_commit(args.repo, args.message, args.exclude, args.include)
    if args.json:
        print(json.dumps({
            "repo": args.repo,
            "committed": [c[0] for c in result["committed"]],
            "blocked": [{"path": p, "reason": r} for p, r in result["blocked"]],
            "staged": len(result["safe"]),
        }, indent=2))
    else:
        if result["blocked"]:
            print(f"🛑 [guard] {len(result['blocked'])} file(s) blocked; nothing committed.")
        else:
            print(f"✅ [guard] committed {len(result['safe'])} file(s) in {args.repo}")
    return 2 if result["blocked"] else 0


def cmd_check_messages(args) -> int:
    repo = args.repo
    strict = getattr(args, "strict", False)
    as_json = getattr(args, "json", False)
    limit = getattr(args, "limit", 20)
    upstream = args.upstream
    if not upstream:
        up = run_git(["rev-parse", "--abbrev-ref", "@{upstream}"], check=False, cwd=repo)
        upstream = up.stdout.strip() or None

    if not (strict or as_json):
        missing = commits_without_body(upstream, repo=repo)
        if missing:
            listing = "\n".join(f"  {sha} {subject}" for sha, subject in missing)
            print(f"❌ {len(missing)} commit(s) with no description:\n{listing}")
            return 1
        print("✅ Every outgoing commit has a description.")
        return 0

    try:
        records = read_commit_records(repo, upstream, limit=limit)
    except (RuntimeError, OSError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    report = audit_report(records, repo=repo, upstream=upstream, limit=limit, strict=strict)

    if strict:
        blocks = report["counts"]["block"]
        report["passed"] = blocks == 0
        exit_code = 1 if blocks else 0
    else:
        missing = commits_without_body(upstream, repo=repo)
        report["passed"] = not missing
        exit_code = 1 if missing else 0

    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif exit_code:
        print(f"❌ Commit-message audit failed "
              f"({report['counts']['block']} block, {report['counts']['warning']} warning).")
        for commit in report["commits"]:
            for finding in commit["findings"]:
                print(f"  {commit['sha'][:7]} {finding['rule']} "
                      f"[{finding['severity']}] {finding['message']}")
    else:
        print(f"✅ Commit-message audit passed ({report['checked']} checked).")
    return exit_code


HOOK_TEMPLATE = """#!/usr/bin/env bash
# Managed by github-architect. Refuses a commit with no description, and
# blocks routing or sync regressions on the skills repo. Reach audit is advisory.
repo="$(git rev-parse --show-toplevel)"
python3 "{script}" check-messages --repo "$repo"
rc=$?
if [ "$repo" = "{skills_repo}" ]; then
  gate="{gate}"
  if [ -f "$gate" ]; then
    python3 "$gate" || grc=$?
    grc=${{grc:-0}}
    [ "$rc" -eq 0 ] && rc=$grc
  fi
  sync_skills="{skills_repo}/sync_skills.sh"
  if [ -f "$sync_skills" ]; then
    bash "$sync_skills" verify || src=$?
    src=${{src:-0}}
    [ "$rc" -eq 0 ] && rc=$src
    if [ "$src" -ne 0 ]; then
      echo "❌ sync-skills verify failed: surface and harness copies disagree. Fix before pushing." >&2
    fi
  fi
fi
audit="{audit}"
if [ -f "$audit" ]; then
  python3 "$audit" --repo "$repo" >/dev/null 2>&1 || true
fi
exit $rc
"""


def cmd_install_hook(args) -> int:
    root = Path(args.repo).resolve()
    hook = root / ".git" / "hooks" / "pre-push"
    if hook.exists():
        text = hook.read_text(errors="ignore")
        if "github-architect" not in text and not args.force:
            print(f"❌ {hook} exists and was not written by github-architect. Pass --force to replace it.")
            return 1
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(HOOK_TEMPLATE.format(script=Path(__file__).resolve(), skills_repo=Path(__file__).resolve().parents[3], gate=Path(__file__).resolve().parent.parent / ".." / "omnicli" / "tests" / "routing_gate.py", audit=Path(__file__).resolve().parent.parent / ".." / "omnicli" / "tests" / "reach_audit.py"))
    hook.chmod(0o755)
    print(f"🪝 Installed pre-push description gate at {hook}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    epilog = (
        "Exit codes: 0 success; 1 runtime/validation error; "
        "2 invalid arguments (usage error); other non-zero values are script-specific."
    )
    parser = argparse.ArgumentParser(
        epilog=epilog,
        prog="git-sync",
        description="Disciplined 6-Stage Git Branch Synchronization Engine (Look -> Guard -> Commit -> Gate -> Pull -> Push -> Report)",
    )
    parser.add_argument("-m", "--message", help="Commit message (default: auto conventional summary)")
    parser.add_argument("-y", "--yes", action="store_true", help="Auto-confirm push to protected default branches (main/master)")
    parser.add_argument("--no-pull", action="store_true", help="Skip pulling from remote before pushing")
    parser.add_argument("--no-gate", action="store_true", help="Skip pre-push automated test/lint gates")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and display actions without committing or pushing")

    parser.add_argument("--table", "-t", action="store_true", help="Emit receipt as Markdown table")
    parser.add_argument("--json", action="store_true", help="Emit receipt as JSON")

    sub = parser.add_subparsers(dest="command", required=False)

    cp = sub.add_parser(
        "check-messages",
        epilog=epilog,
        help="Fail if any outgoing commit has no description body",
        description="Fail if any outgoing commit has no description body",
    )
    cp.add_argument("--repo", default=".", help="Repository to inspect")
    cp.add_argument("--upstream", help="Range start (default: @{upstream})")
    cp.add_argument("--strict", action="store_true", help="Run the full user-facing message audit")
    cp.add_argument("--json", action="store_true", help="Emit a JSON audit report")
    cp.add_argument("--limit", type=int, default=20, help="Maximum commits to inspect (default: 20)")

    ip = sub.add_parser(
        "install-hook",
        epilog=epilog,
        help="Install the pre-push description gate",
        description="Install the pre-push description gate",
    )
    ip.add_argument("--repo", default=".", help="Repository to install into")
    ip.add_argument("--force", action="store_true", help="Replace a foreign pre-push hook")

    gp = sub.add_parser(
        "guarded-commit",
        epilog=epilog,
        help="Stage and commit only the files that pass the secret guard",
        description="Stage and commit only the files that pass the secret guard",
    )
    gp.add_argument("--repo", required=True, help="Repository to commit in")
    gp.add_argument("-m", "--message", help="Commit message (default: derived from the staged diff)")
    gp.add_argument("--exclude", action="append", default=[], help="rsync-style exclude pattern (repeatable)")
    gp.add_argument("--include", action="append", default=[], help="only stage paths matching pattern/prefix (repeatable)")
    gp.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "check-messages":
        return cmd_check_messages(args)
    if args.command == "install-hook":
        return cmd_install_hook(args)
    if args.command == "guarded-commit":
        return cmd_guarded_commit(args)
    # Stage 1: Look
    look_info = stage1_look()
    branch = look_info["branch"]
    changed = look_info["changed_files"]

    if not changed and look_info["ahead"] == 0 and look_info["behind"] == 0:
        if args.json:
            print(json.dumps({"status": "clean", "branch": branch, "message": "Branch is clean and in sync with remote."}, indent=2))
        else:
            print(f"✨ Branch '{branch}' is clean and in sync with remote.")
        return 0

    # Stage 2: Guard
    safe_files, blocked_files = stage2_guard(changed)

    if args.dry_run:
        if args.json:
            print(json.dumps({
                "status": "dry_run",
                "branch": branch,
                "safe_files": safe_files,
                "blocked_files": blocked_files,
                "ahead": look_info["ahead"],
                "behind": look_info["behind"]
            }, indent=2))
        else:
            print(f"\n🔍 [git-sync DRY-RUN] Status for branch '{branch}':")
            print(f"   Safe to stage ({len(safe_files)}): {', '.join(safe_files) if safe_files else 'none'}")
            print(f"   Blocked ({len(blocked_files)}): {', '.join([f[0] for f in blocked_files]) if blocked_files else 'none'}")
            print(f"   Ahead: {look_info['ahead']} | Behind: {look_info['behind']}")
        return 0

    # Stage 3: Commit
    committed = []
    if safe_files:
        committed = stage3_commit(safe_files, message=args.message)

    # Stage 4: Gate
    if not args.no_gate:
        try:
            gates = stage4_gate()
        except subprocess.CalledProcessError as e:
            sys.exit(f"❌ Error: Pre-push quality gate failed with exit code {e.returncode}. Commit created, but push halted.")

    # Stage 5: Pull
    pull_status = "Skipped"
    if not args.no_pull and look_info["has_upstream"]:
        pull_status = stage5_pull(look_info["upstream"])

    # Stage 6: Push
    stage6_push(branch, look_info["has_upstream"], auto_yes=args.yes)

    # Stage 7: Report
    if args.json:
        receipt = {
            "status": "ok",
            "branch": branch,
            "commits": [{"sha": sha, "message": msg} for sha, msg in committed],
            "pull": pull_status,
            "push": f"Pushed to {branch}",
            "blocked": [{"file": bf, "reason": r} for bf, r in blocked_files]
        }
        print(json.dumps(receipt, indent=2))
        return 0

    if args.table:
        rows = [
            {"step": "Branch", "status": branch, "details": look_info.get("upstream") or "local only"},
            {"step": "Commit", "status": f"{len(committed)} commit(s)" if committed else "Clean", "details": ", ".join(f"{s} {m}" for s, m in committed) if committed else "Working tree clean"},
            {"step": "Pull", "status": pull_status, "details": pull_status},
            {"step": "Push", "status": "Success", "details": f"Pushed upstream to {branch}"},
            {"step": "Left Out", "status": f"{len(blocked_files)} blocked" if blocked_files else "None", "details": ", ".join(bf for bf, _ in blocked_files) if blocked_files else "Clean"},
        ]
        print(f"### git-sync Receipt: `{branch}`\n")
        print(render_table(rows, ["step", "status", "details"]))
        return 0

    print("\n📋 \033[1m[git-sync Receipt]\033[0m")
    print("─" * 60)
    if committed:
        for sha, msg in committed:
            print(f"   Committed  : {sha} {msg}")
    else:
        print("   Committed  : None (clean working tree)")

    print(f"   Pull       : {pull_status}")
    print(f"   Push       : Successfully pushed to {branch}")

    if blocked_files:
        print("   Left out   :")
        for bf, reason in blocked_files:
            print(f"     • {bf} ({reason})")
    print("─" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
