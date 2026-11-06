#!/usr/bin/env python3
"""
publication_guard.py — Pre-publication safety gate for public skill bundles.

The hub (`my-agent-skills`) is private. The spokes (`workstation-clis`,
`glitch-cat-skills`, `academic-agent-skills`, `free-frontier-skills`) are
public. Every file the sync copies from a hub into a spoke is a one-way trip:
a mistake made in the hub becomes permanent and public on the next push, and
fixing it later means rewriting public history.

This gate runs before each spoke publication and refuses to publish:

  * secret-shaped filenames (`.env`, `*.pem`, `*.key`, `id_rsa`, `credentials.json`)
  * credential content in any text file
  * files above the 50 MB blob ceiling
  * a skill published from an `archived/` path that carries no archived status
    marker, so a retired tool cannot read as a supported one

It also reaps directories a spoke used to publish and no longer does. A
skill that leaves the manifest used to leave a frozen copy behind, because
the bundle sync copies per skill and never pruned the spoke's root.

Usage:
    publication_guard.py scan --source DIR [--source DIR ...] --label NAME [--json]
    publication_guard.py reap --root DIR --managed-file FILE --current a,b,c [--json]

Exit codes: 0 clean, 1 blocked.
"""

import argparse
import fnmatch
import json
import re
import shutil
import sys
from pathlib import Path

MAX_BLOB_SIZE_MB = 50.0

SKIP_DIR_NAMES = {
    ".git", "__pycache__", ".venv", "venv", "env", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
}

SKIP_FILE_SUFFIXES = {".pyc", ".pyo", ".so", ".o", ".a"}

SECRET_FILE_PATTERNS = [
    (re.compile(r"^\.env(?!\.example$)"), "env file"),
    (re.compile(r"\.env$"), "env file"),
    (re.compile(r"\.pem$"), "private key file"),
    (re.compile(r"\.key$"), "private key file"),
    (re.compile(r"^id_rsa"), "ssh private key"),
    (re.compile(r"\.pfx$"), "pkcs12 bundle"),
    (re.compile(r"\.p12$"), "pkcs12 bundle"),
    (re.compile(r"credentials\.json$"), "credentials file"),
    (re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)$"), "ssh private key"),
]

SECRET_CONTENT_PATTERNS = [
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub Personal Access Token"),
    (re.compile(r"gho_[A-Za-z0-9]{36}"), "GitHub OAuth Token"),
    (re.compile(r"ghu_[A-Za-z0-9]{36}"), "GitHub User-to-Server Token"),
    (re.compile(r"ghs_[A-Za-z0-9]{36}"), "GitHub Server-to-Server Token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{22,}"), "GitHub Fine-Grained Token"),
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"), "Anthropic API Key"),
    (re.compile(r"sk-[A-Za-z0-9\-_]{20,}"), "OpenAI / LiteLLM Secret Key"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "Google API Key"),
    (re.compile(r"hf_[A-Za-z0-9]{34}"), "HuggingFace Token"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "Slack Token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "Private Key Block"),
    (re.compile(
        r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|"
        r"client[_-]?secret|password|passwd)\b\s*[:=]\s*[\"'][^\"'\s]{16,}[\"']"
    ), "Credential Assignment"),
]

PLACEHOLDER_MARKERS = (
    "<", ">", "{", "}", "$", "YOUR", "your", "XXX", "xxx", "EXAMPLE", "example",
    "placeholder", "PLACEHOLDER", "changeme", "CHANGEME", "redacted", "REDACTED",
    "TODO", "FIXME", "****", "....", "example-key", "notarealkey",
)

ARCHIVED_STATUS_VALUES = {"archived", "deprecated", "retired", "historical"}


def is_placeholder(value: str) -> bool:
    return any(marker in value for marker in PLACEHOLDER_MARKERS)


def is_excluded(rel_path: Path, patterns: list) -> bool:
    """Model rsync's --exclude semantics: a bare pattern matches any path
    component, a pattern containing '/' matches the relative path."""
    for pattern in patterns:
        if not pattern:
            continue
        if "/" in pattern:
            if fnmatch.fnmatch(str(rel_path), pattern):
                return True
        else:
            for part in rel_path.parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
    return False


def iter_files(root: Path, excludes: list = None):
    excludes = excludes or []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if is_excluded(rel, excludes):
            continue
        if any(part in SKIP_DIR_NAMES for part in rel.parts[:-1]):
            continue
        if path.suffix in SKIP_FILE_SUFFIXES:
            continue
        if path.name.endswith(".pyc"):
            continue
        yield path


def frontmatter(skill_md: Path) -> dict:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fields = {}
    for line in text[3:end].splitlines():
        if not line.strip() or line[:1].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key:
            fields[key] = value.strip().strip('"').strip("'")
    return fields


