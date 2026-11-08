#!/usr/bin/env python3
"""frontend-uat — sub-second frontend UAT loop.

Capture architecture (Fast Frontend UAT with JEV; source reel unidentified): the
page is handed to the decision model as an *indexed array of clickable targets*;
deterministic code executes the click; the
model then reads the screen back and answers whether the test's assertion held.
No open-ended text is ever generated, which is why the loop costs seconds and
fractions of a cent instead of minutes and dollars.

Steps carry the eval-pipeline taxonomy, so a failure is attributable to code or
to a model turn:

    [D] deterministic  — candidate extraction, navigation, the click, assertions
    [P] probabilistic  — target choice, visual verification gate

Composition, not duplication:

    playwright-rs (`fast-cdp` is its alias) — extract candidates, click, assert
    jev-decision's CLI           — pick the target, gate the result

Both halves are reached through their own stable CLIs. Neither is reimplemented
here; this script is the loop that joins them.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# locating the two halves
# --------------------------------------------------------------------------

SKILL_DIR = Path(__file__).resolve().parent.parent


def find_fast_cdp() -> Optional[str]:
    """playwright-rs, the native CDP client this loop drives."""
    env = os.environ.get("FAST_CDP")
    if env and Path(env).is_file():
        return env
    found = shutil.which("fast-cdp") or shutil.which("playwright-rs")
    if found:
        return found
    for cand in (
        Path(__file__).resolve().parents[3] / "multimodal" / "playwright" / "bin" / "playwright-rs",
        Path.home() / ".local" / "bin" / "playwright-rs",
    ):
        if cand.is_file():
            return str(cand)
    return None


def find_jev_cli() -> Optional[Path]:
    """jev-decision's CLI, searched the same way eval-router searches the engine.

    The skill is installed in a repo, in a flat harness tree, and in bundles;
    the CLI is what this loop needs, so the search follows the same roots.
    """
    env = os.environ.get("JEV_CLI")
    if env and Path(env).is_file():
        return Path(env)
    roots: List[Path] = [
        Path("/run/media/rodri/AI/skills"),
        SKILL_DIR.parent,
        *SKILL_DIR.parents,
        *(Path.home() / d for d in (
            ".config/opencode/skills", ".gemini/config/skills", ".pi/agent/skills",
        )),
    ]
    for root in roots:
        for cand in (
            root / "jev-decision" / "jev_decision.py",
            root / "glitch-cat" / "jev-decision" / "jev_decision.py",
        ):
            if cand.is_file():
                return cand
    return None


# --------------------------------------------------------------------------
# [D] candidate extraction
# --------------------------------------------------------------------------

# Mirror of UAT_EXTRACT_JS in multimodal/playwright/playwright-rs/src/main.rs.
# The ref space (`uat-N`, in DOM order, tagging each element with data-uat-ref)
# MUST stay identical to `playwright-rs uat`, because that is what `--ref`
# addresses. `playwright-rs candidates <url> --json` prints the same list, and
# tests/test_frontend_uat.py asserts the binary still exposes both `--ref` and
# `candidates`, so a binary change cannot break this silently.
EXTRACT_JS = r"""
(() => {
    const elements = [];
    const candidates = document.querySelectorAll('button, a, input, select, textarea, [role="button"], [tabindex]:not([tabindex="-1"])');
    let idx = 0;
    for (const el of candidates) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        if (rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none') {
            idx++;
            const tag = el.tagName.toLowerCase();
            const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.id || '').trim().replace(/\s+/g, ' ').slice(0, 80);
            const role = el.getAttribute('role') || tag;
            const ref = `uat-${idx}`;
            el.setAttribute('data-uat-ref', ref);
            elements.push({
                ref: ref,
                description: `${role} '${text}'`
            });
        }
    }
    return elements;
})()
"""


class DependencyError(RuntimeError):
    """A half of the loop is missing or not answering."""


def run_cmd(cmd: List[str], timeout: float = 30.0) -> "subprocess.CompletedProcess[str]":
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise DependencyError(f"timed out after {timeout}s: {' '.join(cmd[:3])} …")
    except OSError as exc:
        raise DependencyError(f"could not execute {cmd[0]}: {exc}")


def _decode(value: str) -> Any:
    """Decode a value that may be JSON, or a JSON string containing JSON.

    `fast-cdp eval` returns the evaluated value JSON-encoded, so a script that
    returns an array arrives as a quoted string of JSON.
    """
    try:
        parsed = json.loads(value)
    except ValueError:
        raise DependencyError(f"unparseable JSON from fast-cdp: {value[:200]}")
    if isinstance(parsed, str):
        try:
            return json.loads(parsed)
        except ValueError:
            return parsed
    return parsed


def open_page(fast_cdp: str, url: str) -> Dict[str, Any]:
    proc = run_cmd([fast_cdp, "open", url, "--json"], timeout=30.0)
    if proc.returncode != 0:
        raise DependencyError(
            f"fast-cdp could not open {url}: "
            f"{(proc.stderr or proc.stdout).strip()[:300]}\n"
            f"       Is the CDP browser up? Start it with `fast-cdp daemon start` "
            f"or `playwright-rs daemon start`."
        )
    return _decode(proc.stdout)


def extract_candidates(fast_cdp: str, url: str) -> List[Dict[str, str]]:
    open_page(fast_cdp, url)
    proc = run_cmd([fast_cdp, "eval", EXTRACT_JS, "--json"], timeout=30.0)
    if proc.returncode != 0:
        raise DependencyError(f"candidate extraction failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    raw = proc.stdout.strip()
    try:
        payload = json.loads(raw)
    except ValueError:
        raise DependencyError(f"unparseable fast-cdp eval output: {raw[:200]}")
    value = payload.get("value", payload) if isinstance(payload, dict) else payload
    candidates = _decode(value) if isinstance(value, str) else value
    if not isinstance(candidates, list):
        raise DependencyError(f"candidate extraction returned {type(candidates).__name__}, expected a list")
    return [{"ref": str(c.get("ref", "")), "description": str(c.get("description", ""))} for c in candidates]


# --------------------------------------------------------------------------
# [P] the model halves
# --------------------------------------------------------------------------

def call_jev(cli: Path, args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
    proc = run_cmd([sys.executable, str(cli), *args, "--json", "--require-server"], timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[:300]
        raise DependencyError(
            f"jev-decision exited {proc.returncode}: {detail}\n"
            f"       Is the decision server up? `curl -s http://127.0.0.1:8083/health`."
        )
    try:
        return json.loads(proc.stdout)
    except ValueError:
        raise DependencyError(f"jev-decision returned unparseable JSON: {proc.stdout[:200]}")


def choose_target(cli: Path, url: str, intent: str,
                  candidates: List[Dict[str, str]]) -> Dict[str, Any]:
    """Hand the indexed candidate array to the decision model; it returns an index."""
    options = [f"{c['ref']}: {c['description']}" for c in candidates]
    context = f"Page: {url}\nInteractive elements:\n" + "\n".join(options)
    question = f"Which interactive element satisfies the user intent: '{intent}'?"
    res = call_jev(cli, ["choice", "--context", context, "--question", question,
                         "--options", *options])
    selection = str(res.get("selection", ""))
    ref = selection.split(":", 1)[0].strip()
    probs = res.get("probabilities") or {}
    return {
        "ref": ref,
        "selection": selection,
        "p_selected": round(float(probs.get(selection, 0.0)), 4),
        "confidence": res.get("confidence"),
        "probabilities": probs,
        "source": res.get("source"),
        "n_candidates": len(options),
    }


def visual_gate(cli: Path, screenshot: Path, question: str) -> Dict[str, Any]:
    res = call_jev(cli, ["bool",
                         "--context", f"Post-action screenshot at {screenshot.name}.",
                         "--question", question,
                         "--image", str(screenshot)])
    probs = res.get("probabilities") or {}
    return {
        "question": question,
        "passed": bool(res.get("decision")),
        "p_true": round(float(probs.get("true", 0.0)), 4),
        "source": res.get("source"),
    }


# --------------------------------------------------------------------------
# [D] the action
# --------------------------------------------------------------------------

def execute_action(fast_cdp: str, url: str, intent: str, ref: str,
                   expect_text: Optional[str], expect_url: Optional[str],
                   screenshot: Optional[Path], timeout_ms: int) -> Dict[str, Any]:
    cmd = [fast_cdp, "uat", url, "--goal", intent, "--ref", ref, "--json",
           "--timeout", str(timeout_ms)]
    if expect_text:
        cmd += ["--expect-text", expect_text]
    if expect_url:
        cmd += ["--expect-url", expect_url]
    if screenshot:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        cmd += ["--screenshot", str(screenshot)]
    proc = run_cmd(cmd, timeout=max(30.0, timeout_ms / 1000.0 + 10.0))
    out = proc.stdout.strip()
    try:
        result = json.loads(out) if out else {}
    except ValueError:
        result = {"raw": out[:500]}
    if proc.returncode != 0 and not result.get("errors"):
        result["errors"] = [(proc.stderr or out).strip()[:400]]
    result["ok"] = bool(result.get("ok"))
    return result


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------

def plan(fast_cdp: str, jev: Path, url: str, intent: str,
         min_p: float = 0.0) -> Dict[str, Any]:
    """Steps 1-2 only: extract candidates and let the model pick, without acting.

    This is the validate-before-execute half of the loop. Its output is a plan
    file that `run --plan` can execute, so a human (or a reviewer) can read the
    decision before any click happens.
    """
    steps: List[Dict[str, Any]] = []

    t0 = time.time()
    candidates = extract_candidates(fast_cdp, url)
    steps.append({"tag": "[D]", "step": "extract_candidates",
                  "detail": f"{len(candidates)} interactive elements", "ms": _ms(t0)})
    if not candidates:
        raise DependencyError(f"no interactive elements found at {url} — nothing to decide")

    t0 = time.time()
    decision = choose_target(jev, url, intent, candidates)
    steps.append({"tag": "[P]", "step": "choose_target",
                  "detail": f"{decision['ref']} p={decision['p_selected']}", "ms": _ms(t0)})

    if not decision["ref"]:
        raise DependencyError(f"the decision model returned no selection for intent '{intent}'")
    if not any(c["ref"] == decision["ref"] for c in candidates):
        raise DependencyError(
            f"the decision model selected {decision['ref']!r}, which is not one of the "
            f"{len(candidates)} candidates. Candidates were {[c['ref'] for c in candidates][:10]}…"
        )
    decision["below_min_p"] = decision["p_selected"] < min_p

    return {"url": url, "intent": intent, "candidates": candidates,
            "decision": decision, "steps": steps, "min_p": min_p}


def run(fast_cdp: str, jev: Path, url: str, intent: str,
        expect_text: Optional[str] = None, expect_url: Optional[str] = None,
        screenshot: Optional[Path] = None, assert_image: Optional[str] = None,
        min_p: float = 0.0, timeout_ms: int = 5000,
        plan_in: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    started = time.time()
    errors: List[str] = []

    prepared = plan_in or plan(fast_cdp, jev, url, intent, min_p=min_p)
    if plan_in:
        errors.extend(plan_in.get("errors", []))
    steps: List[Dict[str, Any]] = list(prepared["steps"])
    decision = prepared["decision"]
    candidates = prepared["candidates"]

    # A replayed plan is the caller's own artifact, so the ref is re-validated
    # against the candidate set rather than trusted: a stale plan and a moved
    # page must fail, not click the wrong element.
    if plan_in and not any(c.get("ref") == decision.get("ref") for c in candidates):
        errors.append(
            f"plan's ref {decision.get('ref')!r} is not in its candidate set "
            f"{[c.get('ref') for c in candidates][:10]}"
        )
        return _report(url, intent, "fail", steps, decision, None, None, errors, started,
                       candidates=candidates)

    if decision.get("below_min_p"):
        errors.append(
            f"selected {decision['ref']} with p={decision['p_selected']} < --min-p {min_p}; "
            f"refusing to click. Candidates: {[c['ref'] + ' ' + c['description'] for c in candidates][:8]}"
        )
        return _report(url, intent, "fail", steps, decision, None, None, errors, started,
                       candidates=candidates)

    if screenshot is None:
        screenshot = Path("/tmp") / f"frontend-uat-{os.getpid()}.png"

    t0 = time.time()
    action = execute_action(fast_cdp, url, intent, decision["ref"],
                            expect_text, expect_url, screenshot, timeout_ms)
    steps.append({"tag": "[D]", "step": "execute_action",
                  "detail": f"fast-cdp uat --ref {decision['ref']}", "ms": _ms(t0)})

    verification: Dict[str, Any] = {
        "method": "assert" if (expect_text or expect_url) else "action_executed",
        "passed": bool(action.get("ok")),
        "detail": action.get("verification"),
    }
    if action.get("errors"):
        errors.extend(str(e) for e in action["errors"])

    # The visual gate is the *second* model turn from the capture: read the screen
    # back and answer the test's question. Opt-in, because an assertion the DOM
    # can answer is deterministic and free.
    if assert_image and action.get("ok"):
        if not screenshot.is_file():
            errors.append(f"--assert-image needs a screenshot, but {screenshot} was not written")
        else:
            t0 = time.time()
            gate = visual_gate(jev, screenshot, assert_image)
            steps.append({"tag": "[P]", "step": "visual_gate",
                          "detail": f"p(true)={gate['p_true']}", "ms": _ms(t0)})
            verification = {
                "method": "visual_gate",
                "passed": gate["passed"],
                "detail": f"{assert_image} -> p(true)={gate['p_true']}",
                "gate": gate,
            }
            if not gate["passed"]:
                errors.append(f"visual gate failed: {assert_image} (p(true)={gate['p_true']})")

    result = "pass" if verification["passed"] and not errors else "fail"
    return _report(url, intent, result, steps, decision, action, verification, errors, started,
                   screenshot=str(screenshot) if screenshot.is_file() else None,
                   candidates=candidates)


def _ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def _report(url: str, intent: str, result: str, steps: List[Dict[str, Any]],
            decision: Dict[str, Any], action: Optional[Dict[str, Any]],
            verification: Optional[Dict[str, Any]], errors: List[str],
            started: float, screenshot: Optional[str] = None,
            candidates: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    return {
        "result": result,
        "url": url,
        "intent": intent,
        "selected": decision,
        "action": action,
        "verification": verification,
        "candidates": candidates or [],
        "steps": steps,
        "errors": errors,
        "screenshot": screenshot,
        "duration_ms": _ms(started),
    }


def format_report(rep: Dict[str, Any]) -> str:
    """One line, so a suite of runs does not flood the caller's context."""
    dec = rep.get("selected") or {}
    ver = rep.get("verification") or {}
    verdict = "PASS" if rep["result"] == "pass" else "FAIL"
    line = (f"[{verdict}] {rep['intent']} — {dec.get('ref', '?')} ({ver.get('detail', '')}) "
            f"p={dec.get('p_selected', 0.0)} {rep['duration_ms']}ms")
    if rep.get("errors"):
        line += "\n  " + "\n  ".join(rep["errors"][:3])
    return line


