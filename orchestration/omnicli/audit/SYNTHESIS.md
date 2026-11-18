# Cross-batch synthesis — 59-skill audit

Inputs: `RUBRIC.md` (10 points) + `findings/batch1.md … batch5.md`.
Scope: 10 + 11 + 10 + 12 + 16 = **59 skills**, 590 points. Nothing in the skills repo was edited.

---

## 1. Total point counts (PASS / FAIL / N-A per point 1–10)

### Grand tally by point

| Point | PASS | FAIL | N-A | Total | Note |
| :--- | ---: | ---: | ---: | ---: | :--- |
| 1 — name valid + matches dir | 58 | 1 | 0 | 59 | only `archived/gemini-api` has no frontmatter |
| 2 — description what+when, intent-first, ≤1024 | 45 | 14 | 0 | 59 | 13 passive; 1 over-length (`jev-decision` 1095) |
| 3 — SKILL.md <500 lines / ~5k tokens, tables in refs | 58 | 1 | 0 | 59 | `gws-drive` inlines 100+ row API table |
| 4 — refs skill-root-relative, one level, no chains | 50 | 8 | 1 | 59 | 8 FAIL + 8 more "hardcoded path" notes |
| 5 — `scripts/` only runnable CLIs | 26 | 25 | 8 | 59 | **single largest failure class** |
| 6 — typed contracts (argparse / parseArgs / --omni-schema) | 47 | 5 | 7 | 59 | hand-rolled `sys.argv`/`CMD="$1"`/Bash case |
| 7 — non-interactive, actionable stderr + non-zero | 51 | 1 | 7 | 59 | only `cornell-notes` `input()` |
| 8 — `--help` with `Usage:` line, zero side effects | 50 | 2 | 7 | 59 | `ed_ws.js`, icm-architect helpers |
| 9 — structured `--json` on clean stdout | 40 | 11 | 8 | 59 | +3 partial (`P9~`) skills |
| 10 — bounded output + safe defaults / `--dry-run` | 33 | 19 | 7 | 59 | worst single point after P5 |
| **TOTAL** | **458** | **87** | **45** | **590** | 77.6% PASS / 14.7% FAIL / 7.6% N-A |

### Per-batch reconciliation (arithmetic verified)

| Batch | Scope | Skills | PASS | FAIL | N-A | Points | Check |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| 1 | `academic/` | 10 | 84 | 16 | 0 | 100 | stated totals ✓ |
| 2 | `glitch-cat/` A | 11 | 85 | 19 | 6 | 110 | stated totals ✓ |
| 3 | `glitch-cat/` B | 10 | 75 | 24 | 1 | 100 | **derived** from per-skill table (batch had no summary) ✓ |
| 4 | `hardware/` + `multimodal/` | 12 | 110 | 10 | 0 | 120 | stated per-point tallies ✓ |
| 5 | orchestration + engineering + archived | 16 | 104 | 18 | 38 | 160 | per-point N-A sums to **38**, not 32 ✓ |
| **TOTAL** | | **59** | **458** | **87** | **45** | **590** | 59 × 10 = 590 ✓ |

Verification details:
- Batch 3 derivation: P1 10/0/0 · P2 6/4/0 · P3 10/0/0 · P4 10/0/0 · P5 3/6/1 · P6 9/1/0 · P7 10/0/0 · P8 10/0/0 · P9 7/3/0 · P10 0/10/0 → 75/24/1.
- Batch 5 N-A re-sum: pt4 1 + pt5 6 + pt6 6 + pt7 6 + pt8 6 + pt9 7 + pt10 6 = 38. (A quick read of the six docs-only skills alone gives 30 for points 6–10; the missing 8 are pt5×6, pt4×1, and `design-system` pt9 N-A.) 104+18+38 = 160 ✓.
- Column sums check across all five batches: every point totals exactly 59 ✓.

---

## 2. Ranked top 10 cross-cutting fixes

Rank = (skills affected × impact on execing). Impact scale: High = 3, Medium = 2, Low = 1. Overlaps are de-duplicated by root cause; "skills affected" counts formal FAILs unless noted.

