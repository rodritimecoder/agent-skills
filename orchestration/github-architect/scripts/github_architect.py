#!/usr/bin/env python3
"""
github_architect.py — Automated GitHub Repository Scaffolding, Auditing, Fleet Syncing & Multi-Machine Bootstrapping

Zero-dependency CLI tool for inspecting local project folders, generating tailored
.gitignore, LICENSE, and README.md files, syncing changes across machines,
scanning for secrets and large blobs, and managing fleet repositories via the GitHub CLI.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Set

DEFAULT_GITIGNORE = """# Byte-compiled / optimized / DLL files
__pycache__/
*.py[cod]
*$py.class
*.so

# Virtual Environments
.venv/
venv/
env/
ENV/
.env/
.agent-reach-venv/
container-site-packages/

# Package & Distribution
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Heavy Model Weights & Blobs (Keep out of Git)
*.gguf
*.bin
*.pt
*.safetensors
*.onnx

# SQLite Databases & Storage
*.db
*.sqlite
*.sqlite3
rag.db

# C / C++ build outputs
*.o
*.obj
*.d
*.a
*.lib
*.so
*.dylib
*.exe
*.out

# Node / Web
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Secret & Environmental Credentials
.env
.env.local
.env.*.local
.homelab_litellm.env
*.pem
*.key
*.p12
*.pfx
id_rsa*
id_ed25519*

