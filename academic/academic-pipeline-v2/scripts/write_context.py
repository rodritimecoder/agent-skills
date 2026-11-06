#!/usr/bin/env python3
"""Write a per-stage CONTEXT.md into each working folder.

ICM expects a ``CONTEXT.md`` in every working folder: what it reads, what it
does, what it writes, and what a human must check.  No stage of this pipeline
wrote one, so this module fills the gap.

It renders ``_templates/stage-CONTEXT.md`` (inline fallback if that file is
absent) into ``workspace/0N_<name>/CONTEXT.md`` for stages 1-5. The stage
template is distinct from ``_templates/CONTEXT.md``, which is the workspace
stage map: a per-stage contract that carried the whole map would duplicate the
pipeline list once per folder.

Public API
----------
write_stage_context(workspace, stage, *, reads, writes, checks, human="",
                    overwrite=False) -> Path
run(workspace, dry_run=False, deps=None) -> dict   # step.schema.json payload

CLI
---
    python write_context.py WORKSPACE [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_contracts import (  # noqa: E402 - path set above
    STAGE_CONTRACTS,
    STAGE_NAMES,
    STAGE_TITLES,
    STAGE_STEP_TYPES,
    STEP_TYPE_ACTORS,
    proof,
)

# Folder + title are derived from the contract table, never restated here.
STAGES = {
    number: (f"{number:02d}_{STAGE_NAMES[number]}", STAGE_TITLES[number])
    for number in STAGE_NAMES
}

TEMPLATE_RELPATH = Path("_templates") / "stage-CONTEXT.md"

INLINE_TEMPLATE = """# {{FOLDER}} — {{TITLE}}

One job: produce the {{TITLE}} artefacts for stage {{STAGE}}.

**Actor:** {{ACTOR}}
**Step type:** {{STEP_TYPE}}
**Proof:** {{PROOF}}

## Inputs
{{READS}}

## Process
1. Read the inputs above. Do not load the whole workspace.
2. Produce the outputs below, following the checks in this contract.
3. Write `05_verify/step_{{STAGE_PADDED}}.json` so the step can be replayed.

## Outputs
{{WRITES}}

## Human check
{{CHECKS}}

Sign-off: {{HUMAN}}
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _bullet(items):
    """Render a list of strings as a markdown bullet list."""
    if isinstance(items, str):
        items = [items]
    items = [str(i).strip() for i in (items or []) if str(i).strip()]
    if not items:
        return "- _none_"
    return "\n".join(f"- `{i}`" for i in items)


def stage_dir_name(stage):
    stage = int(stage)
    if stage not in STAGES:
        raise ValueError(f"stage must be one of 1-5, got {stage!r}")
    return STAGES[stage][0]


def stage_title(stage):
    stage = int(stage)
    if stage not in STAGES:
        raise ValueError(f"stage must be one of 1-5, got {stage!r}")
    return STAGES[stage][1]


