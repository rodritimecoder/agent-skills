#!/usr/bin/env python3
"""JEV decision CLI — h2o-lightning-4b primitives, plus batch and cleanup.

Output is one compact line by default. `--json` prints the structured result,
`--out FILE` writes the JSON to disk and keeps stdout to one pointer line, so a
caller pays a handful of tokens instead of a full payload.

`box` (visual grounding) delegates to `decision-model box`, so the geometry
client, its gates and its exit codes stay in one place.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "modules"))
from jev_engine import JevEngine
import jev_engine

_VRAM_RIG_CTL = shutil.which("llama-rig") or shutil.which("vram-rig-ctl")


def _die(message: str, code: int) -> "SystemExit":
    """Errors go to stderr with a stable exit code: 2 usage, 3 dependency."""
    print(message, file=sys.stderr)
    return SystemExit(code)


def _decision_up(health_url: str, engine=None) -> bool:
    if engine is not None:
        return engine.is_online()
    try:
        with urllib.request.urlopen(health_url, timeout=0.8) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_decision_server(engine=None, host: str = "127.0.0.1", port: int = 8083,
                           timeout: float = 20.0) -> bool:
    """Start the decision server if it is down — mirrors OCR's ensure_lighton."""
    if isinstance(engine, str):
        host, engine = engine, None
    elif isinstance(engine, int):
        port, engine = engine, None
    health_url = engine.health_url if engine is not None else f"http://{host}:{port}/health"
    resolved_host = engine.host if engine is not None else host
    if _decision_up(health_url, engine):
        return True
    if resolved_host not in ("127.0.0.1", "localhost"):
        return False
    ctl = _VRAM_RIG_CTL
    if not ctl:
        return False
    try:
        subprocess.Popen([ctl, "up", "decision"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _decision_up(health_url, engine):
            return True
        time.sleep(0.5)
    return False


_DECISION_MODEL_ENV = "JEV_DECISION_MODEL"


def _decision_model_script() -> Path | None:
    """Where `box` lives: this checkout first, `decision-model` on PATH second."""
    override = os.environ.get(_DECISION_MODEL_ENV, "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    sibling = (Path(__file__).resolve().parents[2]
               / "hardware" / "decision-model" / "scripts" / "decision_model.py")
    if sibling.is_file():
        return sibling
    found = shutil.which("decision-model")
    return Path(found) if found else None


def _run_box(args) -> int:
    """Forward to `decision-model box` and return its exit code unchanged.

    Exit 2 is the gate rejecting a hit (absent target, low present/confidence);
    callers such as `t3-locate` branch on it, so it must not be flattened.
    """
    target = _decision_model_script()
    if target is None:
        raise _die(
            "Error: decision-model was not found — looked for "
            "hardware/decision-model/scripts/decision_model.py and `decision-model` on PATH.\n"
            f"       Set {_DECISION_MODEL_ENV} to the client's path to override.",
            3,
        )
    cmd = ([sys.executable, str(target)] if target.suffix == ".py" else [str(target)])
    cmd += [
        "box",
        "--image", str(args.image),
        "--target", args.target,
        "--min-present", str(args.min_present),
        "--min-confidence", str(args.min_confidence),
        "--timeout", str(args.timeout),
    ]
    if args.crop:
        cmd += ["--crop", args.crop]
    if args.json:
        cmd.append("--json")

    env = os.environ.copy()
    env["DECISION_PORT"] = str(args.port)
    if getattr(args, "host", None):
        env["DECISION_HOST"] = args.host

    if not args.json:
        return subprocess.call(cmd, env=env)
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    sys.stderr.write(proc.stderr)
    out = (proc.stdout or "").strip()
    if out:
        try:
            json.loads(out)
        except json.JSONDecodeError:
            print(f"jev box: non-JSON stdout from decision-model: {out[:400]}", file=sys.stderr)
            return 1
        print(out)
    return proc.returncode


def _context(args) -> str:
    """Facts may be inline (--context) or on disk (--context-file).

    A large context on disk costs the caller nothing: the agent never has to
    copy it into its own token stream.
    """
    if getattr(args, "context_file", None):
        try:
            return Path(args.context_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise _die(f"Error: cannot read --context-file {args.context_file}: {exc}", 2)
    return args.context


def _out(args, res: dict, compact: str) -> None:
    """Emit the result: file + pointer, JSON, or one line."""
    if getattr(args, "out", None):
        Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")
        if getattr(args, "json", False):
            print(json.dumps(res, indent=2))
        else:
            print(f"{compact.rstrip()} -> {args.out}")
    elif getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        print(compact)


def _split_options(values: list) -> list:
    """`--options a,b,c` and `--options a b c` both mean three options.

    A comma inside one token is always a separator: a single option that still
    holds commas is a typo, and reading it as one option answers 100% confident
    nonsense instead of failing.
    """
    out = []
    for value in values:
        out.extend(part.strip() for part in str(value).split(",") if part.strip())
    return out


def _check_source(args, res: dict) -> None:
    """The server is the point. Say so when it was not the one answering."""
    if res.get("source") == "heuristic_fallback":
        detail = jev_engine.LAST_ERROR
        if getattr(args, "require_server", False):
            raise _die(
                "Error: the decision server did not answer, and --require-server was given.\n"
                f"       {detail or 'Probe it with: curl -s http://127.0.0.1:'
                   + str(getattr(args, 'port', 8083)) + '/health'}",
                3,
            )
        print(
            "warning: decision server did not answer — answered with the keyword heuristic"
            + (f" ({detail})" if detail else "") + ". Pass --require-server to make this an error.",
            file=sys.stderr,
        )


def main():
    parent_parser = argparse.ArgumentParser(add_help=False)
    default_port = int(os.environ.get("JEV_PORT", os.environ.get("DECISION_PORT", "8083")))
    parent_parser.add_argument("--host", default=None, help="Decision host (default: $JEV_HOST or 127.0.0.1, supports Tailscale *.ts.net)")
    parent_parser.add_argument("--port", type=int, default=None, metavar="PORT", help=f"Decision service port (default: {default_port} = h2o-lightning-4b / gliclass-edge)")
    parent_parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parent_parser.add_argument("--out", default=None, help="Write the JSON result here and print a one-line pointer")
    parent_parser.add_argument("--require-server", action="store_true",
                               help="Fail instead of falling back to the keyword heuristic")
    parent_parser.add_argument("--no-autostart", action="store_true",
                               help="Do not auto-start the decision server (for tests / offline contexts)")

    # Subparsers re-declare the shared options with SUPPRESS so that a --port
    # given before the subcommand is not silently overwritten by the default.
    sub_parent = argparse.ArgumentParser(add_help=False)
    sub_parent.add_argument("--host", default=argparse.SUPPRESS)
    sub_parent.add_argument("--port", type=int, default=argparse.SUPPRESS, metavar="PORT")
    sub_parent.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    sub_parent.add_argument("--out", default=argparse.SUPPRESS)
    sub_parent.add_argument("--require-server", action="store_true", default=argparse.SUPPRESS)
    sub_parent.add_argument("--no-autostart", action="store_true", default=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(
        description="JEV decision engine — h2o-lightning-4b native /v1/systemone, vision-capable",
        epilog=(
            "Primitives: bool (binary), choice (constrained enum), score (0.0-1.0), "
            "composite (gate + action + quality), box (visual grounding).\n"
            "Exit codes: 0 answered · 2 usage error or gate rejection (box) · "
            "3 --require-server but no server / decision-model missing."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[parent_parser],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def context_args(p):
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--context", help="Input context or background facts")
        g.add_argument("--context-file", help="Read the context from a file (keeps it out of the agent's context)")

    # bool
    p_bool = subparsers.add_parser("bool", parents=[sub_parent], help="Binary boolean decision primitive")
    context_args(p_bool)
    p_bool.add_argument("--question", required=True, help="Binary question to decide (Yes/No)")
    p_bool.add_argument("--image", default=None, help="Optional image path or base64 data for vision decision")

    # choice
    p_choice = subparsers.add_parser("choice", parents=[sub_parent], help="Constrained discrete enum selection primitive")
    context_args(p_choice)
    p_choice.add_argument("--question", required=True, help="Question to decide")
    p_choice.add_argument("--options", nargs="+", required=True, help="Candidate options list")
    p_choice.add_argument("--image", default=None, help="Optional image path or base64 data for vision decision")

    # score
    p_score = subparsers.add_parser("score", parents=[sub_parent], help="Continuous scalar magnitude score primitive (0.0 to 1.0)")
    context_args(p_score)
    p_score.add_argument("--criteria", required=True, help="Criteria for evaluation")
    p_score.add_argument("--image", default=None, help="Optional image path or base64 data for vision decision")

    # composite
    p_comp = subparsers.add_parser("composite", parents=[sub_parent], help="Composite decision primitive (gate bool + action choice + quality score)")
    context_args(p_comp)
    p_comp.add_argument("--question", required=True, help="Question to decide")
    p_comp.add_argument("--options", nargs="+", required=True, help="Candidate options list")
    p_comp.add_argument("--criteria", default=None, help="Optional quality criteria")
    p_comp.add_argument("--image", default=None, help="Optional image path or base64 data for vision decision")

    # box — visual grounding, delegated to decision-model
    box_parent = argparse.ArgumentParser(add_help=False)
    box_parent.add_argument("--host", default=argparse.SUPPRESS)
    box_parent.add_argument("--port", type=int, default=argparse.SUPPRESS, metavar="PORT")
    box_parent.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    p_box = subparsers.add_parser(
        "box", parents=[box_parent],
        help="Visual grounding: gated bounding box in an image",
        description=(
            "Locate a phrase in an image: `box` fractions, pixel coordinates, a\n"
            "tightness confidence and a `present` probability that gates the answer.\n"
            "Delegates to `decision-model box`; the gates and the geometry client live there.\n\n"
            "Exit codes match that client: 0 accepted · 2 rejected by a gate · 1 request error."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_box.add_argument("--image", required=True, help="Image to search (PNG/JPG)")
    p_box.add_argument("--target", required=True, help="Object or phrase to locate")
    p_box.add_argument("--crop", default=None, help="Save the accepted region here (needs Pillow)")
    p_box.add_argument("--min-present", type=float, default=0.5, metavar="SCORE",
                       help="Reject below this presence probability (default: 0.5)")
    p_box.add_argument("--min-confidence", type=float, default=0.3, metavar="SCORE",
                       help="Reject below this tightness confidence (default: 0.30)")
    p_box.add_argument("--timeout", type=float, default=120.0, metavar="SECONDS",
                       help="Request timeout in seconds (default: 120)")

    # batch
    p_batch = subparsers.add_parser(
        "batch", parents=[sub_parent],
        help="Many typed questions in one request (one forward pass)",
        description=(
            "Decide several questions in a single /v1/systemone request.\n\n"
            "File format:\n"
            '  {"state": "facts the questions share",\n'
            '   "questions": {\n'
            '     "ship":   {"type": "bool",   "instructions": "Should this ship?"},\n'
            '     "target": {"type": "choice", "instructions": "Which button?",\n'
            '                "options": ["Back", "Complete purchase"]},\n'
            '     "risk":   {"type": "score",  "instructions": "How risky is this?",\n'
            '                "levels": ["none", "low", "medium", "high"]}}}\n\n'
            "`levels` is optional for score; `options` is required for choice."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_batch.add_argument("file", help="JSON file of typed questions")
    p_batch.add_argument("--image", default=None, help="Optional shared image")

    # clean-context
    p_clean = subparsers.add_parser("clean-context", parents=[sub_parent], help="Pairwise context de-duplication and superseding prune")
    p_clean.add_argument("--claims-file", required=True, help="JSON file containing array of {timestamp, text} claims")

    # doctor
    p_doc = subparsers.add_parser("doctor", parents=[sub_parent], help="Probe the decision server")

    args = parser.parse_args()
    if args.command == "box":
        args.port = args.port if getattr(args, "port", None) is not None else int(
            os.environ.get("DECISION_PORT", "8083"))
    else:
        args.port = args.port if getattr(args, "port", None) is not None else default_port
    args.json = getattr(args, "json", False)
    if getattr(args, "options", None):
        args.options = _split_options(args.options)
    engine = JevEngine(host=getattr(args, "host", None), port=args.port)

    if args.command == "doctor":
        reachable = engine.is_online()
        backend = engine.backend()
        online = backend == "systemone" and reachable
        status = "ONLINE" if online else "OFFLINE or wrong model"
        model = engine.model_name or "unknown model"
        endpoint = engine.systemone_url.rsplit('/v1/', 1)[0]
        if args.json:
            print(json.dumps({
                "status": status,
                "online": online,
                "model": model,
                "endpoint": endpoint,
                "backend": backend,
            }, indent=2))
        else:
            print(f"{status} {model} {endpoint}")
        return 0 if online else 3

    if args.command == "box":
        return _run_box(args)

    if not getattr(args, "no_autostart", False):
        ensure_decision_server(engine)

    if args.command == "bool":
        res = engine.decide_bool(_context(args), args.question, image=args.image)
        _check_source(args, res)
        _out(args, res, f"⚖️ [JEV Bool] -> {'YES' if res['decision'] else 'NO'} "
                        f"(Confidence: {res['confidence'] * 100:.1f}%) [{res['source']}]")

    elif args.command == "choice":
        res = engine.decide_choice(_context(args), args.question, args.options, image=args.image)
        _check_source(args, res)
        _out(args, res, f"🎯 [JEV Choice] -> '{res['selection']}' "
                        f"(Confidence: {res['confidence'] * 100:.1f}%) [{res['source']}]")

    elif args.command == "score":
        res = engine.decide_score(_context(args), args.criteria, image=args.image)
        _check_source(args, res)
        _out(args, res, f"📊 [JEV Score] -> {res['score']:.4f} / 1.0000 [{res['source']}]")

    elif args.command == "composite":
        res = engine.decide_composite(_context(args), args.question, args.options,
                                      criteria=args.criteria, image=args.image)
        _check_source(args, res)
        _out(args, res, f"🎛️ [JEV Composite] Gate: {'PASS' if res['gate'] else 'FAIL'} | "
                        f"Action: '{res['action']}' | Score: {res['quality_score']:.4f} [{res['source']}]")

    elif args.command == "batch":
        try:
            spec = json.loads(Path(args.file).read_text(encoding="utf-8"))
        except OSError as exc:
            raise _die(f"Error: cannot read {args.file}: {exc}", 2)
        except ValueError as exc:
            raise _die(f"Error: {args.file} is not valid JSON: {exc}", 2)
        if not isinstance(spec, dict) or "questions" not in spec:
            raise _die(
                'Error: the batch file needs a top-level "questions" object.\n'
                '       Example: {"state": "...", "questions": {"q1": {"type": "bool", '
                '"instructions": "..."}}}',
                2,
            )
        try:
            res = engine.decide_batch(str(spec.get("state", "")), spec["questions"],
                                      image=args.image)
        except ValueError as exc:
            raise _die(f"Error: {exc}", 2)
        except RuntimeError as exc:
            raise _die(f"Error: {exc}", 3)

        def _summary(v: dict) -> str:
            prim = v.get("primitive")
            if prim == "bool":
                return "YES" if v.get("decision") else "NO"
            if prim == "choice":
                return str(v.get("selection"))
            return f"{v.get('score')}"

        if args.out:
            Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"batch: {len(res)} answers -> {args.out}")
        elif args.json:
            print(json.dumps(res, indent=2))
        else:
            for qid, value in res.items():
                print(f"{qid}: {_summary(value)}")

    elif args.command == "clean-context":
        claims = json.loads(Path(args.claims_file).read_text(encoding="utf-8"))
        res = engine.clean_context_claims(claims)
        _out(args, res, f"🧹 [JEV Context Cleaner] {res['total_input_claims']} claims -> "
                        f"{res['active_claims_retained']} active, {res['superseded_count']} superseded")

    return 0


if __name__ == "__main__":
    sys.exit(main())
