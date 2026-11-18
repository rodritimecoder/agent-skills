# Batch 1 — findings

Scope: `academic/` — 10 skills. Ground truth: agentskills.io spec dossier, `orchestration/omnicli/references/agent-skills-checklist.md`, and the live code-mode design.
Evidence sources: direct reads of every `SKILL.md`, `find` of every skill tree, targeted `grep` of every `scripts/` entrypoint, and objective runs of `verify_agent_skills.py --skill X --strict --json` and `verify_code_mode.py --skill X --json` from `orchestration/omnicli/`.

## Per-skill table

Notation: `4/5 (F5)` = 4 of 5 points PASS, point 5 FAIL. Blockers carry `file:line` evidence.

| Skill | Lines | Spec (1-5) | Exec (6-10) | Blockers | Quick wins |
| :--- | :---: | :--- | :--- | :--- | :--- |
| academic-icm | 190 | 5/5 | 4/5 (F9) | **P9:** `--json` only on `verify`/`smart` (`scripts/academic_icm.py:2370,2380`); `status`/`audit`/`compile`/`srs` emit emoji-laden human text to stdout (`:188-514`). Named `../academic-pipeline-v2/SKILL.md` at `SKILL.md:23` is a `../` sibling pointer, not in-skill relative. Verifiers: both clean. | Add global `--json` + route progress to stderr; make the v1/v2 note a plain-text pointer instead of a `../` SKILL.md link. |
| academic-pipeline-v2 | 138 | 4/5 (F5) | 4/5 (F9) | **P5:** helper/library modules with no CLI or `if __name__` live in `scripts/`: `adapters.py:31-40`, `stage_contracts.py:13`, `anki_cards.py:17`. **P9:** `gates.py:599` prints JSON unconditionally but has no `--json` flag (verifier `script-no-json`); `run_pipeline.py:393-396` prints human text. Verifiers: agent-skills 1 warning, code-mode clean. | Move 3 helper modules to `modules/`; add `--json` to `gates.py` and `run_pipeline.py`. `--dry-run` already good (`run_pipeline.py:416`, `gates.py:596`). |
| agent-reach | 164 | 3/5 (F4,F5) | 5/5 | **P4:** `SKILL.md:70,73,77,88,107` reference the DERIVED harness copy `~/.gemini/config/skills/agent-reach/scripts/reach_filter.py` / `/home/rodri/.gemini/...` — not skill-root-relative, breaks one-source-of-truth. **P5:** `scripts/test_reach_filter.py` in scripts/. Verifiers: both clean. | Replace 5 absolute paths with `scripts/reach_filter.py` and `sys.path.insert(0,"scripts")`; move test to `tests/`. |
| canvas-cli | 102 | 4/5 (F5) | 5/5 | **P5:** `scripts/test_canvas_cli.py` in scripts/ (should be `tests/`). Verifiers: both clean; strong contracts (`scripts/canvas_cli.py:624-639` argparse + subparsers, `--limit/--project/--out`, default JSON at `:626`, errors to stderr at `:654-657`). | Move test to `tests/`, or drop exec bit/shebang so omnicli does not catalog it. |
| cornell-notes | 88 | 5/5 | 4/5 (F7) | **P7:** interactive `input()` prompts in `scripts/srs_review.py:214,227,433,446` (verifier `script-interactive`). Verifiers: agent-skills 1 warning, code-mode clean. Contracts otherwise good: `format_notes.py:696-736` argparse, `--json/--limit/--output`, errors to stderr. | Gate the SM-2 quiz behind explicit `--answer/--rate` flags (or move quiz to a non-cataloged script); keep `status` non-interactive. |
| edstem-cli | 132 | 4/5 (F5) | 3/5 (F6,F8) | **P5:** `scripts/test_ed_cli.py` in scripts/. **P6:** `scripts/ed_ws.js:311` hand-rolled `process.argv`, no `parseArgs`/`--omni-schema`. **P8:** `ed_ws.js` has no `--help` (only error-path `Usage:` at `:316`; verifier `script-no-help`). Verifiers: agent-skills 1 warning, code-mode clean. | Move test to `tests/`; add `parseArgs` from `node:util` + zero-side-effect `--help` to `ed_ws.js`. `ed_cli.py:868-921` and `workspace_sync.py:280-293` are already good argparse contracts. |
| icm-architect | 136 | 5/5 | 2/5 (F6,F8,F10) | **P6:** hand-rolled argv, no typed contract in `scripts/links.py:84`, `quotes.py:177`, `viz.py:64`, `index.py:50`. **P8:** those helpers lack `--help` (verifier `script-no-help` on links/quotes/viz). **P10:** code-mode `b2b` violation — "no --fields/--project: list output is unbounded" (`icm_architect.py:552-583` map prints every stage). Verifiers: agent-skills 3 warnings, code-mode 1 violation. | Add `argparse`+`--help` to the 4 helpers; add `--fields/--project` + `--limit` to `map`/`validate` list output. `icm_architect.py:621-639` already has `--json` on init/validate/doctor. |
| markitdown-cli | 96 | 4/5 (F5) | 5/5 | **P5:** `scripts/test_markitdown_cli.py` in scripts/. Verifiers: both clean; strong contracts (`scripts/markitdown_cli.py:485-525` argparse, `--outline/--section/--grep/--limit/--project/--json/--output`, errors to stderr at `:413,561-563`). | Move test to `tests/`, or omit exec bit/shebang. |
| okf-architect | 119 | 5/5 | 4/5 (F10) | **P10:** code-mode `b2b` violation — "no --fields/--project: list output is unbounded"; only `-o/--output` on viz/tree (`scripts/okf_architect.py:1742,1748`), no `--fields/--project/--limit`. Verifiers: agent-skills clean, code-mode 1 violation. Contracts otherwise good: argparse subparsers at `:1725-1752`, `--json` with progress→stderr at `:112,125`. | Add `--project/--fields` and `--limit N` to `validate`/`index`/`viz` list output, default to a compact table. |
| zoom-recorder | 65 | 4/5 (F5) | 5/5 | **P5:** `scripts/test_zoom_download.py` in scripts/. Verifiers: both clean; strong contracts (`scripts/zoom_download.py:526-538` argparse, `--limit/--project/--json/--table/--info-only/--out-dir`, errors to stderr at `:546,653,669,680`). | Move test to `tests/`, or omit exec bit/shebang. |

