#!/usr/bin/env python3
"""Stage dispatcher for academic-pipeline-v2.

Each stage handler imports its lane module(s) lazily, runs them, and merges
their step payloads into ONE ``05_verify/step_NN.json`` evidence file:

    stage1 -> stage1_canvas + stage1_zoom        (one step_01.json)
    stage2 -> stage2_sift                        (one step_02.json)
    stage3 -> stage3_structure                   (one step_03.json)
    stage4 -> render_graph + render_anki +
              render_cornell                     (one step_04.json)
    stage5 -> gates                              (one step_05.json)

A missing lane module never breaks ``--help``: imports happen inside the
handlers only.  Evidence is written on success *and* failure, and the process
exits 0 only when the merged status is ``ok``.  ``--dry-run`` writes nothing.

Every written step is tagged with ``step_type`` (``D`` deterministic, ``P``
probabilistic, ``H`` human) per ``STAGE_STEP_TYPES``; see
``contracts/step.schema.json``.
"""

import argparse
import importlib
import inspect
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_contracts import (  # noqa: E402 - path set above
    STAGE_CONTRACTS,
    STAGE_NAMES,
    STAGE_STEP_TYPES,
    STEP_TYPE_ACTORS,
    VALID_STEP_TYPES,
    proof,
)

STAGE_CHOICES = ["stage1", "stage2", "stage3", "stage4", "stage5", "all"]

VALID_STATUSES = ("ok", "failed", "skipped")

# Every stage is tagged with the kind of work it performs, so a step file says
# *who* produced it: ``D`` = deterministic code, ``P`` = probabilistic model
# call, ``H`` = human.  The tag is stamped by the dispatcher, never by a lane,
# and is written on success, failure and skip alike.  Stage 5 is ``P`` because
# its final gate is a fresh-context judge; when no judge is available the tag
# stays ``P`` and the step is recorded as ``skipped``.
def _now():
    return datetime.now(timezone.utc).isoformat()


def _stage_number(name):
    return int(name[-1])


def _load_lane(module_name):
    """Import a lane module from this script's directory, lazily."""
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    return importlib.import_module(module_name)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _normalise_output(workspace, item):
    """Coerce one lane output entry into a workspace-relative POSIX path string.

    Lanes have historically emitted absolute paths and, for cornell, a dict
    ``{"path": ..., "kind": ..., "bytes": ...}``.  The step contract wants a
    flat array of workspace-relative path strings, so both shapes collapse to
    the path.  Unusable entries return ``None``.
    """
    if isinstance(item, dict):
        item = item.get("path")
    if not isinstance(item, (str, Path)):
        return None
    text = str(item).strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        root = Path(workspace).resolve()
        try:
            path = path.resolve().relative_to(root)
        except (OSError, ValueError):
            try:
                path = Path(os.path.relpath(path, root))
            except (OSError, ValueError):
                return None
    return path.as_posix()


def _normalise_outputs(workspace, items):
    """Return sorted, deduplicated workspace-relative path strings."""
    normalised = set()
    for item in items:
        rel = _normalise_output(workspace, item)
        if rel is not None:
            normalised.add(rel)
    return sorted(normalised)


def _merge_results(stage_number, started_at, parts, workspace=None):
    """Merge ``[(lane_name, payload_or_exception_text)]`` into one step payload.

    Every merged stage reports ``outputs`` as workspace-relative path strings,
    deduplicated and sorted (see :func:`_normalise_outputs`).

    Status: ``ok`` if any lane ran ok, ``skipped`` if every lane skipped,
    ``failed`` otherwise (including a lane that raised).  Stage 5 is stricter:
    a skipped gate (e.g. the missing fresh-context judge) can never be merged
    into ``ok``, so a missing check never looks green.
    """
    statuses = []
    outputs = []
    evidence = []
    errors = []
    lanes = {}
    extras = {}

    for name, result in parts:
        if not isinstance(result, dict):
            statuses.append("failed")
            errors.append(f"{name}: {result}")
            continue
        status = str(result.get("status") or "failed")
        statuses.append(status if status in VALID_STATUSES else "failed")
        if isinstance(result.get("inputs"), dict):
            lanes[name] = result["inputs"]
        outputs.extend(_as_list(result.get("outputs")))
        evidence.extend(_as_list(result.get("evidence")))
        errors.extend(str(item) for item in _as_list(result.get("errors")))
        for key, value in result.items():
            if key in ("gates", "facts", "details"):
                extras[key] = value

    if stage_number == 5:
        # A missing judge dependency must never look green: skip wins over ok.
        if "failed" in statuses:
            status = "failed"
        elif "skipped" in statuses:
            status = "skipped"
        elif statuses:
            status = "ok"
        else:
            status = "skipped"
    elif stage_number in (3, 4):
        # Structure and render are deterministic and every lane is required:
        # one renderer raising means the deliverable set is incomplete, so the
        # stage must not report ok on the strength of its siblings.
        status = "failed" if "failed" in statuses else ("ok" if statuses else "skipped")
    elif "ok" in statuses:
        status = "ok"
    elif statuses and all(item == "skipped" for item in statuses):
        status = "skipped"
    else:
        status = "failed"

    if stage_number == 5 and status == "skipped":
        # Keep the step_type (the judge is still the intended worker) and make
        # the skip explicit in the evidence, so a missing judge never reads ok.
        evidence.append(
            "stage5: step_type P retained, step recorded as skipped - "
            "no fresh-context judge supplied"
        )

    payload = {
        "stage": stage_number,
        "stage_name": STAGE_NAMES[stage_number],
        "step_type": STAGE_STEP_TYPES.get(stage_number, "D"),
        "status": status,
        "started_at": started_at,
        "finished_at": _now(),
        "inputs": {"lanes": lanes},
        "outputs": _normalise_outputs(workspace, outputs),
        "evidence": evidence,
        "errors": errors,
    }
    payload.update(extras)
    return payload


