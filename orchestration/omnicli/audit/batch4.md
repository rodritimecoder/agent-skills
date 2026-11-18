# Batch 4 — findings

Scope: 12 skills (hardware × 6, multimodal × 6). Audited against `agentskills.io/specification`
(dossier `07_agentskills-spec-file-references/source.md`), `orchestration/omnicli/references/agent-skills-checklist.md`,
and the current omnicli Code Mode contract. Evidence gathered by reading each SKILL.md, listing each
`scripts/`, running `python3 <entry> --help` on all 14 primary CLIs (all exit 0, print a `usage:` line
with flags/positionals/subcommands, no side effects), and grepping parsers/flags/prompt patterns.
Nothing in the skills repo was edited.

Scoring note: "usage:" from `argparse` is accepted for point 8 (canonical, case-insensitive in spirit).
Point 5 follows the checklist rule — non-CLI helper modules and `test_*.py` in `scripts/` are flagged
even when non-executable; a single non-exec renderer (`doc-layout/scripts/render_md.js`) is tolerated
with a note because omnicli will not index it.

## Per-skill table

| Skill | Lines | Spec (1-5) | Exec (6-10) | Blockers | Quick wins |
| :--- | :---: | :--- | :--- | :--- | :--- |
| hardware/audiocpp | 175 | 4/5 — P5 FAIL (P4 note) | 5/5 (P10 weak) | P5: helper modules `audiocpp_core.py:1`, `audiocpp_diar.py:1`, `audiocpp_http.py:1`, gate `check-docs.py:1`, wrapper `run-diarization.sh:1` live in `scripts/`; P4: absolute install paths in examples `SKILL.md:51,91`. | Move core/diar/http to `scripts/modules/`; use `scripts/audiocpp_cli.py` relative paths in examples; add `--dry-run` to `switch-version.sh:101` before symlink flip. |
| hardware/decision-model | 155 | 4/5 — P5 FAIL | 5/5 (P10 weak) | P5: runnable server modules `glide_serve.py:1`, `h2o_serve.py:1`, `pplx_decider.py:1`, helper `gguf_meta.py:1`, test `eval_golden.py:1` all in `scripts/`. | Move servers to `bin/`/`modules/`, `eval_golden.py` to `tests/`; keep only `decision_model.py` as indexed CLI. |
| hardware/local-llm | 120 | 5/5 | 5/5 | None (only `__pycache__` noise). | Drop `scripts/__pycache__`; otherwise exemplary (`--out`, `--json`, `--project`, `--stream`, argparse help). |
| hardware/model-layer | 172 | 5/5 | 5/5 | None (only `__pycache__` noise). | Drop `scripts/__pycache__`; `llama_rig.py` already has `--dry-run` (`SKILL.md:44,65`) and JSON reports. |
| hardware/nvidia-nim | 153 | 3/5 — P2 FAIL, P5 FAIL | 5/5 | P2: description `SKILL.md:4-8` is a passive feature list with no "Use when…"/"MUST USE for…". P5: `scripts/test_nim_client.py:1` (test in scripts). | Prepend "Use when … autonomous subagent / hosted inference …" to description; move test to `tests/`. |
| hardware/tailscale-ops | 96 | 4/5 — P2 FAIL | 3/5 — P6 FAIL, P10 FAIL | P2: description `SKILL.md:4-7` states what, no imperative "when". P6: `scripts/ts_ops.sh:5-17` hand-rolled `CMD="$1"` case, no argparse/parseArgs/`--omni-schema`. P10: destructive `sync` (`:110`) and `reset-tunnels` (`:102`) have no `--dry-run`, no `--limit`/`--output`. | Add `--omni-schema` emitting an MCP JSON Schema for the 7 subcommands; add `--dry-run` to sync/reset that prints planned serve/funnel changes; prepend "Use when…" to description. |
| multimodal/design-pack | 237 | 5/5 | 5/5 | None. `check_runner.mjs:1` is a proper shebang+parseArgs JSON helper; `tests/` already separate. | Optional `--limit` on `design-pack look`/`verify --json` for large builds; otherwise clean. |
| multimodal/doc-layout | 198 | 5/5 (P5 note) | 5/5 | P5 note: `scripts/render_md.js:1` non-exec internal renderer in `scripts/` (not indexed; acceptable per checklist). | Move `render_md.js` to `scripts/modules/` for hygiene. 322-line sibling (`video-miner`) is the only size watch, not this skill. |
| multimodal/ocr | 98 | 4/5 — P5 FAIL | 5/5 | P5: `scripts/ocr_engine.py:1` is a non-CLI library module in `scripts/`; canonical CLI `ocr.py:1` sits at skill root, not `scripts/`. | Move `ocr_engine.py` to `scripts/modules/`; relocate or symlink `ocr.py` into `scripts/` so all entrypoints live in one indexed dir. |
| multimodal/playwright | 176 | 4/5 — P2 FAIL | 5/5 (P9 via wrapper) | P2: description `SKILL.md:3-7` lists features but never says "Use this skill when…"; "Use frontend-uat for…" routes to a different skill. P9 note: in-repo `desktop_cdp.py` has no `--json`; primary `playwright-rs` wrapper does. | Add a "Use when you need browser control, screenshots, CDP attach…" trigger clause to the description. |
| multimodal/t3-browser-hands | 85 | 5/5 | 5/5 | None (only `__pycache__` noise). `t3_locate.py:1` argparse, `--json`, `--offset`, presence/confidence gates, documented exit codes. | Drop `scripts/__pycache__`; otherwise clean. |
| multimodal/video-miner | 322 | 4/5 — P5 FAIL (P3 watch) | 5/5 | P5: helper modules `videomine_core.py:1`, `videomine_stages.py:1`, `videomine_visual.py:1`, `procure.py:1` + test `test_videomine.py:1` in `scripts/`. P3 watch: 322 lines / dense prose approaches the ~5k-token soft cap. P4 note: stale `~/.gemini/config/skills/...` paths `SKILL.md:38,321`. | Move helpers to `scripts/modules/` and test to `tests/`; move the vault-publish block (`SKILL.md:287-316`) to `references/publish.md`; replace `~/.gemini/...` with skill-relative paths. |

