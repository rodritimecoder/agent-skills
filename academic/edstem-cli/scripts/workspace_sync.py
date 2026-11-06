#!/usr/bin/env python3
"""Preview and safely apply Ed workspace snapshots to a Git repository."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MANIFEST = ".edstem-workspace.json"
MAX_FILE_BYTES = 50 * 1024 * 1024
SKIP_COMPONENTS = {".git", "build", "node_modules", "__pycache__"}
SKIP_NAMES = {".env", "credentials.json", "id_rsa", "id_ed25519"}


class WorkspaceSyncError(Exception):
    pass


def safe_relative_path(value: str) -> str:
    """Validate a workspace-relative POSIX path before using it locally."""
    raw = str(value)
    if not raw or "\x00" in raw or "\\" in raw:
        raise WorkspaceSyncError(f"unsafe workspace path: {raw!r}")
    if any(part in ("", ".", "..") for part in raw.split("/")):
        raise WorkspaceSyncError(f"unsafe workspace path: {raw!r}")
    path = PurePosixPath(raw)
    if path.is_absolute() or path.parts[0].endswith(":") or path.parts[0] == MANIFEST:
        raise WorkspaceSyncError(f"unsafe workspace path: {raw!r}")
    return path.as_posix()


def skip_reason(relative: str) -> str | None:
    """Exclude generated, backup, and credential-shaped files by default."""
    path = PurePosixPath(relative)
    name = path.name
    lowered = name.lower()
    if any(part in SKIP_COMPONENTS for part in path.parts):
        return "generated directory"
    if name in SKIP_NAMES or lowered.startswith(".env."):
        return "credential file"
    if lowered.endswith((".bak", ".swp", ".swo", "~", ".pem", ".key", ".p12", ".pfx")):
        return "backup or secret file"
    return None


def snapshot_files(snapshot: Path) -> tuple[dict[str, Path], list[dict[str, str]]]:
    """Return safe files and exclusions from a fully downloaded snapshot."""
    snapshot = Path(snapshot).resolve()
    files: dict[str, Path] = {}
    skipped: list[dict[str, str]] = []
    for path in sorted(snapshot.rglob("*")):
        if path.is_symlink():
            raise WorkspaceSyncError(f"snapshot contains symlink: {path.relative_to(snapshot)}")
        if not path.is_file():
            continue
        relative = safe_relative_path(path.relative_to(snapshot).as_posix())
        reason = skip_reason(relative)
        if reason:
            skipped.append({"path": relative, "reason": reason})
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceSyncError(f"file exceeds {MAX_FILE_BYTES} bytes: {relative}")
        files[relative] = path
    return files, skipped


def load_manifest(repo: Path) -> tuple[str | None, set[str]]:
    """Load the paths previously imported from this Ed workspace."""
    path = Path(repo) / MANIFEST
    if not path.is_file():
        return None, set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkspaceSyncError(f"cannot read {MANIFEST}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise WorkspaceSyncError(f"unsupported {MANIFEST} format")
    files = data.get("files")
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise WorkspaceSyncError(f"invalid files list in {MANIFEST}")
    return data.get("workspace_id"), {safe_relative_path(item) for item in files}


def compare_snapshot(snapshot: Path, repo: Path) -> dict:
    """Classify a downloaded tree without modifying the destination repo."""
    repo = Path(repo).resolve()
    files, skipped = snapshot_files(snapshot)
    previous_workspace, previous = load_manifest(repo)
    result = {"added": [], "changed": [], "unchanged": [], "removed": [], "skipped": skipped}
    for relative, source in files.items():
        target = repo / relative
        if not target.exists():
            result["added"].append(relative)
        elif target.is_symlink() or not target.is_file():
            raise WorkspaceSyncError(f"destination is not a regular file: {relative}")
        elif source.read_bytes() == target.read_bytes():
            result["unchanged"].append(relative)
        else:
            result["changed"].append(relative)
    result["removed"] = sorted(previous - set(files))
    result["workspace_id"] = previous_workspace
    result["files"] = files
    for key in ("added", "changed", "unchanged"):
        result[key].sort()
    return result


def unified_diff(snapshot: Path, repo: Path, report: dict, limit: int = 4000) -> str:
    """Render bounded text diffs for changed text files."""
    chunks: list[str] = []
    remaining = limit
    for relative in report["changed"]:
        before = (Path(repo) / relative).read_bytes()
        after = report["files"][relative].read_bytes()
        if b"\x00" in before or b"\x00" in after:
            chunks.append(f"Binary file differs: {relative}\n")
            continue
        try:
            old_text = before.decode("utf-8").splitlines(keepends=True)
            new_text = after.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            chunks.append(f"Binary file differs: {relative}\n")
            continue
        diff = list(difflib.unified_diff(
            old_text,
            new_text,
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        ))
        text = "".join(diff)
        if text:
            if len(text) > remaining:
                text = text[:remaining] + "\n[diff output truncated]\n"
            chunks.append(text)
            remaining -= len(text)
        if remaining <= 0:
            break
    return "".join(chunks)


def require_clean_git_repo(repo: Path) -> None:
    """Fail before applying if the destination has any uncommitted work."""
    import subprocess

    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorkspaceSyncError(f"not a Git repository: {repo}")
    if result.stdout.strip():
        raise WorkspaceSyncError(
            "destination Git tree is not clean; commit or save local changes before applying"
        )


def apply_snapshot(snapshot: Path, repo: Path, workspace_id: str) -> dict:
    """Copy new/changed Ed files and write a manifest; never delete files."""
    repo = Path(repo).resolve()
    snapshot = Path(snapshot).resolve()
    report = compare_snapshot(snapshot, repo)
    prior_id, prior_files = load_manifest(repo)
    if prior_id and prior_id != workspace_id:
        raise WorkspaceSyncError(
            f"repo manifest belongs to workspace {prior_id}, not {workspace_id}"
        )

    applied = []
    for relative in report["added"] + report["changed"]:
        safe_relative_path(relative)
        target = repo / relative
        current = repo
        for component in PurePosixPath(relative).parts[:-1]:
            current = current / component
            if current.is_symlink():
                raise WorkspaceSyncError(f"destination path crosses symlink: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise WorkspaceSyncError(f"refusing to overwrite symlink: {relative}")
        shutil.copyfile(report["files"][relative], target)
        applied.append(relative)

    managed = prior_files | set(report["files"])
    manifest = {
        "version": 1,
        "workspace_id": workspace_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "files": sorted(managed),
    }
    manifest_path = repo / MANIFEST
    temporary = manifest_path.with_name(MANIFEST + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)

    return {
        "applied": sorted(applied),
        "unchanged": report["unchanged"],
        "removed_not_deleted": report["removed"],
        "skipped": report["skipped"],
        "manifest": MANIFEST,
    }


def copy_tracked_repo(repo: Path, destination: Path) -> None:
    """Make a temporary test tree from tracked files only."""
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorkspaceSyncError(f"cannot list tracked repo files: {repo}")
    root = Path(repo).resolve()
    for raw in result.stdout.split(b"\x00"):
        if not raw:
            continue
        relative = safe_relative_path(raw.decode("utf-8"))
        source = root / relative
        if source.is_symlink():
            raise WorkspaceSyncError(f"tracked repo has symlink, cannot stage safely: {relative}")
        if not source.is_file():
            continue
        target = Path(destination) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _json_report(report: dict) -> dict:
    """Replace in-memory Path objects with strings so the report serializes."""
    return {
        "workspace_id": report.get("workspace_id"),
        "snapshot": str(report["snapshot"]) if report.get("snapshot") else None,
        "added": report.get("added", []),
        "changed": report.get("changed", []),
        "unchanged": report.get("unchanged", []),
        "removed": report.get("removed", []),
        "skipped": report.get("skipped", []),
        "files": {key: str(value) for key, value in report.get("files", {}).items()},
    }


def _render_compare(report: dict, diff: str) -> str:
    lines = [
        f"[workspace-sync] snapshot: {report.get('snapshot')}",
        f"[workspace-sync] workspace: {report.get('workspace_id') or '(none)'}",
        f"[workspace-sync] added: {len(report['added'])} | changed: {len(report['changed'])} | "
        f"unchanged: {len(report['unchanged'])} | removed: {len(report['removed'])} | "
        f"skipped: {len(report['skipped'])}",
    ]
    for relative in report["added"]:
        lines.append(f"  + {relative}")
    for relative in report["changed"]:
        lines.append(f"  ~ {relative}")
    for relative in report["removed"]:
        lines.append(f"  - {relative} (not deleted)")
    for item in report["skipped"]:
        lines.append(f"  · {item['path']} ({item['reason']})")
    if diff:
        lines.append("")
        lines.append(diff.rstrip())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview and safely apply Ed workspace snapshots to a Git repository."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare_parser = subparsers.add_parser("compare", help="Preview a snapshot against a repo")
    compare_parser.add_argument("--snapshot", type=Path, required=True, help="Downloaded workspace snapshot directory")
    compare_parser.add_argument("--repo", type=Path, required=True, help="Destination Git repository")
    compare_parser.add_argument("--diff", action="store_true", help="Include bounded text diffs for changed files")
    compare_parser.add_argument("--limit", type=int, default=4000, metavar="LIMIT", help="Maximum diff characters (default: 4000)")
    compare_parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report on stdout")

    apply_parser = subparsers.add_parser("apply", help="Copy new/changed files and write the manifest")
    apply_parser.add_argument("--snapshot", type=Path, required=True, help="Downloaded workspace snapshot directory")
    apply_parser.add_argument("--repo", type=Path, required=True, help="Destination Git repository")
    apply_parser.add_argument("--workspace-id", type=str, required=True, help="Ed workspace identifier")
    apply_parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report on stdout")

    args = parser.parse_args(argv)

    def progress(message: str = "") -> None:
        print(message, file=sys.stderr if args.json else sys.stdout)

    try:
        if args.command == "compare":
            report = compare_snapshot(args.snapshot, args.repo)
            report["snapshot"] = Path(args.snapshot).resolve()
            diff = unified_diff(args.snapshot, args.repo, report, limit=args.limit) if args.diff else ""
            if args.json:
                payload = _json_report(report)
                payload["diff"] = diff
                print(json.dumps(payload, indent=2))
            else:
                progress(_render_compare(report, diff))
            return 0

        require_clean_git_repo(args.repo)
        result = apply_snapshot(args.snapshot, args.repo, args.workspace_id)
        result["snapshot"] = str(Path(args.snapshot).resolve())
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            progress(
                f"[workspace-sync] applied: {len(result['applied'])} | "
                f"unchanged: {len(result['unchanged'])} | "
                f"removed (not deleted): {len(result['removed_not_deleted'])}"
            )
            progress(f"[workspace-sync] manifest: {result['manifest']}")
        return 0
    except WorkspaceSyncError as exc:
        print(f"[workspace-sync] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