def scan_file(path: Path, label: str) -> list:
    findings = []
    for pattern, kind in SECRET_FILE_PATTERNS:
        if pattern.search(path.name):
            findings.append({
                "severity": "block", "kind": "secret-filename",
                "source": label, "path": path.name, "detail": f"blocked {kind}",
            })
            break

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_BLOB_SIZE_MB:
        findings.append({
            "severity": "block", "kind": "oversized-blob",
            "source": label, "path": path.name,
            "detail": f"{size_mb:.1f} MB exceeds the {MAX_BLOB_SIZE_MB:.0f} MB ceiling",
        })

    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return findings
    for pattern, kind in SECRET_CONTENT_PATTERNS:
        match = pattern.search(content)
        if not match:
            continue
        value = match.group(0)
        if is_placeholder(value):
            continue
        token = value[:6] + "..." + value[-4:] if len(value) > 12 else "***"
        findings.append({
            "severity": "block", "kind": "secret-content",
            "source": label, "path": path.name,
            "detail": f"{kind}: {token}",
        })
        break

    return findings


def scan_source(source: Path, label: str, excludes: list = None) -> list:
    findings = []
    if not source.is_dir():
        return findings

    for path in iter_files(source, excludes):
        for finding in scan_file(path, label):
            finding["path"] = str(path.relative_to(source))
            findings.append(finding)

    return findings


def scan_status_marker(source: Path, published_path: str, label: str) -> list:
    if "archived" not in Path(published_path).parts:
        return []
    skill_md = source / "SKILL.md"
    if not skill_md.is_file():
        return [{
            "severity": "block", "kind": "missing-status-marker",
            "source": label, "path": published_path,
            "detail": "published from an archived/ path but has no SKILL.md",
        }]
    fields = frontmatter(skill_md)
    status = fields.get("status", "").lower()
    deprecated = fields.get("deprecated", "").lower() in ("true", "yes")
    if status in ARCHIVED_STATUS_VALUES or deprecated:
        return []
    return [{
        "severity": "block", "kind": "missing-status-marker",
        "source": label, "path": published_path,
        "detail": (
            "published from an archived/ path but SKILL.md declares no archived "
            "status (add `status: archived` to the frontmatter)"
        ),
    }]


def load_managed(managed_file: Path) -> list:
    if not managed_file.is_file():
        return []
    try:
        data = json.loads(managed_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return list(data.get("managed", []))


def reap(bundle_root: Path, managed_file: Path, current: list) -> dict:
    previous = load_managed(managed_file)
    stale = [d for d in previous if d not in current]
    removed = []
    for rel in stale:
        target = bundle_root / rel
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        elif target.exists() or target.is_symlink():
            target.unlink()
        removed.append(rel)
        # Drop a parent that the removal emptied, but never the bundle root.
        parent = target.parent
        while parent != bundle_root and bundle_root in parent.parents:
            try:
                if not any(parent.iterdir()):
                    parent.rmdir()
                else:
                    break
            except OSError:
                break
            parent = parent.parent
    managed_file.write_text(
        json.dumps({"managed": sorted(current)}, indent=2) + "\n", encoding="utf-8"
    )
    return {"removed": removed, "managed": sorted(current)}


def cmd_scan(args) -> int:
    findings = []
    excludes = args.exclude or []
    published = args.published or []
    for index, raw in enumerate(args.source):
        source = Path(raw)
        findings.extend(scan_source(source, args.label, excludes))
        if index < len(published):
            findings.extend(scan_status_marker(source, published[index], args.label))
    blocked = [f for f in findings if f["severity"] == "block"]
    if args.json:
        print(json.dumps({
            "label": args.label,
            "findings": findings,
            "blocked": len(blocked),
        }, indent=2))
    else:
        if blocked:
            print(f"🛡️  [publication-guard] {args.label}: {len(blocked)} blocked file(s)")
            for f in blocked:
                print(f"   ❌ {f['path']} — {f['detail']}")
        else:
            print(f"✅ [publication-guard] {args.label}: clean")
    return 1 if blocked else 0


def cmd_reap(args) -> int:
    current = [c for c in args.current.split(",") if c]
    result = reap(Path(args.root), Path(args.managed_file), current)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["removed"]:
            print(f"🧹 [publication-guard] reaped {len(result['removed'])} stale dir(s): "
                  f"{', '.join(result['removed'])}")
        else:
            print(f"✅ [publication-guard] no stale dirs in {args.root}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Scan sources for secrets, oversized blobs, and status markers")
    p_scan.add_argument("--source", action="append", required=True, help="Directory to scan (repeatable)")
    p_scan.add_argument("--published", action="append", default=[], help="Published relative path of the source at the same index (repeatable)")
    p_scan.add_argument("--exclude", action="append", default=[], help="rsync-style exclude pattern (repeatable)")
    p_scan.add_argument("--label", default="bundle", help="Name of the bundle being published")
    p_scan.add_argument("--json", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_reap = sub.add_parser("reap", help="Remove directories a bundle no longer publishes")
    p_reap.add_argument("--root", required=True, help="Bundle repository root")
    p_reap.add_argument("--managed-file", required=True, help="File recording the previously managed dirs")
    p_reap.add_argument("--current", required=True, help="Comma-separated current managed dirs")
    p_reap.add_argument("--json", action="store_true")
    p_reap.set_defaults(func=cmd_reap)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
