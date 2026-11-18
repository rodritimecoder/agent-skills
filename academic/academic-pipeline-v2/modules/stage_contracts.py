#!/usr/bin/env python3
"""The one stage contract table for academic-pipeline-v2.

Every fact about a stage lives here and nowhere else: its folder name, title,
step type, and what it reads, writes and must be checked for. ``run_pipeline``
dispatches from it, ``write_context`` renders it into each stage's CONTEXT.md,
and nothing keeps a second copy.

Step types: ``D`` deterministic code, ``P`` probabilistic model call, ``H``
human in the loop. The actor is derived, not stored twice.
"""

from __future__ import annotations

STAGE_NAMES = {
    1: "ingest",
    2: "sift",
    3: "structure",
    4: "render",
    5: "verify",
}

STAGE_TITLES = {
    1: "Ingest",
    2: "Sift",
    3: "Structure",
    4: "Render",
    5: "Verify",
}

VALID_STEP_TYPES = ("D", "P", "H")

STEP_TYPE_ACTORS = {"D": "code", "P": "agent", "H": "human"}

STAGE_STEP_TYPES = {
    1: "P",  # ingest: model triage of canvas items and recordings
    2: "P",  # sift: markdown classifier
    3: "D",  # structure: pure code, no model calls
    4: "D",  # render: pure templating, no model calls
    5: "P",  # verify: fresh-context judge (skipped, not downgraded, if absent)
}

STAGE_CONTRACTS = {
    1: {
        "reads": [
            "Canvas items for weeks 1-12 (canvas-cli)",
            "Zoom recordings: transcripts + slide keyframes only (zoom-recorder)",
            "01_ingest/meta.json (existing constellation nodes, merged)",
        ],
        "writes": [
            "01_ingest/meta.json (contracts/meta.schema.json)",
            "01_ingest/markdown/Week_NN/*.md",
            "01_ingest/transcripts/Week_NN/*.vtt",
            "01_ingest/CONTEXT.md",
        ],
        "checks": [
            "meta.json validates against contracts/meta.schema.json",
            "asset doctor: MIME types and Zoom passcode presence",
            "scope check: weeks 1-12 only",
            "orientation, admin fluff, empty announcements and quiz "
            "administration are dropped before download",
            "full Zoom video is never downloaded",
        ],
    },
    2: {
        "reads": [
            "01_ingest/**/*.md (ingested lecture and tutorial markdown)",
        ],
        "writes": [
            "02_sift/sift_report.json (contracts/sift_report.schema.json)",
            "02_sift/cleaned/**/*.md",
            "02_sift/CONTEXT.md",
        ],
        "checks": [
            "sift_report.json validates against contracts/sift_report.schema.json",
            "every item routes to keep, review or drop",
            "confidence is within 0..1 and honours the classifier floor",
            "duplicate fingerprints are dropped, not reclassified",
            "markdown and KaTeX fences are balanced",
        ],
    },
    3: {
        "reads": [
            "01_ingest/meta.json (contracts/meta.schema.json)",
            "02_sift/sift_report.json (contracts/sift_report.schema.json)",
            "02_sift/cleaned/**/*.md",
        ],
        "writes": [
            "03_structure/<course>/01_weeks/Week_NN/topic.md",
            "03_structure/<course>/01_weeks/Week_NN/tutorial.md",
            "03_structure/<course>/02_index/index.md",
            "03_structure/<course>/03_state/.agent_state.json",
            "03_structure/<course>/03_state/STATE.md",
            "03_structure/CONTEXT.md",
        ],
        "checks": [
            "OKF v0.2 layout: 01_weeks/, 02_index/, 03_state/, _templates/",
            "02_index/index.md lists every week directory",
            "one home per fact: links over copies",
            "no write escapes the workspace root",
        ],
    },
    4: {
        "reads": [
            "01_ingest/meta.json (contracts/meta.schema.json)",
            "02_sift/cleaned/**/*.md",
        ],
        "writes": [
            "04_render/graph.html",
            "04_render/anki.html",
            "04_render/cornell.html",
            "04_render/CONTEXT.md",
        ],
        "checks": [
            "each page is standalone: inline CSS/JS, no external script src",
            "graph nodes match the weeks and nodes in meta.json",
            "links and anchors resolve inside each page",
            "pages open offline and print cleanly",
        ],
    },
    5: {
        "reads": [
            "01_ingest/meta.json",
            "02_sift/**/*.md and 02_sift/sift_report.json",
            "03_structure/<course>/ (01_weeks/, 02_index/index.md)",
            "04_render/graph.html, anki.html, cornell.html",
        ],
        "writes": [
            "05_verify/step_05.json",
            "05_verify/CONTEXT.md",
        ],
        "checks": [
            "gate1_assets: meta.json validates against contracts/meta.schema.json",
            "gate2_sift: markdown/KaTeX balance and confidence floor",
            "gate3_okf: index.md lists every week directory",
            "gate4_render: three standalone HTML pages present",
            "gate5_judge: fresh-context judge accepts the final sample",
        ],
    },
}


def folder(stage):
    """``02_sift`` for stage 2."""
    stage = int(stage)
    return f"{stage:02d}_{STAGE_NAMES[stage]}"


def title(stage):
    return STAGE_TITLES[int(stage)]


def step_type(stage):
    return STAGE_STEP_TYPES[int(stage)]


def actor(stage):
    return STEP_TYPE_ACTORS[step_type(stage)]


def proof(stage):
    """The artifact that proves the step ran: its serialized ledger entry."""
    return f"05_verify/step_{int(stage):02d}.json"


def contract(stage):
    """Reads / writes / checks plus the three contract fields, for one stage."""
    stage = int(stage)
    entry = STAGE_CONTRACTS[stage]
    return {
        "reads": list(entry["reads"]),
        "writes": list(entry["writes"]),
        "checks": list(entry["checks"]),
        "actor": actor(stage),
        "step_type": step_type(stage),
        "proof": proof(stage),
    }
