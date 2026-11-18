# Batch 5 — findings

Scope: 16 skills (orchestration ×8, engineering ×6, archived ×2). Audited against the 10-point rubric in `/tmp/opencode/skills-audit/RUBRIC.md`. Evidence gathered from each `SKILL.md`, its `scripts/` tree, and live `--help` invocations (all 10 script-bearing CLIs exit 0 with a `usage:` line and no side effects). "N-A" = skill ships no local scripts (external-CLI wrappers / command cookbooks), so exec points 6–10 do not apply locally.

## Per-skill table

Legend: `P`=PASS, `F`=FAIL, `N`=N-A. Spec columns are points 1|2|3|4|5; Exec columns are points 6|7|8|9|10.

| Skill | Lines | Spec (1-5) | Exec (6-10) | Blockers | Quick wins |
| :--- | :---: | :--- | :--- | :--- | :--- |
| orchestration/cf-architect | 122 | 1P 2P 3P 4P 5F | 6P 7P 8P 9F 10F | `scripts/test_cf_architect.py:1` is a test inside `scripts/` (pt5). `--json` only on `probe` (`cf_architect.py:250`); `budget`/`scripts-fix`/`doctor` emit prose (pt9). No `--limit/--offset/--fields/--output/--dry-run` (pt10). | Move test to `tests/`; add a top-level `--json` and route all command output through `json.dumps`; add `--out`/`--limit` to `budget`. |
| orchestration/free-swarm | 136 | 1P 2P 3P 4P 5P | 6P 7P 8P 9P 10P | No hard blockers. `install.py` has no `--json` (installer, N-A in practice); `fanout.py` has `--out`/`--timeout` but no `--limit`/`--offset`. | Add `--limit` to `fanout.py`; `--json` to `install.py:64` for symmetry. |
| orchestration/gemini-studio | 228 | 1P 2P 3P 4P 5P | 6P 7P 8P 9F 10F→P* | `--json` only on `quota` (`gemini_studio.py:933`) and `doctor` (:937); `decide`/`embed`/`subagent`/`chat`/`agent` require `--project` to get JSON (pt9). Output capped ad hoc via `[:20000]` at :623 (works but no documented bound flag). | Add one top-level `--json` to the parser at :850; document `--max-bytes`. (*pt10 passes via `--out`/`--out-json`/`--project`/`--max-*`.) |
| orchestration/gh-action-subagent | 95 | 1P 2P 3P 4P 5P | 6F 7P 8P 9F 10F | Primary CLI is hand-rolled Bash `scripts/subagent_ctl.sh` (symlinked `gh-subagent`): no `argparse`/`parseArgs`/`--omni-schema` (pt6), no `--json` (pt9), no bounded-output flags (pt10). It *does* have a literal `Usage:` line at :7 and fail-fast token check to stderr (:25) — pts7/8 pass. `roster.py` alone is clean (argparse + `--json` at :770). | Add `--omni-schema` to `subagent_ctl.sh`, or port dispatch to Python argparse; add `--json` + `--limit`. |
| orchestration/github-architect | 183 | 1P 2P 3P 4P 5F | 6P 7P 8P 9P 10P | `scripts/test_github_architect.py:1` (23 KB test) sits in `scripts/` (pt5). `git_sync.py:449` has `input()` but it is guarded by `not sys.stdin.isatty()` at :444 → non-interactive safe (pt7 PASS). | Move test to `tests/`. Otherwise the strongest exec citizen in the batch (`--limit` :939, `--project` :938, `--dry-run` :1002). |
| orchestration/omnicli | 132 | 1P 2P 3P 4P 5F | 6P 7P 8P 9P 10P | `scripts/` holds non-CLI helpers: `test_asr.py`, `test_ocr.py`, `verify_agent_skills.py`, `verify_code_mode.py` (pt5). Very large skill dir (85 KB `omnicli.py`, `.venv/`, `AUDIT.md`) but `SKILL.md` itself is 132 lines and refs are one level — pt3 passes. | Relocate test/verify scripts to `tests/` (they are intentionally documented at `SKILL.md:108–119`, so update those refs too). |
| orchestration/openrouter-free | 119 | 1P 2P 3P 4P 5P | 6P 7P 8P 9F 10P | `--json` only on `doctor` (`or_agent.py:903`); `agent`/`chat`/`decide`/`embed`/`tts`/`multi` need `--project` to return JSON (pt9). `tests/` already separated — pt5 good. | Add one top-level `--json` to the parser at :851; keep `--out`/`--project`/`--max-turns` as-is. |
| orchestration/subagent-spaces | 98 | 1P 2P 3P 4P 5P | 6P 7P 8P 9P 10F | `--json` only on `slots`/`ps` (`subagent_spaces.py:440,443`) — fine for read commands. No `--limit`/`--offset`/`--output`; destructive `prune` has no `--dry-run` (pt10). | Add `--limit`/`--offset` to `ps`, `--dry-run` to `prune`, parser at :432. |
| engineering/gws-docs | 57 | 1P 2P 3P 4F 5N | N N N N N | References escape skill root via `../gws-shared/SKILL.md` (:24) and `../gws-docs-write/SKILL.md` (:34) (pt4). No local scripts (wraps external `gws`) → exec N-A; external CLI documents `--format json`, `--dry-run`, `--page-limit`. | Replace filesystem `../` links with omnicli skill-ID references or inline the 3 shared flags needed here. |
| engineering/gws-docs-write | 58 | 1P 2P 3P 4F 5N | N N N N N | Same cross-skill `../` refs (:24, :57) (pt4). No local scripts → exec N-A. Good practice: CAUTION on write command (:52). | Same as gws-docs: drop `../` path refs. |
| engineering/gws-drive | 152 | 1P 2P 3F 4F 5N | N N N N N | **Broken reference**: `../gws-drive-upload/SKILL.md` at :33 — that skill does not exist in the repo (pt4). Exhaustive 100+ row API table inlined (:37–137), no `references/` dir (pt3). No local scripts → exec N-A. | Delete dead `+upload` row; move API resource table to `references/drive-api.md` and link it. |
| engineering/gws-shared | 91 | 1P 2P 3P 4P 5N | N N N N N | References products by name, not `../` paths — pt4 OK. No local scripts → exec N-A. External CLI is well-contracted (`--dry-run`, `--format json`, `--page-limit`, `-o/--output` at :42–62). | None material. |
| engineering/leanrea | 74 | 1P 2P 3P 4P 5N | N N N N N | Command cookbook over system tools; no local scripts and no file refs → exec N-A, pt4 N-A. Router table is core content, not an exhaustive dump (pt3 OK). | None material. |
| engineering/review-hub | 93 | 1P 2P 3P 4P 5P | 6P 7P 8P 9P 10P | Main CLI lives at root `review_hub.py` rather than `scripts/` (omnicli catalog may not index it as a skill script) — noted, not a rubric failure. `scripts/` has only runnable `update_suites.py`. `--json`/`--out`/`--project` throughout (:582–624). | Consider moving/symlinking `review_hub.py` into `scripts/` for catalog discovery. |
| archived/design-system | 90 | 1P 2F* 3P 4P 5P | 6P 7P 8P 9N 10P | Description opens passive ("One token layer and one renderer…" :5) though it contains a late "Use when…" (:10) — pt2 strict FAIL. `render.py` reads stdin only via explicit `--body -` (:147,167), not a prompt (pt7 OK). JSON N-A — it is an HTML renderer. | Move "Use when…" to the front of `description`. |
| archived/gemini-api | 44 | 1F 2F 3P 4N 5N | N N N N N | **No YAML frontmatter at all** — file starts with `# Skill: gemini-api` at :1 (pts1/2 FAIL, invisible to omnicli metadata tier). No local scripts (external Go binary) → exec N-A; that CLI does document `--schema`/`--dry-run` (:21–24). | Prepend `---\nname: gemini-api\ndescription: >- Use when…\n---`. Add archived-status marker (guard checks for it — see github-architect SKILL.md:143). |

