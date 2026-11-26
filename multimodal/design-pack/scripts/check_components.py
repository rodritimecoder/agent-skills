#!/usr/bin/env python3
"""check_components — the behavioural & structural gate for design-pack.

Complements design_pack.py (static token conformance) with runtime checks
driven by each look's check configuration (or neutral defaults):
  1. Every part works when you use it (keyboard/click interactions, 0 console/page errors)
  2. Every press answers within the configured latency ceiling (requestAnimationFrame latency)
  3. Everything works by keyboard (configured shortcut triggers + focusable stops)
  4. Nothing overlaps, nothing is cut off (bounding-box intersection + clipping + type-size floor)
  5. It fits all configured viewports and theme variants
  6. Contrast measured across visible text elements

Exit codes: 0 pass, 1 fail, 2 usage error, 3 runtime/dependency unavailable.
"""

from __future__ import annotations

import argparse
import copy
import functools
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "check_runner.mjs"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from design_pack import infer_look_from_paths, load_look_config  # noqa: E402

NEUTRAL_CHECK_CONFIG = {
    "viewports": ["375x812", "768x1024", "1280x800", "1440x900"],
    "theme_variants": [],
    "min_type_px": 10.0,
    "min_contrast": 3.0,
    "max_press_ms": 100.0,
    "fallback_bg": None,
    "clip_selectors": [],
    "group_selectors": ["[data-dp-group]"],
    "forbidden_selectors": [],
    "forbidden_reason": "forbidden element {el}",
    "skip_contrast_selectors": [
        '[aria-hidden="true"]',
        ".is-disabled",
        "[disabled]",
        '[aria-disabled="true"]',
    ],
    "shortcut_selector": None,
    "tab_stop_selectors": [
        "a[href]",
        "button",
        "input",
        "select",
        "textarea",
        "[tabindex]",
        '[role="switch"]',
        '[role="tab"]',
    ],
    "interactive_selectors": [
        "a[href]",
        "button:not([disabled])",
        '[role="switch"]:not([aria-disabled="true"])',
        '[role="tab"]:not([aria-disabled="true"])',
    ],
    "text_selectors": [
        "p",
        "span",
        "div",
        "a",
        "b",
        "figcaption",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "code",
        "button",
        "label",
        "li",
        "td",
        "th",
    ],
}


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
        # Walk up if a parent contains shared tokens.css, look.json, or SKILL.md
        for candidate in [root, *root.parents]:
            if (
                (candidate / "tokens.css").exists()
                or (candidate / "look.json").exists()
                or (candidate / "SKILL.md").exists()
            ):
                root = candidate
                break

    targets: list[tuple[str, Path | str]] = [(str(p), p) for p in file_targets]
    targets.extend([(u, u) for u in url_targets])
    return targets, root


def run_check(
    inputs: list[str],
    *,
    look: str | None = None,
    check_config: dict | None = None,
    viewports: str | None = None,
    allow_controls: bool = False,
    max_press_ms: float | None = None,
    min_contrast: float | None = None,
    as_json: bool = False,
) -> int:
    node = shutil.which("node")
    if not node:
        print("check_components: node not found on PATH", file=sys.stderr)
        return 3
    if not RUNNER.exists():
        print(f"check_components: missing runner {RUNNER}", file=sys.stderr)
        return 3

    resolved_look = look or infer_look_from_paths(inputs)
    cfg = copy.deepcopy(NEUTRAL_CHECK_CONFIG)
    if resolved_look:
        look_check = load_look_config(resolved_look).get("check", {})
        if isinstance(look_check, dict):
            cfg.update(copy.deepcopy(look_check))
    if check_config:
        cfg.update(copy.deepcopy(check_config))

    if viewports is not None:
        cfg["viewports"] = [v.strip() for v in viewports.split(",") if v.strip()]
    if max_press_ms is not None:
        cfg["max_press_ms"] = float(max_press_ms)
    if min_contrast is not None:
        cfg["min_contrast"] = float(min_contrast)
    if allow_controls:
        cfg["forbidden_selectors"] = []

    raw_targets, root = _collect_targets(inputs)
    httpd = None
    cfg_path: str | None = None
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

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=False
        ) as tmp:
            json.dump(cfg, tmp)
            cfg_path = tmp.name

        cmd = [node, str(RUNNER), "--config", cfg_path]
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
        if cfg_path is not None:
            try:
                os.unlink(cfg_path)
            except OSError:
                pass
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()

    data["look"] = resolved_look

    if as_json:
        print(json.dumps(data, indent=2))
        return 0 if data.get("pass") else 1

    vp_count = len(cfg["viewports"])
    themes = cfg.get("theme_variants") or []
    theme_note = f" · {len(themes)} themes ({'/'.join(themes)})" if themes else ""
    look_note = f" [{resolved_look}]" if resolved_look else ""
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
        print(f"{status}  {t['label']}{look_note} · {vp_count} viewports{theme_note} · {contrast_note} · {key_note}")
        for iss in t.get("issues", []):
            total_issues += 1
            print(f"      [{iss['viewport']}] {iss['check']}: {iss['detail']}")

    verdict = "PASS" if data.get("pass") else "FAIL"
    n_targets = len(data.get("targets", []))
    if data.get("pass"):
        print(
            f"\n{verdict}{look_note}  {n_targets} target(s) · {vp_count} viewports{theme_note}"
            " · 0 issues — then it waits for your sign-off."
        )
    else:
        print(
            f"\n{verdict}{look_note}  {n_targets} target(s) · {vp_count} viewports{theme_note}"
            f" · {total_issues} issue(s)"
        )
    return 0 if data.get("pass") else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="check_components",
        description="Check rendered component behaviour, overlap, clipping, keyboard, viewports, latency, and contrast.",
        epilog="Exit codes: 0 pass, 1 fail, 2 usage error, 3 runtime/dependency unavailable.",
    )
    parser.add_argument("targets", nargs="+", help="HTML file(s), directory, or http(s) URL(s)")
    parser.add_argument(
        "--look",
        default=None,
        help="Look name for check config (auto-inferred from target paths if omitted)",
    )
    parser.add_argument(
        "--viewports",
        default=None,
        help="Comma-separated WxH viewports (overrides look config)",
    )
    parser.add_argument(
        "--allow-controls",
        action="store_true",
        help="Clear look forbidden_selectors",
    )
    parser.add_argument(
        "--max-press-ms",
        type=float,
        default=None,
        help="Max interaction response ms (overrides look config)",
    )
    parser.add_argument(
        "--min-contrast",
        type=float,
        default=None,
        help="Minimum WCAG contrast ratio (overrides look config)",
    )
    parser.add_argument("--json", action="store_true", help="Emit structured JSON report")
    args = parser.parse_args()

    return run_check(
        args.targets,
        look=args.look,
        viewports=args.viewports,
        allow_controls=args.allow_controls,
        max_press_ms=args.max_press_ms,
        min_contrast=args.min_contrast,
        as_json=args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