### #1 — Evict helpers / tests / docs from `scripts/` (P5) — 25 skills × 2 = **50**
Evidence (representative, all `scripts/`):
- b1: `academic/academic-pipeline-v2/scripts/adapters.py:31`, `stage_contracts.py:13`, `anki_cards.py:17`; tests `academic/{agent-reach/scripts/test_reach_filter.py, canvas-cli/scripts/test_canvas_cli.py, edstem-cli/scripts/test_ed_cli.py, markitdown-cli/scripts/test_markitdown_cli.py, zoom-recorder/scripts/test_zoom_download.py}`
- b2: `glitch-cat/agentic-engineering/scripts/test_agentic.py`; helpers `glitch-cat/{eval-pipeline/scripts/pipeline_core.py, eval-router/scripts/classifier.py (0755), glitch-orchestra/scripts/orchestra_conductor.py, jev-decision/scripts/jev_engine.py}`
- b3: `notes-index/scripts/notes_index_core.py:1` (775), `projects-harness/scripts/harness_core.py:1`, `semantic-cache/scripts/cache_engine.py:1`, `swarm-contract/scripts/swarm_engine.py:1`, `verification/scripts/{cdp_lite,verify_common,verify_control,verify_forge}.py:1`, `reply-meter/scripts/card.md:1`, `memory/_tools/test_capture.mjs`
- b4: `hardware/{decision-model/scripts/{gguf_meta,glide_serve,h2o_serve,pplx_decider,eval_golden}.py:1, audiocpp/scripts/{audiocpp_core,audiocpp_diar,audiocpp_http,check-docs}.py:1, nvidia-nim/scripts/test_nim_client.py:1}`; `multimodal/{ocr/scripts/ocr_engine.py:1, video-miner/scripts/{videomine_core,videomine_stages,videomine_visual,procure,test_videomine}.py:1}`
- b5: `orchestration/{cf-architect/scripts/test_cf_architect.py:1, github-architect/scripts/test_github_architect.py:1, omnicli/scripts/{test_asr.py,test_ocr.py,verify_agent_skills.py,verify_code_mode.py}:1}`

Minimal change: `mkdir -p <skill>/modules <skill>/tests && git mv scripts/<helper>.py modules/ && git mv scripts/test_*.py tests/`; for non-exec docs/renderers either move to `references/` or drop the exec bit/shebang so omnicli never catalogs them. Update the two SKILL.md refs that document these files: `cf-architect/SKILL.md:121`, `omnicli/SKILL.md:108–119`. Why this ranks first: 25 skills, zero runtime-code risk, and it removes **phantom tools** from the catalog (`eval-router/scripts/classifier.py` is 0755 and already trips `script-no-help`; `verification/scripts/cdp_lite.py` is 775 with no `__main__`).

### #2 — Add `--dry-run` to every stateful CLI (P10) — ~15 skills × 3 = **48**
Evidence: batch 3 explicitly reports **10/10 FAIL** with "repo-wide grep for `--dry-run` returns zero hits": `worktree-harness/scripts/harness.py:591` (`integrate`), `:603` (`teardown`); `state-compactor/scripts/compactor.py` (`record`/`wrap`/`compact`); `swarm-contract/swarm_contract.py:14` (`check`/`record`); `verification/scripts/verify.py:857` (`control`); `parallel-test-lane/scripts/test_lane.py:202` (`run`); plus `memory` (`save`/`forget`), `notes-index` (`init`/`update`), `semantic-cache` (`store`/`query`), `projects-harness` write paths. Also `guard-hooks/guard_hooks.py:5-8` (`wrap` executes gated command), `hardware/tailscale-ops/scripts/ts_ops.sh:102,110`, `hardware/audiocpp/scripts/switch-version.sh:101-135`, `orchestration/subagent-spaces` `prune` (parser `:432`), `cf-architect` (`budget`).
Minimal change: in each mutating subparser add `p.add_argument("--dry-run", action="store_true")` and guard the write/mutate/merge call — print the planned action (JSON when `--json`) and exit 0 before side effects. Existing good examples: `model-layer/llama_rig.py` (`SKILL.md:44,65`), `github-architect/git_sync.py:1002`, `run_pipeline.py:416`, `gates.py:596`.

