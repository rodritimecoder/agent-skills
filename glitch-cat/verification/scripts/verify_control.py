from __future__ import annotations

import hashlib
import json
from pathlib import Path

from verify_common import (
    Dependency,
    EXIT_PASS,
    EXIT_FAIL,
    _rel,
)
from verify_forge import PROTECTED_PARTS, PROTECTED_SUFFIXES

def _get_default_gate(pass_path, artifacts):
    import verify
    return verify.run_pass(verify.load_pass(pass_path), out_dir=artifacts)

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _guard_target(root: Path, target: Path) -> Path:
    path = (root / target).resolve() if not target.is_absolute() else target.resolve()
    if path != root and root not in path.parents:
        raise Dependency(f"{path} is outside the repository at {root}")
    if PROTECTED_PARTS & set(path.parts):
        raise Dependency(f"{path} is a protected path; a control run does not edit it")
    if path.name.startswith(".env") or path.suffix in PROTECTED_SUFFIXES:
        raise Dependency(f"{path} looks like a credential file; refusing to mutate it")
    return path


def control(repo: Path, target: Path, find: str, replace: str,
            pass_file: Path = Path(".verify/pass.json"), out_dir: Path | None = None,
            runner=None) -> dict:
    root = Path(repo).resolve()
    path = _guard_target(root, target)
    if not path.is_file():
        raise Dependency(f"no file at {path}")
    original = path.read_bytes()
    before = hashlib.sha256(original).hexdigest()
    text = original.decode(errors="ignore")
    count = text.count(find)
    if count != 1:
        raise Dependency(f"the find string occurs {count} times in {path}; the control needs exactly one")
    if find == replace:
        raise Dependency("find and replace are identical; nothing would be broken")
    artifacts = out_dir or (root / ".verify" / "artifacts")
    pass_path = pass_file if pass_file.is_absolute() else root / pass_file
    gate = runner or (lambda: _get_default_gate(pass_path, artifacts))

    red: dict = {}
    green: dict = {}
    try:
        path.write_text(text.replace(find, replace, 1))
        red = gate()
    finally:
        path.write_bytes(original)

    restored = _sha256(path) == before
    if restored:
        green = gate()

    red_seen = red.get("exit") == EXIT_FAIL or red.get("verdict") == "fail"
    green_seen = green.get("verdict") == "pass" and green.get("exit") == EXIT_PASS
    if not restored:
        verdict, exit_code = "fail", EXIT_FAIL
    elif not red_seen:
        verdict, exit_code = "fail", EXIT_FAIL
    elif not green_seen:
        verdict, exit_code = "fail", EXIT_FAIL
    else:
        verdict, exit_code = "pass", EXIT_PASS

    report = {
        "verdict": verdict,
        "exit": exit_code,
        "target": _rel(path, root),
        "find": find,
        "replace": replace,
        "sha256_before": before,
        "sha256_after": _sha256(path),
        "restored": restored,
        "red": {"verdict": red.get("verdict"), "exit": red.get("exit"), "failed": red.get("failed", [])},
        "green": {"verdict": green.get("verdict"), "exit": green.get("exit")},
        "detail": ("the gate was seen failing on the mutation and passing after the exact restore"
                   if verdict == "pass" else
                   "the gate stayed green on a broken feature" if not red_seen else
                   "the file was not restored byte for byte" if not restored else
                   "the gate did not pass after the restore"),
    }
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "control.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    return report


