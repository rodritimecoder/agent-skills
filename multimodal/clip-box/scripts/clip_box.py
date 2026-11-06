#!/usr/bin/env python3
"""clip-box — the "where is it" front door to decision-model's box primitive.

The routing vocabulary is different from the decision vocabulary ("where is
the total amount on this receipt" is not "should I approve this refund"), so
this stays its own entry point. The implementation does not: the gates, the
crop and the exit codes live in decision-model, which also owns the shim that
answers the box question.

    clip-box --image receipt.png --target "the total amount"
    clip-box --image scene.png --target "the red square" --json --crop out.png
    clip-box --image scene.png --target "the red square" --port 8761

Exit codes: 0 accepted, 2 rejected by a gate, 1 request error.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[3] / "hardware" / "decision-model" / "scripts" / "decision_model.py"
DEFAULT_PORT = int(os.environ.get("BOX_PORT", os.environ.get("DECISION_PORT", 8083)))
DEFAULT_HOST = os.environ.get("DECISION_HOST", "127.0.0.1")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clip-box",
        description="Locate a referring phrase in an image and return a gated bounding box.",
        epilog="Exit codes: 0 accepted, 2 rejected by a gate, 1 request error.",
    )
    parser.add_argument("--image", required=True, help="Image to search")
    parser.add_argument("--target", required=True, help="Object or phrase to locate")
    parser.add_argument("--crop", help="Save the accepted region to this path (needs Pillow)")
    parser.add_argument("--min-present", type=float, default=0.5, metavar="SCORE",
                        help="Reject below this presence probability (default: %(default)s)")
    parser.add_argument("--min-confidence", type=float, default=0.3, metavar="SCORE",
                        help="Reject below this tightness confidence (default: %(default)s)")
    parser.add_argument("--timeout", type=float, default=30.0, metavar="TIMEOUT",
                        help="Request timeout in seconds (default: %(default)s)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, metavar="PORT",
                        help="Decision/box port (default: %(default)s)")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help="Decision host (default: %(default)s)")
    parser.add_argument("--json", action="store_true",
                        help="Emit one JSON object on stdout, nothing else")
    return parser


def split(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    """Lift transport flags out of a raw argv and into the environment.

    Kept for wrappers that forward an argv verbatim instead of parsing it; the
    CLI itself builds the same environment from --port/--host.
    """
    env: dict[str, str] = {}
    rest: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ("--port", "--host") and index + 1 < len(argv):
            env["BOX_PORT" if token == "--port" else "DECISION_HOST"] = argv[index + 1]
            index += 2
            continue
        if token.startswith(("--port=", "--host=")):
            name, value = token.split("=", 1)
            env["BOX_PORT" if name == "--port" else "DECISION_HOST"] = value
            index += 1
            continue
        rest.append(token)
        index += 1
    return env, rest


def command(args: argparse.Namespace) -> list[str]:
    """The `decision-model box` invocation this front door stands for."""
    cmd = [
        sys.executable, str(TARGET), "box",
        "--image", args.image,
        "--target", args.target,
        "--min-present", str(args.min_present),
        "--min-confidence", str(args.min_confidence),
        "--timeout", str(args.timeout),
    ]
    if args.crop:
        cmd += ["--crop", args.crop]
    if args.json:
        cmd.append("--json")
    return cmd


def run(args: argparse.Namespace, env: dict[str, str]) -> int:
    if args.json:
        proc = subprocess.run(command(args), env=env, capture_output=True, text=True)
        sys.stderr.write(proc.stderr)
        out = proc.stdout.strip()
        if out:
            try:
                json.loads(out)
            except json.JSONDecodeError:
                print(f"clip-box: non-JSON stdout from decision-model: {out[:400]}", file=sys.stderr)
                return 1
            print(out)
        return proc.returncode
    return subprocess.call(command(args), env=env)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not TARGET.is_file():
        print(f"clip-box: decision-model is not installed at {TARGET}", file=sys.stderr)
        return 1
    env = os.environ.copy()
    env["BOX_PORT"] = str(args.port)
    env["DECISION_HOST"] = args.host
    return run(args, env)


if __name__ == "__main__":
    sys.exit(main())
