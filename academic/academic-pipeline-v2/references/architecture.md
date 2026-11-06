# Academic Notes Pipeline v2 — Plan

**Status:** Draft plan (no code yet), revised per feedback and per the 2026-10-25 audit corrections. This document plans to supersede v1 `academic-icm` for structuring + render **after v2 passes its own gates**; v1 remains the live implementation until then.
**Goal:** Text-first ingestion (Canvas + Zoom) → parallel classifier sifting → ICM/Kem-structured corpus → three focused HTML outputs.
**Principle:** Clean upstream, render downstream. Poison sits upstream. Code decides wherever it can.

## 1. Why v2

v1 (`academic-icm`) grew into a monolith: one `viz.html` cosmos + one `study.html` + `cornell_index.html`, all entangled, with `CURRICULUM_TREE.md` retired mid-flight and stale source paths everywhere. Quality felt "mid" because filtering happened downstream and the render surface tried to do everything. `CURRICULUM_TREE.md` specifically was bad (manual, drift-prone) — replace with OKF v0.2.

v2 plans to invert that: sift cheaply and early with classifiers, keep structure in folders (ICM), and ship **three small, single-purpose HTMLs** instead of one mega-page. Heavy on Kem/Glitch Cat machinery. Nothing below is implemented yet; every stage is a plan until the corresponding scripts and gate runners land.

## 2. The three outputs (render layer)

| File | Responsibility | Notes |
|---|---|---|
| **`graph.html`** | **Constellation view** (primary): radial layout by course → week → topic/solution, nodes + edges, node settings panel (the good one from v1). Minimal — no extra cosmos/semantic-web/sunburst views. Graph functions ported from old `viz.html`, trimmed to constellation + settings only. | Canvas-aligned: every node traces back to a Canvas module/page/file. |
| **`anki.html`** | Anki **full hub**: deck management + card review, flip/reveal, progress, import/export TSV. Reuse the Anki UI from the old `viz.html`. | Port Anki hub from v1 (viz.html UI). |
| **`cornell.html`** | Sleek white Cornell sheet: cues + notes, hidden answers by default, self-quiz toggle, print styles. | Reuse `cornell-notes` skill output. |

Each HTML is standalone, small, independently verifiable. No cross-page coupling. **Planned, not yet implemented.**

## 3. Pipeline stages (ICM folders)

```
01_ingest/        Smart Canvas + Zoom digestion → raw markdown + transcripts (relevant only)
02_sift/          Classifier pass → cleaned, tagged, deduped notes
03_structure/     ICM/Kem layout (OKF v0.2) → numbered weeks, CONTEXT.md, state files
04_render/        graph.html (constellation) + anki.html + cornell.html
05_verify/        Gates (asset, markdown/KaTeX, schema, render, judge)
```

Each stage folder has its own `CONTEXT.md`. State in `.agent_state.json` + `STATE.md` (one fact per line, supersede in place). Context gating (`cgate`) slices files instead of dumping. The runner is
`scripts/run_pipeline.py`; every stage `CONTEXT.md` is generated from
`scripts/stage_contracts.py`, the single contract table.

## 4. Stage 1 — Smart ingestion (planned around the constellation)

The constellation view is the spine: Canvas modules become nodes, topics/solutions become child nodes, videos become linked nodes, edges are "belongs-to-week", "prerequisite", "related", "has-explainer". **Digestion is planned to feed that graph, and only pulls what the graph needs.**

**Tools reused:** `canvas-cli`, `zoom-recorder`, `markitdown-cli`.

**Two streams per week** (the "two sides" of Canvas):
1. **Topic notes** — lecture content (pages, PDFs, slides).
2. **Tutorial solutions** — worked problems.

Either may carry an **explainer video** (Zoom recording or local MP4). Store URL/passcode + transcript, never the full video.

**Smart digestion rules (classifier-gated, before download):**
- `canvas-cli` lists modules/pages/files (names + metadata only). A light classifier (`jev-decision` bool) decides `is_relevant_note` per item from its name/title — no download yet. Drop admin/welcome/empty/overview/quiz-admin pages.
- Only download + markitdown-convert items that pass. Skip the rest (logged in `sift_report.json` as `skipped_irrelevant`).
- Scope filter: only necessary stuff — weeks 1–12 notes + tutorial solutions. Ignore orientation/admin modules, duplicates, and anything outside the course weeks.
- Zoom: only fetch transcript (ASR/VTT) + keyframes if a video is referenced; never the hour-long file. **De-risk note:** `academic/zoom-recorder/scripts/zoom_download.py --help` currently fails at `import requests` (`ModuleNotFoundError`), so this mode is unverified until dependencies are installed and the script is exercised (see `DE-RISK.md`).
- Dedup by signature fingerprint before writing to disk (poison stays upstream).

