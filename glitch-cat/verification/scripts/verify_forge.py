from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from verify_common import (
    Dependency,
    EXIT_PASS,
    EXIT_FAIL,
    EXIT_USAGE,
    EXIT_DEPENDENCY,
    EXIT_UNCONFIGURED,
    QUESTIONS,
    init_config,
)

SURFACE_TOOLS = {
    "web": [("playwright", "drives a real browser: clicks, typing, screenshots, one journey per feature"),
            ("your browser", "Chrome or Edge already installed, so the site behaves as it does for visitors")],
    "cli": [("its own CLI", "runs the real command and reads stdout, stderr and the exit code")],
    "api": [("a fake outbox", "sends real requests and catches outgoing email, so nothing leaves the machine")],
    "desktop": [("Chrome DevTools", "remote-controls the real app window and reads its console")],
    "mobile": [("adb", "taps the real buttons on an emulator and reads the screen")],
}

HARNESS_ROOTS = {
    "agents": ".agents/skills",
    "opencode": ".opencode/skills",
    "claude": ".claude/skills",
}

PROTECTED_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__"}
PROTECTED_SUFFIXES = {".pem", ".key", ".p12", ".keystore"}

ROUTE_GLOBS = (
    ("app/**/page.tsx", ""),
    ("app/**/page.jsx", ""),
    ("app/**/page.ts", ""),
    ("app/**/page.js", ""),
    ("src/app/**/page.tsx", ""),
    ("src/app/**/page.jsx", ""),
    ("pages/**/*.tsx", ""),
    ("pages/**/*.jsx", ""),
    ("src/routes/**/+page.svelte", ""),
    ("src/pages/**/*.astro", ""),
    ("*.html", ""),
    ("public/*.html", ""),
)

API_PATTERNS = (
    re.compile(r"@(?:app|router)\.(?:get|post|put|patch|delete)\(\s*[\"']([^\"']+)"),
    re.compile(r"@app\.route\(\s*[\"']([^\"']+)"),
    re.compile(r"(?:app|router)\.(?:get|post|put|patch|delete)\(\s*[\"']([^\"']+)"),
)

SCAN_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "app"


def _title(value: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_/]+", value) if part) or "Feature"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _json_or(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _pkg(repo: Path) -> dict:
    return _json_or(repo / "package.json")


def _deps(pkg: dict) -> set[str]:
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        names.update(pkg.get(key) or {})
    return names


def _pyproject(repo: Path) -> str:
    path = repo / "pyproject.toml"
    return path.read_text(errors="ignore") if path.is_file() else ""


def _requirements(repo: Path) -> str:
    text = []
    for name in ("requirements.txt", "requirements-dev.txt", "setup.py", "setup.cfg"):
        path = repo / name
        if path.is_file():
            text.append(path.read_text(errors="ignore"))
    return "\n".join(text)


def _detect_surfaces(repo: Path, pkg: dict) -> list[dict]:
    deps = _deps(pkg)
    python = _pyproject(repo) + "\n" + _requirements(repo)
    surfaces: list[dict] = []

    def add(surface: str, evidence: str) -> None:
        if surface not in [row["surface"] for row in surfaces]:
            surfaces.append({"surface": surface, "evidence": evidence})

    for marker in ("next.config.js", "next.config.mjs", "next.config.ts", "vite.config.ts",
                   "vite.config.js", "svelte.config.js", "astro.config.mjs", "nuxt.config.ts",
                   "remix.config.js", "angular.json"):
        if (repo / marker).is_file():
            add("web", marker)
    if deps & {"react", "vue", "svelte", "@angular/core", "next", "nuxt", "astro", "@sveltejs/kit", "solid-js"}:
        add("web", "package.json dependencies")
    if any((repo / name).is_file() for name in ("index.html", "public/index.html")):
        add("web", "index.html")
    if deps & {"electron", "@tauri-apps/api", "tauri"}:
        add("desktop", "package.json dependencies")
    if any((repo / name).is_dir() for name in ("android", "ios")) or (repo / "AndroidManifest.xml").is_file():
        add("mobile", "android/ or ios/ directory")
    if deps & {"express", "fastify", "koa", "hapi", "@nestjs/core", "@hapi/hapi"}:
        add("api", "package.json dependencies")
    if any(token in python for token in ("fastapi", "flask", "django", "starlette", "litestar")):
        add("api", "python dependencies")
    if pkg.get("bin") or "[project.scripts]" in python:
        add("cli", "package.json bin or [project.scripts]")
    cargo = repo / "Cargo.toml"
    if cargo.is_file() and "[[bin]]" in cargo.read_text(errors="ignore"):
        add("cli", "Cargo.toml [[bin]]")
    if not surfaces and any((repo / name).is_file() for name in ("go.mod", "Cargo.toml")):
        add("cli", "go.mod or Cargo.toml")
    return surfaces


