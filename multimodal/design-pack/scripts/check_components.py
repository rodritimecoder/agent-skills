#!/usr/bin/env python3
"""check_components — the behavioural & structural gate for design-pack.

Complements design_pack.py (static token conformance) with Kem's runtime checks:
  1. Every part works when you use it (keyboard/click interactions, 0 console/page errors)
  2. Every press answers in <= 100 ms (requestAnimationFrame latency)
  3. Everything works by keyboard (.keybar triggers + focusable stops)
  4. Nothing overlaps, nothing is cut off (bounding-box intersection + clipping + 10px floor)
  5. It fits seven screens, phone to monitor (375x812 .. 1440x900)
  6. Contrast measured across visible text elements

Exit codes: 0 pass, 1 fail, 2 usage error, 3 runtime/dependency unavailable.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "check_runner.mjs"

DEFAULT_VIEWPORTS = "375x812,480x320,640x400,768x1024,800x600,1280x800,1440x900"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


def _start_server(root: Path):
    handler = functools.partial(_QuietHandler, directory=str(root))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


def _collect_targets(inputs: list[str]) -> tuple[list[tuple[str, Path | str]], Path | None]:
    file_targets: list[Path] = []
    url_targets: list[str] = []

    for raw in inputs:
        if raw.startswith(("http://", "https://")):
            url_targets.append(raw)
            continue
        p = Path(raw).resolve()
        if p.is_dir():
            htmls = sorted(p.glob("*.html"))
            for sub in ("examples", "profiles"):
                if (p / sub).is_dir():
                    htmls.extend(sorted((p / sub).glob("*.html")))
            if not htmls:
                htmls = sorted(p.rglob("*.html"))
            file_targets.extend(htmls)
        elif p.exists():
            file_targets.append(p)
        else:
            sys.exit(f"check_components: no such file or url: {raw}")

    if not file_targets and not url_targets:
        sys.exit("check_components: nothing to check")

    root = None
    if file_targets:
        common = os.path.commonpath([str(p.parent) for p in file_targets])
        root = Path(common)
        # Walk up if a parent contains shared tokens.css / sprites.js
        for candidate in [root, *root.parents]:
            if (candidate / "tokens.css").exists() or (candidate / "SKILL.md").exists():
                root = candidate
                break

    targets: list[tuple[str, Path | str]] = [(str(p), p) for p in file_targets]
    targets.extend([(u, u) for u in url_targets])
    return targets, root


def run_check(
    inputs: list[str],
    *,
    viewports: str = DEFAULT_VIEWPORTS,
    allow_controls: bool = False,
    max_press_ms: float = 100.0,
    min_contrast: float = 3.0,
    as_json: bool = False,
) -> int:
    node = shutil.which("node")
    if not node:
        print("check_components: node not found on PATH", file=sys.stderr)
        return 3
    if not RUNNER.exists():
        print(f"check_components: missing runner {RUNNER}", file=sys.stderr)
        return 3

    raw_targets, root = _collect_targets(inputs)
    httpd = None
    try:
        resolved: list[tuple[str, str]] = []
        if root is not None:
            httpd, port = _start_server(root)
            for label, val in raw_targets:
                if isinstance(val, Path):
                    rel = val.relative_to(root).as_posix()
                    resolved.append((rel, f"http://127.0.0.1:{port}/{rel}"))
                else:
                    resolved.append((label, val))
        else:
            resolved = [(label, str(val)) for label, val in raw_targets]

        cmd = [
            node,
            str(RUNNER),
            "--viewports",
            viewports,
            "--max-press-ms",
            str(max_press_ms),
            "--min-contrast",
            str(min_contrast),
        ]
        if allow_controls:
            cmd.append("--allow-controls")
        for label, url in resolved:
            cmd.extend(["--target", f"{label}={url}"])

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 3:
            print(proc.stderr.strip() or "check_components: playwright unavailable", file=sys.stderr)
            return 3
        if not proc.stdout.strip():
            print(proc.stderr.strip() or "check_components: empty runner output", file=sys.stderr)
            return 3

        data = json.loads(proc.stdout)
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()

    if as_json:
        print(json.dumps(data, indent=2))
        return 0 if data.get("pass") else 1

    vp_count = len([v for v in viewports.split(",") if v.strip()])
    total_issues = 0
    for t in data.get("targets", []):
        status = "PASS" if t["pass"] else "FAIL"
        worst = None
        for v in t.get("viewports", []):
            wc = v["metrics"].get("worstContrast")
            if wc and (worst is None or wc["ratio"] < worst["ratio"]):
                worst = wc
        contrast_note = f"min contrast {worst['ratio']}:1 ({worst['element']})" if worst else "no text"
        keys = ", ".join(f"{k['key']}:{k['ms']}ms" for k in t["interactions"].get("keysTested", []))
        key_note = f"keys [{keys}]" if keys else f"tabStops={t['interactions'].get('tabStops', 0)}"
        print(f"{status}  {t['label']} · {vp_count} viewports · {contrast_note} · {key_note}")
        for iss in t.get("issues", []):
            total_issues += 1
            print(f"      [{iss['viewport']}] {iss['check']}: {iss['detail']}")

    verdict = "PASS" if data.get("pass") else "FAIL"
    n_targets = len(data.get("targets", []))
    if data.get("pass"):
        print(f"\n{verdict}  {n_targets} target(s) · {vp_count} viewports · 0 issues — then it waits for your sign-off.")
    else:
        print(f"\n{verdict}  {n_targets} target(s) · {vp_count} viewports · {total_issues} issue(s)")
    return 0 if data.get("pass") else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="check_components",
        description="Check rendered component behaviour, overlap, clipping, keyboard, viewports, latency, and contrast.",
        epilog='Exit codes: 0 pass, 1 fail, 2 usage error, 3 runtime/dependency unavailable.',
    )
    parser.add_argument("targets", nargs="+", help="HTML file(s), directory, or http(s) URL(s)")
    parser.add_argument("--viewports", default=DEFAULT_VIEWPORTS, help="Comma-separated WxH viewports")
    parser.add_argument("--allow-controls", action="store_true", help="Allow native <button>/<input>/<select> inside .win")
    parser.add_argument("--max-press-ms", type=float, default=100.0, help="Max interaction response ms (default: 100)")
    parser.add_argument("--min-contrast", type=float, default=3.0, help="Minimum WCAG contrast ratio (default: 3.0)")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON report")
    args = parser.parse_args()

    return run_check(
        args.targets,
        viewports=args.viewports,
        allow_controls=args.allow_controls,
        max_press_ms=args.max_press_ms,
        min_contrast=args.min_contrast,
        as_json=args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