## Top 5 cross-cutting fixes (ranked, with exact file:line and the minimal change)

1. **Restore frontmatter to `archived/gemini-api/SKILL.md:1`** — the only one of 16 skills with no YAML block; fails points 1 and 2 outright and drops it from the metadata tier / catalog. Minimal change: prepend `---`, `name: gemini-api`, a `Use when …` description, `---`. Also add the archived-status marker that `github-architect guard` expects (`github-architect/SKILL.md:143`).

2. **Evict test/verifier files from `scripts/` (point 5, 3 skills)** — `orchestration/cf-architect/scripts/test_cf_architect.py:1`, `orchestration/github-architect/scripts/test_github_architect.py:1`, and `orchestration/omnicli/scripts/{test_asr.py,test_ocr.py,verify_agent_skills.py,verify_code_mode.py}:1`. Minimal change: move to each skill's `tests/` (drop executable bit) so omnicli catalogs only runnable CLI entrypoints; update the SKILL.md refs at `cf-architect/SKILL.md:121` and `omnicli/SKILL.md:108–119`.

3. **Add a uniform top-level `--json` to the three partial CLIs (point 9, 3 skills)** — `cf_architect.py:242`, `gemini_studio.py:850`, `or_agent.py:851`. Today `--json` exists only on one subcommand each (`cf_architect.py:250`, `gemini_studio.py:933/937`, `or_agent.py:903`), forcing agents to remember `--project`. Minimal change: one `parser.add_argument("--json", action="store_true")` plus routing output through `json.dumps` when set; progress to stderr.