def _detect_run(repo: Path, pkg: dict, surfaces: list[dict]) -> dict:
    scripts = pkg.get("scripts") or {}
    for name in ("dev", "start", "serve", "develop"):
        if scripts.get(name):
            return {"command": f"npm run {name}", "evidence": f"package.json scripts.{name}"}
    if (repo / "Makefile").is_file():
        targets = re.findall(r"^([A-Za-z0-9_-]+):", (repo / "Makefile").read_text(errors="ignore"), re.M)
        for name in ("dev", "run", "serve", "start"):
            if name in targets:
                return {"command": f"make {name}", "evidence": f"Makefile target {name}"}
    pyproject = _pyproject(repo)
    match = re.search(r"\[project\.scripts\]\s*((?:\n[A-Za-z0-9_.-]+\s*=.*)+)", pyproject)
    if match:
        first = re.search(r"^([A-Za-z0-9_.-]+)\s*=", match.group(1), re.M)
        if first:
            return {"command": first.group(1), "evidence": "pyproject [project.scripts]"}
    if (repo / "docker-compose.yml").is_file() or (repo / "compose.yml").is_file():
        return {"command": "docker compose up", "evidence": "compose file"}
    if (repo / "Cargo.toml").is_file():
        return {"command": "cargo run", "evidence": "Cargo.toml"}
    if (repo / "manage.py").is_file():
        return {"command": "python3 manage.py runserver", "evidence": "manage.py"}
    if surfaces and surfaces[0]["surface"] == "cli":
        return {"command": _slug(pkg.get("name") or repo.name), "evidence": "the installed CLI"}
    return {}


def _detect_drivers(repo: Path) -> list[dict]:
    rows = []
    for tool, markers in (
        ("playwright", ("playwright.config.ts", "playwright.config.js", "playwright.config.mjs")),
        ("cypress", ("cypress.config.ts", "cypress.config.js", "cypress.json")),
        ("storybook", (".storybook",)),
        ("sentry", (".sentryclirc", "sentry.client.config.js", "sentry.server.config.js")),
        ("vitest", ("vitest.config.ts", "vitest.config.js")),
        ("pytest", ("pytest.ini", "conftest.py")),
    ):
        hit = next((marker for marker in markers if (repo / marker).exists()), None)
        rows.append({"tool": tool, "present": bool(hit), "evidence": hit or ""})
    return rows


def _detect_harness(repo: Path) -> str:
    if (repo / ".opencode").is_dir() or (repo / "opencode.json").is_file():
        return "opencode"
    if (repo / ".claude").is_dir() or (repo / "CLAUDE.md").is_file():
        return "claude"
    return "agents"


def _routes(repo: Path) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    for pattern, _ in ROUTE_GLOBS:
        for path in sorted(repo.glob(pattern))[:40]:
            relative = _rel(path, repo)
            if any(part.startswith("_") for part in path.relative_to(repo).parts[:-1]):
                continue
            route = relative
            for prefix in ("src/app/", "app/", "src/pages/", "pages/", "src/routes/", "public/"):
                if route.startswith(prefix):
                    route = route[len(prefix):]
                    break
            if route.endswith(".astro"):
                route = route[:-len(".astro")]
            elif route.endswith(".html"):
                route = "" if route == "index.html" else route[:-len(".html")]
            else:
                route = re.sub(r"(^|/)(page\.(tsx|jsx|ts|js)|\+page\.svelte|index\.(tsx|jsx|ts|js))$", "", route)
            route = "/" + route.strip("/") if route.strip("/") else "/"
            if route in seen or route.startswith("/404"):
                continue
            seen.add(route)
            found.append({"id": _slug(route if route != "/" else "home"), "title": _title(route if route != "/" else "home"),
                          "kind": "route", "entry": route, "source": relative})
    return found