### #3 — Add one top-level `--json` to partial CLIs (P9) — 11 FAIL (+3 partial) × 3 = **33**
Evidence: `academic/academic_icm.py:2370,2380` (only `verify`/`smart`; `:188-514` human text), `academic-pipeline-v2/gates.py:599` + `run_pipeline.py:393-396`; `glitch-cat/apiv-loop/scripts/apiv_loop.py` (verifier `script-no-json`); `parallel-test-lane/scripts/test_lane.py:199-208` (JSON only to `--out` at `:173`), `state-compactor/scripts/compactor.py:365,374` (`check`/`inspect` only), `worktree-harness/scripts/harness.py:600` (`status` only); `cf_architect.py:242/250`, `gemini_studio.py:850/933/937`, `or_agent.py:851/903`. Partial: `graph-memory` (`recall`), `kem-dev-loop` (`validate`/`review`), `jev-decision`/`eval-router`/`agentic-engineering` (hallmarked clean but with caveats).
Minimal change: add `parser.add_argument("--json", action="store_true")` to the **shared parent parser**, route all command output through `json.dumps`, and gate human `print()` behind `if not args.json`; progress/errors to stderr. Copy `notes-index/notes_index.py:42` and `verification/scripts/verify.py:785-787`.

### #4 — Make descriptions intent-first and enforce the length cap (P2) — 14 skills × 2 = **28**
Evidence: `glitch-cat/{agentic-engineering/SKILL.md:4-7, eval-pipeline:4-8, glitch-orchestra:4-8, graph-memory:4-7}` (no `Use when` trigger); `glitch-cat/jev-decision/SKILL.md:4-17` = 1095 chars (verifier `description-length` ERROR, cap 1024); b3 `parallel-test-lane:4-8`, `projects-harness:4-9`, `reply-meter:4-11`, `swarm-contract:4-8`; b4 `hardware/nvidia-nim:4-8`, `hardware/tailscale-ops:4-7`, `multimodal/playwright:3-7`; b5 `archived/design-system:5,10` (late "Use when"), `archived/gemini-api:1` (no frontmatter at all).
Minimal change: prepend one imperative `Use when <user intent> …` sentence to the `description:` scalar; drop the two longest `box` examples from `jev-decision`; move `design-system`'s existing late trigger to the front; repair the truncated "workflow from." at `glitch-orchestra/SKILL.md:6`. All stay under 1024 chars.

### #5 — Bound list output (`--fields` / `--project` / `--limit`) (P10 "b2b") — ~8 skills × 3 = **24**
Evidence: explicit code-mode `b2b` violations — `icm-architect/scripts/icm_architect.py:552-583` (`map` prints every stage), `okf-architect/scripts/okf_architect.py:1742,1748` (only `-o/--output`), `eval-pipeline/scripts/eval_pipeline.py:100-111` (`audit` prints every step), `glitch-orchestra` (`status` has no `--fields/--project`). Plus `reply-meter` fault list (`:210`), `verification` `states` (`:827`), `subagent-spaces` `ps`, `cf-architect budget`, `gemini-studio` ad-hoc `[:20000]` at `:623`.
Minimal change: add comma-separated `--fields`, `--project NAME`, and `--limit N` (default ~20) to those list subparsers and default to a compact table — this is exactly what `verify_code_mode.py` checks.