def _stamp_step_type(payload, stage_number):
    """Guarantee ``step_type`` on any payload about to be written.

    Lanes never set it; the dispatcher owns it.  This is the last line of
    defence so a step file can never be written without a contract-valid tag,
    even on the failure path.
    """
    if payload.get("step_type") not in VALID_STEP_TYPES:
        payload["step_type"] = STAGE_STEP_TYPES.get(stage_number, "D")
    return payload


def _write_step(workspace, stage_number, payload):
    """Serialize a merged step payload into 05_verify/step_NN.json."""
    step_path = Path(workspace) / "05_verify" / f"step_{stage_number:02d}.json"
    step_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _stamp_step_type(payload, stage_number)
    step_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return step_path


def _accepts(run, name):
    try:
        params = inspect.signature(run).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins/C callables
        return False
    if name in params:
        return True
    return any(p.kind is p.VAR_KEYWORD for p in params.values())


def _call(module_name, workspace, dry_run, deps=None, **kwargs):
    """Run one lane module, returning its payload (exceptions become text)."""
    try:
        module = _load_lane(module_name)
    except Exception as exc:  # noqa: BLE001 - a missing module is step evidence
        return f"cannot import {module_name}: {exc}"
    run = getattr(module, "run", None)
    if not callable(run):
        return f"{module_name}.run is not callable"

    call_kwargs = dict(kwargs)
    if _accepts(run, "dry_run"):
        call_kwargs["dry_run"] = dry_run
    elif dry_run:
        # The lane has no dry-run switch: never let it write during --dry-run.
        return {
            "status": "skipped",
            "outputs": [],
            "evidence": [f"{module_name}: skipped (no dry-run support)"],
            "errors": [],
        }
    if "deps" not in call_kwargs and _accepts(run, "deps"):
        call_kwargs["deps"] = deps

    try:
        return run(workspace, **call_kwargs)
    except Exception as exc:  # noqa: BLE001 - serialize as evidence
        return f"{module_name}.run raised: {exc}"


def _run_lanes(workspace, dry_run, lanes):
    """Run ``[(name, kwargs)]`` and return merged payload parts."""
    parts = []
    for name, kwargs in lanes:
        parts.append((name, _call(name, workspace, dry_run, **kwargs)))
    return parts


def _write_stage_context(workspace, stage_number, dry_run):
    """Write ``0N_<name>/CONTEXT.md`` before the stage dispatches.

    ``--dry-run`` must leave the workspace untouched, so it writes nothing.
    Re-runs refresh the file (``overwrite=True``) rather than failing on the
    CONTEXT.md left by a previous run.
    """
    if dry_run:
        return None
    contract = STAGE_CONTRACTS[stage_number]
    module = _load_lane("write_context")
    return module.write_stage_context(
        workspace,
        stage_number,
        reads=contract["reads"],
        writes=contract["writes"],
        checks=contract["checks"],
        actor=STEP_TYPE_ACTORS[STAGE_STEP_TYPES[stage_number]],
        step_type=STAGE_STEP_TYPES[stage_number],
        proof=proof(stage_number),
        overwrite=True,
    )


def stage1(workspace, dry_run=False, real=False, course_id=None):
    _write_stage_context(workspace, 1, dry_run)
    deps = _real_stage1_deps(workspace, course_id) if real else {}
    return _run_lanes(
        workspace,
        dry_run,
        [("stage1_canvas", {"deps": deps}), ("stage1_zoom", {"deps": deps})],
    )


def stage2(workspace, dry_run=False, real=False, course_id=None):
    _write_stage_context(workspace, 2, dry_run)
    deps = {}
    if real:
        adapters = _load_lane("adapters")
        deps = adapters.stage2_deps(workspace)
    return _run_lanes(workspace, dry_run, [("stage2_sift", {"deps": deps})])