**Outputs (per week, per stream):**
- `markdown/<stream>.md` — text only.
- `transcripts/<stream>.vtt` + `.md` — ASR/VTT from Zoom.
- `meta.json` — course, week, stream, video URL/passcode, timestamps, node id for the constellation.

**Rule:** No HTML, no Anki yet. Just text + transcript + node metadata.

## 5. Stage 2 — Sifting (parallel classifiers)

**Concurrency (planned):** the local 35B classifier (Qwen3.6-35B-A3B, port 8080 per `ports.py list`) + free OpenRouter models (`openrouter-free`: nemotron, etc.) running in parallel, plus `free-swarm` fan-out. Repeated classifier prompts are skipped by the `glitch-cat/semantic-cache` Python module. Classifiers are cheap and fast — high-volume triage, not deep reasoning.

**`free-swarm` (real path `orchestration/free-swarm`):** it is not a CLI command. It is an OpenCode subagent skill. Invocation:
1. Install once: `python3 orchestration/free-swarm/scripts/install.py` (symlinks the nine `free-*` agents into `~/.config/opencode/agents`).
2. In a session: launch named read-only subagents such as `subagent(agent: "free-glm", ...)`, `free-minimax`, `free-lightning`, etc., with `background: true` for parallel fan-out.
3. Outside the loop: `python3 orchestration/free-swarm/scripts/fanout.py --models glm,minimax,flint "<task>"` for deterministic fan-out with answers written to disk.

For this pipeline, fan the "extract 6-8 cues" / "tag topics" / "summarize tutorial solution" jobs across several `free-*` agents and merge or majority-vote the results.

**`semantic-cache` (module path `glitch-cat/semantic-cache`):** this is an importable Python library, **not a CLI command**. Import it in code (e.g. `from glitch-cat.semantic_cache import ...`) rather than invoking a `semantic-cache` executable. It has no CLI entry, so the cache layer must be wired in code.

**Classifier tasks (typed via `jev-decision` bool/choice/score where possible):**
- `is_admin_fluff` — drop welcome/overview/empty pages.
- `is_duplicate` — near-duplicate transcript detection (signature fingerprint).
- `topic_tag` — which topic(s) this note covers (feeds constellation edges).
- `quality_score` — is this worth keeping? (0–1)
- `has_worked_solution` — does it contain a worked problem?
- `cue_candidate` — extract 6–8 active-recall cue seeds (optional, defer to Stage 3).
- `node_type` — topic / tutorial / video / reference (drives constellation node styling).

**Outputs:** cleaned markdown + `sift_report.json` (decisions + confidence). Low-confidence → human review queue, not auto-dropped.

**Kem alignment:** "code decides wherever it can" — deterministic filters (empty links, size thresholds) in code; models judge ambiguity. "Always run the control" — gates exit codes.

## 6. Stage 3 — Structuring (ICM + Kem playbook, OKF v0.2)

Replace `CURRICULUM_TREE.md` with **OKF v0.2** (`okf-architect`) for curriculum/knowledge architecture. Heavy Kem/Glitch Cat incorporation: state-compactor, cgate, guard-hooks, jev-decision, eval-pipeline (step-level gates), semantic-cache, graph-memory (hybrid RAG), notes-index.

**Layout (agreed, single source of truth — `SKILL.md` mirrors this exactly):** numbered folders per course, one home per fact, links over copies.

```
<course>/
  01_weeks/
    Week_01/
      CONTEXT.md        (inputs, process, outputs, human checkpoint)
      topic.md
      tutorial.md
      meta.json
  02_index/             generated file maps (OKF v0.2), never hand-edited
  03_state/             .agent_state.json, STATE.md
  _templates/           copy, don't blank-page
```

Within the workspace, Stage 3 writes this scaffold under `03_structure/<course>/`; the `01_weeks/`, `02_index/`, `03_state/`, and `_templates/` folders live at the course root. `SKILL.md` documents the same course-root layout.

**Invariants (icm-architect):** one folder one job; small stable entry file (AGENTS.md < ~60 lines, with "Not this workspace" + status rules incl. STALE); numbering encodes order; factory vs product; every output is an edit surface; filesystem is the state machine (STALE by mtime).

