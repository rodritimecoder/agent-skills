#!/usr/bin/env python3
"""verification — hands and eyes for an agent that has to prove its own work.

One command that opens the app like a person, watches what the browser actually
did behind the screen, compares the pixels, walks every Storybook state, and
reports what real users are hitting. Every layer is tagged so a failure is
attributable to code, to the app, or to a missing dependency.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

import cdp_lite

EXIT_PASS, EXIT_FAIL, EXIT_USAGE, EXIT_DEPENDENCY, EXIT_UNCONFIGURED = 0, 1, 2, 3, 4
QUESTIONS = [
    "Which journey does a person actually perform, and on which viewport?",
    "What must be on screen at the end, in the exact words that prove it?",
    "What must be true behind the screen — which request, status, or record?",
    "What did it look like before, and which pixels must not move?",
    "Which real-user error already happened, and how do we see the next one first?",
]


class Dependency(RuntimeError):
    pass


def _json_line(value) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride] for y in range(height))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def _decode_png(path: Path) -> tuple[int, int, bytes]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise Dependency("ffmpeg is required for the pixel layer but is not on PATH")
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    if probe.returncode != 0 or not probe.stdout:
        raise Dependency(f"could not decode {path}: {probe.stderr.decode('utf-8', 'replace')[-300:]}")
    dims = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True,
    ).stderr
    match = re.search(r",\s*(\d+)x(\d+)[,\s]", dims)
    if not match:
        raise Dependency(f"could not read dimensions of {path}")
    width, height = int(match.group(1)), int(match.group(2))
    if len(probe.stdout) != width * height * 3:
        raise Dependency(f"{path} decoded to {len(probe.stdout)} bytes, expected {width * height * 3}")
    return width, height, probe.stdout


def compare_pixels(before: Path, after: Path, tolerance: int = 8,
                   max_changed: float = 0.0, diff_out: Path | None = None) -> dict:
    bw, bh, bpx = _decode_png(before)
    aw, ah, apx = _decode_png(after)
    if (bw, bh) != (aw, ah):
        return {
            "status": "fail",
            "detail": f"size changed {bw}x{bh} -> {aw}x{ah}",
            "changed": None, "ratio": None, "box": None, "diff": None,
        }
    changed = 0
    min_x, min_y, max_x, max_y = bw, bh, -1, -1
    diff = bytearray(bpx)
    for i in range(0, len(bpx), 3):
        d = max(abs(bpx[i] - apx[i]), abs(bpx[i + 1] - apx[i + 1]), abs(bpx[i + 2] - apx[i + 2]))
        if d > tolerance:
            changed += 1
            p = i // 3
            x, y = p % bw, p // bw
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x), max(max_y, y)
            diff[i], diff[i + 1], diff[i + 2] = 255, 0, 255
    ratio = changed / (bw * bh)
    if diff_out and changed:
        _write_png(diff_out, bw, ah, bytes(diff))
    ok = ratio <= max_changed
    return {
        "status": "pass" if ok else "fail",
        "detail": f"{changed} px changed ({ratio:.4%}) over tolerance {tolerance}, allowed {max_changed:.4%}",
        "changed": changed,
        "ratio": round(ratio, 6),
        "box": None if max_x < 0 else {"x": min_x, "y": min_y, "w": max_x - min_x + 1, "h": max_y - min_y + 1},
        "diff": str(diff_out) if diff_out and changed else None,
    }


class Eyes:
    def __init__(self, port: int = 9222, viewport: str | None = None, timeout: float = 20.0):
        self.port = port
        self.timeout = timeout
        self.viewport = _parse_viewport(viewport) if viewport else None
        self.client: cdp_lite.CDP | None = None
        self.seen_console: set[tuple[str, str]] = set()
        self.seen_log: set[str] = set()
        self.responses: dict[str, dict] = {}
        self.failures: list[dict] = []
        self.exceptions: list[dict] = []

    def __enter__(self) -> "Eyes":
        try:
            self.client = cdp_lite.connect(port=self.port, timeout=self.timeout)
        except cdp_lite.CDPNotRunning as exc:
            raise Dependency(str(exc)) from exc
        for domain in ("Page.enable", "Runtime.enable", "Log.enable", "Network.enable"):
            self.client.send(domain)
        if self.viewport:
            width, height, scale, mobile = self.viewport
            self.client.send("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height, "deviceScaleFactor": scale, "mobile": mobile,
            })
        self.client.drain()
        return self

    def __exit__(self, *exc) -> None:
        if self.client:
            self.client.close()

    def navigate(self, url: str, settle_ms: int = 800) -> None:
        self.client.send("Page.navigate", {"url": url})
        self.client.pump(settle_ms / 1000.0)
        self._collect()

    def _collect(self) -> None:
        for event in self.client.drain():
            method, params = event.get("method"), event.get("params", {})
            if method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "assert"):
                text = " ".join(str(a.get("value", a.get("description", ""))) for a in params.get("args", []))
                key = (params["type"], text)
                if key not in self.seen_console:
                    self.seen_console.add(key)
                    self.failures.append({"kind": "console", "level": params["type"], "text": text})
            elif method == "Log.entryAdded":
                entry = params.get("entry", {})
                if entry.get("level") == "error":
                    text = entry.get("text", "")
                    key = f"{entry.get('source')}|{text}"
                    if key not in self.seen_log:
                        self.seen_log.add(key)
                        self.failures.append({"kind": "log", "level": "error", "text": text,
                                              "url": entry.get("url", "")})
            elif method == "Runtime.exceptionThrown":
                details = params.get("exceptionDetails", {})
                text = details.get("exception", {}).get("description") or details.get("text", "")
                self.exceptions.append({"text": text, "url": details.get("url", "")})
                self.failures.append({"kind": "exception", "level": "error", "text": text})
            elif method == "Network.responseReceived":
                response = params.get("response", {})
                self.responses[params.get("requestId", "")] = {
                    "url": response.get("url", ""),
                    "status": response.get("status", 0),
                    "type": params.get("type", ""),
                }
            elif method == "Network.loadingFailed":
                self.failures.append({
                    "kind": "request",
                    "level": "error",
                    "text": f"{params.get('errorText', 'failed')} ({params.get('type', '')})",
                    "requestId": params.get("requestId", ""),
                })

    def settle(self, seconds: float = 0.4) -> None:
        self.client.pump(seconds)
        self._collect()

    def text(self) -> str:
        result = self.client.send("Runtime.evaluate", {
            "expression": "document.body ? document.body.innerText : ''",
            "returnByValue": True,
        })
        return result.get("result", {}).get("value", "") or ""

    def screenshot(self, path: Path) -> Path:
        result = self.client.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(result["data"]))
        return path

    def _box(self, selector: str) -> dict:
        expression = (
            "(() => { const el = document.querySelector(%s); if (!el) return null;"
            " const r = el.getBoundingClientRect();"
            " const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;"
            " return {x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height,"
            " left: r.left, right: r.right, vw: vw, vh: vh,"
            " visible: !!(r.width && r.height && el.offsetParent !== null)}; })()"
        ) % json.dumps(selector)
        result = self.client.send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        box = result.get("result", {}).get("value")
        if not box:
            raise Dependency(f"selector not found: {selector}")
        return box

    def _assert_visible(self, selector: str, box: dict) -> None:
        if not box.get("visible"):
            self.failures.append({
                "kind": "visibility", "level": "error",
                "text": f"{selector} rendered with zero size or is not laid out "
                        f"({box['w']:.0f}x{box['h']:.0f}) — present in DOM, invisible to a person",
            })
            return
        vw = self.viewport[0] if self.viewport else box["vw"]
        vh = self.viewport[1] if self.viewport else box["vh"]
        overflow = max(box["right"] - vw, box["left"] * -1, 0)
        outside = not (0 <= box["x"] <= vw and 0 <= box["y"] <= vh)
        if overflow > 0 or outside:
            where = (f"centre ({box['x']:.0f}, {box['y']:.0f}) in {vw}x{vh}"
                     if outside else f"right edge {box['right']:.0f} past the {vw}px viewport")
            self.failures.append({
                "kind": "viewport", "level": "error",
                "text": f"{selector} is cut off on this viewport: {where}"
                        + (f", {overflow:.0f}px hidden" if overflow > 0 else ""),
            })

    def _assert_reachable(self, selector: str) -> None:
        expression = (
            "(() => { const el = document.querySelector(%s); if (!el) return null;"
            " const r = el.getBoundingClientRect();"
            " const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);"
            " if (!top || top === el || el.contains(top)) return {hits: true};"
            " const name = top.tagName.toLowerCase()"
            "   + (top.id ? '#' + top.id : '')"
            "   + (typeof top.className === 'string' && top.className.trim()"
            "        ? '.' + top.className.trim().split(/\\s+/).join('.') : '');"
            " return {hits: false, covering: name, text: (top.textContent || '').trim().slice(0, 60)}; })()"
        ) % json.dumps(selector)
        result = self.evaluate(expression)
        if result and not result.get("hits"):
            self.failures.append({
                "kind": "occluded", "level": "error",
                "text": f"{selector} is covered at its own centre by {result.get('covering')}"
                        + (f" ({result['text']!r})" if result.get("text") else "")
                        + " — a click lands on the other element",
            })

    def click(self, selector: str) -> None:
        box = self._box(selector)
        self._assert_visible(selector, box)
        self._assert_reachable(selector)
        self.client.send("Runtime.evaluate", {
            "expression": "document.querySelector(%s).scrollIntoView({block:'center'})" % json.dumps(selector),
        })
        self.settle(0.15)
        box = self._box(selector)
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.client.send("Input.dispatchMouseEvent", {
                "type": kind, "x": box["x"], "y": box["y"],
                "button": "left", "clickCount": 1,
            })
        self.settle(0.4)

    def fill(self, selector: str, value: str) -> None:
        self.click(selector)
        self.client.send("Runtime.evaluate", {
            "expression": "(() => { const el = document.querySelector(%s);"
                          " el.select && el.select(); return !!el; })()" % json.dumps(selector),
        })
        self.client.send("Input.insertText", {"text": value})
        self.settle(0.2)

    def press(self, key: str) -> None:
        self.client.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "text": key if len(key) == 1 else ""})
        self.client.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": key})
        self.settle(0.3)

    def evaluate(self, expression: str):
        result = self.client.send("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        })
        return result.get("result", {}).get("value")

    def run_journey(self, steps: list[dict]) -> list[dict]:
        log = []
        for step in steps:
            started = time.monotonic()
            if "click" in step:
                self.click(step["click"])
                log.append({"step": f"click {step['click']}", "ms": _ms(started)})
            elif "fill" in step:
                selector, value = step["fill"]
                self.fill(selector, value)
                log.append({"step": f"fill {selector}", "ms": _ms(started)})
            elif "press" in step:
                self.press(step["press"])
                log.append({"step": f"press {step['press']}", "ms": _ms(started)})
            elif "eval" in step:
                self.evaluate(step["eval"])
                log.append({"step": "eval", "ms": _ms(started)})
            elif "wait" in step:
                self.settle(step["wait"] / 1000.0)
                log.append({"step": f"wait {step['wait']}ms", "ms": _ms(started)})
            else:
                raise Dependency(f"unknown journey step: {step}")
        return log

    def layout(self) -> dict:
        measured = self.evaluate(
            "({inner: window.innerWidth, scroll: document.documentElement.scrollWidth,"
            " client: document.documentElement.clientWidth})"
        ) or {}
        declared = self.viewport[0] if self.viewport else None
        inner = measured.get("inner") or 0
        scroll = measured.get("scroll") or 0
        shrink = bool(declared and inner > declared * 1.02)
        overflow = bool(declared and scroll > declared + 1 and not shrink)
        return {
            "declared": declared,
            "inner": inner,
            "scroll": scroll,
            "shrink_to_fit": shrink,
            "horizontal_overflow": overflow,
        }

    def report(self, expect: dict | None = None) -> dict:
        expect = expect or {}
        failures = list(self.failures)
        layout = self.layout()
        if layout["shrink_to_fit"]:
            failures.append({
                "kind": "layout", "level": "error",
                "text": f"page needs {layout['inner']}px but the viewport is {layout['declared']}px: "
                        f"Chrome is scaling it down to fit, so a person reads it at "
                        f"{layout['declared'] / layout['inner']:.0%} size",
            })
        elif layout["horizontal_overflow"]:
            failures.append({
                "kind": "layout", "level": "error",
                "text": f"page is {layout['scroll']}px wide inside a {layout['declared']}px viewport: "
                        f"{layout['scroll'] - layout['declared']}px reachable only by scrolling sideways",
            })
        if expect.get("no_failed_requests", True):
            for response in self.responses.values():
                if response["status"] >= 400:
                    failures.append({
                        "kind": "request", "level": "error",
                        "text": f"{response['status']} {response['url']}",
                    })
        matched = []
        for wanted in expect.get("requests", []):
            contains = wanted.get("contains", "")
            status = wanted.get("status")
            hit = next((r for r in self.responses.values()
                        if contains in r["url"] and (status is None or r["status"] == status)), None)
            close = [r for r in self.responses.values() if contains in r["url"]]
            if hit:
                matched.append({"contains": contains, "status": hit["status"], "url": hit["url"], "ok": True})
            else:
                saw = ", ".join(f"{r['status']} {r['url']}" for r in close)
                matched.append({
                    "contains": contains, "status": None, "ok": False,
                    "saw": [f"{r['status']} {r['url']}" for r in close],
                })
                failures.append({
                    "kind": "expectation", "level": "error",
                    "text": f"no request matching {contains!r}"
                            + (f" with status {status}" if status else "")
                            + (f"; saw {saw}" if close else " was ever sent"),
                })
        text_check = None
        if expect.get("text"):
            body = self.text()
            case_sensitive = expect.get("case_sensitive", False)
            haystack = body if case_sensitive else body.casefold()
            needle = expect["text"] if case_sensitive else expect["text"].casefold()
            text_check = {"wanted": expect["text"], "found": needle in haystack,
                          "case_sensitive": case_sensitive}
            if not text_check["found"]:
                failures.append({
                    "kind": "expectation", "level": "error",
                    "text": f"missing text {expect['text']!r}"
                            + ("" if case_sensitive else " (case-insensitive)"),
                })
        eval_checks = []
        for wanted in expect.get("eval", []):
            expression = wanted.get("expression", "")
            label = wanted.get("label") or expression
            try:
                value = self.evaluate(expression)
            except Exception as exc:
                value, problem = None, f"{label!r} threw: {exc}"
            else:
                problem = None if value else f"{label!r} evaluated falsy: {value!r}"
            eval_checks.append({"label": label, "expression": expression,
                                "value": value, "ok": problem is None})
            if problem:
                failures.append({"kind": "expectation", "level": "error", "text": problem})
        status = "pass" if not failures else "fail"
        return {
            "layer": "eyes",
            "status": status,
            "detail": f"{len(self.responses)} request(s), {len(failures)} problem(s)",
            "requests": sorted(self.responses.values(), key=lambda r: r["url"]),
            "layout": layout,
            "expectations": matched,
            "text": text_check,
            "evals": eval_checks,
            "problems": failures,
        }


def _parse_viewport(value: str) -> tuple[int, int, float, bool]:
    match = re.fullmatch(r"(\d+)x(\d+)(?:@([\d.]+))?", value.strip())
    if not match:
        raise Dependency(f"viewport must look like 390x844 or 390x844@2 — got {value!r}")
    width, height = int(match.group(1)), int(match.group(2))
    scale = float(match.group(3)) if match.group(3) else 1.0
    return width, height, scale, width < 768


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def probe(url: str, viewport: str | None = None, settle_ms: int = 800,
          journey: list[dict] | None = None, expect: dict | None = None,
          screenshot: Path | None = None, port: int = 9222) -> dict:
    started = time.monotonic()
    with Eyes(port=port, viewport=viewport) as eyes:
        eyes.navigate(url, settle_ms=settle_ms)
        steps = eyes.run_journey(journey or [])
        eyes.settle(0.4)
        if screenshot:
            eyes.screenshot(screenshot)
        report = eyes.report(expect)
    report["url"] = url
    report["viewport"] = viewport
    report["journey"] = steps
    report["screenshot"] = str(screenshot) if screenshot else None
    report["ms"] = _ms(started)
    return report


def storybook_states(base_url: str, prefix: str = "", limit: int = 30,
                     screenshot_dir: Path | None = None, port: int = 9222,
                     settle_ms: int = 400) -> dict:
    base = base_url.rstrip("/")
    index = None
    for candidate in ("index.json", "stories.json"):
        try:
            with urllib.request.urlopen(f"{base}/{candidate}", timeout=8) as resp:
                index = json.loads(resp.read().decode("utf-8", "replace"))
            break
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            continue
    if index is None:
        raise Dependency(f"no Storybook index at {base}/index.json — is Storybook running?")
    entries = index.get("entries", index.get("stories", {}))
    stories = [e for e in (entries.values() if isinstance(entries, dict) else entries)
               if e.get("type", "story") == "story"]
    if prefix:
        stories = [s for s in stories if prefix in (s.get("title", "") + s.get("name", "") + s.get("id", ""))]
    stories = stories[:limit]
    if not stories:
        return {"layer": "states", "status": "skip", "detail": f"no stories matched {prefix!r}", "stories": []}
    results = []
    for story in stories:
        story_id = story.get("id") or story.get("storyId")
        url = f"{base}/iframe.html?id={urllib.parse.quote(story_id)}&viewMode=story"
        shot = (screenshot_dir / f"{story_id}.png") if screenshot_dir else None
        try:
            report = probe(url, journey=[{"wait": 300}], expect={"no_failed_requests": True},
                           screenshot=shot, port=port, settle_ms=settle_ms)
            status = report["status"]
            detail = report["detail"] if status == "pass" else "; ".join(
                p["text"] for p in report["problems"][:2])
        except Dependency as exc:
            status, detail = "error", str(exc)
        results.append({"id": story_id, "title": story.get("title", ""), "name": story.get("name", ""),
                        "status": status, "detail": detail, "url": url})
    failed = [r for r in results if r["status"] != "pass"]
    return {
        "layer": "states",
        "status": "pass" if not failed else "fail",
        "detail": f"{len(results) - len(failed)}/{len(results)} states clean",
        "stories": results,
    }


def sentry_errors(org: str, project: str, token: str | None = None,
                  stats_period: str = "24h", query: str = "is:unresolved",
                  max_issues: int = 0, limit: int = 10) -> dict:
    token = token or os.environ.get("SENTRY_AUTH_TOKEN")
    if not token:
        config = Path.home() / ".config" / "verify-app" / "sentry.json"
        if config.exists():
            token = json.loads(config.read_text()).get("token")
            org = org or json.loads(config.read_text()).get("org", "")
            project = project or json.loads(config.read_text()).get("project", "")
    if not token or not org or not project:
        return {"layer": "errors", "status": "unconfigured",
                "detail": "set SENTRY_AUTH_TOKEN (and --org/--project) or ~/.config/verify-app/sentry.json",
                "issues": []}
    url = (f"https://sentry.io/api/0/projects/{org}/{project}/issues/"
           f"?query={urllib.parse.quote(query)}&statsPeriod={stats_period}&limit={limit}")
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            issues = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return {"layer": "errors", "status": "error",
                "detail": f"Sentry API {exc.code}: {exc.read()[:200].decode('utf-8', 'replace')}",
                "issues": []}
    except (urllib.error.URLError, OSError) as exc:
        return {"layer": "errors", "status": "error", "detail": f"Sentry unreachable: {exc}", "issues": []}
    trimmed = [{"title": i.get("title"), "count": i.get("count"), "culprit": i.get("culprit"),
                "permalink": i.get("permalink")} for i in issues]
    status = "pass" if len(trimmed) <= max_issues else "fail"
    return {"layer": "errors", "status": status,
            "detail": f"{len(trimmed)} unresolved issue(s) in {stats_period} (allowed {max_issues})",
            "issues": trimmed}


def _resolve_token() -> str | None:
    token = os.environ.get("SENTRY_AUTH_TOKEN")
    if token:
        return token
    config = Path.home() / ".config" / "verify-app" / "sentry.json"
    return json.loads(config.read_text()).get("token") if config.exists() else None


def doctor(port: int = 9222, storybook: str | None = None) -> dict:
    layers = {}
    playwright = shutil.which("playwright-rs") or shutil.which("fast-cdp")
    daemon = {"running": False, "detail": "playwright-rs not on PATH"}
    if playwright:
        result = subprocess.run([playwright, "daemon", "status"], capture_output=True, text=True)
        daemon = {"running": "running" in (result.stdout + result.stderr),
                  "detail": (result.stdout or result.stderr).strip().splitlines()[0] if result.stdout or result.stderr else ""}
    layers["hands"] = {"ok": bool(playwright and daemon["running"]),
                       "detail": f"{playwright or 'playwright-rs missing'}; daemon {daemon['detail']}"}
    browser = None
    try:
        targets = cdp_lite.list_targets(port=port)
        version = cdp_lite._http_json(f"http://127.0.0.1:{port}/json/version")
        browser = {"product": version.get("Browser"), "targets": len(targets)}
    except (cdp_lite.CDPError, urllib.error.URLError, OSError) as exc:
        browser = {"error": str(exc)}
    layers["eyes"] = {"ok": "product" in browser, "detail": browser}
    ffmpeg = shutil.which("ffmpeg")
    layers["pixels"] = {"ok": bool(ffmpeg), "detail": ffmpeg or "ffmpeg missing (required to decode PNGs)"}
    states = {"ok": False, "detail": "not requested"}
    if storybook:
        try:
            with urllib.request.urlopen(f"{storybook.rstrip('/')}/index.json", timeout=5) as resp:
                entries = json.loads(resp.read().decode("utf-8", "replace")).get("entries", {})
            states = {"ok": True, "detail": f"{len(entries)} stories at {storybook}"}
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            states = {"ok": False, "detail": f"{storybook}: {exc}"}
    layers["states"] = states
    token = _resolve_token()
    layers["errors"] = {"ok": bool(token), "detail": "SENTRY_AUTH_TOKEN present" if token
                        else "no Sentry token (layer will report unconfigured, not pass)"}
    required = ["hands", "eyes", "pixels"]
    layers["ready"] = all(layers[name]["ok"] for name in required)
    layers["optional_missing"] = [n for n in ("states", "errors") if not layers[n]["ok"]]
    return layers


def load_pass(path: Path) -> dict:
    if not path.exists():
        raise Dependency(f"no pass file at {path} — run `verify.py init --out {path.parent}` first")
    return json.loads(path.read_text())


def _unanswered(config: dict) -> list[str]:
    gaps = []
    if not (config.get("api") or {}).get("url"):
        gaps.append("api.url — question 1: which journey, on which viewport?")
    if not config.get("journey"):
        gaps.append("journey — question 1: the steps a person performs")
    if not (config.get("expect") or {}).get("text") and not (config.get("expect") or {}).get("requests"):
        gaps.append("expect — questions 2 and 3: what proves it worked, on screen and behind it")
    if not (config.get("pixels") or {}).get("baseline"):
        gaps.append("pixels.baseline — question 4: which pixels must not move")
    sentry = (config.get("errors") or {}).get("sentry") or {}
    if not (sentry.get("org") and sentry.get("project")):
        gaps.append("errors.sentry — question 5: which real-user error do we watch")
    return gaps


def run_pass(config: dict, only: list[str] | None = None, port: int = 9222,
             out_dir: Path | None = None) -> dict:
    artifacts = Path(config.get("artifacts", ".verify/artifacts"))
    if out_dir:
        artifacts = out_dir
    api = config.get("api", {})
    expect = config.get("expect", {})
    layers: dict[str, dict] = {}
    wanted = set(only) if only else {"hands", "pixels", "states", "errors"}

    shot = artifacts / f"{config.get('name', 'pass')}-after.png"
    if "hands" in wanted or "eyes" in wanted:
        try:
            layers["eyes"] = probe(
                api.get("url", ""), viewport=api.get("viewport"), settle_ms=api.get("settle_ms", 800),
                journey=config.get("journey"), expect=expect, screenshot=shot, port=port,
            )
        except Dependency as exc:
            layers["eyes"] = {"layer": "eyes", "status": "error", "detail": str(exc), "problems": []}
    if "pixels" in wanted:
        pixels = config.get("pixels", {})
        raw_baseline = pixels.get("baseline") or ""
        baseline = Path(raw_baseline)
        if raw_baseline and baseline.is_file() and shot.exists():
            try:
                layers["pixels"] = {"layer": "pixels", **compare_pixels(
                    baseline, shot, tolerance=pixels.get("tolerance", 8),
                    max_changed=pixels.get("max_changed", 0.0),
                    diff_out=artifacts / f"{config.get('name', 'pass')}-diff.png",
                )}
            except Dependency as exc:
                layers["pixels"] = {"layer": "pixels", "status": "error", "detail": str(exc)}
        else:
            layers["pixels"] = {"layer": "pixels", "status": "skip",
                                "detail": f"no baseline at {raw_baseline or '(unset)'}"
                                if not (raw_baseline and baseline.is_file())
                                else "no screenshot produced by the eyes layer"}
    if "states" in wanted:
        states = config.get("states", {})
        if states.get("storybook"):
            try:
                layers["states"] = storybook_states(
                    states["storybook"], prefix=states.get("filter", ""),
                    limit=states.get("max_stories", 30),
                    screenshot_dir=artifacts / "states" if states.get("screenshots", True) else None,
                    port=port,
                )
            except Dependency as exc:
                layers["states"] = {"layer": "states", "status": "error", "detail": str(exc)}
        else:
            layers["states"] = {"layer": "states", "status": "skip", "detail": "no storybook configured"}
    if "errors" in wanted:
        sentry = config.get("errors", {}).get("sentry", {})
        if sentry.get("org") and sentry.get("project"):
            layers["errors"] = sentry_errors(
                sentry["org"], sentry["project"], stats_period=sentry.get("stats_period", "24h"),
                query=sentry.get("query", "is:unresolved"), max_issues=sentry.get("max_issues", 0),
            )
        else:
            layers["errors"] = {"layer": "errors", "status": "skip", "detail": "no sentry project configured"}

    failed = [name for name, layer in layers.items() if layer.get("status") == "fail"]
    errored = [name for name, layer in layers.items() if layer.get("status") == "error"]
    skipped = [name for name, layer in layers.items() if layer.get("status") == "skip"]
    verdict = "pass" if not failed and not errored else "fail"
    if verdict == "fail" and errored and not failed:
        exit_code = EXIT_DEPENDENCY
    elif verdict == "pass" and all(layer.get("status") == "skip" for layer in layers.values()):
        verdict, exit_code = "unconfigured", EXIT_UNCONFIGURED
    else:
        exit_code = EXIT_PASS if verdict == "pass" else EXIT_FAIL
    unanswered = _unanswered(config)
    report = {
        "name": config.get("name", "pass"),
        "url": api.get("url"),
        "viewport": api.get("viewport"),
        "verdict": verdict,
        "gate": "full" if not unanswered else "partial",
        "exit": exit_code,
        "failed": failed + errored,
        "skipped": skipped,
        "unanswered": unanswered,
        "layers": layers,
        "artifacts": str(artifacts),
    }
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "verify.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    return report


def format_report(report: dict) -> str:
    badge = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP", "error": "ERROR", "unconfigured": "NOT CONFIGURED"}
    gate = "" if report.get("gate", "full") == "full" else f" (partial gate: {len(report.get('unanswered', []))} open question(s))"
    lines = [f"{badge.get(report['verdict'], report['verdict'])}  {report['name']}  {report.get('url') or ''}{gate}"]
    for name, layer in report.get("layers", {}).items():
        lines.append(f"  [{badge.get(layer.get('status'), '?'):>4}] {name:<7} {layer.get('detail', '')}")
        for problem in layer.get("problems", [])[:5]:
            lines.append(f"           {problem.get('kind')}: {problem.get('text')}")
        for story in [s for s in layer.get("stories", []) if s.get("status") != "pass"][:5]:
            lines.append(f"           story {story['id']}: {story['detail']}")
        for issue in layer.get("issues", [])[:3]:
            lines.append(f"           sentry: {issue.get('title')} ({issue.get('count')}x)")
    if report.get("unanswered"):
        lines.append("  open questions:")
        for gap in report["unanswered"]:
            lines.append(f"    - {gap}")
    lines.append(f"  artifacts: {report.get('artifacts')}/verify.json")
    return "\n".join(lines)


def init_config(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "pass.json"
    skeleton = {
        "name": out_dir.parent.name or "app",
        "api": {"url": "", "viewport": "390x844", "settle_ms": 800},
        "journey": [],
        "expect": {"text": "", "requests": [], "no_failed_requests": True},
        "pixels": {"baseline": "", "tolerance": 8, "max_changed": 0.0},
        "states": {"storybook": "", "filter": "", "max_stories": 30},
        "errors": {"sentry": {"org": "", "project": "", "stats_period": "24h", "max_issues": 0}},
        "artifacts": str(out_dir / "artifacts"),
    }
    if not path.exists():
        path.write_text(json.dumps(skeleton, indent=2))
    return path


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
    gate = runner or (lambda: run_pass(load_pass(pass_path), out_dir=artifacts))

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


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--port", type=int, default=9222, metavar="PORT")
    common.add_argument("--json", action="store_true")

    parser = argparse.ArgumentParser(
        prog="verify.py",
        description="Hands and eyes: prove the app works instead of saying it does.",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", parents=[common], help="are all five layers available?").add_argument(
        "--storybook", default=None)
    sub.add_parser("ask", parents=[common],
                   help="the five questions a verification gate has to answer").add_argument(
        "--out", type=Path, default=Path(".verify"))

    eyes = sub.add_parser("eyes", parents=[common],
                          help="open the app, drive it, and report what the browser did")
    eyes.add_argument("--url", required=True)
    eyes.add_argument("--viewport", default=None)
    eyes.add_argument("--settle", type=int, default=800, metavar="TIMEOUT")
    eyes.add_argument("--click", action="append", default=[])
    eyes.add_argument("--fill", action="append", nargs=2, metavar=("SELECTOR", "VALUE"), default=[])
    eyes.add_argument("--expect-text", default=None)
    eyes.add_argument("--expect-eval", action="append", default=[], metavar="EXPR")
    eyes.add_argument("--case-sensitive", action="store_true")
    eyes.add_argument("--expect-request", action="append", default=[],
                      metavar="SUBSTR[:STATUS]")
    eyes.add_argument("--screenshot", type=Path, default=None)
    eyes.add_argument("--out", type=Path, default=None)

    pixels = sub.add_parser("pixels", parents=[common], help="compare before and after pixel by pixel")
    pixels.add_argument("--before", type=Path, required=True)
    pixels.add_argument("--after", type=Path, required=True)
    pixels.add_argument("--tolerance", type=int, default=8, metavar="N")
    pixels.add_argument("--max-changed", type=float, default=0.0, metavar="RATIO")
    pixels.add_argument("--diff-out", type=Path, default=None)

    states = sub.add_parser("states", parents=[common], help="walk every Storybook state on its own")
    states.add_argument("--storybook", required=True)
    states.add_argument("--filter", default="")
    states.add_argument("--limit", type=int, default=30, metavar="LIMIT")
    states.add_argument("--screenshot-dir", type=Path, default=None)

    errors = sub.add_parser("errors", parents=[common], help="what real users are hitting right now")
    errors.add_argument("--org", default="")
    errors.add_argument("--project", default="")
    errors.add_argument("--stats-period", default="24h")
    errors.add_argument("--query", default="is:unresolved")
    errors.add_argument("--max-issues", type=int, default=0, metavar="LIMIT")

    run = sub.add_parser("run", parents=[common], help="run the whole gate from a pass file")
    run.add_argument("--pass", dest="pass_file", type=Path, default=Path(".verify/pass.json"))
    run.add_argument("--only", action="append", default=[],
                     choices=["eyes", "pixels", "states", "errors"])
    run.add_argument("--out-dir", type=Path, default=None)

    init = sub.add_parser("init", parents=[common], help="write the five-question skeleton for this app")
    init.add_argument("--out", type=Path, default=Path(".verify"))

    forge_p = sub.add_parser("forge", parents=[common],
                             help="interview the repo and generate a project-local verification skill")
    forge_p.add_argument("repo", nargs="?", type=Path, default=Path("."))
    forge_p.add_argument("--out", type=Path, default=None)
    forge_p.add_argument("--harness", choices=["auto", "agents", "opencode", "claude"], default="auto")
    forge_p.add_argument("--apply", action="store_true")
    forge_p.add_argument("--adopt", action="store_true",
                         help="append the adoption line to --instructions (requires --apply)")
    forge_p.add_argument("--instructions", type=Path, default=Path("AGENTS.md"),
                         help="instruction file the adoption line goes into (default: AGENTS.md)")

    control_p = sub.add_parser("control", parents=[common],
                               help="break one feature on purpose and prove the gate catches it")
    control_p.add_argument("--repo", type=Path, default=Path("."))
    control_p.add_argument("--file", dest="target", type=Path, required=True)
    control_p.add_argument("--find", required=True)
    control_p.add_argument("--replace", required=True)
    control_p.add_argument("--pass", dest="pass_file", type=Path, default=Path(".verify/pass.json"))
    control_p.add_argument("--out-dir", type=Path, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor(port=args.port, storybook=args.storybook)
            if args.json:
                print(_json_line(result))
            else:
                for name in ("hands", "eyes", "pixels", "states", "errors"):
                    layer = result[name]
                    detail = layer["detail"]
                    detail = json.dumps(detail) if isinstance(detail, dict) else detail
                    print(f"  {'ok  ' if layer['ok'] else 'MISS'} {name:<7} {detail}")
                print(f"  ready: {result['ready']}")
            return EXIT_PASS if result["ready"] else EXIT_DEPENDENCY

        if args.command == "ask":
            path = init_config(args.out)
            payload = {"questions": QUESTIONS, "pass_file": str(path), "partner_config": None}
            if args.json:
                print(_json_line(payload))
            else:
                print("Five questions, one gate. Unanswered question = layer still missing.\n")
                for number, question in enumerate(QUESTIONS, start=1):
                    print(f"  {number}. {question}")
                print(f"\n  skeleton: {path}")
            return EXIT_PASS

        if args.command == "eyes":
            expect = {"no_failed_requests": True}
            if args.expect_text:
                expect["text"] = args.expect_text
            if args.case_sensitive:
                expect["case_sensitive"] = True
            if args.expect_eval:
                expect["eval"] = [{"expression": expr, "label": expr} for expr in args.expect_eval]
            expect["requests"] = []
            for raw in args.expect_request:
                sub_str, _, status = raw.partition(":")
                expect["requests"].append({"contains": sub_str, "status": int(status) if status else None})
            journey = [{"click": selector} for selector in args.click]
            journey += [{"fill": [selector, value]} for selector, value in args.fill]
            report = probe(args.url, viewport=args.viewport, settle_ms=args.settle,
                           journey=journey, expect=expect, screenshot=args.screenshot, port=args.port)
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(json.dumps(report, indent=2, sort_keys=True))
            if args.json:
                print(_json_line(report))
            else:
                print(format_report({"name": "eyes", "verdict": report["status"], "url": args.url,
                                     "layers": {"eyes": report}, "artifacts": str(args.out.parent if args.out else ".")}))
            return EXIT_PASS if report["status"] == "pass" else EXIT_FAIL

        if args.command == "pixels":
            result = compare_pixels(args.before, args.after, tolerance=args.tolerance,
                                    max_changed=args.max_changed, diff_out=args.diff_out)
            print(_json_line(result) if args.json else f"{result['status'].upper()}  {result['detail']}")
            return EXIT_PASS if result["status"] == "pass" else EXIT_FAIL

        if args.command == "states":
            result = storybook_states(args.storybook, prefix=args.filter, limit=args.limit,
                                      screenshot_dir=args.screenshot_dir, port=args.port)
            if args.json:
                print(_json_line(result))
            else:
                print(f"{result['status'].upper()}  {result['detail']}")
                for story in [s for s in result["stories"] if s["status"] != "pass"][:10]:
                    print(f"  {story['id']}: {story['detail']}")
            return EXIT_PASS if result["status"] in ("pass", "skip") else EXIT_FAIL

        if args.command == "errors":
            result = sentry_errors(args.org, args.project, stats_period=args.stats_period,
                                   query=args.query, max_issues=args.max_issues)
            if args.json:
                print(_json_line(result))
            else:
                print(f"{result['status'].upper()}  {result['detail']}")
                for issue in result["issues"][:5]:
                    print(f"  {issue['count']}x {issue['title']} — {issue.get('permalink', '')}")
            if result["status"] == "unconfigured":
                return EXIT_UNCONFIGURED
            return EXIT_PASS if result["status"] == "pass" else EXIT_FAIL

        if args.command == "init":
            path = init_config(args.out)
            print(f"wrote {path}")
            for number, question in enumerate(QUESTIONS, start=1):
                print(f"  {number}. {question}")
            return EXIT_PASS

        if args.command == "run":
            config = load_pass(args.pass_file)
            report = run_pass(config, only=args.only, port=args.port, out_dir=args.out_dir)
            print(_json_line(report) if args.json else format_report(report))
            return report["exit"]

        if args.command == "forge":
            if args.adopt and not args.apply:
                print("verify.py: --adopt writes into the repo, so it needs --apply", file=sys.stderr)
                return EXIT_USAGE
            result = forge(args.repo, out=args.out, harness=args.harness, apply=args.apply,
                           adopt_to=args.instructions if args.adopt else None)
            if args.json:
                print(_json_line(result))
            else:
                interview = result["interview"]
                run = interview.get("run") or {}
                print(f"verify-{result['app']}  →  {result['out_dir']}  ({result['harness']})")
                for row in interview["surfaces"]:
                    print(f"  surface  {row['surface']:<8} {row['evidence']}")
                print(f"  run      {run.get('command', 'UNANSWERED')}  [{run.get('evidence', 'no evidence')}]")
                for tool in interview["tools"]:
                    state = "installed" if tool["present"] else "proposed"
                    print(f"  {tool['tool']:<12} {state:<9} {tool['why']}")
                print(f"  features {len(interview['features'])} detected")
                if interview["open"]:
                    print("  open questions — each one is a layer this gate does not have:")
                    for question in interview["open"]:
                        print(f"    - {question}")
                if result["written"]:
                    print("  written:")
                    for path in result["written"]:
                        print(f"    {path}")
                elif not args.apply:
                    print("  dry run — pass --apply to write the skill")
                if result["adopted"]:
                    state = "added to" if result["adopted"]["changed"] else "already in"
                    print(f"  adoption {state} {result['adopted']['path']}")
            return result["exit"]

        if args.command == "control":
            report = control(args.repo, args.target, args.find, args.replace,
                             pass_file=args.pass_file, out_dir=args.out_dir)
            if args.json:
                print(_json_line(report))
            else:
                badge = "PASS" if report["verdict"] == "pass" else "FAIL"
                print(f"{badge}  control  {report['target']}")
                print(f"  red    {report['red']['verdict']} ({report['red']['exit']})  expected a failing gate")
                print(f"  restore {report['sha256_after'][:12]}  {'exact' if report['restored'] else 'DIFFERENT'}")
                print(f"  green  {report['green']['verdict']} ({report['green']['exit']})")
                print(f"  {report['detail']}")
            return report["exit"]
    except Dependency as exc:
        print(f"verify.py: {exc}", file=sys.stderr)
        return EXIT_DEPENDENCY
    except KeyboardInterrupt:
        return EXIT_USAGE
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