### Per-point tallies (across all 10 skills)
- P1 name valid + matches dir: **10 PASS / 0 FAIL** (all names valid `^[a-z0-9]+(-[a-z0-9]+)*$`, all match parent dir).
- P2 description what+when, imperative, ≤1024: **10 PASS / 0 FAIL** (measured 266–632 chars).
- P3 SKILL.md <500 lines / ~5k tokens: **10 PASS / 0 FAIL** (65–190 lines).
- P4 relative refs, one level, no chains: **9 PASS / 1 FAIL** (agent-reach).
- P5 scripts/ only runnable CLIs, helpers/tests out: **4 PASS / 6 FAIL** (pipeline-v2, agent-reach, canvas-cli, edstem-cli, markitdown-cli, zoom-recorder).
- P6 typed contracts (argparse/parseArgs/--omni-schema): **8 PASS / 2 FAIL** (edstem-cli, icm-architect).
- P7 non-interactive, actionable stderr + non-zero on missing args: **9 PASS / 1 FAIL** (cornell-notes).
- P8 `--help` with `Usage:` line, zero side effects: **8 PASS / 2 FAIL** (edstem-cli, icm-architect). argparse auto-`usage:` accepted as the Usage line.
- P9 structured `--json` clean stdout, progress/errors stderr: **8 PASS / 2 FAIL** (academic-icm, academic-pipeline-v2).
- P10 bounded output + safe defaults: **8 PASS / 2 FAIL** (icm-architect, okf-architect).

