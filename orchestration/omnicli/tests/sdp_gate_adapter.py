#!/usr/bin/env python3
"""SDP_GATE blind-holdout adapter backed by the real ``routing_gate.py``.

Protocol:
  --describe                       -> {"legs":[4 names],"advisory":false,"bm25":false}
  --run [--override NAME=STATE]    -> JSON verdict on stdout, exit 0 green / 1 red

``NAME`` is one of the gate's four hard legs; ``STATE`` is pass|fail|missing.
With no overrides the adapter runs the real gate (``routing_gate.check()``) and
reports its verdict. Overrides only fabricate leg results for the pure
``decide()`` function — they never skip a leg in the real gate and never touch
the catalog, bindings, traces or artifact store.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(SKILL))
from tests import routing_gate as rg  # noqa: E402

VALID_STATES = ("pass", "fail", "missing")


def describe() -> dict:
    return {
        "legs": list(rg.HARD_LEGS),
        "advisory": False,
        "bm25": False,
    }


def parse_overrides(specs: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for spec in specs:
        name, sep, state = spec.partition("=")
        if not sep or name not in rg.HARD_LEGS or state not in VALID_STATES:
            raise ValueError(
                f"bad override {spec!r}; want NAME=one of {VALID_STATES}, "
                f"NAME in {list(rg.HARD_LEGS)}"
            )
        overrides[name] = state
    return overrides


def verdict(report: dict) -> dict:
    failures = rg.decide(report)
    legs = report.get("legs", {})
    return {
        "pass": not failures,
        "legs": {name: bool(legs.get(name, {}).get("pass", False)) for name in rg.HARD_LEGS},
        "failures": failures,
    }


def run_with_overrides(overrides: dict[str, str]) -> dict:
    """Fabricate only the leg results; ``decide`` stays the real decision fn."""
    report: dict = {"legs": {}}
    for name in rg.HARD_LEGS:
        state = overrides.get(name, "pass")
        if state == "missing":
            continue  # absence is itself a red-leg signal to decide()
        report["legs"][name] = {
            "pass": state == "pass",
            "exit": 0 if state == "pass" else 1,
            "detail": f"adapter-override-{state}",
        }
    return verdict(report)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--describe", action="store_true", help="emit the gate surface as JSON")
    p.add_argument("--run", action="store_true", help="run the real gate (or overrides)")
    p.add_argument(
        "--override", action="append", default=[], metavar="NAME=STATE",
        help="fabricate one leg result: pass|fail|missing (repeatable)",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.describe:
        print(json.dumps(describe(), sort_keys=True))
        return 0
    if not args.run:
        print("error: choose --describe or --run", file=sys.stderr)
        return 2
    try:
        overrides = parse_overrides(args.override)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if overrides:
        result = run_with_overrides(overrides)
    else:
        ok, report = rg.check()
        result = verdict(report)
        result["pass"] = ok and result["pass"]
    print(json.dumps(result, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