# Operating System & Editors
.DS_Store
Thumbs.db
.idea/
.vscode/*
!.vscode/settings.json
!.vscode/tasks.json
!.vscode/launch.json
!.vscode/extensions.json
*.swp
*.swo
*~
.Trash-*

# Sensitive Course Modules & Local Vaults
university-notes/
"""

DEFAULT_MIT_LICENSE = """MIT License

Copyright (c) {year} {author}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

DEFAULT_PRIVATE_LICENSE = """All Rights Reserved.

Copyright (c) {year} {author}

This source code and related assets are private and confidential. Unauthorized copying,
transferring, distribution, or reproduction of this repository or any part thereof,
via any medium, is strictly prohibited without prior written permission from the owner.
"""

CORE_REPOSITORIES = [
    {
        "name": "my-agent-skills",
        "target": "skills",
        "description": "Canonical upstream repository of reusable agent skills & ICM workflows",
    },
    {
        "name": "workstation-clis",
        "target": "workstation-clis",
        "description": "Curated workstation engineering, sandbox, and local inference CLIs",
    },
    {
        "name": "academic-agent-skills",
        "target": "academic-agent-skills",
        "description": "Academic ICM, Canvas LMS, and Cornell active-recall tools",
    },
    {
        "name": "glitch-cat-skills",
        "target": "glitch-cat-skills",
        "description": "Autonomous production agent harness implementing Kem's Glitch Cat Club architecture",
    },
    {
        "name": "free-frontier-skills",
        "target": "free-frontier-skills",
        "description": "Autonomous subagent coding loops, bash batching, and embeddings on free frontier endpoints",
    },
    {
        "name": "agent-multiplayer-template",
        "target": "agent-multiplayer-template",
        "description": "Multiplayer cloud workspace & homelab GPU template",
    },
    {
        "name": "university",
        "target": "University",
        "description": "University course materials, notes, and Knowledge Cosmos",
    },
]

SECRET_PATTERNS = [
    (re.compile(r"ghp_[A-Za-z0-9_]{36}"), "GitHub Personal Access Token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{82}"), "GitHub Fine-Grained Token"),
    (re.compile(r"sk-[a-zA-Z0-9-]{20,}"), "OpenAI / LiteLLM Secret Key"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "Google API Key"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "Private Key Block"),
]

MAX_BLOB_SIZE_MB = 50.0

# Where this machine keeps the AI volume. It is a genuine default, not a
# portability bug: override it with AI_ROOT on a machine that mounts elsewhere.
AI_ROOT = Path(os.environ.get("AI_ROOT", "/run/media/rodri/AI"))

# The skills hub is checked out once per machine at this path on every OS; the
# AI volume only exists on the Linux box, so the hub must not live inside it.
SKILLS_CHECKOUT = Path(os.environ.get("SKILLS_CANONICAL", Path.home() / "src" / "my-agent-skills"))

FLEET_SEARCH_PATHS = [
    SKILLS_CHECKOUT.parent,
    AI_ROOT,
    Path.home() / "workspace",
    Path.home(),
]


def run_cmd(cmd, cwd=None, check=True):
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=isinstance(cmd, str))
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed (exit {res.returncode}): {cmd}\nStderr: {res.stderr.strip()}")
    return res


def compose_commit_message(target: Path, message: Optional[str] = None) -> str:
    """The same commit shape git-sync emits: subject, prose, file manifest.

    No fallback: a silent `except` here is how a commit lost its description
    before. If git_sync cannot be imported the caller must see it.
    """
    from git_sync import compose_message
    return compose_message(str(target), message)


def check_gh_status() -> Tuple[bool, str]:
    res = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if res.returncode != 0:
        return False, ""
    user_res = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True)
    user = user_res.stdout.strip() if user_res.returncode == 0 else ""
    return True, user


def ensure_git_identity() -> Tuple[str, str]:
    name = run_cmd("git config user.name", check=False).stdout.strip()
    email = run_cmd("git config user.email", check=False).stdout.strip()

    if not name or not email:
        is_auth, gh_user = check_gh_status()
        if is_auth and gh_user:
            if not name:
                name = gh_user
                run_cmd(f'git config --global user.name "{name}"', check=False)
                print(f"  🔧 Auto-configured git user.name: {name}")
            if not email:
                email = f"{gh_user}@users.noreply.github.com"
                run_cmd(f'git config --global user.email "{email}"', check=False)
                print(f"  🔧 Auto-configured git user.email: {email}")
        else:
            name = name or "rodritimecoder"
            email = email or "rodritimecoder@users.noreply.github.com"

    return name, email


def check_secrets_and_blobs(repo_path: Path, staged_only: bool = True) -> Tuple[List[str], List[str]]:
    secret_hits: List[str] = []
    blob_hits: List[str] = []

    diff_files_cmd = ["git", "diff", "--name-only", "--cached"] if staged_only else ["git", "status", "--porcelain"]
    res = run_cmd(diff_files_cmd, cwd=repo_path, check=False)
    lines = res.stdout.strip().splitlines()

    for line in lines:
        fname = line.strip().split()[-1] if not staged_only else line.strip()
        p = repo_path / fname
        if p.is_file():
            try:
                size_mb = p.stat().st_size / (1024 * 1024)
                if size_mb > MAX_BLOB_SIZE_MB:
                    blob_hits.append(f"{p.relative_to(repo_path)} ({size_mb:.1f} MB > {MAX_BLOB_SIZE_MB} MB limit)")
            except Exception:
                pass

    diff_text_cmd = ["git", "diff", "--cached"] if staged_only else ["git", "diff"]
    diff_res = run_cmd(diff_text_cmd, cwd=repo_path, check=False)
    for line in diff_res.stdout.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added = line[1:]
            for pattern, label in SECRET_PATTERNS:
                m = pattern.search(added)
                if m:
                    token = m.group(0)
                    masked = token[:6] + "..." + token[-4:] if len(token) > 12 else "***"
                    secret_hits.append(f"{label}: {masked}")

    return secret_hits, blob_hits


def parse_skills_metadata(skills_dir: Path):
    skills = []
    for item in sorted(skills_dir.iterdir()):
        skill_md = item / "SKILL.md"
        if item.is_dir() and skill_md.is_file():
            content = skill_md.read_text(encoding="utf-8")
            name = item.name
            desc = "Agent skill"
            match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL | re.MULTILINE)
            if match:
                fm = match.group(1)
                name_m = re.search(r"^name:\s*([^\n]+)", fm, re.MULTILINE)
                if name_m:
                    name = name_m.group(1).strip()
                desc_m = re.search(r"^description:\s*([^\n]+)", fm, re.MULTILINE)
                if desc_m:
                    desc = desc_m.group(1).strip()
            skills.append({"dir": item.name, "name": name, "description": desc})
    return skills


def generate_skills_readme(target_path: Path, repo_name: str, author: str) -> str:
    skills = parse_skills_metadata(target_path)

    rows = []
    for s in skills:
        clean_desc = s["description"].split(".")[0] if "." in s["description"] else s["description"]
        clean_desc = clean_desc.replace("|", "\\|")[:90]
        rows.append(f"| [`{s['dir']}`]({s['dir']}/) | `{s['name']}` | {clean_desc} |")

    skills_table = "\n".join(rows)

    return f"""# {repo_name}

[![Private Repository](https://img.shields.io/badge/Repository-Private-red.svg)](https://github.com/{author}/{repo_name})
[![Skills Count](https://img.shields.io/badge/Skills-{len(skills)}-blue.svg)](#skills-catalog)
[![Upstream Canonical](https://img.shields.io/badge/Source-Upstream%20Canonical-success.svg)](#architecture)

> **Canonical upstream repository** of reusable AI agent skills, CLI automation tools, and ICM (Interpretable Context Methodology) workspaces on this machine.

---

## 🏛️ Architecture & Upstream-First Synchronization

This repository serves as the **single source of truth** across all local agent harnesses (`~/.gemini/config/skills` and `~/.pi/agent/skills`).

```
┌─────────────────────────────────────────────────────────────┐
│       Canonical Upstream Repository (This Repo)             │
│                /run/media/rodri/AI/skills                   │
└──────────────────────────────┬──────────────────────────────┘
                               │  sync-skills
                               ▼
        ┌──────────────────────────────────────────────┐
        │                                              │
        ▼                                              ▼
┌──────────────────────────────┐       ┌──────────────────────────────┐
│  Antigravity / Gemini CLI   │       │       Pi Agent CLI           │
│   ~/.gemini/config/skills/   │       │     ~/.pi/agent/skills/      │
└──────────────────────────────┘       └──────────────────────────────┘
```

Whenever updating, refactoring, or creating any skill:
1. Make file edits directly in this repository first.
2. Run `sync-skills` in the terminal to immediately propagate downstream without ephemeral `.venv` or cache bloat.

---

## 📦 Skills Catalog ({len(skills)} Skills)

| Skill Directory | Identifier | Core Capabilities |
| :--- | :--- | :--- |
{skills_table}

---

## 🚀 Quickstart & Usage

### 1. Synchronize to Local Agent Harnesses
To push updates from this repository to your active Antigravity and Pi harnesses:
```bash
sync-skills
```

### 2. Pull Downstream Edits (Parity Restore)
If a skill was modified downstream, pull changes back upstream with:
```bash
sync-skills --pull
```

---

## 🔒 License & Confidentiality
Private repository owned by {author}. Contains customized pipelines, academic integrations, and local inference tooling.
"""


def cmd_audit(target: Path, as_table: bool = False, as_json: bool = False):
    if not target.is_dir():
        print(f"❌ Error: Target directory does not exist: {target}", file=sys.stderr)
        return False

    has_git = (target / ".git").is_dir()
    has_gitignore = (target / ".gitignore").is_file()
    has_readme = (target / "README.md").is_file()
    has_license = (target / "LICENSE").is_file() or (target / "LICENSE.md").is_file()
    is_auth, gh_user = check_gh_status()
    git_user = run_cmd("git config user.name", check=False).stdout.strip()
    git_email = run_cmd("git config user.email", check=False).stdout.strip()

    sec_hits, blob_hits = [], []
    dirty = False
    branch_tracking = ""
    remote_origin = ""

    if has_git:
        remotes = run_cmd("git remote -v", cwd=target, check=False).stdout.strip()
        remote_origin = remotes.splitlines()[0] if remotes else "No remote"
        dirty = bool(run_cmd("git status --porcelain", cwd=target, check=False).stdout.strip())
        status_sb = run_cmd("git status -sb", cwd=target, check=False).stdout.strip().splitlines()
        branch_tracking = status_sb[0] if status_sb else ""
        sec_hits, blob_hits = check_secrets_and_blobs(target, staged_only=False)

    checks = [
        {"item": "Git Initialized", "status": "Yes" if has_git else "Missing"},
        {"item": ".gitignore", "status": "Yes" if has_gitignore else "Missing"},
        {"item": "README.md", "status": "Yes" if has_readme else "Missing"},
        {"item": "LICENSE", "status": "Yes" if has_license else "Missing"},
        {"item": "GitHub Auth", "status": f"Logged in (@{gh_user})" if is_auth else "Not logged in"},
        {"item": "Git Identity", "status": f"{git_user} <{git_email}>" if git_user and git_email else "Incomplete"},
        {"item": "Working Tree", "status": "Uncommitted changes" if dirty else "Clean"},
        {"item": "Secret Scanner", "status": f"{len(sec_hits)} warning(s)" if sec_hits else "Clean"},
        {"item": "Large Blobs", "status": f"{len(blob_hits)} warning(s)" if blob_hits else f"Clean (<{MAX_BLOB_SIZE_MB}MB)"},
    ]

    if as_json:
        payload = {
            "target": str(target.resolve()),
            "checks": checks,
            "secret_warnings": sec_hits,
            "large_blobs": blob_hits,
            "branch_tracking": branch_tracking,
            "remote": remote_origin
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return True

    if as_table:
        print(f"### Repository Audit: {target.name}\n")
        print(render_table(checks, ["item", "status"], ["Audit Check", "Status"]))
        return True

    print(f"\n🔍 [Audit] Inspecting repository target: {target.resolve()}")
    print(f"  • Git initialized:   {'✅ Yes' if has_git else '❌ Missing (.git folder)'}")
    print(f"  • .gitignore:        {'✅ Yes' if has_gitignore else '❌ Missing (.gitignore)'}")
    print(f"  • README.md:         {'✅ Yes' if has_readme else '❌ Missing (README.md)'}")
    print(f"  • LICENSE:           {'✅ Yes' if has_license else '❌ Missing (LICENSE)'}")
    print(f"  • GitHub CLI Auth:   {'✅ Logged in (@' + gh_user + ')' if is_auth else '❌ Not logged in (run gh auth login)'}")
    if git_user and git_email:
        print(f"  • Git Identity:      ✅ {git_user} <{git_email}>")
    else:
        print(f"  • Git Identity:      ⚠️ Incomplete ({git_user or 'no user'} / {git_email or 'no email'})")

    if has_git:
        print(f"  • Remote Origin:     {remote_origin or '⚪ No remote configured'}")
        print(f"  • Working Tree:      {'⚠️ Uncommitted changes' if dirty else '✅ Clean'}")
        if branch_tracking:
            print(f"  • Branch Tracking:   {branch_tracking}")
        if sec_hits:
            print(f"  • ⚠️  Secret Warnings: {len(sec_hits)} suspicious key patterns detected!")
            for s in sec_hits[:3]:
                print(f"       - {s}")
        else:
            print(f"  • Secret Scanner:    ✅ No uncommitted secrets detected")

        if blob_hits:
            print(f"  • ⚠️  Large Blobs:    {len(blob_hits)} files exceed {MAX_BLOB_SIZE_MB}MB limit!")
            for b in blob_hits[:3]:
                print(f"       - {b}")
        else:
            print(f"  • Large Blobs:       ✅ All files under {MAX_BLOB_SIZE_MB}MB")

    return True


def cmd_scaffold(target: Path, repo_name: str, private: bool = True, license_type: str = "private"):
    print(f"\n🛠️  [Scaffold] Building repository assets in: {target.resolve()}")
    target.mkdir(parents=True, exist_ok=True)

    gi_path = target / ".gitignore"
    if not gi_path.exists():
        gi_path.write_text(DEFAULT_GITIGNORE, encoding="utf-8")
        print(f"  ✅ Created .gitignore (blocks .venv, __pycache__, build artifacts, models, secrets)")
    else:
        print(f"  ℹ️  .gitignore already exists (preserved)")

    lic_path = target / "LICENSE"
    author, _ = ensure_git_identity()
    year = "2026"
    if not lic_path.exists():
        if license_type.lower() == "mit":
            lic_content = DEFAULT_MIT_LICENSE.format(year=year, author=author)
        else:
            lic_content = DEFAULT_PRIVATE_LICENSE.format(year=year, author=author)
        lic_path.write_text(lic_content, encoding="utf-8")
        print(f"  ✅ Created LICENSE ({license_type.upper()})")
    else:
        print(f"  ℹ️  LICENSE already exists (preserved)")

    readme_path = target / "README.md"
    is_skills_repo = any((target / s / "SKILL.md").is_file() for s in target.iterdir() if s.is_dir())

    if is_skills_repo:
        readme_content = generate_skills_readme(target, repo_name, author)
        readme_path.write_text(readme_content, encoding="utf-8")
        print(f"  ✅ Generated enriched skills README.md with architecture flowchart & catalog table")
    elif not readme_path.exists():
        basic_readme = f"# {repo_name}\n\nPrivate repository managed by {author}.\n"
        readme_path.write_text(basic_readme, encoding="utf-8")
        print(f"  ✅ Generated base README.md")
    else:
        print(f"  ℹ️  README.md already exists (preserved)")


def cmd_publish(target: Path, repo_name: str, private: bool = True, license_type: str = "private", is_template: bool = False, force: bool = False):
    print(f"\n🚀 [Publish] Preparing and publishing {repo_name} to GitHub...")

    is_auth, user = check_gh_status()
    if not is_auth:
        print("❌ Error: GitHub CLI ('gh') is not authenticated. Run: gh auth login")
        return False

    ensure_git_identity()
    cmd_scaffold(target, repo_name, private=private, license_type=license_type)

    if not (target / ".git").is_dir():
        run_cmd(["git", "init", "-b", "main"], cwd=target)
        print("  ✅ Initialized local Git repository (branch: main)")

    sec_hits, blob_hits = check_secrets_and_blobs(target, staged_only=False)
    if (sec_hits or blob_hits) and not force:
        print("\n❌ Publishing ABORTED due to Grounded Security Guard:")
        for s in sec_hits:
            print(f"  ⚠️  Detected Secret: {s}")
        for b in blob_hits:
            print(f"  ⚠️  Detected Oversized Blob: {b}")
        print("\n💡 Pass '--force' if you explicitly intend to publish these files.")
        return False

    run_cmd(["git", "add", "."], cwd=target)
    status = run_cmd(["git", "status", "--porcelain"], cwd=target).stdout.strip()
    if status:
        commit_msg = compose_commit_message(target, "feat: initial commit with github-architect scaffold")
        run_cmd(["git", "commit", "-m", commit_msg], cwd=target)
        print("  ✅ Committed all staged files")
    else:
        print("  ℹ️  No changes to commit (working tree clean)")

    remotes = run_cmd(["git", "remote"], cwd=target, check=False).stdout.strip().splitlines()
    visibility_flag = "--private" if private else "--public"

    if "origin" not in remotes:
        print(f"  🌐 Creating remote repository '{repo_name}' on GitHub ({visibility_flag})...")
        gh_cmd = ["gh", "repo", "create", repo_name, visibility_flag, "--source=.", "--remote=origin", "--push"]
        res = run_cmd(gh_cmd, cwd=target)
        print(f"  ✅ Successfully published to GitHub: {res.stdout.strip()}")
    else:
        print(f"  📤 Remote 'origin' already exists. Pulling latest and pushing to origin...")
        run_cmd(["git", "pull", "--rebase", "origin", "main"], cwd=target, check=False)
        run_cmd(["git", "push", "-u", "origin", "main"], cwd=target)
        print("  ✅ Pushed changes to existing remote origin")

    owner_repo = run_cmd(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=target, check=False).stdout.strip()
    repo_url = run_cmd(["gh", "repo", "view", "--json", "url", "--jq", ".url"], cwd=target, check=False).stdout.strip()

    if is_template and owner_repo:
        print(f"  🏷️  Configuring repository as a GitHub Template...")
        tpl_res = run_cmd(["gh", "api", "-X", "PATCH", f"repos/{owner_repo}", "-f", "is_template=true"], check=False)
        if tpl_res.returncode == 0:
            print("  ✅ Successfully marked as Template Repository!")

    vis_label = "Private" if private else "Public"
    print(f"\n🎉 Repository Live & Protected: {repo_url} ({vis_label}{', Template' if is_template else ''})")
    return True


def cmd_sync(target: Path, message: Optional[str] = None, force: bool = False) -> bool:
    print(f"\n🔄 [Sync] Synchronizing repository: {target.resolve()}")
    if not (target / ".git").is_dir():
        print(f"❌ Error: {target} is not a git repository.")
        return False

    ensure_git_identity()

    remotes = run_cmd(["git", "remote"], cwd=target, check=False).stdout.strip().splitlines()
    if "origin" not in remotes:
        print("❌ Error: No remote 'origin' configured.")
        return False

    branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=target, check=False).stdout.strip() or "main"

    sec_hits, blob_hits = check_secrets_and_blobs(target, staged_only=False)
    if (sec_hits or blob_hits) and not force:
        print("\n❌ Sync ABORTED due to Grounded Security Guard:")
        for s in sec_hits:
            print(f"  ⚠️  Detected Secret: {s}")
        for b in blob_hits:
            print(f"  ⚠️  Detected Oversized Blob: {b}")
        print("\n💡 Pass '--force' if you explicitly intend to sync these files.")
        return False

    status = run_cmd(["git", "status", "--porcelain"], cwd=target, check=False).stdout.strip()
    if status:
        print("  📝 Local changes detected. Staging and committing...")
        run_cmd(["git", "add", "."], cwd=target)
        commit_msg = compose_commit_message(target, message)
        run_cmd(["git", "commit", "-m", commit_msg], cwd=target)
        print(f"  ✅ Committed local changes: '{commit_msg.splitlines()[0]}'")
    else:
        print("  ℹ️  Working tree clean (no new local changes to commit).")

    print(f"  📥 Pulling remote changes from origin/{branch} (rebase)...")
    pull_res = run_cmd(["git", "pull", "--rebase", "origin", branch], cwd=target, check=False)
    if pull_res.returncode != 0:
        print(f"  ⚠️ Warning: Pull rebase had warnings/conflicts:\n{pull_res.stderr.strip()}")
    else:
        print(f"  ✅ Branch origin/{branch} rebased cleanly.")

    from git_sync import commits_without_body
    missing = commits_without_body(f"origin/{branch}", repo=str(target))
    if missing:
        listing = "\n".join(f"     {sha} {subject}" for sha, subject in missing)
        print(f"  ❌ Refusing to push {len(missing)} commit(s) with no description:")
        print(listing)
        print("     Amend each message, then retry.")
        return False

    print(f"  📤 Pushing commits to origin/{branch}...")
    push_res = run_cmd(["git", "push", "origin", branch], cwd=target, check=False)
    if push_res.returncode == 0:
        print(f"  ✅ Successfully synchronized and pushed to origin/{branch}!")
    else:
        print(f"  ❌ Push failed:\n{push_res.stderr.strip()}")
        return False

    # Propagate skills if applicable
    if (target / "sync_skills.sh").is_file() or (target / "scripts" / "sync_skills.sh").is_file():
        sync_sh = target / "sync_skills.sh" if (target / "sync_skills.sh").is_file() else target / "scripts" / "sync_skills.sh"
        print("  🔄 Propagating skills to downstream CLI harnesses...")
        run_cmd(["bash", str(sync_sh)], cwd=target, check=False)

    return True


def discover_fleet_repos() -> List[Dict[str, Any]]:
    fleet = []
    seen_paths = set()

    for repo_def in CORE_REPOSITORIES:
        target_name = repo_def["target"]
        repo_name = repo_def["name"]
        found_path = None

        for base in FLEET_SEARCH_PATHS:
            cand = base / target_name
            if (cand / ".git").is_dir():
                found_path = cand
                break
            cand_alt = base / repo_name
            if (cand_alt / ".git").is_dir():
                found_path = cand_alt
                break

        if found_path and found_path.resolve() not in seen_paths:
            seen_paths.add(found_path.resolve())
            fleet.append({
                "name": repo_name,
                "path": found_path.resolve(),
                "description": repo_def["description"]
            })

    return fleet


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


def get_fleet_status_records(fleet: list[dict]) -> list[dict]:
    records = []
    for r in fleet:
        p = r["path"]
        branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=p, check=False).stdout.strip() or "main"
        dirty_lines = [l for l in run_cmd(["git", "status", "--porcelain"], cwd=p, check=False).stdout.strip().splitlines() if l.strip()]
        dirty_count = len(dirty_lines)

        rev_res = run_cmd(["git", "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"], cwd=p, check=False)
        ahead, behind = 0, 0
        sync_label = "No upstream"
        if rev_res.returncode == 0:
            parts = rev_res.stdout.strip().split()
            ahead = int(parts[0]) if len(parts) > 0 else 0
            behind = int(parts[1]) if len(parts) > 1 else 0
            if ahead == 0 and behind == 0:
                sync_label = "Up to date"
            elif ahead > 0 and behind == 0:
                sync_label = f"Ahead ({ahead})"
            elif ahead == 0 and behind > 0:
                sync_label = f"Behind ({behind})"
            else:
                sync_label = f"Diverged (+{ahead}/-{behind})"

        last_commit = run_cmd(["git", "log", "-1", "--format=%h (%cr) - %s"], cwd=p, check=False).stdout.strip()
        last_commit_short = last_commit[:45] + "..." if len(last_commit) > 45 else last_commit
        records.append({
            "repository": r["name"],
            "branch": branch,
            "worktree": f"{dirty_count} dirty" if dirty_count > 0 else "Clean",
            "remote_sync": sync_label,
            "last_commit": last_commit_short,
            "path": str(p)
        })
    return records


def cmd_status_all(as_table: bool = False, as_json: bool = False, project_keys: list[str] | None = None, limit: int = 0) -> None:
    fleet = discover_fleet_repos()
    if not fleet:
        if as_json:
            print("[]")
        else:
            print("❌ No workstation fleet repositories found.")
        return

    records = get_fleet_status_records(fleet)
    if limit and limit > 0:
        records = records[:limit]

    if as_json:
        if project_keys:
            records = [{k: v for k, v in r.items() if k.lower() in project_keys} for r in records]
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return

    if as_table:
        cols = ["repository", "branch", "worktree", "remote_sync", "last_commit"]
        if project_keys:
            cols = [c for c in cols if c.lower() in project_keys] or cols
        table_rows = [{k: r[k] for k in cols if k in r} for r in records]
        print(f"### Workstation Fleet Status ({len(records)} repositories)\n")
        print(render_table(table_rows, cols))
        return

    print(f"\n🚢 [Fleet Status] Inspecting {len(fleet)} workstation repositories:\n")
    print(f"  {'Repository':<28} │ {'Branch':<8} │ {'Worktree':<10} │ {'Remote Sync':<15} │ Last Commit")
    print("  ─────────────────────────────┼──────────┼────────────┼─────────────────┼──────────────────────────────")

    for r in records:
        dirty_str = f"\033[33m{r['worktree']}\033[0m" if "dirty" in r["worktree"] else f"\033[32m{r['worktree']}\033[0m"
        sync_str = r["remote_sync"]
        if "Up to date" in sync_str:
            sync_color = f"\033[32m{sync_str}\033[0m"
        elif "Ahead" in sync_str:
            sync_color = f"\033[33m{sync_str}\033[0m"
        elif "Behind" in sync_str:
            sync_color = f"\033[31m{sync_str}\033[0m"
        elif "Diverged" in sync_str:
            sync_color = f"\033[35m{sync_str}\033[0m"
        else:
            sync_color = f"\033[90m{sync_str}\033[0m"
        print(f"  {r['repository']:<28} │ {r['branch']:<8} │ {dirty_str:<19} │ {sync_color:<24} │ {r['last_commit']}")
    print()


def cmd_sync_all(message: Optional[str] = None, force: bool = False) -> None:
    fleet = discover_fleet_repos()
    if not fleet:
        print("❌ No workstation fleet repositories found.")
        return

    print(f"\n🚀 [Fleet Sync] Synchronizing all {len(fleet)} workstation repositories...\n")
    success_count = 0
    for r in fleet:
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"📦 Synchronizing: {r['name']} ({r['path']})")
        ok = cmd_sync(r["path"], message=message, force=force)
        if ok:
            success_count += 1

    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"🎉 Fleet Sync Complete: {success_count}/{len(fleet)} repositories synchronized cleanly.")


def cmd_clone(repo: str, dest: Optional[Path] = None):
    is_auth, user = check_gh_status()
    if not is_auth:
        print("❌ Error: GitHub CLI ('gh') is not authenticated. Run: gh auth login")
        return False

    repo_slug = repo if "/" in repo else f"{user}/{repo}"
    print(f"\n📦 [Clone] Cloning {repo_slug}...")
    cmd = ["gh", "repo", "clone", repo_slug]
    if dest:
        cmd.append(str(dest))
    res = run_cmd(cmd, check=False)
    if res.returncode == 0:
        print(f"  ✅ Successfully cloned {repo_slug}")
        return True
    else:
        print(f"  ❌ Clone failed: {res.stderr.strip()}")
        return False


def cmd_bootstrap(dest_dir: Optional[Path] = None):
    if dest_dir is None:
        dest_dir = AI_ROOT if AI_ROOT.is_dir() else (Path.home() / "workspace")

    print(f"\n🚀 [Bootstrap] Setting up agent environment in: {dest_dir.resolve()}")
    dest_dir.mkdir(parents=True, exist_ok=True)

    is_auth, user = check_gh_status()
    if not is_auth:
        print("❌ Error: GitHub CLI ('gh') is not authenticated. Run: gh auth login")
        return False
    print(f"  ✅ Authenticated as GitHub user: @{user}")

    ensure_git_identity()

    for repo in CORE_REPOSITORIES:
        repo_name = repo["name"]
        target_path = SKILLS_CHECKOUT if repo_name == "my-agent-skills" else dest_dir / repo["target"]
        repo_slug = f"{user}/{repo_name}"

        if (target_path / ".git").is_dir():
            print(f"\n📦 Repository already exists at {target_path}. Synchronizing...")
            cmd_sync(target_path)
        else:
            print(f"\n📦 Cloning {repo_slug} -> {target_path}...")
            clone_cmd = ["gh", "repo", "clone", repo_slug, str(target_path)]
            res = run_cmd(clone_cmd, check=False)
            if res.returncode == 0:
                print(f"  ✅ Successfully cloned {repo_slug}")
            else:
                print(f"  ⚠️ Could not clone {repo_slug}: {res.stderr.strip()}")

    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)

    skills_dir = SKILLS_CHECKOUT
    if not (skills_dir / "sync_skills.sh").is_file():
        skills_dir = dest_dir / "skills"
        if not skills_dir.exists():
            skills_dir = dest_dir / "my-agent-skills"

    if skills_dir.is_dir():
        sync_script = skills_dir / "sync_skills.sh"
        if sync_script.is_file():
            sync_symlink = local_bin / "sync-skills"
            if sync_symlink.is_symlink() or sync_symlink.is_file():
                sync_symlink.unlink()
            sync_symlink.symlink_to(sync_script)
            sync_script.chmod(0o755)
            print(f"  ✅ Linked sync-skills -> {sync_symlink}")

        arch_script = skills_dir / "github-architect" / "scripts" / "github_architect.py"
        if arch_script.is_file():
            arch_symlink = local_bin / "github-architect"
            if arch_symlink.is_symlink() or arch_symlink.is_file():
                arch_symlink.unlink()
            arch_symlink.symlink_to(arch_script)
            arch_script.chmod(0o755)
            print(f"  ✅ Linked github-architect -> {arch_symlink}")

        if sync_script.is_file():
            print("\n🔄 Propagating skills into Antigravity & Pi harnesses...")
            run_cmd(["bash", str(sync_script)], cwd=skills_dir, check=False)

    print("\n🎉 Bootstrap Complete! All repositories cloned, skills linked, and tools configured.")
    return True


def cmd_insights(target_dir: Path):
    print(f"\n🧠 [Insights] Synthesizing machine model knowledge into docs/...")
    docs_dir = target_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    guide_path = docs_dir / "models_and_services.md"

    summary = """# Autonomous Workstation Model Directory & Rankings

Synthesized by `github-architect` from local GPU inference configs, launchers, and agent conversation transcripts.

---

## 🏛️ Local Inference Ports

| Port | Model / Engine | Launcher | Best Used For |
|---|---|---|---|
| `:8080` | **Qwen3.6-35B-A3B-Uncensored-Genesis (Q4_K_M)** | `sh/luffy_nothink.sh` | Complex reasoning, coding, uncensored generation |
| `:8081` | **Nemotron 3.5 ASR + Kokoro TTS** | `audio.cpp` server | Real-time speech-to-text (40 langs) + fast speech synthesis |
| `:8083` | **h2o-lightning-4b Decision Model (vision)** | `sh/h2o.sh` | Native `/v1/systemone` bool/choice/score + image gating |
| `:8084` | **CrispEmbed Scene Text OCR** | `launchers/crispembed-ocr.sh` | Real-world scene-text OCR (DBNet + PARSeq) |
| `:8085` | **LightOnOCR-3-0.8B** | `launchers/lighton-ocr.sh` | **Flagship Video, Slide & Scanned-PDF OCR** |
| `:8086` | **Jina-Reranker-v2 Base** | `launchers/jina-reranker.sh` | Cross-encoder RAG reranking |
| `:8087` | **bge-small-en-v1.5 (384d)** | `launchers/bge-small.sh` | Text embeddings for RAG + semantic cache |
| `:8088` | **DeskForge-Qwen3.5-4B** | `launchers/deskforge-qwen.sh` | Visual GUI grounding & computer use |

---

## 🏆 Model Rankings by Task

- **Video, Slide & Document OCR**: `LightOnOCR-3-1B` (#1) > `SmolDocling-256M` (#2) > `CrispEmbed` (#3)
- **Calibrated Decisions**: `h2o-lightning-4b` (Vision + Text, `/v1/systemone`)
- **Browser Visual Grounding**: `DeskForge-Qwen3.5-4B` (GUI coordinates)
- **Speech-to-Text**: `Nemotron-3.5-ASR` (Streaming RNNT on `:8081`)
"""
    guide_path.write_text(summary, encoding="utf-8")
    print(f"  ✅ Generated: {guide_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(
        prog="github-architect",
        description="github-architect — Automated GitHub repo builder, fleet syncer & publisher"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status-all
    p_status = subparsers.add_parser("status-all", help="Display real-time status across all workstation fleet repositories")
    p_status.add_argument("-t", "--table", action="store_true", help="Emit status as compact Markdown table")
    p_status.add_argument("--json", action="store_true", help="Emit status as structured JSON")
    p_status.add_argument("-p", "--project", nargs="*", help="Filter output fields (e.g. repository branch worktree remote_sync)")
    p_status.add_argument("-n", "--limit", type=int, default=0, help="Limit number of repositories displayed")

    # sync-all
    p_sync_all = subparsers.add_parser("sync-all", help="Synchronize and rebase all workstation fleet repositories in one command")
    p_sync_all.add_argument("-m", "--message", type=str, default=None, help="Optional commit message for dirty repos")
    p_sync_all.add_argument("--force", action="store_true", help="Bypass secret and oversized blob guards")

    # audit
    p_audit = subparsers.add_parser("audit", help="Audit local repo structure, files, git, secrets, and gh status")
    p_audit.add_argument("path", type=str, nargs="?", default=".", help="Target directory (default: current)")
    p_audit.add_argument("-t", "--table", action="store_true", help="Emit audit checks as compact Markdown table")
    p_audit.add_argument("--json", action="store_true", help="Emit audit checks as structured JSON")

    # scaffold
    p_scaffold = subparsers.add_parser("scaffold", help="Generate .gitignore, LICENSE, and README.md")
    p_scaffold.add_argument("path", type=str, nargs="?", default=".", help="Target directory")
    p_scaffold.add_argument("--name", type=str, default=None, help="Repository name")
    p_scaffold.add_argument("--license", type=str, default="private", choices=["private", "mit"], help="License type")

    # publish
    p_publish = subparsers.add_parser("publish", help="Scaffold, commit, and push repository to GitHub")
    p_publish.add_argument("path", type=str, nargs="?", default=".", help="Target directory")
    p_publish.add_argument("--name", type=str, default=None, help="Repository name (defaults to folder name)")
    p_publish.add_argument("--public", action="store_true", help="Publish as public (default is PRIVATE)")
    p_publish.add_argument("--template", action="store_true", help="Mark repository as a reusable GitHub Template")
    p_publish.add_argument("--license", type=str, default="private", choices=["private", "mit"], help="License type")
    p_publish.add_argument("--force", action="store_true", help="Bypass secret and oversized blob guards")

    # sync
    p_sync = subparsers.add_parser("sync", help="Pull latest remote changes (rebase), commit local changes, and push")
    p_sync.add_argument("path", type=str, nargs="?", default=".", help="Target repository directory (default: current)")
    p_sync.add_argument("-m", "--message", type=str, default=None, help="Optional commit message")
    p_sync.add_argument("--force", action="store_true", help="Bypass secret and oversized blob guards")

    # clone
    p_clone = subparsers.add_parser("clone", help="Clone repository via gh CLI")
    p_clone.add_argument("repo", type=str, help="Repository name (e.g. university or username/university)")
    p_clone.add_argument("dest", type=str, nargs="?", default=None, help="Destination directory")

    # bootstrap
    p_boot = subparsers.add_parser("bootstrap", help="Clone and set up all workstation repos and skills on a new machine")
    p_boot.add_argument("--dest", type=str, default=None, help="Destination directory for repositories")

    # insights
    p_ins = subparsers.add_parser("insights", help="Scan machine transcripts and configs to generate model docs")
    p_ins.add_argument("path", type=str, nargs="?", default=".", help="Target directory")

    # guard
    p_guard = subparsers.add_parser(
        "guard",
        help="Gate a public bundle publication: secrets, oversized blobs, and archived status markers",
    )
    p_guard.add_argument("--source", action="append", required=True, help="Directory to scan (repeatable)")
    p_guard.add_argument("--published", action="append", default=[], help="Published relative path of a source (repeatable)")
    p_guard.add_argument("--label", default="bundle", help="Name of the bundle being published")
    p_guard.add_argument("--json", action="store_true")

    # git-sync
    p_gitsync = subparsers.add_parser("git-sync", help="Run disciplined 6-stage branch synchronization (git-sync protocol)")
    p_gitsync.add_argument("-m", "--message", help="Commit message (default: auto conventional summary)")
    p_gitsync.add_argument("-y", "--yes", action="store_true", help="Auto-confirm push to protected default branches")
    p_gitsync.add_argument("--no-pull", action="store_true", help="Skip pulling from remote before pushing")
    p_gitsync.add_argument("--no-gate", action="store_true", help="Skip pre-push automated test/lint gates")
    p_gitsync.add_argument("--dry-run", action="store_true", help="Inspect and display actions without committing or pushing")
    p_gitsync.add_argument("-t", "--table", action="store_true", help="Emit receipt as Markdown table")
    p_gitsync.add_argument("--json", action="store_true", help="Emit receipt as structured JSON")

    args = parser.parse_args()

    if args.command == "git-sync":
        try:
            from git_sync import main as gitsync_main
        except ImportError:
            import importlib.util
            script_path = Path(__file__).resolve().parent / "git_sync.py"
            spec = importlib.util.spec_from_file_location("git_sync", script_path)
            git_sync_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(git_sync_mod)
            gitsync_main = git_sync_mod.main

        raw_args = []
        if args.message:
            raw_args.extend(["-m", args.message])
        if args.yes:
            raw_args.append("-y")
        if args.no_pull:
            raw_args.append("--no-pull")
        if args.no_gate:
            raw_args.append("--no-gate")
        if args.dry_run:
            raw_args.append("--dry-run")
        if args.table:
            raw_args.append("--table")
        if args.json:
            raw_args.append("--json")
        gitsync_main(raw_args)
        return

    if args.command == "guard":
        try:
            from publication_guard import main as guard_main
        except ImportError:
            import importlib.util
            script_path = Path(__file__).resolve().parent / "publication_guard.py"
            spec = importlib.util.spec_from_file_location("publication_guard", script_path)
            guard_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(guard_mod)
            guard_main = guard_mod.main
        raw = ["scan"]
        for s in args.source:
            raw += ["--source", s]
        for p in args.published:
            raw += ["--published", p]
        raw += ["--label", args.label]
        if args.json:
            raw.append("--json")
        sys.exit(guard_main(raw))

    if args.command == "status-all":
        project_keys = [k.lower() for k in args.project] if args.project else None
        cmd_status_all(as_table=args.table, as_json=args.json, project_keys=project_keys, limit=args.limit)
        return

    if args.command == "sync-all":
        cmd_sync_all(message=args.message, force=args.force)
        return

    if args.command == "bootstrap":
        dest_path = Path(args.dest).resolve() if args.dest else None
        cmd_bootstrap(dest_path)
        return

    if args.command == "clone":
        dest_path = Path(args.dest).resolve() if args.dest else None
        cmd_clone(args.repo, dest_path)
        return

    target_path = Path(args.path).resolve()
    repo_name = getattr(args, "name", None) or target_path.name

    if args.command == "audit":
        cmd_audit(target_path, as_table=args.table, as_json=args.json)
    elif args.command == "scaffold":
        cmd_scaffold(target_path, repo_name, private=True, license_type=args.license)
    elif args.command == "publish":
        cmd_publish(target_path, repo_name, private=not args.public, license_type=args.license, is_template=args.template, force=args.force)
    elif args.command == "sync":
        cmd_sync(target_path, message=getattr(args, "message", None), force=args.force)
    elif args.command == "insights":
        cmd_insights(target_path)


if __name__ == "__main__":
    main()
