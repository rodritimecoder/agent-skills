# CONTEXT.md — {{COURSE}}

Stage execution map and status for the {{COURSE}} workspace.

## Stages
1. 01_ingest/     Smart Canvas + Zoom ingestion (relevant notes only)
2. 02_sift/       Classifier triage and deduplication
3. 03_structure/  OKF v0.2 course scaffold
4. 04_render/     graph.html, anki.html, cornell.html
5. 05_verify/     Micro-gates and step_NN.json evidence

## Status
- [ ] stage1 ingest
- [ ] stage2 sift
- [ ] stage3 structure
- [ ] stage4 render
- [ ] stage5 verify

## Rules
- Run stages in order with scripts/run_pipeline.py.
- A stage is complete only when 05_verify/step_NN.json records status "ok".
- Do not claim the pipeline works until all five steps are "ok".