### #6 — Replace absolute / deep `../` file references with skill-root-relative ones (P4) — 8 formal FAIL × 2 = **16** (8 further hardcode notes are non-scoring, listed for scope)
Evidence: `agent-reach/SKILL.md:70,73,77,88,107` (`~/.gemini/config/skills/...`, incl. `sys.path.insert(0,"/home/rodri/.gemini/...")`); `eval-pipeline:49`, `eval-router:66,84,94` + `../../orchestration/gh-action-subagent/SKILL.md:143`, `glitch-orchestra:44`, `graph-memory:56` (`/run/media/...`); b3 notes `notes-index:51`, `parallel-test-lane:39`, `projects-harness:87`, `semantic-cache:34`, `swarm-contract:26`, `reply-meter:114,165`; b4 `audiocpp:51,91`, `video-miner:38,321` (`~/.gemini/...`); b5 `gws-docs:24,34`, `gws-docs-write:24,57`, `gws-drive:33` (dead `../gws-drive-upload` link).
Minimal change: write examples as `python3 scripts/<entry>.py` with a "run from skill root" note; replace `../../` skill links with plain-text "see the `<skill-id>` skill" pointers discoverable via `omnicli describe`; delete the dead `+upload` row. *(Only 8 are hard FAILs; the other 8 are notes, so the score stays 16 — below #5.)*

### #7 — Give hand-rolled CLIs typed contracts (P6) — 5 formal FAIL × 3 = **15** (the guard-hooks clap carve-out is counted in #8)
Evidence: `icm-architect/scripts/{links.py:84, quotes.py:177, viz.py:64, index.py:50}` raw `sys.argv`; `edstem-cli/scripts/ed_ws.js:311` raw `process.argv`; `tailscale-ops/scripts/ts_ops.sh:5-17` `CMD="${1:-peers}"`; `gh-action-subagent/scripts/subagent_ctl.sh:1` Bash case; `state-compactor/bin/cgate` clap-only (`--omni-schema` → exit 2); `guard-hooks` clap derive typed but no `--omni-schema` (`guard-rs/src/main.rs:265`).
Minimal change: `import argparse` / `parseArgs` from `node:util` with a `main()` and zero-side-effect `--help`, keeping positional semantics; for shell/Rust entrypoints add an `--omni-schema` branch emitting one MCP JSON Schema with `x-flag`/`x-positional`.

### #8 — Make non-introspectable primary CLIs code-mode-drivable (P6+P9+P10) — 3 skills × 3 = **9**
Evidence: `guard-hooks/guard_hooks.py:5-8` `os.execv` → `bin/guard-hooks` (verifier **deferred**: "`--json` needs a Rust change and a rebuild"); `state-compactor/bin/cgate` (2.5 MB ELF, `cgate grep --json` → exit 2); `gh-action-subagent/scripts/subagent_ctl.sh` (symlinked as `gh-subagent` in `~/.local/bin`).
Minimal change: add `--omni-schema` + `--json` + `--limit` to the clap `Cli` struct / shell dispatcher and rebuild the binary — **or** point omnicli at the Python wrappers (`guard_hooks.py`, `scripts/cgate.py`) and keep binaries as operator conveniences. Highest per-skill impact: today these primary paths cannot be driven with structured output at all.

### #9 — Restore frontmatter and remove interactive prompts (P1/P2/P7) — 2 skills × 3 = **6**
Evidence: `archived/gemini-api/SKILL.md:1` starts `# Skill: gemini-api` — no YAML block, invisible to the metadata tier; `cornell-notes/scripts/srs_review.py:214,227,433,446` `input()` SM-2 quiz.
Minimal change: prepend `---\nname: gemini-api\ndescription: >- Use when …\n---` plus the archived-status marker expected at `github-architect/SKILL.md:143`; gate the quiz behind `--cue-id/--rating 1-4` or move it to a non-cataloged 0644 script under `assets/`.

### #10 — Add zero-side-effect `--help` to hand-rolled CLIs (P8) — 2 skills × 2 = **4**
Evidence: `edstem-cli/scripts/ed_ws.js:316` has only an error-path `Usage:` (verifier `script-no-help`); `icm-architect/scripts/{links.py,quotes.py,viz.py}` lack `--help` (same verifier). `eval-router/scripts/classifier.py` also trips `script-no-help` but is resolved by fix #1.
Minimal change: add a `-h/--help` branch that prints `Usage: <cmd> [flags] <positionals>` and exits 0 with no writes — usually free once fix #7 introduces argparse/parseArgs.

---

## 3. Three systemic root causes

1. **`scripts/` has no enforced directory convention (P5: 25 failures).** Every batch independently rediscovered the same problem: library/helper modules and `test_*.py` land next to runnable CLIs, sometimes executable (`eval-router/classifier.py` 0755, `notes-index_core.py` 775, `cdp_lite.py` 775). `omnicli` therefore catalogs phantom tools and emits `script-no-help`. The checklist rule exists (`agent-skills-checklist.md`) but is not wired into a pre-commit/verifier gate, so it regresses per skill.

2. **Output contracts are treated as optional authoring polish, not a required interface (P6: 5, P9: 11, P10: 19).** Each skill hand-builds its CLI instead of inheriting a shared `common` parent parser with `--json`, `--limit/--offset/--output`, and `--dry-run`. Consequences: JSON appears on only one subcommand (forcing agents to remember `--project`), list output is unbounded (the 7 KB code-mode cap and `b2b` gate then reject it), and destructive subcommands have no preview. `--dry-run` is essentially absent repo-wide.

3. **Manifests are written for the author, not for the agent router (P2: 14, P4: 8 + 8 notes, P1: 1).** Descriptions are passive feature lists that say *what* but not *when*, so intent-based routing cannot find them. File references are absolute (`/run/media/rodri/AI/...`) or point at derived harness copies (`~/.gemini/config/skills/...`) and `../` siblings — copied between machines, they violate the one-source-of-truth invariant and break outside this host. `gemini-api` has no frontmatter at all.

---

## 4. Exec-ready list and "one fix away"

### Exec-ready — clean on points 6–10 (20 skills)
Strict definition: all five exec points PASS (or legitimately N-A), verifiers clean/near-clean.

| # | Skill | Batch |
| ---: | :--- | :--- |
| 1 | `academic/agent-reach` | 1 |
| 2 | `academic/canvas-cli` | 1 |
| 3 | `academic/markitdown-cli` | 1 |
| 4 | `academic/zoom-recorder` | 1 |
| 5 | `glitch-cat/frontend-uat` | 2 |
| 6 | `glitch-cat/jev-decision` | 2 |
| 7 | `glitch-cat/eval-router` | 2 |
| 8 | `glitch-cat/graph-memory` | 2 |
| 9 | `glitch-cat/agentic-engineering` | 2 |
| 10 | `glitch-cat/kem-dev-loop` | 2 |
| 11 | `hardware/local-llm` | 4 |
| 12 | `hardware/model-layer` | 4 |
| 13 | `multimodal/design-pack` | 4 |
| 14 | `multimodal/doc-layout` | 4 |
| 15 | `multimodal/t3-browser-hands` | 4 |
| 16 | `orchestration/github-architect` | 5 |
| 17 | `orchestration/omnicli` | 5 |
| 18 | `engineering/review-hub` | 5 |
| 19 | `orchestration/free-swarm` | 5 |
| 20 | `archived/design-system` | 5 |

Caveats (do not pad): 1–4 carry the P5 test-in-`scripts/` issue (agent-reach also P4). 5–10 carry hygiene/description caveats: `jev-decision` P2 length ERROR, `eval-router`/`agentic-engineering` P5 helper/test, `graph-memory`/`kem-dev-loop` partial `--json` (P9~). 20 has point 9 legitimately N-A (HTML renderer). **Batch 3 contributes zero skills here** — all 10 pass gates 6–9 but every one fails point 10.

### One fix away — exactly one failing exec point (17 skills)
| Skill | Single failing point | Fix |
| :--- | :---: | :--- |
| `academic/academic-icm` | P9 | global `--json`; progress → stderr |
| `academic/academic-pipeline-v2` | P9 | `--json` on `gates.py:599`, `run_pipeline.py:393-396` |
| `academic/cornell-notes` | P7 | gate `input()` at `srs_review.py:214,227,433,446` |
| `academic/okf-architect` | P10 | `--project/--fields/--limit` at `okf_architect.py:1742,1748` |
| `glitch-cat/apiv-loop` | P9 | global `--json` on `apiv_loop.py` |
| `glitch-cat/eval-pipeline` | P10 | `--limit/--out` at `eval_pipeline.py:100-111` |
| `glitch-cat/glitch-orchestra` | P10 | `--project/--fields` on `status` |
| `memory` | P10 | `--dry-run` on `save`/`forget` |
| `notes-index` | P10 | `--dry-run` on `init`/`update` |
| `projects-harness` | P10 | `--dry-run` on writes |
| `reply-meter` | P10 | `--limit` on fault list |
| `semantic-cache` | P10 | `--dry-run`/`--limit` on `store`/`query` |
| `swarm-contract` | P10 | `--dry-run` at `swarm_contract.py:14` |
| `verification` | P10 | `--dry-run` at `verify.py:857` (`control`) |
| `orchestration/gemini-studio` | P9 | one top-level `--json` at `gemini_studio.py:850` |
| `orchestration/openrouter-free` | P9 | one top-level `--json` at `or_agent.py:851` |
| `orchestration/subagent-spaces` | P10 | `--dry-run` on `prune` (parser `:432`) |

Borderline (scored 5/5 but flagged "P10 weak"): `hardware/audiocpp` (`switch-version.sh:101`) and `hardware/decision-model`. Two-fix-or-more: `icm-architect` (P6/P8/P10), `guard-hooks` (P9/P10), `parallel-test-lane` (P9/P10), `state-compactor` (P6/P9/P10), `worktree-harness` (P9/P10), `tailscale-ops` (P6/P10), `cf-architect` (P9/P10), `gh-action-subagent` (P6/P9/P10); docs-only/N-A: `kem-thought`, `gws-*`, `leanrea`, `gemini-api`.

---

## 5. Recommended first slice

**Single change:** Fix #1 — evict every helper, test, and non-CLI doc from `scripts/` (25 skills, P5).

**Why this one:** best skills-fixed-to-risk ratio in the audit. 25 of 59 skills (42%) move from FAIL to PASS on point 1 with **mechanical file moves only** — no runtime code, no behavior change, fully reversible with `git mv`. It also immediately removes the phantom-tool entries (`eval-router/classifier.py`, `verification/cdp_lite.py`) that currently pollute the omnicli catalog and cause `script-no-help` warnings. The runner-up, `--dry-run` (#2), fixes ~15 skills but needs a semantic guard in each of ~15 different mutation sites and per-skill verification — far higher risk for fewer skills.

**Scope of the slice:** the 25 P5 FAILs listed under fix #1, plus doc-ref updates at `cf-architect/SKILL.md:121` and `omnicli/SKILL.md:108–119`; leave the two tolerated non-exec cases (`doc-layout/render_md.js`, `decision-model` servers) for a follow-up if strict zero-noise is wanted.

**Negative control that proves it works** (a gate that cannot fail is not a gate):
1. Gate = `python3 orchestration/omnicli/scripts/verify_agent_skills.py --skill <S> --strict --json`, exit 0 on clean.
2. Baseline: run it on a clean control (`hardware/local-llm`) → exit 0, `P5: PASS`.
3. **Mutated negative control:** temporarily `cp glitch-cat/eval-router/scripts/classifier.py` back into `scripts/` with mode `0755` (already flagged `script-no-help` in batch 2), or plant a dummy `test_probe.py` in `hardware/local-llm/scripts/`. Re-run the same verifier → **exit != 0**, `P5: FAIL / script-no-help`. Then remove the planted file → exit 0 again.
4. Catalog check: confirm `omnicli` lists `classifier.py` as a phantom callable before the move and not after, while `eval-router/scripts/roster.py` (argparse + `--json` at `:770`) still executes with `--help` exit 0. The control fails when the gate is blind to the planted helper — proving the clean result is meaningful, not vacuous.