**Kem principles applied:**
- State ledger (`.agent_state.json`/`STATE.md`) for long sessions; compaction via state-compactor.
- Context gating (`cgate`) — slice files, don't dump.
- Guard hooks for destructive ops.
- Judge independence — verification judge must not share the author's context.
- Eval-pipeline step-level gates `[D]/[P]/[H]` with disk-serialized intermediate state.

## 7. Kem skills chosen for ICM (3) + playbook

Three Kem/Glitch Cat skills anchor the pipeline. Each maps to a distinct concern so they don't overlap. (Note: `jev-decision` is folded in as the typed-decision primitive underneath `eval-router`, not a headline dependency.)

### 7.1 `eval-router` — digestion workhorse (sifting stage)
- **What:** self-calibrating request router. Classifies prompt complexity (Easy/Moderate/Hard) via a local model, dispatches to local zero-cost models or free tiers (OpenRouter), verifies output quality (speculative shadow eval), and harvests failures into training evals. Claimed 30-40% token cost reduction.
- **Real CLI (verified in `DE-RISK.md`):** `python3 glitch-cat/eval-router/eval_router.py {route,exec,stats,harvest}`. Stage 2 will call `eval_router.py route` for tier classification and `eval_router.py exec` for routed execution with fallback.
- **How implemented (planned):** digestion prompts (is_admin_fluff, is_duplicate, topic_tag, quality_score, cue_candidate, node_type) get routed — easy ones to the cheapest free 9B, harder ones to the local 35B (Qwen3.6-35B-A3B, :8080). Shadow verification catches bad classifier outputs; harvested failures feed back into better prompts. Replaces ad-hoc fan-out with measured routing + verification + learning.
- **Why here:** this is the digestion engine — "mix of free models + classifiers in parallel with quality control."

### 7.2 `free-swarm` (path `orchestration/free-swarm`) — parallel fan-out (digestion + conversion)
- **What:** nine zero-cost OpenCode models exposed as named read-only subagents; fan a task out to all of them at once for independent answers, majority votes, long-context reads, cheap parallel review.
- **How invoked:** install agents with `python3 orchestration/free-swarm/scripts/install.py`, then either launch `free-*` subagents in-session or run `python3 orchestration/free-swarm/scripts/fanout.py --models glm,minimax,flint "<task>"` for disk-backed fan-out.
- **How implemented (planned):** for each week's notes, fan the "extract 6-8 cues" / "tag topics" / "summarize tutorial solution" jobs across several of the 9 models in parallel, then take a majority vote or merge. For Cornell conversion, parallel subagents per note so the whole course converts in one pass. Cheap and fast because they're all free-tier.
- **Why here:** this is the "speed up digestion" and "turn stuff to cornell/anki" accelerator — parallelism across models.

### 7.3 `graph-memory` — constellation backend + retrieval (render stage)
- **What:** SQLite k-hop graph + hybrid BM25/vector search (bge-small, 384d) + exact-quote distillation.
- **How implemented (planned):** weeks/topics/solutions/videos become entities with typed relations (`belongs-to-week`, `prerequisite`, `related-topic`, `has-explainer`). `graph.html`'s constellation renders from this graph; `graph recall "Supernode" --hops 3` gives the traversal for the node-settings panel. Dedups entities across weeks (no duplicate "Week 5 Phasors" nodes). Also powers search in the constellation.
- **Why here:** the constellation view needs a real graph data model, not a hand-rolled JSON.

### Kem playbook (operating discipline across all stages)
- **Code decides wherever it can.** Deterministic filters (empty links, size thresholds, week-range scope) run in code; models only judge ambiguity. `eval-router`'s complexity classifier is the boundary.
- **The poison sits upstream.** Sift before structuring; `free-swarm` votes filter garbage before it hits the corpus.
- **Always run the control.** Every phase ends with Launch -> Doctor -> Drive -> Evidence -> Cleanup; per-stage gates (hard stops on failure) with serialized evidence.
- **A skill is instructions; a hook is code that ALWAYS runs.** Guard-hooks protect destructive ops; don't rely on model obedience.
- **A judge that shares the author's context is not a judge.** Independent context for the 0-context gate.
- **One home per fact (links, not copies).** Structuring stage enforces this.

## 8. Verification — a gate at every stage (not just the end)

Per-stage micro-gates (Kem: "always run the control"). Each stage must pass its gate before the next stage runs; a failing gate is a hard stop with serialized evidence (`step_NN.json`), not a warning. Implemented in `scripts/gates.py`; the five gates run in order and
write `05_verify/step_05.json`.