def _endpoints(repo: Path) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    scanned = 0
    for path in repo.rglob("*"):
        if scanned >= 400:
            break
        if path.suffix not in SCAN_SUFFIXES or not path.is_file():
            continue
        if PROTECTED_PARTS & set(path.relative_to(repo).parts):
            continue
        scanned += 1
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for pattern in API_PATTERNS:
            for entry in pattern.findall(text):
                if entry in seen or not entry.startswith("/") or entry.startswith("/static"):
                    continue
                seen.add(entry)
                found.append({"id": _slug(entry), "title": _title(entry), "kind": "endpoint",
                              "entry": entry, "source": _rel(path, repo)})
    return found


def _commands(repo: Path, pkg: dict) -> list[dict]:
    found: list[dict] = []
    bin_field = pkg.get("bin")
    if isinstance(bin_field, str):
        found.append({"id": _slug(pkg.get("name") or repo.name), "title": _title(pkg.get("name") or repo.name),
                      "kind": "command", "entry": pkg.get("name") or repo.name, "source": "package.json bin"})
    elif isinstance(bin_field, dict):
        for name in bin_field:
            found.append({"id": _slug(name), "title": _title(name), "kind": "command",
                          "entry": name, "source": "package.json bin"})
    match = re.search(r"\[project\.scripts\]\s*((?:\n[A-Za-z0-9_.-]+\s*=.*)+)", _pyproject(repo))
    if match:
        for name in re.findall(r"^([A-Za-z0-9_.-]+)\s*=", match.group(1), re.M):
            found.append({"id": _slug(name), "title": _title(name), "kind": "command",
                          "entry": name, "source": "pyproject [project.scripts]"})
    return found


def _tool_present(tool: str, drivers: list[dict]) -> bool:
    driver = {row["tool"]: row["present"] for row in drivers}
    if tool == "your browser":
        return driver.get("playwright", False) or any(
            shutil.which(name) for name in
            ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "chrome"))
    if tool == "adb":
        return bool(shutil.which("adb"))
    if tool == "Chrome DevTools":
        return driver.get("playwright", False) or bool(shutil.which("google-chrome") or shutil.which("chromium"))
    if tool == "its own CLI":
        return True
    return driver.get(tool, False)


def interview_repo(repo: Path, harness: str = "auto") -> dict:
    repo = repo.resolve()
    if not repo.is_dir():
        raise Dependency(f"no repository at {repo}")
    pkg = _pkg(repo)
    surfaces = _detect_surfaces(repo, pkg)
    if not surfaces:
        surfaces = [{"surface": "unknown", "evidence": "no marker matched"}]
    drivers = _detect_drivers(repo)
    features = (_routes(repo) + _endpoints(repo) + _commands(repo, pkg))[:5]
    run = _detect_run(repo, pkg, surfaces)
    chosen = _detect_harness(repo) if harness == "auto" else harness
    app = _slug(pkg.get("name") or repo.name)
    out_dir = f"{HARNESS_ROOTS[chosen]}/verify-{app}"

    open_questions: list[str] = []
    if surfaces[0]["surface"] == "unknown":
        open_questions.append("Surface — what does a user actually touch? No marker in this repo answered it.")
    if not run:
        open_questions.append("Run — how does this app start on this machine? No dev command was found.")
    if not features:
        open_questions.append("Features — no route, endpoint or command was found; the feature map starts empty.")
    if not any(row["present"] for row in drivers if row["tool"] in ("playwright", "cypress")):
        open_questions.append("Drive — no browser driver is installed; Playwright is a proposal, not an answer.")
    if not any((repo / name).exists() for name in (".env.example", "docker-compose.yml")):
        open_questions.append("Isolate — no disposable port or data directory was found; two runs may share state.")

    tools = []
    for surface in [row["surface"] for row in surfaces]:
        for tool, why in SURFACE_TOOLS.get(surface, []):
            tools.append({"tool": tool, "surface": surface, "why": why,
                          "present": _tool_present(tool, drivers)})

    return {
        "app": app,
        "repo": str(repo),
        "harness": chosen,
        "out_dir": out_dir,
        "surfaces": surfaces,
        "run": run,
        "drivers": drivers,
        "features": features,
        "tools": tools,
        "open": open_questions,
        "pass_file": ".verify/pass.json",
    }