def write_ledger(workdir: Path, rep: Dict[str, Any]) -> None:
    """Serialize intermediate state, the eval-pipeline way ([D]/[P] boundaries)."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "step_01_candidates.json").write_text(
        json.dumps(rep.get("candidates", []), indent=2), encoding="utf-8")
    (workdir / "step_02_decision.json").write_text(
        json.dumps(rep.get("selected", {}), indent=2), encoding="utf-8")
    (workdir / "step_03_action.json").write_text(
        json.dumps(rep.get("action") or {}, indent=2), encoding="utf-8")
    (workdir / "step_04_verification.json").write_text(
        json.dumps(rep.get("verification") or {}, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# diagnostics
# --------------------------------------------------------------------------

def doctor() -> Dict[str, Any]:
    fast_cdp = find_fast_cdp()
    jev = find_jev_cli()
    host = os.environ.get("JEV_HOST") or "127.0.0.1"
    port = os.environ.get("JEV_PORT") or "8083"
    scheme = "https" if ".ts.net" in host or os.environ.get("JEV_SCHEME") == "https" else "http"
    out: Dict[str, Any] = {
        "fast_cdp": fast_cdp,
        "jev_cli": str(jev) if jev else None,
        "cdp_browser": False,
        "decision_server": False,
        "decision_endpoint": f"{scheme}://{host}:{port}",
    }
    if fast_cdp:
        proc = run_cmd([fast_cdp, "daemon", "status"], timeout=10.0)
        out["cdp_browser"] = proc.returncode == 0 and "running" in (proc.stdout or "")
    out["decision_server"] = _health(f"{scheme}://{host}:{port}/health")
    out["ready"] = bool(fast_cdp and jev and out["cdp_browser"] and out["decision_server"])
    return out


def _health(url: str, timeout: float = 2.0) -> bool:
    import ssl
    import urllib.error
    import urllib.request
    ctx = None
    if url.startswith("https"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout, context=ctx):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def _require_halves() -> tuple[str, Path]:
    fast_cdp = find_fast_cdp()
    if not fast_cdp:
        raise DependencyError(
            "playwright-rs (fast-cdp) not found. Set FAST_CDP to its path, or install the playwright skill.\n"
            "       Expected: <repo>/multimodal/playwright/bin/playwright-rs"
        )
    jev = find_jev_cli()
    if not jev:
        raise DependencyError(
            "jev-decision CLI not found. Install the jev-decision skill, or set JEV_CLI.\n"
            "       Expected: /run/media/rodri/AI/skills/jev-decision/jev_decision.py"
        )
    return fast_cdp, jev


def _require_url(args: argparse.Namespace) -> str:
    """A url may be given positionally or as --url, but it must be given."""
    url = args.url or args.url_flag
    if not url:
        print(
            "Error: a target URL is required.\n"
            "       Examples: frontend-uat doctor\n"
            "                 frontend-uat candidates http://localhost:3000\n"
            "                 frontend-uat run --url http://localhost:3000 --intent \"proceed to checkout\"",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return url


def main() -> int:
    p = argparse.ArgumentParser(
        description="frontend-uat — model-backed UAT loop: DOM candidates -> decision -> CDP click -> verify.",
        epilog=(
            "Exit codes: 0 pass · 1 failed verification · 2 usage error · 3 a dependency is down.\n"
            "Examples:\n"
            "  frontend-uat run --url http://localhost:3000 --intent \"proceed to checkout\" --expect-text \"Order confirmed\"\n"
            "  frontend-uat plan --url http://localhost:3000 --intent \"open the cart\" --out /tmp/cart-plan.json\n"
            "  frontend-uat run --url http://localhost:3000 --intent \"open the cart\" --plan /tmp/cart-plan.json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("candidates", help="List the interactive elements the loop can address")
    c.add_argument("url", nargs="?")
    c.add_argument("--url", dest="url_flag", help="Target URL (same as the positional)")
    c.add_argument("--json", action="store_true", help="Emit JSON instead of a table")

    pl = sub.add_parser("plan", help="Extract candidates and let the model choose — no click")
    pl.add_argument("url", nargs="?")
    pl.add_argument("--url", dest="url_flag", help="Target URL (same as the positional)")
    pl.add_argument("--intent", required=True, help="What the user is trying to do, in their words")
    pl.add_argument("--min-p", type=float, default=0.0, metavar="SCORE",
                    help="Refuse the pick if the model's probability for it is below this (default 0.0)")
    pl.add_argument("--out", help="Write the plan JSON here so `run --plan` can execute it")
    pl.add_argument("--json", action="store_true")

    r = sub.add_parser("run", help="Run the full loop: choose, click, verify")
    r.add_argument("url", nargs="?")
    r.add_argument("--url", dest="url_flag", help="Target URL (same as the positional)")
    r.add_argument("--intent", required=True, help="What the user is trying to do, in their words")
    r.add_argument("--expect-text", help="Assert this text appears after the action (deterministic)")
    r.add_argument("--expect-url", help="Assert the URL becomes this after the action (deterministic)")
    r.add_argument("--assert-image", help="Ask the decision model this question about the post-action screenshot")
    r.add_argument("--screenshot", help="Where to save the evidence screenshot")
    r.add_argument("--plan", help="Execute a plan produced by `plan` instead of deciding again")
    r.add_argument("--min-p", type=float, default=0.0, metavar="SCORE", help="Refuse to click below this probability")
    r.add_argument("--timeout", type=int, default=5000, metavar="N", help="Action timeout in ms (default 5000)")
    r.add_argument("--workdir", help="Serialize each step to disk here (step_01_candidates.json, …)")
    r.add_argument("--out", help="Write the full report JSON here; stdout stays one line")
    r.add_argument("--json", action="store_true", help="Print the full report JSON")

    d = sub.add_parser("doctor", help="Check that both halves of the loop are alive")
    d.add_argument("--json", action="store_true")

    args = p.parse_args()

    try:
        if args.cmd == "doctor":
            out = doctor()
            print(json.dumps(out, indent=2) if args.json else
                  "\n".join(f"{k:18s} {v}" for k, v in out.items()))
            return 0 if out["ready"] else 3

        fast_cdp, jev = _require_halves()
        url = _require_url(args)

        if args.cmd == "candidates":
            cands = extract_candidates(fast_cdp, url)
            if args.json:
                print(json.dumps(cands, indent=2))
            else:
                for cd in cands:
                    print(f"{cd['ref']:>8}  {cd['description']}")
            return 0

        if args.cmd == "plan":
            prepared = plan(fast_cdp, jev, url, args.intent, min_p=args.min_p)
            report = {"result": "planned", **prepared, "duration_ms":
                      sum(s["ms"] for s in prepared["steps"])}
            if args.out:
                Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(f"[PLAN] {args.intent} — {prepared['decision']['ref']} "
                      f"({prepared['decision']['selection']}) p={prepared['decision']['p_selected']} "
                      f"-> {args.out}")
            elif args.json:
                print(json.dumps(report, indent=2))
            else:
                print(f"[PLAN] {args.intent} — {prepared['decision']['ref']} "
                      f"({prepared['decision']['selection']}) p={prepared['decision']['p_selected']}")
            return 0

        # run
        plan_in = None
        if args.plan:
            plan_path = Path(args.plan)
            if not plan_path.is_file():
                print(f"Error: --plan file not found: {plan_path}", file=sys.stderr)
                return 2
            plan_in = json.loads(plan_path.read_text(encoding="utf-8"))
            if plan_in.get("url") != url:
                print(f"Error: plan was made for {plan_in.get('url')!r} but the target is {url!r}.",
                      file=sys.stderr)
                return 2
            if plan_in.get("intent") != args.intent:
                print(f"Error: plan was made for intent {plan_in.get('intent')!r}, "
                      f"but --intent is {args.intent!r}.", file=sys.stderr)
                return 2

        rep = run(fast_cdp, jev, url, args.intent,
                  expect_text=args.expect_text, expect_url=args.expect_url,
                  screenshot=Path(args.screenshot) if args.screenshot else None,
                  assert_image=args.assert_image, min_p=args.min_p,
                  timeout_ms=args.timeout, plan_in=plan_in)

        if args.workdir:
            write_ledger(Path(args.workdir), rep)
        if args.out:
            Path(args.out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
            print(format_report(rep) + f"\n  report: {args.out}")
        elif args.json:
            print(json.dumps(rep, indent=2))
        else:
            print(format_report(rep))
        return 0 if rep["result"] == "pass" else 1

    except DependencyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