Point tallies (PASS / FAIL / N-A):
P1 12/0/0 · P2 9/3/0 · P3 12/0/0 · P4 12/0/0 · P5 7/5/0 · P6 11/1/0 · P7 12/0/0 · P8 12/0/0 · P9 12/0/0 · P10 11/1/0.
Total hard FAILs: 10 across the batch (3× P2, 5× P5, 1× P6, 1× P10). No point was N-A.

## Top 5 cross-cutting fixes (ranked, with exact file:line and the minimal change)

1. **Give `tailscale-ops` a typed contract + safe defaults** — `hardware/tailscale-ops/scripts/ts_ops.sh:5` (`CMD="${1:-peers}"`), `:18` (`usage()`), `:102` (reset-tunnels), `:110` (sync). It is the only script in the batch with a hand-rolled parser (P6) and the only skill failing P10. Minimal change: keep the `case` dispatcher but add a `--omni-schema` branch that prints one JSON Schema for `{peers,check-port,sync,status,reset-tunnels,send-file,doctor}` with `x-flag`/`x-positional`, and add `--dry-run` to `sync`/`reset-tunnels` that prints the planned serve/funnel edits without applying them. Fixes P6+P10 (2 of 10 hard FAILs) in one file.

2. **Evict helper/test modules from `scripts/` (5 skills)** — `hardware/decision-model/scripts/gguf_meta.py:1` + `glide_serve.py:1`/`h2o_serve.py:1`/`pplx_decider.py:1` + `eval_golden.py:1`; `hardware/audiocpp/scripts/audiocpp_core.py:1` + `audiocpp_diar.py:1` + `audiocpp_http.py:1` + `check-docs.py:1`; `hardware/nvidia-nim/scripts/test_nim_client.py:1`; `multimodal/ocr/scripts/ocr_engine.py:1`; `multimodal/video-miner/scripts/test_videomine.py:1` + `videomine_core.py:1` + `videomine_stages.py:1` + `videomine_visual.py:1` + `procure.py:1`. Minimal change: `mkdir scripts/modules tests` and `git mv` libraries into `modules/`, `test_*.py` into `tests/` (keep entrypoints named in each SKILL.md at `scripts/` top level). Fixes all 5 P5 FAILs so omnicli catalogs only runnable CLIs.

3. **Make three descriptions intent-first** — `hardware/nvidia-nim/SKILL.md:4`, `hardware/tailscale-ops/SKILL.md:4`, `multimodal/playwright/SKILL.md:3`. All three are passive feature lists; the spec requires what *and* when in imperative form. Minimal change: prepend one sentence — e.g. "Use this skill when the user wants hosted frontier-model inference or an autonomous subagent loop …" / "Use when checking tailnet node reachability, reconciling served UIs, or beaming files …" / "Use when browser control, screenshots, CDP attach or JS evaluation is needed …" — each stays well under 1024 chars. Fixes 3 P2 FAILs.

4. **Add `--dry-run` to the remaining destructive gate** — `hardware/audiocpp/scripts/switch-version.sh:101-135` (symlink flip + :8081 restart, currently validated+rollback but no preview). Minimal change: accept `--dry-run <candidate>` that runs `validate()` and prints candidate/version/link plan but stops before `ln -sfn` and the restart. Complements fix #1 so every stateful op in the batch has a preview mode.

5. **Normalise file references to skill-root-relative paths** — `hardware/audiocpp/SKILL.md:51,91` (`AC="/run/media/rodri/AI/skills/audiocpp/scripts/audiocpp_cli.py"`), `multimodal/video-miner/SKILL.md:38,321` (`~/.gemini/config/skills/video-miner/scripts/...`, a stale derived-harness path). Minimal change: use `scripts/audiocpp_cli.py` and `scripts/videomine.py` (with a note that they are relative to the skill root), which also makes the examples reproducible outside this machine. Closes the two P4 notes and prevents future drift.

## Skills that are already exec-ready (name them — do not pad)

- `hardware/local-llm` — argparse CLI, `--json`/`--out`/`--project`/`--stream`, clean help, no prompt, bounded output; only `__pycache__` noise.
- `hardware/model-layer` — `llama_rig.py` argparse, documented `--dry-run`, JSON reports, clean help; only `__pycache__` noise.
- `multimodal/design-pack` — three argparse CLIs + parseArgs JSON helper, gates fail closed (`--mutate` negative control), `tests/` separate.
- `multimodal/doc-layout` — argparse CLI, `--json PATH`/`-o`/`--pages`/`--max-tokens`/`--max-edge`, required `--vlm` prevents accidental :8080 use; single tolerated non-exec renderer.
- `multimodal/t3-browser-hands` — `t3_locate.py` argparse, `--json`, `--offset`, presence/confidence gates, documented exit codes; only `__pycache__` noise.

(5 of 12. `hardware/decision-model`, `hardware/nvidia-nim`, `multimodal/ocr` and `multimodal/video-miner` are one P5 move away from ready; `hardware/tailscale-ops` needs the parser + dry-run work in fixes #1/#3.)