def _surface_names(interview: dict) -> str:
    return ", ".join(row["surface"] for row in interview["surfaces"])


def _render_feature_page(interview: dict, feature: dict) -> str:
    name = interview["app"]
    entry = feature["entry"]
    if feature["kind"] == "route":
        arrival = f"Open `{entry}` in a browser."
        drive = f"Run `verify-app eyes --url <origin>{entry} --viewport 390x844` with this feature's journey steps."
    elif feature["kind"] == "endpoint":
        arrival = f"Call `{entry}` the way the client does."
        drive = f"Issue a real request to `{entry}` and keep the response body, status and any row or file it changes."
    else:
        arrival = f"Run `{entry}` in a terminal."
        drive = f"Run `{entry} <args>` in its own PTY and keep stdout, stderr and the exit code."
    return f"""# {feature['title']}

What a user does here, and the end state that proves it worked.

## Sub-features

- `{feature['id']}-open` reaches the entry point.
- `{feature['id']}-act` performs the one action the feature exists for.
- `{feature['id']}-confirm` proves the result from a second user-facing view.

## How to get to it (user POV)

- {arrival}
- Source: `{feature['source']}`.

## Driving it with verify-{name}

Preconditions:

- `verify-app doctor` reports the expected URL or binary, the port or data directory this run owns, and the build revision.
- The disposable data directory is empty or holds exactly the seed this page names.
- No state from a previous run: restore the baseline in `features/README.md` first.

- **Open.** {arrival} The expected screen or prompt appears.
- **Act.** Perform the action a person performs. {drive} The end state is the exact text, record or file that proves it.
- **Confirm.** Re-read the state from a second user-facing view. The same value is visible.
- **Undo.** Restore the seed data this run changed. Keep the proof artifacts.

## Gotchas

- **Seeded page, unproven feature.** `verify-app forge` seeded this file from the detected entry point; until the end state above is written and driven, treat the feature as unverified.
- **Missing seed data is a failure, not a reason to relax.** If a precondition is absent, the journey fails and the reason is recorded here — never weaken the journey to make it pass.
- **Unproven isolation means one instance only.** If the interview left `Isolate` open, never start a second copy; report the shared-instance risk instead of corrupting the user's session.
- **Stable handles only.** Prefer ARIA roles, data attributes, prompt strings and route paths over coordinates and tab order.
- **Keep implementation details out of this page.** Name user paths, stable handles, required state, commands and observable proof.
- **Windows and Git Bash** can rewrite a path like `/order` into a file path; pass page paths quoted and verify the URL the browser actually opened.
"""


def _render_features_index(interview: dict) -> str:
    name = interview["app"]
    run = interview.get("run") or {}
    rows = "\n".join(
        f"- [{feature['title']}](./{feature['id']}.md) covers the `{feature['kind']}` entry at `{feature['entry']}` (from `{feature['source']}`)."
        for feature in interview["features"]
    ) or "- No feature detected yet. Add one file per user-facing feature before trusting this map."
    return f"""# {name} verification map

This directory is the maintained source for verifying the user-facing behaviour of {name}.
Read the index before driving the app, then use the matching feature file as the recipe.

## Baseline preconditions

- Launch: `{run.get('command', 'UNANSWERED — see Open questions')}` ({run.get('evidence', 'no evidence')}).
- Use a disposable data directory owned by this run; never reuse the live one.
- Seed only what the feature page names; report a missing precondition as a failure.
- Run `verify-app doctor` and require the expected URL or binary, the port or data directory this run owns, and the build revision.
- Never drive an instance that was not started by this verification run.

## Driving conventions

- Start every recipe from the baseline state unless its preconditions say otherwise.
- Prefer ARIA roles and accessible names over CSS selectors or DOM position.
- Treat every command as literal. Keep quoted names and flags unchanged.
- Run browser actions through `verify-app eyes`; run terminal actions through the app's own CLI in its own PTY.
- Restore seeded data after a mutation. Do not remove proof artifacts during cleanup.

## Proof and skip reporting

- Capture the user action and the resulting state, not only the final screen.
- UI proof includes an ARIA snapshot and a screenshot with the app identity visible.
- CLI proof includes the command, stdout, stderr and the exit code.
- Mutation proof includes a read-only second view of the stored value.
- Record the feature ID and entry point used with every artifact.
- Report an unreachable path with the attempted command and the unmet precondition.
- Do not report a skipped entry point as verified through a different path.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible
behaviour. It then uses exactly four H2 sections in this order:

1. `Sub-features` lists short IDs with one line for each behaviour.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with verify-{name}` starts with `Preconditions:` and uses labeled bullets
   that pair each user action with an exact command and an observable result.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map. Name only user paths, stable handles, required
state, commands and observable proof.

## Features

{rows}

Seeded from the top detected entry points; add the rest as the map grows. A proof that drives
one convenient entry point is incomplete when the map lists others.
"""