def stage3(workspace, dry_run=False, real=False, course_id=None):
    _write_stage_context(workspace, 3, dry_run)
    return _run_lanes(workspace, dry_run, [("stage3_structure", {})])


def stage4(workspace, dry_run=False, real=False, course_id=None):
    _write_stage_context(workspace, 4, dry_run)
    return _run_lanes(
        workspace,
        dry_run,
        [("render_graph", {}), ("render_anki", {}), ("render_cornell", {})],
    )


def stage5(workspace, dry_run=False, real=False, course_id=None):
    """Verify: four disk gates plus the fresh-context judge.

    The judge is opt-in.  Set ``PIPELINE_CLI_JUDGE=1`` to wire
    ``gates.cli_judge`` (the opencode CLI) into the gate; without it the judge
    gate is skipped, which is what tests and offline runs rely on.
    """
    _write_stage_context(workspace, 5, dry_run)
    deps = {}
    if os.environ.get("PIPELINE_CLI_JUDGE", "").strip().lower() in ("1", "true", "yes"):
        deps["use_cli_judge"] = True
    return _run_lanes(workspace, dry_run, [("gates", {"deps": deps})])


def _real_stage1_deps(workspace, course_id):
    """Build live Canvas + Zoom dependencies, failing loudly when unconfigured."""
    if not course_id:
        raise ValueError("--real needs --course-id <canvas course id>")
    adapters = _load_lane("adapters")
    return adapters.stage1_deps(workspace, course_id)


STAGE_FUNCTIONS = {
    1: stage1,
    2: stage2,
    3: stage3,
    4: stage4,
    5: stage5,
}


def _run_one(workspace, stage_number, dry_run=False, real=False, course_id=None):
    """Run one stage and always write step_NN.json evidence (unless dry run)."""
    started_at = _now()
    try:
        parts = STAGE_FUNCTIONS[stage_number](
            workspace, dry_run=dry_run, real=real, course_id=course_id
        )
        payload = _merge_results(stage_number, started_at, parts, workspace=workspace)
        payload["evidence"].insert(
            0,
            "deps: live adapters (canvas-cli, zoom-recorder, markitdown-cli, jev)"
            if real
            else "deps: none supplied (dependency-injected default)",
        )
    except Exception as exc:  # noqa: BLE001 - serialize any failure as evidence
        payload = {
            "stage": stage_number,
            "stage_name": STAGE_NAMES[stage_number],
            "step_type": STAGE_STEP_TYPES.get(stage_number, "D"),
            "status": "failed",
            "started_at": started_at,
            "finished_at": _now(),
            "inputs": {"workspace": str(Path(workspace).resolve())},
            "outputs": [],
            "evidence": [],
            "errors": [str(exc)],
        }

    if not dry_run:
        try:
            _write_step(workspace, stage_number, payload)
        except OSError as exc:
            payload["status"] = "failed"
            payload["errors"] = list(payload.get("errors") or []) + [
                f"cannot write step file: {exc}"
            ]

    status = payload["status"]
    message = (
        f"stage{stage_number} ({STAGE_NAMES[stage_number]}): {status}"
    )
    if status == "ok":
        print(message)
    else:
        detail = "; ".join(payload.get("errors") or [])
        print(f"{message}{' - ' + detail if detail else ''}", file=sys.stderr)
    return status == "ok"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="run_pipeline.py",
        description="Academic Notes Pipeline v2 stage dispatcher.",
    )
    parser.add_argument(
        "stage",
        choices=STAGE_CHOICES,
        help="stage to run: stage1..stage5, or all",
    )
    parser.add_argument(
        "--workspace",
        default="./workspace",
        help="course workspace directory (default: ./workspace)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the stages that would run without dispatching or writing evidence",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="wire live dependencies (canvas-cli, zoom-recorder, markitdown-cli, jev)",
    )
    parser.add_argument(
        "--course-id",
        default=None,
        help="Canvas course id for --real (required with --real)",
    )
    args = parser.parse_args(argv)

    workspace = Path(args.workspace)
    if not workspace.is_dir():
        parser.error(f"workspace does not exist: {workspace}")
    if args.real and not args.course_id:
        parser.error("--real needs --course-id")

    if args.stage == "all":
        stage_numbers = [1, 2, 3, 4, 5]
    else:
        stage_numbers = [_stage_number(args.stage)]

    if args.dry_run:
        for number in stage_numbers:
            print(f"would run stage{number} ({STAGE_NAMES[number]}) in {workspace}")
        return 0

    for number in stage_numbers:
        if not _run_one(
            workspace,
            number,
            real=args.real,
            course_id=args.course_id,
        ):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