- **Stage 1 (ingest) gate `[D]`:** asset doctor (MIME, video size, Zoom passcode presence); scope check (only weeks 1-12 notes + tutorial solutions); dedup fingerprint sanity. Output: `step_01.json`.
- **Stage 2 (sift) gate `[D]+[P]`:** markdown + KaTeX balance; classifier confidence floor (low-confidence items routed to review queue, not auto-dropped); no `.vtt` in DOM. Output: `step_02.json`.
- **Stage 3 (structure) gate `[D]`:** schema (JSON shape, stem inheritance, source linkage via OKF v0.2); one-home-per-fact check; STALE detection by mtime. Output: `step_03.json`.
- **Stage 4 (render) gate `[D]`:** render smoke - each HTML parses, no console errors, constellation/anki/cornell each load; Anki UI loads from viz.html-derived template. Output: `step_04.json`.
- **Stage 5 (final) gate `[P]`:** 0-context judge (`jev-decision`, independent context) accepts a sample; range server optional (constellation video drawers degrade gracefully). Output: `step_05.json`.

Exit codes gate CI. "Always run the control."

## 9. What we reuse vs replace

| Reuse | Replace |
|---|---|
| `canvas-cli`, `zoom-recorder`, `markitdown-cli` (ingestion) | `academic-icm` monolithic orchestrator |
| `cornell-notes` skill (white-page renderer) | `viz.html` mega-page → 3 focused HTMLs |
| `okf-architect` (OKF v0.2 curriculum architecture) | `CURRICULUM_TREE.md` manual tree |
| `free-swarm` (`orchestration/free-swarm` subagents + fanout) | ad-hoc parallel fan-out |

## 10. Phased rollout (validation-first)

1. **Phase 0** — Run on a **user-specified subject** (or all 4: 41200, 48430, 48520, 48521). The pipeline takes a subject list / course IDs, not a hardcoded subject. Run stages 1-2 manually on one week, inspect sift quality + constellation node shape. Don't touch others until Phase 0 passes.
2. **Phase 1** — Automate ingestion + sifting for 48520 all weeks. Verify dedup/fluff/relevance numbers.
3. **Phase 2** — Add structuring (OKF v0.2) + render for 48520. Ship `graph.html` (constellation) + `anki.html` + `cornell.html` for that subject only.
4. **Phase 3** — Run gates, fix, replicate to 48521, 48430, 41200.
5. **Phase 4** — Retire v1 artifacts (`viz.html`, `study.html`, `cornell_index.html`) once v2 verified.

**Validation rule:** each phase ends with a grounded check (Launch → Doctor → Drive → Evidence → Cleanup) before moving on. No "it compiled, ship it."

## 11. Resolved decisions

1. **Graph view:** minimal constellation view (Canvas-aligned) + node settings panel. Drop extra cosmos/semantic-web/sunburst views. Constellation is the spine; digestion feeds it.
2. **CURRICULUM_TREE.md:** fully gone. OKF v0.2 (`okf-architect`) handles curriculum/knowledge architecture.
3. **Kem/Glitch Cat:** heavy incorporation (state-compactor, cgate, guard-hooks, jev-decision, eval-pipeline, semantic-cache, graph-memory, notes-index).
4. **Digestion:** smart, classifier-gated — only download relevant note stuff; skip admin/fluff/dupes before writing to disk.
5. **Local model:** Qwen3.6-35B-A3B on :8080 (per `ports.py list`). All "27B" references are corrected to 35B.

## 12. Still open (need your call)

1. ~~Classifier concurrency~~ — RESOLVED: local 35B (Qwen3.6-35B-A3B, :8080) + OpenRouter free models in parallel.
2. ~~Smart digestion~~ — RESOLVED: first stage; light classifier (`jev-decision` bool) triages on Canvas metadata (names) before download; scope = weeks 1-12 notes + tutorial solutions only.
3. ~~Anki~~ — RESOLVED: full hub (deck mgmt + review), reusing the Anki UI from old `viz.html`.
4. ~~Phase 0 subject~~ — RESOLVED: user-specified subject list (default all 4: 41200, 48430, 48520, 48521); not hardcoded.
5. ~~Kem verification~~ — RESOLVED: a micro-gate at every stage (hard stop on failure, serialized evidence).
6. `eval-router` CLI contract — RESOLVED (see §7.1): `python3 glitch-cat/eval-router/eval_router.py {route,exec,stats,harvest}`.

## 13. Out of scope (deliberately)

- Full video playback / MP4 streaming (defer; text + transcript first).
- Rebuilding `canvas-cli`/`zoom-recorder` (reuse as-is).
- Public bundle syndication changes (satellite picks up on next `sync-skills --push`).
