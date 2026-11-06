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

SECRET_FILE_PATTERNS = [
    r"^\.env(?!\.example$)",
    r"\.pem$",
    r"\.key$",
    r"^id_rsa",
    r"\.pfx$",
    r"\.p12$",
    r"credentials\.json$",
]

SECRET_CONTENT_PATTERNS = [
    (r"ghp_[A-Za-z0-9]{36}", "GitHub Personal Access Token"),
    (r"gho_[A-Za-z0-9]{36}", "GitHub OAuth Token"),
    (r"ghu_[A-Za-z0-9]{36}", "GitHub User-to-Server Token"),
    (r"ghs_[A-Za-z0-9]{36}", "GitHub Server-to-Server Token"),
    (r"github_pat_[A-Za-z0-9_]{22,}", "GitHub Fine-Grained Token"),
    (r"sk-ant-[A-Za-z0-9\-_]{20,}", "Anthropic API Key"),
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI / API Secret Key"),
    (r"AIza[0-9A-Za-z-_]{35}", "Google API Key"),
    (r"hf_[A-Za-z0-9]{34}", "HuggingFace Token"),
    (r"xox[baprs]-[A-Za-z0-9\-]{10,}", "Slack Token"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"-----BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY-----", "Private Key Header"),
]


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
    changed_files = [line[3:].strip() for line in status_res.stdout.splitlines() if line.strip()]

    return {
        "branch": branch,
        "upstream": upstream,
        "has_upstream": has_upstream,
        "ahead": ahead,
        "behind": behind,
        "changed_files": changed_files,
    }


