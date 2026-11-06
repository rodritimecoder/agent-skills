# AGENTS.md — {{COURSE}}

Workspace routing for the {{COURSE}} academic pipeline run.

## What this workspace is
- Text-first ingestion → sift → OKF v0.2 structure → three HTML outputs.
- One course per workspace. Course name: {{COURSE}}.

## Folder map
- 01_ingest/  raw markdown + transcripts + meta.json
- 02_sift/    sift_report.json + cleaned notes
- 03_structure/  OKF v0.2 course scaffold
- 04_render/  graph.html, anki.html, cornell.html
- 05_verify/  step_NN.json evidence

## Routing rules
- Stage work stays in its numbered folder; do not edit other stages.
- 02_index/ and step_NN.json are generated; never hand-edit.
- If a file is STALE, stop and report before acting.

## Status rules
- This workspace is DRAFT unless 05_verify/step_05.json has status "ok".
- Not this workspace: anything outside {{COURSE}}.