def _doctor_requirement(surfaces: list[str]) -> str:
    primary = surfaces[0] if surfaces else "unknown"
    return {
        "web": "the expected URL, the disposable data directory this run owns, and a build revision",
        "cli": "the binary path, the disposable working directory this run owns, and the build revision",
        "api": "the base URL, the disposable database or fixture directory, and the build revision",
        "desktop": "the app binary path, the disposable profile directory, and the build revision",
        "mobile": "the device or emulator id, the installed package, and the build revision",
    }.get(primary, "the entry point this run owns, and the build revision")


def _render_skill(interview: dict, today: str) -> str:
    name = interview["app"]
    run = interview.get("run") or {}
    surfaces = _surface_names(interview)
    open_lines = "\n".join(f"- {question}" for question in interview["open"]) or "- none"
    doctor = _doctor_requirement([row["surface"] for row in interview["surfaces"]])
    return f"""---
name: verify-{name}
description: >
  Prove {name} ({surfaces}) before a change is called done: launch it, drive one mapped
  feature the way a person would, capture evidence and clean up. Use when a change touches
  {name} and needs proof instead of a claim.
compatibility: "Generated by glitch-cat/verification forge. Needs verify-app on PATH. Surfaces: {surfaces}."
---

# Verify {name}

Built for this repository on {today}. A verification skill only works when it is built for
the app it checks, so this one was generated from the repo, not downloaded.

**Unanswered when this was generated** — each line is a layer this gate does not have yet:

{open_lines}

## Launch

```
{run.get('command', 'UNANSWERED')}
```

Detected in {run.get('evidence', 'no command found')}; the generator did not execute it —
run it once before trusting this gate, and fix or report a base that does not start. Launch
must reach a usable state from an empty data directory, including migrations and seed data.
Ready means usable, not just that a process answers: a database health check can pass while
its init scripts are still running. For a short-lived CLI or TUI there is no server to keep
alive: build once, then start each drive in its own isolated PTY or tmux session. Teardown
stops what this run started, by PID, never by process name.

If an irrelevant missing asset blocks startup (a static dir the API never serves, a sample
config), create it, mark it as verification scaffolding, and remove it in cleanup.

## Doctor

```
verify-app doctor --json
```

One read-only check answering "is this instance worth driving?": process up, the right
version or build, the port owned by this run, and auth valid if the app needs it. Require
{doctor}. It changes nothing, and a missing layer is a skip with a reason, never a pass.

## Drive

Surface: {surfaces}. Use an existing harness first — Playwright or Cypress specs, expect
scripts, PTY helpers, curl-able endpoints, a debug port — and only then a generic recipe:
browser/CDP for web and Electron, tmux/PTY for CLI/TUI, plain HTTP for services. Prefer
stable handles (ARIA labels, data attributes, prompt strings, route paths) over coordinates
and tab order. Open `features/README.md`, then drive the matching feature page exactly as
written.

## Evidence

Keep proof under `.verify/artifacts/` and the machine-readable report in `.verify/verify.json`.
Exercise the real user path, not internal setters or test-only endpoints; capture the action
and the resulting state, not just the final screen; verify side effects (files written, rows
inserted, messages sent) alongside what is visible. Mock only where a production boundary
already isolates the external system. When the safe path is a dry-run or test mode, verify
what it actually skips by observing files, network and git refs — some dry-runs still touch
the network. A skipped layer is reported as skipped, with the question it leaves open, and
proof artifacts survive cleanup at the location this skill names.

## Cleanup

Tear down only the instances this run created. Never kill by process name; kill what you
started. Cleanup removes instances and scratch state, never evidence.

## Helpers

```
verify-app doctor --json          # are the layers actually there?
verify-app run --pass .verify/pass.json
./scripts/verify control --file <path> --find <text> --replace <text>
```

`scripts/verify` is a shim onto the global `verify-app`; it refuses to pretend if the CLI
is missing.

Before handing this gate over, run it end to end once: launch, doctor, drive one mapped
feature, capture evidence, clean up, then confirm the evidence still exists. A generated
skill that was never executed is a draft, not a deliverable.

Load this skill by its ID `verify-{name}` wherever the harness has skills (OpenCode:
`@verify-{name}`, Claude Code: `/verify-{name}`), or read this file directly anywhere else.
Nothing here depends on a particular harness.

Before you call any change done, check it with the verify-{name} skill and show its evidence.
"""