def stage2_guard(changed_files: list[str], repo: str = None) -> list[str]:
    safe_files = []
    blocked_files = []

    for f_str in changed_files:
        p = Path(f_str)
        fname = p.name

        # 1. Filename secret checks
        is_secret = any(re.search(pat, fname, re.IGNORECASE) for pat in SECRET_FILE_PATTERNS)
        if is_secret:
            blocked_files.append((f_str, "Secret file pattern blocked"))
            continue

        # 2. Oversized blob check (>50 MB)
        if p.is_file() and p.stat().st_size > 50 * 1024 * 1024:
            blocked_files.append((f_str, f"Oversized file ({p.stat().st_size // (1024*1024)} MB > 50 MB ceiling)"))
            continue

        # 3. Diff content secret scan
        if p.is_file():
            try:
                diff_res = run_git(["diff", "HEAD", "--", f_str], check=False, cwd=repo)
                diff_text = diff_res.stdout
                leak_found = False
                for pat, label in SECRET_CONTENT_PATTERNS:
                    if re.search(pat, diff_text):
                        blocked_files.append((f_str, f"Diff contains leaked {label}"))
                        leak_found = True
                        break
                if leak_found:
                    continue
            except Exception:
                pass

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
        if target.exists():
            run_git(["add", "--", f], cwd=repo)
        else:
            run_git(["rm", "--cached", "--", f], check=False, cwd=repo)

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
        if not sys.stdin.isatty():
            sys.exit(
                f"❌ Refusing to push to protected branch '{branch}' without confirmation.\n"
                f"   Re-run with -y, or push manually."
            )
        confirm = input(f"⚠️  Branch '{branch}' is a protected default branch. Confirm push to remote? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            sys.exit("Push cancelled by user.")

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
    files = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ")[-1].strip()
        if path:
            files.append(path)
    return files


def guarded_commit(repo: str, message: str, excludes: list = None) -> dict:
    """Stage and commit only the files that pass the secret guard.

    The content scan reads whole files rather than diffs: a brand-new file is
    untracked, so `git diff HEAD` shows nothing for it and a secret planted
    in a new file would sail straight through a diff-based guard.
    """
    scan_file = _load_publication_guard()
    is_excluded = _load_exclude_matcher()
    excludes = excludes or []
    files = changed_files_in(repo)
    safe, blocked = [], []
    for rel in files:
        if is_excluded(Path(rel), excludes):
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
        print("🛡️  [guard] Blocked files from staging:")
        for rel, reason in blocked:
            print(f"   ❌ {rel} — {reason}")
        return {"committed": [], "blocked": blocked, "safe": safe}

    committed = stage3_commit(safe, message=message, repo=repo) if safe else []
    return {"committed": committed, "blocked": [], "safe": safe}


def cmd_guarded_commit(args) -> int:
    result = guarded_commit(args.repo, args.message, args.exclude)
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
    return 1 if result["blocked"] else 0


def cmd_check_messages(args) -> int:
    upstream = args.upstream
    if not upstream:
        up = run_git(["rev-parse", "--abbrev-ref", "@{upstream}"], check=False, cwd=args.repo)
        upstream = up.stdout.strip() or None
    missing = commits_without_body(upstream, repo=args.repo)
    if missing:
        listing = "\n".join(f"  {sha} {subject}" for sha, subject in missing)
        print(f"❌ {len(missing)} commit(s) with no description:\n{listing}")
        return 1
    print("✅ Every outgoing commit has a description.")
    return 0


HOOK_TEMPLATE = """#!/usr/bin/env bash
# Managed by github-architect. Refuses to publish a commit with no description.
exec python3 "{script}" check-messages --repo "$(git rev-parse --show-toplevel)"
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
    hook.write_text(HOOK_TEMPLATE.format(script=Path(__file__).resolve()))
    hook.chmod(0o755)
    print(f"🪝 Installed pre-push description gate at {hook}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "check-messages":
        cp = argparse.ArgumentParser(
            prog="git-sync check-messages",
            description="Fail if any outgoing commit has no description body",
        )
        cp.add_argument("--repo", default=".", help="Repository to inspect")
        cp.add_argument("--upstream", help="Range start (default: @{upstream})")
        return cmd_check_messages(cp.parse_args(argv[1:]))

    if argv and argv[0] == "install-hook":
        ip = argparse.ArgumentParser(
            prog="git-sync install-hook",
            description="Install the pre-push description gate",
        )
        ip.add_argument("--repo", default=".", help="Repository to install into")
        ip.add_argument("--force", action="store_true", help="Replace a foreign pre-push hook")
        return cmd_install_hook(ip.parse_args(argv[1:]))

    if argv and argv[0] == "guarded-commit":
        gp = argparse.ArgumentParser(
            prog="git-sync guarded-commit",
            description="Stage and commit only the files that pass the secret guard",
        )
        gp.add_argument("--repo", required=True, help="Repository to commit in")
        gp.add_argument("-m", "--message", help="Commit message (default: derived from the staged diff)")
        gp.add_argument("--exclude", action="append", default=[], help="rsync-style exclude pattern (repeatable)")
        gp.add_argument("--json", action="store_true")
        gargs = gp.parse_args(argv[1:])
        return cmd_guarded_commit(gargs)

    parser = argparse.ArgumentParser(
        prog="git-sync",
        description="Disciplined 6-Stage Git Branch Synchronization Engine (Look -> Guard -> Commit -> Gate -> Pull -> Push -> Report)"
    )
    parser.add_argument("-m", "--message", help="Commit message (default: auto conventional summary)")
    parser.add_argument("-y", "--yes", action="store_true", help="Auto-confirm push to protected default branches (main/master)")
    parser.add_argument("--no-pull", action="store_true", help="Skip pulling from remote before pushing")
    parser.add_argument("--no-gate", action="store_true", help="Skip pre-push automated test/lint gates")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and display actions without committing or pushing")

    parser.add_argument("--table", "-t", action="store_true", help="Emit receipt as Markdown table")
    parser.add_argument("--json", action="store_true", help="Emit receipt as JSON")

    args = parser.parse_args(argv)
    # Stage 1: Look
    look_info = stage1_look()
    branch = look_info["branch"]
    changed = look_info["changed_files"]

    if not changed and look_info["ahead"] == 0 and look_info["behind"] == 0:
        if args.json:
            print(json.dumps({"status": "clean", "branch": branch, "message": "Branch is clean and in sync with remote."}, indent=2))
        else:
            print(f"✨ Branch '{branch}' is clean and in sync with remote.")
        return

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
        return

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
        return

    if args.table:
        rows = [
            {"step": "Branch", "status": branch, "details": look_info.get("upstream") or "local only"},
            {"step": "Commit", "status": f"{len(committed)} commit(s)" if committed else "Clean", "details": ", ".join(f"{s} {m}" for s, m in committed) if committed else "Working tree clean"},
            {"step": "Pull", "status": pull_status, "details": "Merged remote changes" if "Auto" in pull_status else pull_status},
            {"step": "Push", "status": "Success", "details": f"Pushed upstream to {branch}"},
            {"step": "Left Out", "status": f"{len(blocked_files)} blocked" if blocked_files else "None", "details": ", ".join(bf for bf, _ in blocked_files) if blocked_files else "Clean"},
        ]
        print(f"### git-sync Receipt: `{branch}`\n")
        print(render_table(rows, ["step", "status", "details"]))
        return

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


if __name__ == "__main__":
    sys.exit(main())