Totals: **84 PASS / 16 FAIL / 0 N-A** out of 100 points. No skill fails P1–P3 — the failures are concentrated in script hygiene (P5) and a handful of contract gaps.

## Top 5 cross-cutting fixes (ranked, with exact file:line and the minimal change)

1. **Get tests out of `scripts/` (P5 — 5 skills, highest count).** Files: `academic/agent-reach/scripts/test_reach_filter.py`, `academic/canvas-cli/scripts/test_canvas_cli.py`, `academic/edstem-cli/scripts/test_ed_cli.py`, `academic/markitdown-cli/scripts/test_markitdown_cli.py`, `academic/zoom-recorder/scripts/test_zoom_download.py`. Minimal change: `git mv` each to that skill's `tests/` (cornell-notes, icm-architect already do this correctly). Alternative: keep the file but remove the shebang/exec bit (`0644`) so omnicli never catalogs it as a tool. Related P5: `academic/academic-pipeline-v2/scripts/{adapters.py:31,stage_contracts.py:13,anki_cards.py:17}` are import-only library modules — move to `modules/`.

2. **De-derive agent-reach's self-paths (P4 + root one-source-of-truth invariant).** `academic/agent-reach/SKILL.md:70,73,77,88` use `~/.gemini/config/skills/agent-reach/scripts/reach_filter.py`; `SKILL.md:107` uses `sys.path.insert(0, "/home/rodri/.gemini/config/skills/agent-reach/scripts")`. Minimal change: replace all five with skill-root-relative `scripts/reach_filter.py` and `sys.path.insert(0, "scripts")`. These are derived harness copies; the canonical source is `~/src/my-agent-skills/academic/agent-reach/`, so the current commands break on any machine without the Gemini harness layout.

3. **Give hand-rolled CLIs typed contracts and `--help` (P6 + P8 — 2 skills).** `academic/icm-architect/scripts/links.py:84`, `quotes.py:177`, `viz.py:64`, `index.py:50` parse raw `sys.argv`; `academic/edstem-cli/scripts/ed_ws.js:311` parses raw `process.argv` with no `--help` (only an error-path `Usage:` at `:316`). Minimal change: import `argparse` (Python) / `parseArgs` from `node:util` (JS), add a `main()` with a zero-side-effect `-h/--help`, and keep existing positional semantics as positionals. This clears 4 of the 5 warnings from `verify_agent_skills.py`.

4. **Remove interactive prompts from a cataloged CLI (P7).** `academic/cornell-notes/scripts/srs_review.py:214,227,433,446` call `input()` in the `review` subcommand. Minimal change: accept answers via explicit flags (`--cue-id`, `--rating 1-4`) for Code Mode, and keep the human quiz in a separate non-cataloged script under `assets/` or with `0644`. `status` is already clean (`--json/--table/--limit` at `:489-493`).

5. **Bound list output (P10 — code-mode `b2b` violations).** `academic/icm-architect/scripts/icm_architect.py:552-583` (`map` prints all stages) and `academic/okf-architect/scripts/okf_architect.py` (`validate`/`index`/`viz` list output) have no `--fields/--project/--limit`. Minimal change: add comma-separated `--fields/--project` plus `--limit N` (default ~20) to those subparsers and default to a compact table; this is exactly what `verify_code_mode.py` checks and what clears both `b2b` violations.

## Skills that are already exec-ready (name them — do not pad)

By the strict definition (all 5 exec-readiness points 6–10 PASS, no code-mode violations): **agent-reach, canvas-cli, markitdown-cli, zoom-recorder.** All four have argparse + subcommands/flags, `--json`, `--limit/--project/--output`-style bounds, non-interactive failure, and `--help`; both verifiers return `clean: true` for them.

Caveat: three of those four (agent-reach, canvas-cli, markitdown-cli, zoom-recorder) still carry the P5 test-in-`scripts/` hygiene issue and agent-reach additionally fails P4, so they are exec-ready but not spec-clean. No skill in this batch is clean on all 10 points. Closest: cornell-notes and okf-architect (single failing point each: P7 and P10 respectively).