def _find_template(workspace):
    """Locate _templates/CONTEXT.md: inside the workspace, then beside it."""
    candidates = [
        Path(workspace) / TEMPLATE_RELPATH,
        Path(__file__).resolve().parent.parent / TEMPLATE_RELPATH,
        Path(__file__).resolve().parent / TEMPLATE_RELPATH,
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def render_context(
    template_text,
    stage,
    title,
    reads,
    writes,
    checks,
    human="",
    actor="agent",
    step_type="P",
    proof="",
):
    """Substitute the placeholders; keep stage facts in the body always."""
    folder = stage_dir_name(stage)
    human = (human or "").strip() or "_to be confirmed by the researcher_"
    stage_number = int(stage)

    replacements = {
        "{{STAGE_PADDED}}": f"{stage_number:02d}",
        "{{STAGE}}": str(stage),
        "{{TITLE}}": title,
        "{{FOLDER}}": folder,
        "{{COURSE}}": f"stage {stage} ({title})",
        "{{READS}}": _bullet(reads),
        "{{WRITES}}": _bullet(writes),
        "{{CHECKS}}": _bullet(checks),
        "{{HUMAN}}": human,
        "{{ACTOR}}": actor,
        "{{STEP_TYPE}}": step_type,
        "{{PROOF}}": proof or f"05_verify/step_{stage_number:02d}.json",
    }

    text = template_text
    had_stage = "{{STAGE}}" in text
    had_sections = "{{READS}}" in text or "{{WRITES}}" in text
    for key, value in replacements.items():
        text = text.replace(key, value)

    parts = []
    if not had_stage:
        parts.append(f"# CONTEXT - Stage {stage}: {title}\n\nFolder: `{folder}`")
    body = text.rstrip("\n")
    # Only drop the template's H1 when we prepended our own stage heading.
    if not had_stage and body.lstrip().startswith("# "):
        body = "\n".join(body.splitlines()[1:]).lstrip("\n")
    parts.append(body)
    if not had_sections:
        parts.append(
            f"**Actor:** {actor}\n"
            f"**Step type:** {step_type}\n"
            f"**Proof:** {replacements['{{PROOF}}']}\n\n"
            "## Inputs\n"
            f"{_bullet(reads)}\n\n"
            "## Process\n"
            f"1. Produce the stage {stage} artefacts.\n\n"
            "## Outputs\n"
            f"{_bullet(writes)}\n\n"
            "## Human check\n"
            f"{_bullet(checks)}\n\n"
            f"Sign-off: {human}"
        )
    body = "\n\n".join(parts)
    if not body.endswith("\n"):
        body += "\n"
    return body


def write_stage_context(
    workspace,
    stage,
    *,
    reads,
    writes,
    checks,
    human="",
    actor="agent",
    step_type="P",
    proof="",
    overwrite=False,
):
    """Render CONTEXT.md into ``workspace/0N_<name>/CONTEXT.md``.

    Refuses to clobber an existing file unless ``overwrite=True``.
    Returns the Path written.
    """
    workspace = Path(workspace)
    stage = int(stage)
    folder = stage_dir_name(stage)
    title = stage_title(stage)

    target_dir = workspace / folder
    target = target_dir / "CONTEXT.md"

    if target.exists() and not overwrite:
        raise FileExistsError(
            f"{target} already exists; pass overwrite=True to replace it"
        )

    tmpl = _find_template(workspace)
    template_text = tmpl.read_text(encoding="utf-8") if tmpl else INLINE_TEMPLATE

    body = render_context(
        template_text,
        stage,
        title,
        reads,
        writes,
        checks,
        human,
        actor=actor,
        step_type=step_type,
        proof=proof,
    )

    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


# --------------------------------------------------------------------------
# Step-runner entry point (payload valid against contracts/step.schema.json)
# --------------------------------------------------------------------------
def default_spec(stage):
    """Reads/writes/checks plus the three contract fields, from the one table."""
    stage = int(stage)
    entry = STAGE_CONTRACTS[stage]
    step_kind = STAGE_STEP_TYPES[stage]
    return {
        "reads": list(entry["reads"]),
        "writes": list(entry["writes"]),
        "checks": list(entry["checks"]),
        "human": "Confirm scope and listed reads before running the stage.",
        "actor": STEP_TYPE_ACTORS[step_kind],
        "step_type": step_kind,
        "proof": proof(stage),
    }


def run(workspace, dry_run=False, deps=None):
    """Write CONTEXT.md for stages 1-5; return a step.schema.json payload."""
    workspace = Path(workspace)
    started_at = _now()
    outputs = []
    evidence = []
    errors = []

    for stage in sorted(STAGES):
        spec = default_spec(stage)
        target = workspace / stage_dir_name(stage) / "CONTEXT.md"
        try:
            if target.exists():
                outputs.append(str(target))
                evidence.append(f"stage{stage}: context kept (already present)")
                continue
            if dry_run:
                outputs.append(str(target))
                evidence.append(f"stage{stage}: would write {target}")
                continue
            path = write_stage_context(
                workspace,
                stage,
                reads=spec["reads"],
                writes=spec["writes"],
                checks=spec["checks"],
                human=spec["human"],
                actor=spec["actor"],
                step_type=spec["step_type"],
                proof=spec["proof"],
                overwrite=False,
            )
            outputs.append(str(path))
            evidence.append(f"stage{stage}: wrote {path}")
        except Exception as exc:  # noqa: BLE001 - serialize as step evidence
            errors.append(f"stage{stage}: {exc}")
            evidence.append(f"stage{stage}: failed - {exc}")

    missing = [
        str(workspace / stage_dir_name(s) / "CONTEXT.md")
        for s in sorted(STAGES)
        if not (workspace / stage_dir_name(s) / "CONTEXT.md").is_file()
    ]
    status = "ok" if not errors and not missing else "failed"
    if dry_run and not errors:
        status = "ok"

    return {
        "stage": 5,
        "stage_name": "verify",
        "step_type": "D",
        "status": status,
        "started_at": started_at,
        "finished_at": _now(),
        "inputs": {
            "workspace": str(workspace),
            "template": str(_find_template(workspace) or "<inline fallback>"),
            "dry_run": bool(dry_run),
        },
        "outputs": outputs,
        "evidence": evidence,
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write per-stage CONTEXT.md files")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    payload = run(args.workspace, dry_run=args.dry_run)
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
