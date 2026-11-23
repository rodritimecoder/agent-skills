#!/usr/bin/env python3
"""Real-path discovery mutant for the routing gate's hard legs.

Copies the bundled ``exec_only_flow.py`` hard-leg script into a tempdir, mutates
the copy so it reliably exits 1 with a clear marker, points
``ROUTING_GATE_EXEC_ONLY_FLOW`` at the mutant, and runs the REAL gate as a
subprocess from ROOT. Asserts the gate exits 1 and its failure names the leg.
Also runs a clean gate with no overrides and asserts exit 0.

No canonical file is mutated and every write stays inside a TemporaryDirectory.

    python3 tests/discovery_mutant.py            # standalone
    from tests.discovery_mutant import run_discovery_mutant   # from a test
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

SOURCE_LEG = "exec_only_flow.py"
LEG_NAME = "exec_only_flow"
MARKER = "DISCOVERY_MUTANT_EXEC_ONLY_RED"
OVERRIDE = "ROUTING_GATE_EXEC_ONLY_FLOW"
ALL_OVERRIDES = (
    "ROUTING_GATE_EXEC_ONLY_FLOW",
    "ROUTING_GATE_SKILLS_BRIDGE_FLOW",
    "ROUTING_GATE_OVERFIT_CHECK",
    "ROUTING_GATE_DOC_DRIFT_CHECK",
)


def mutated_source(source_text: str) -> str:
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
        "\nimport sys as _discovery_mutant_sys\n",
        f"_discovery_mutant_sys.stdout.write({MARKER!r} + '\\n')\n",
        "_discovery_mutant_sys.exit(1)\n",
    ]
    return "".join(lines[:insert_at] + injected + lines[insert_at:])


def write_mutant(tmp: Path) -> Path:
    """Copy the canonical hard leg into tmp, then mutate only the copy."""
    source = HERE / SOURCE_LEG
    if not source.exists():
        raise RuntimeError(f"bundled hard leg missing: {source}")
    copied = tmp / SOURCE_LEG
    shutil.copy2(source, copied)                 # real script, copied verbatim
    mutated = mutated_source(copied.read_text(encoding="utf-8"))
    copied.write_text(mutated, encoding="utf-8")  # mutation stays in the tempdir
    if MARKER not in copied.read_text(encoding="utf-8"):
        raise RuntimeError("failed to inject the discovery mutant marker")
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


def run_discovery_mutant() -> dict:
    """Return observable results and assert the hard-leg red/green contract."""
    with tempfile.TemporaryDirectory(prefix="routing-gate-mutant-") as td:
        mutant = write_mutant(Path(td))

        # 1. The copied+muted leg is a reliable RED on its own.
        direct = subprocess.run(
            [sys.executable, str(mutant)],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        direct_ok = direct.returncode == 1 and MARKER in direct.stdout

        # 2. The REAL gate goes RED through the env override, naming the leg.
        gated = run_gate({OVERRIDE: str(mutant)})

        # 3. The REAL gate with no overrides stays GREEN.
        clean = run_gate({})

    gate_out = f"{gated.stdout}\n{gated.stderr}"
    result = {
        "mutant_script": str(mutant),
        "direct_exit": direct.returncode,
        "direct_marked_red": direct_ok,
        "mutant_exit": gated.returncode,
        "mutant_names_leg": LEG_NAME in gate_out,
        "mutant_output": gate_out.strip(),
        "clean_exit": clean.returncode,
        "clean_output": f"{clean.stdout}\n{clean.stderr}".strip(),
    }

    if not result["direct_marked_red"]:
        raise AssertionError(
            f"mutant leg did not exit 1 with marker {MARKER}: "
            f"exit={direct.returncode} stdout={direct.stdout!r} stderr={direct.stderr!r}"
        )
    if result["mutant_exit"] != 1:
        raise AssertionError(f"mutant gate expected exit 1, got {result['mutant_exit']}: {gate_out}")
    if not result["mutant_names_leg"]:
        raise AssertionError(f"mutant gate failure did not name {LEG_NAME!r}: {gate_out}")
    if result["clean_exit"] != 0:
        raise AssertionError(f"clean gate expected exit 0, got {result['clean_exit']}: {result['clean_output']}")
    return result


def main() -> int:
    try:
        result = run_discovery_mutant()
    except Exception as exc:
        print(f"discovery_mutant: FAIL | {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        "discovery_mutant: PASS | "
        f"leg exit={result['direct_exit']} marked={result['direct_marked_red']} | "
        f"mutant gate exit={result['mutant_exit']} names {LEG_NAME}={result['mutant_names_leg']} | "
        f"clean gate exit={result['clean_exit']} | writes confined to tempdir"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
