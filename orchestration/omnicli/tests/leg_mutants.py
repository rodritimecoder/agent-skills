#!/usr/bin/env python3
"""Real-mutant library for the routing gate's two remaining hard legs.

``discovery_mutant.py`` already proves ``exec_only_flow``. This module does the
same for ``skills_bridge_flow`` and ``doc_drift``: each bundled leg
script is copied verbatim into a TemporaryDirectory, an unconditional marked
exit-1 is spliced in just after its ``__future__`` import, and the REAL gate is
run as a subprocess from ROOT with that leg's env override pointed at the temp
copy. The gate must go RED and name the leg; a clean gate (no overrides) must
stay GREEN.

No canonical file is mutated and every write stays inside a TemporaryDirectory.

    python3 tests/leg_mutants.py                    # standalone
    from tests.leg_mutants import run_leg_mutant    # from a test
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]              # tests -> omnicli -> orchestration -> repo
GATE = HERE / "routing_gate.py"

# The two legs NOT covered by discovery_mutant.py. Keys are the gate's own
# HARD_LEGS names (the strings decide() uses to name a failing leg).
LEGS: dict[str, dict[str, str]] = {
    "skills_bridge_flow": {
        "source": "skills_bridge_flow.py",
        "override": "ROUTING_GATE_SKILLS_BRIDGE_FLOW",
        "marker": "LEG_MUTANT_SKILLS_BRIDGE_FLOW_RED",
    },
    "doc_drift": {
        "source": "doc_drift_check.py",
        "override": "ROUTING_GATE_DOC_DRIFT_CHECK",
        "marker": "LEG_MUTANT_DOC_DRIFT_RED",
    },
}

ALL_OVERRIDES = (
    "ROUTING_GATE_EXEC_ONLY_FLOW",
    "ROUTING_GATE_SKILLS_BRIDGE_FLOW",
    "ROUTING_GATE_DOC_DRIFT_CHECK",
)


def mutated_source(source_text: str, marker: str) -> str:
    """Splice an unconditional, marked exit-1 into a copy of a real hard leg."""
    lines = source_text.splitlines(keepends=True)
    future_idx = [i for i, line in enumerate(lines)
                  if line.startswith("from __future__ import ")]
    if future_idx:
        insert_at = future_idx[-1] + 1
    else:
        insert_at = 1 if lines and lines[0].startswith("#!") else 0
        if insert_at < len(lines) and lines[insert_at].lstrip().startswith(('"""', "'''")):
            quote = lines[insert_at].lstrip()[:3]
            j = insert_at + 1
            if lines[insert_at].count(quote) < 2:
                while j < len(lines) and quote not in lines[j]:
                    j += 1
                j += 1
            insert_at = j
    injected = [
        "\nimport sys as _leg_mutant_sys\n",
        f"_leg_mutant_sys.stdout.write({marker!r} + '\\n')\n",
        "_leg_mutant_sys.stdout.flush()\n",
        "_leg_mutant_sys.exit(1)\n",
    ]
    return "".join(lines[:insert_at] + injected + lines[insert_at:])


def write_mutant(tmp: Path, cfg: dict[str, str]) -> Path:
    """Copy the canonical hard leg into tmp, then mutate only the copy."""
    source = HERE / cfg["source"]
    if not source.exists():
        raise RuntimeError(f"bundled hard leg missing: {source}")
    copied = tmp / cfg["source"]
    shutil.copy2(source, copied)                 # real script, copied verbatim
    mutated = mutated_source(copied.read_text(encoding="utf-8"), cfg["marker"])
    copied.write_text(mutated, encoding="utf-8")  # mutation stays in the tempdir
    if cfg["marker"] not in copied.read_text(encoding="utf-8"):
        raise RuntimeError("failed to inject the leg mutant marker")
    return copied


def run_gate(overrides: dict[str, str] | None) -> subprocess.CompletedProcess:
    """Run the real gate from ROOT with a clean override baseline."""
    env = os.environ.copy()
    for name in ALL_OVERRIDES:
        env.pop(name, None)
    if overrides:
        env.update(overrides)
    return subprocess.run(
        [sys.executable, str(GATE)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=600,
    )


def run_leg_mutant(name: str) -> dict:
    """Run one real leg mutant and assert the red/green contract; return facts.

    Raises AssertionError if the mutant is not a reliable RED, if the gate does
    not go RED naming the leg, or if the clean gate is not GREEN.
    """
    if name not in LEGS:
        raise ValueError(f"unknown leg {name!r}; expected one of {sorted(LEGS)}")
    cfg = LEGS[name]
    marker = cfg["marker"]
    failure_line = f"{name} leg failed"

    with tempfile.TemporaryDirectory(prefix="routing-gate-leg-mutant-") as td:
        mutant = write_mutant(Path(td), cfg)

        # 1. The copied+mutated leg is a reliable RED on its own. Checking here
        #    keeps `marked` uniform across both legs (doc_drift's JSON
        #    result path does not surface the marker in the gate's output).
        direct = subprocess.run(
            [sys.executable, str(mutant)],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        marked = direct.returncode == 1 and marker in direct.stdout

        # 2. The REAL gate goes RED through the env override, naming the leg.
        gated = run_gate({cfg["override"]: str(mutant)})

        # 3. The REAL gate with no overrides stays GREEN.
        clean = run_gate({})

    gate_out = f"{gated.stdout}\n{gated.stderr}"
    clean_out = f"{clean.stdout}\n{clean.stderr}"
    result = {
        "leg": name,
        "mutant_exit": gated.returncode,
        "marked": marked,
        "gate_red": gated.returncode == 1,
        "leg_named": failure_line in gate_out,
        "clean_gate_exit": clean.returncode,
        "ok": False,
    }

    if not marked:
        raise AssertionError(
            f"{name}: mutant did not exit 1 with marker {marker}: "
            f"exit={direct.returncode} stdout={direct.stdout!r} stderr={direct.stderr!r}"
        )
    if not result["gate_red"]:
        raise AssertionError(
            f"{name}: mutant gate expected exit 1, got {result['mutant_exit']}: {gate_out}"
        )
    if not result["leg_named"]:
        raise AssertionError(f"{name}: mutant gate failure did not name {failure_line!r}: {gate_out}")
    if result["clean_gate_exit"] != 0:
        raise AssertionError(
            f"{name}: clean gate expected exit 0, got {result['clean_gate_exit']}: {clean_out}"
        )

    result["ok"] = True
    return result


def main() -> int:
    results: list[dict] = []
    try:
        for name in LEGS:
            results.append(run_leg_mutant(name))
    except Exception as exc:
        bad = results[-1]["leg"] if results else "init"
        print(
            f"leg_mutants: FAIL | {bad}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    parts = [
        f"{r['leg']} red={r['gate_red']} marked={r['marked']} named={r['leg_named']}"
        for r in results
    ]
    print(
        "leg_mutants: PASS | " + ", ".join(parts)
        + f" | clean gate exit={results[0]['clean_gate_exit']}"
        + " | writes confined to tempdir"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
