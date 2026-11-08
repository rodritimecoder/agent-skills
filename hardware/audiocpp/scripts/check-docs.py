#!/usr/bin/env python3
"""Fail when this folder's claims disagree with the installed audio.cpp.

Every fault that survived in this skill was a fact stated in two places and
checked in none: the port slot said 0.9.0 while the binary said 0.9.3, the
architecture note said 0.9.3 while the symlink pointed at 0.9.4, and the
launcher named a server.json that had never existed. This script gives the
folder one place to be wrong in.

Exit 0 = every claim matches. Exit 1 = drift, printed line by line.
"""

from __future__ import annotations

import json
import re
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVE = Path("/run/media/rodri/AI")
LINK = DRIVE / "audio.cpp"
PORT = 8081

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append((ok, f"{label}{': ' + detail if detail else ''}"))
    return ok


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def binary_version(install: Path) -> str | None:
    """The install's own opinion, which outranks every document in this folder."""
    import subprocess

    cli = install / "audiocpp_cli"
    if not cli.is_file():
        return None
    try:
        out = subprocess.run(
            [str(cli), "--version"], capture_output=True, text=True, timeout=30
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    m = re.search(r"audio\.cpp\s+([0-9][0-9.]*)", out.stdout)
    return m.group(1) if m else None


def claimed_versions() -> dict[str, str]:
    """Every document that states a version, so they can be compared to the binary."""
    claims: dict[str, str] = {}

    ctx = read(ROOT / "CONTEXT.md")
    m = re.search(r"\*\*Version:\*\*\s+`([0-9][0-9.]*)`", ctx)
    if m:
        claims["CONTEXT.md"] = m.group(1)

    ports = json.loads(read(ROOT.parent.parent / "ports.json"))
    slot = next((s for s in ports.get("slots", []) if s.get("id") == "audio"), None)
    if slot is None:  # tolerate a flat list of slots
        slot = next((s for s in ports if isinstance(s, dict) and s.get("id") == "audio"), None)
    if slot and (m := re.search(r"audio\.cpp\s+([0-9][0-9.]*)", slot.get("service", ""))):
        claims["ports.json"] = m.group(1)

    return claims


def declared_stale() -> set[str]:
    ctx = read(ROOT / "CONTEXT.md")
    m = re.search(r"\*\*Stale config entries:\*\*(.+)", ctx)
    return set(re.findall(r"`([^`]+)`", m.group(1))) if m else set()


def fenced_json(path: Path) -> dict | None:
    m = re.search(r"```json\n(.*?)\n```", read(path), re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def cli_registry() -> dict:
    """The wrapper's slug table, imported rather than parsed.

    A caller types `--model nemotron`; the server serves `nemotron-asr`. Both
    names have to be right, so the mapping is read from the code that owns it.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "audiocpp_cli_under_test", ROOT / "scripts/audiocpp_cli.py"
    )
    if spec is None or spec.loader is None:
        return {}
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return {}
    return getattr(module, "MODEL_REGISTRY", {})


def main() -> int:
    # 1. The switch point resolves and holds a usable install.
    target = LINK.resolve() if LINK.is_symlink() or LINK.is_dir() else None
    if not check(LINK.exists(), "symlink", f"{LINK} -> {target}"):
        return report()
    for name in ("audiocpp_cli", "audiocpp_server", "server.json"):
        check((LINK / name).exists(), f"install/{name}")

    # 2. One version: the binary, the contract, the port slot.
    live = binary_version(LINK)
    if not check(live is not None, "binary --version"):
        return report()
    for doc, claim in claimed_versions().items():
        check(claim == live, f"version in {doc}", f"says {claim}, install is {live}")

    # 3. The seed and the doc must describe the config that is actually loaded.
    seed = json.loads(read(ROOT / "references/server.json"))
    live_cfg = json.loads(read(LINK / "server.json"))
    check(seed == live_cfg, "references/server.json == live server.json")

    md_cfg = fenced_json(ROOT / "references/server-json.md")
    check(md_cfg == seed, "server-json.md fenced block == seed")

    # 3b. The harness entry states the version too, in prose and in frontmatter.
    # Install paths (`audio-v0.9.5-bin-…`) are examples, not claims.
    skill = read(ROOT / "SKILL.md")
    stated = sorted(set(re.findall(r"(?<!audio-)v0\.9\.\d+", skill)))
    check(
        stated == [f"v{live}"],
        "version mentioned in SKILL.md",
        f"mentions {stated}, install is v{live}",
    )

    # 4. Every model file on disk, except the ones this folder declares stale.
    missing = {
        m["id"] for m in live_cfg["models"] if not Path(m["path"]).is_file()
    }
    stated = declared_stale()
    check(
        missing == stated,
        "stale model entries",
        f"missing={sorted(missing) or '{}'} declared={sorted(stated) or '{}'}",
    )

    # 5. Clone references exist, because a preset pointing nowhere fails at request time.
    for model in live_cfg["models"]:
        for preset, spec in (model.get("voice_presets") or {}).items():
            ref = spec.get("voice_ref")
            if ref:
                check(Path(ref).is_file(), f"voice preset {preset}", ref)

    # 6. The default is a triple claim: this file's Defaults line, the CLI
    #    constants, and the mode the server actually loads the model in.
    m = re.search(r"\*\*Defaults:\*\*\s+tts\s+`([^`]+)`\s+·\s+asr\s+`([^`]+)`", read(ROOT / "CONTEXT.md"))
    if check(m is not None, "CONTEXT.md declares Defaults"):
        default_tts, default_asr = m.group(1), m.group(2)
        cli_src = read(ROOT / "scripts/audiocpp_cli.py")
        for const, want in (("DEFAULT_TTS", default_tts), ("DEFAULT_ASR", default_asr)):
            got = re.search(rf'^{const}\s*=\s*"([^"]+)"', cli_src, re.M)
            check(
                bool(got) and got.group(1) == want,
                f"{const} matches CONTEXT.md",
                f"cli={got.group(1) if got else '?'} context={want}",
            )
        by_id = {m["id"]: m for m in live_cfg["models"]}
        registry = cli_registry()
        for label, slug in (("tts", default_tts), ("asr", default_asr)):
            meta = registry.get(slug) or {}
            model_id = meta.get("server_id", slug)  # the slug the caller types vs the id the server serves
            entry = by_id.get(model_id)
            if not check(entry is not None, f"default {label} exists", f"{slug} -> {model_id}"):
                continue
            check(
                entry.get("mode") == "streaming",
                f"default {label} served streaming",
                f"{model_id} mode={entry.get('mode')}",
            )

    # 7. Links inside this folder resolve.
    for doc in ("README.md", "CONTEXT.md", "SKILL.md"):
        text = read(ROOT / doc)
        for target_link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if target_link.startswith(("http://", "https://", "#")):
                continue
            path = (ROOT / target_link.split("#")[0]).resolve()
            check(path.exists(), f"link in {doc}", target_link)

    return report()


def report() -> int:
    failures = [line for ok, line in results if not ok]
    for ok, line in results:
        print(f"{'PASS' if ok else 'FAIL'}  {line}")
    print()
    if failures:
        print(f"{len(failures)} claim(s) disagree with the install. Fix the docs or the install.")
        return 1
    print(f"{len(results)} checks pass: this folder and the install agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
