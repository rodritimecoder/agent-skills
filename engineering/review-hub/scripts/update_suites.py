#!/usr/bin/env python3
"""
update_suites.py — Refresh the vendored upstream suites.

`ponytail` and `pstack` are third-party collections vendored into
`suites/`. They move upstream, and a stale copy is worse than no copy: the
rubrics drift from the playbooks they describe.

The vendoring is not a plain copy. `review_hub.py` resolves a suite through
`resolve_suite_file()`, which looks for `rubric.md` — not `SKILL.md` — so the
vendored tree renames every `SKILL.md` to `rubric.md`. `pstack` additionally
hoists `skills/poteto-mode/{playbooks,references,scripts}` to the suite root
and keeps a locally written root `rubric.md` that describes the suite itself.

This script reproduces that layout from the upstream tree, so the vendored
copy can be refreshed without hand-copying 200 files and without losing the
adapter contract.

Usage:
    update_suites.py --check            report upstream vs vendored versions
    update_suites.py --suite ponytail   refresh one suite
    update_suites.py --suite all        refresh every vendored suite
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REVIEW_HUB_DIR = Path(__file__).resolve().parent.parent
SUITES_DIR = REVIEW_HUB_DIR / "suites"
STATE_FILE = SUITES_DIR / "UPSTREAMS.json"

SUITES = {
    "ponytail": {
        "repo": "https://github.com/DietrichGebert/ponytail.git",
        "subdir": "",
        "sparse": None,
        "version_file": "package.json",
        "version_key": "version",
        # upstream skill directory -> vendored filename
        "skill_map": {
            "ponytail": "rubric.md",
            "ponytail-review": "review.md",
            "ponytail-audit": "audit.md",
            "ponytail-debt": "debt.md",
            "ponytail-gain": "gain.md",
            "ponytail-help": "help.md",
        },
        "copy_dirs": ["docs", "scripts"],
        "hoist": [],
        "preserve": [],
    },
    "pstack": {
        "repo": "https://github.com/cursor/plugins.git",
        "subdir": "pstack",
        "sparse": "pstack",
        "version_file": "plugin.json",
        "version_key": "version",
        "skill_map": {},
        "copy_dirs": [],
        "hoist": ["playbooks", "references", "scripts"],
        "preserve": ["rubric.md"],
        "rename_skill_md": "rubric.md",
    },
}


def run(cmd, cwd=None, check=True):
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{res.stderr.strip()}")
    return res


def upstream_version(root: Path, spec: dict) -> str:
    data = json.loads((root / spec["version_file"]).read_text(encoding="utf-8"))
    return str(data.get(spec["version_key"], "?"))


def fetch(name: str, spec: dict, workdir: Path) -> Path:
    dest = workdir / name
    if spec.get("sparse"):
        run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", spec["repo"], str(dest)])
        run(["git", "sparse-checkout", "set", spec["sparse"]], cwd=dest)
    else:
        run(["git", "clone", "--depth", "1", spec["repo"], str(dest)])
    root = dest / spec["subdir"] if spec["subdir"] else dest
    if not root.is_dir():
        raise RuntimeError(f"{name}: upstream subdir '{spec['subdir']}' not found at {root}")
    return root


def read_state() -> dict:
    if not STATE_FILE.is_file():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def apply_ponytail(upstream: Path, target: Path) -> dict:
    copied = []
    for skill_dir, filename in SUITES["ponytail"]["skill_map"].items():
        src = upstream / "skills" / skill_dir / "SKILL.md"
        if not src.is_file():
            raise RuntimeError(f"ponytail: upstream skill missing: {src}")
        shutil.copy2(src, target / filename)
        copied.append(filename)
    for d in SUITES["ponytail"]["copy_dirs"]:
        src = upstream / d
        if not src.is_dir():
            continue
        dst = target / d
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        copied.append(f"{d}/")
    return {"copied": copied}


def apply_pstack(upstream: Path, target: Path) -> dict:
    copied = []
    preserved = {}
    for rel in SUITES["pstack"]["preserve"]:
        src = target / rel
        if src.is_file():
            preserved[rel] = src.read_text(encoding="utf-8")

    # Replace the vendored tree wholesale so upstream deletions propagate.
    for child in target.iterdir():
        if child.name in preserved:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    for child in upstream.iterdir():
        dst = target / child.name
        if child.is_dir():
            shutil.copytree(child, dst)
        else:
            shutil.copy2(child, dst)

    # Hoist the playbooks and helpers out of the poteto-mode skill so the
    # vendored layout stays the one the 0.15.x tree had.
    poteto = target / "skills" / "poteto-mode"
    for d in SUITES["pstack"]["hoist"]:
        src = poteto / d
        if not src.is_dir():
            continue
        dst = target / d
        if dst.exists():
            shutil.rmtree(dst)
        shutil.move(str(src), str(dst))
        copied.append(f"{d}/")
    if poteto.is_dir() and not any(poteto.iterdir()):
        poteto.rmdir()

    # The review-hub contract: a suite resolves through rubric.md.
    renamed = 0
    for skill_md in sorted(target.rglob("SKILL.md")):
        skill_md.rename(skill_md.with_name(SUITES["pstack"]["rename_skill_md"]))
        renamed += 1
    copied.append(f"{renamed} SKILL.md -> rubric.md")

    for rel, text in preserved.items():
        (target / rel).write_text(text, encoding="utf-8")
        copied.append(f"preserved {rel}")
    return {"copied": copied}


def refresh(name: str) -> dict:
    spec = SUITES[name]
    target = SUITES_DIR / name
    if not target.is_dir():
        raise RuntimeError(f"{name}: vendored suite missing at {target}")
    with tempfile.TemporaryDirectory() as tmp:
        upstream = fetch(name, spec, Path(tmp))
        version = upstream_version(upstream, spec)
        if name == "ponytail":
            result = apply_ponytail(upstream, target)
        else:
            result = apply_pstack(upstream, target)
    return {"version": version, **result}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="all", choices=["all"] + sorted(SUITES))
    parser.add_argument("--check", action="store_true", help="report versions without changing anything")
    args = parser.parse_args(argv)

    names = sorted(SUITES) if args.suite == "all" else [args.suite]
    state = read_state()
    failures = 0

    for name in names:
        spec = SUITES[name]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                upstream = fetch(name, spec, Path(tmp))
                version = upstream_version(upstream, spec)
        except Exception as exc:
            print(f"❌ {name}: could not reach upstream — {exc}")
            failures += 1
            continue

        local = state.get(name, {}).get("version", "unknown")
        if args.check:
            drift = "UP TO DATE" if local == version else f"DRIFT (vendored {local})"
            print(f"{name:12} upstream={version:10} vendored={local:10} {drift}")
            continue

        try:
            result = refresh(name)
        except Exception as exc:
            print(f"❌ {name}: refresh failed — {exc}")
            failures += 1
            continue

        state[name] = {
            "version": result["version"],
            "repo": spec["repo"],
            "updated_at": subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
                                         capture_output=True, text=True).stdout.strip(),
        }
        print(f"✅ {name}: refreshed to {result['version']} ({len(result['copied'])} paths)")

    if not args.check:
        write_state(state)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