def _render_tree(interview: dict, today: str) -> list[dict]:
    out = Path(interview["out_dir"])
    files = [{"path": out / "SKILL.md", "content": _render_skill(interview, today), "mode": 0o644},
             {"path": out / "features" / "README.md", "content": _render_features_index(interview), "mode": 0o644}]
    for feature in interview["features"]:
        files.append({"path": out / "features" / f"{feature['id']}.md",
                      "content": _render_feature_page(interview, feature), "mode": 0o644})
    files.append({"path": out / "scripts" / "verify", "content": """#!/bin/sh
set -eu
if ! command -v verify-app >/dev/null 2>&1; then
  echo "verify: verify-app is not on PATH (glitch-cat/verification is not installed)" >&2
  exit 3
fi
exec verify-app "$@"
""", "mode": 0o755})
    return files


ADOPTION_HEADING = "## Verification"


def adoption_line(app: str) -> str:
    return (f"Before you call any change done, check it with the verify-{app} skill "
            "and show its evidence.")


def adopt(repo: Path, app: str, instructions: Path = Path("AGENTS.md")) -> dict:
    root = Path(repo).resolve()
    path = instructions if instructions.is_absolute() else root / instructions
    line = adoption_line(app)
    text = path.read_text() if path.is_file() else ""
    if line in text:
        return {"path": _rel(path, root), "changed": False, "line": line}
    if not text:
        updated = f"{ADOPTION_HEADING}\n\n{line}\n"
    elif ADOPTION_HEADING in text:
        updated = text.replace(ADOPTION_HEADING, f"{ADOPTION_HEADING}\n\n{line}", 1)
    else:
        gap = "" if text.endswith("\n") else "\n"
        updated = f"{text}{gap}\n{ADOPTION_HEADING}\n\n{line}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated)
    return {"path": _rel(path, root), "changed": True, "line": line}


def forge(repo: Path, out: Path | None = None, harness: str = "auto", apply: bool = False,
          adopt_to: Path | None = None) -> dict:
    interview = interview_repo(repo, harness=harness)
    if out is not None:
        interview["out_dir"] = _rel(out, Path(interview["repo"])) if out.is_absolute() else out.as_posix()
    today = time.strftime("%Y-%m-%d")
    files = _render_tree(interview, today)
    written: list[str] = []
    adopted: dict | None = None
    if apply:
        base = Path(interview["repo"])
        for item in files:
            path = base / item["path"]
            if path.exists() and "SKILL.md" in path.name:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item["content"])
            path.chmod(item["mode"])
            written.append(_rel(path, base))
        pass_file = base / interview["pass_file"]
        if not pass_file.exists():
            pass_file.parent.mkdir(parents=True, exist_ok=True)
            init_config(pass_file.parent)
            skeleton = json.loads(pass_file.read_text())
            skeleton["name"] = interview["app"]
            pass_file.write_text(json.dumps(skeleton, indent=2))
            written.append(_rel(pass_file, base))
        if adopt_to is not None:
            adopted = adopt(base, interview["app"], adopt_to)
    verdict = "open" if interview["open"] else "ready"
    return {
        "app": interview["app"],
        "repo": interview["repo"],
        "harness": interview["harness"],
        "out_dir": interview["out_dir"],
        "interview": interview,
        "files": [item["path"].as_posix() for item in files],
        "written": written,
        "adopted": adopted,
        "verdict": verdict,
        "exit": EXIT_UNCONFIGURED if interview["open"] else EXIT_PASS,
    }