4. **Fix gws reference integrity (points 3 and 4, 3 skills)** — `gws-drive/SKILL.md:33` links a nonexistent `../gws-drive-upload/SKILL.md`; `gws-docs/SKILL.md:24,34` and `gws-docs-write/SKILL.md:24,57` use cross-skill `../` paths. Minimal change: delete the dead `+upload` row, replace `../` filesystem links with omnicli skill-ID references (or inline the 3 needed shared flags), and move the 100-row Drive API table (`gws-drive/SKILL.md:37–137`) to `references/drive-api.md`.

5. **Give the hand-rolled `gh-subagent` CLI a typed, bounded contract (points 6/9/10)** — `orchestration/gh-action-subagent/scripts/subagent_ctl.sh:1` (symlinked as `gh-subagent` in `~/.local/bin`) parses flags by hand with no `--omni-schema`, no `--json`, no `--limit`/`--dry-run`. Minimal change: add `--omni-schema` emitting the MCP JSON Schema and a `--json` + `--limit` pair to the `status`/`logs` actions; keep the existing literal `Usage:` helper at :7 and the fail-fast token check at :25, which already satisfy points 7–8.

Cross-cutting counts (aggregate over 16 skills):
- Pt1 name: 15 PASS / 1 FAIL / 0 N-A
- Pt2 description: 14 PASS / 2 FAIL / 0 N-A
- Pt3 size/refs-in-references: 15 PASS / 1 FAIL / 0 N-A
- Pt4 one-level refs: 12 PASS / 3 FAIL / 1 N-A
- Pt5 scripts hygiene: 7 PASS / 3 FAIL / 6 N-A
- Pt6 typed contracts: 9 PASS / 1 FAIL / 6 N-A
- Pt7 non-interactive: 10 PASS / 0 FAIL / 6 N-A
- Pt8 `--help` Usage line: 10 PASS / 0 FAIL / 6 N-A
- Pt9 structured `--json`: 5 PASS / 4 FAIL / 7 N-A
- Pt10 bounded output/safe defaults: 7 PASS / 3 FAIL / 6 N-A

Note on point 8: all 10 local CLIs use `argparse`, which prints a lowercase `usage:` line (verified: all exit 0, no side effects). This satisfies the intent (usage line with flags/subcommands, zero side effects) but not the literal capital-U `Usage:`; only `subagent_ctl.sh:7` prints it verbatim. Scored PASS on intent.

## Skills that are already exec-ready (name them — do not pad)

Five skills pass every applicable exec point (6–10) with no blockers:
- **orchestration/github-architect** — argparse, fail-fast, `--json`, `--limit`/`--project`/`--dry-run`; only defect is a test in `scripts/` (spec pt5).
- **orchestration/omnicli** — the gateway itself is the bounded-output reference implementation; only defect is helpers/tests in `scripts/` (spec pt5).
- **engineering/review-hub** — argparse subcommands, `--json`, `--out`, `--project` across list/search/review/audit/all.
- **orchestration/free-swarm** — `fanout.py` has argparse, `--json`, `--out`, `--timeout`, `--check`, `--strict`.
- **archived/design-system** — `render.py` has argparse, explicit `--body -`, `--out`, exit-2 on unknown look; JSON is genuinely N-A for an HTML renderer.

Not exec-ready (exec-point blockers): `cf-architect` (pt9,10), `gemini-studio` (pt9), `gh-action-subagent` (pt6,9,10), `openrouter-free` (pt9), `subagent-spaces` (pt10).
N-A for exec (no local scripts — external-CLI wrappers / cookbook): `gws-docs`, `gws-docs-write`, `gws-drive`, `gws-shared`, `leanrea`, `gemini-api`.
