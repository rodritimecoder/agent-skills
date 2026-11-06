# Agent Skills Spec Audit — `/run/media/rodri/AI/skills`

**Spec:** https://agentskills.io/specification (Agent Skills open format)
**Date:** 2026-10-20
**Scope:** 36 registered skills (all top-level symlinked skill dirs)

> **Follow-up (2026-10-20, after this audit):** the `omnicli` skill and its
> catalog were retired — and then restored to the shelf on 2026-10-30 at
> `orchestration/omnicli/`. The `:8080` LLM now
> has its own `local-llm` skill. References to `omnicli` below describe the
> state at audit time.
>
> **Second follow-up (2026-10-20):** `jev-decision` was split. It is now the
> general decision engine (bool / choice / score / composite + batch), and the
> frontend UAT layer moved to the new `frontend-uat` skill (reel `DeKBMCQNRXU`).
> The `desc-no-trigger`, `hardcoded-path` and `junk-files` findings for
> `jev-decision` were fixed in that change; the table below is the audit-time
> snapshot.

## Verdict

**0 blockers. 57 warnings. The catalogue is spec-compliant.**

Every one of the 36 skills satisfies all hard requirements of the agentskills.io
specification. The warnings are quality/portability improvements, not violations.

---

## Hard Requirements — all pass, all 36 skills

| Requirement | Result |
|---|---|
| Directory contains `SKILL.md` | 36/36 |
| YAML frontmatter present and parseable | 36/36 |
| `name` present, string, 1–64 chars | 36/36 |
| `name` matches `^[a-z0-9]+(-[a-z0-9]+)*$` | 36/36 (no uppercase, no `--`, no edge hyphens) |
| `name` matches parent directory name | 36/36 (symlinks resolve to canonical dirs, names align) |
| `description` present, non-empty, ≤1024 chars | 36/36 (range: 189–539 chars) |
| Optional `license` / `compatibility` / `metadata` / `allowed-tools` well-typed | 36/36 (3 skills use `metadata`, all string values) |
| No unknown frontmatter keys | 36/36 |
| `SKILL.md` under 500 lines | 36/36 (max: `omnicli` at 162 lines / ~1098 tokens) |
| Progressive disclosure (details in `scripts/`, `references/`, `assets/`) | 36/36 — 15 of 18 sampled skills ship a `references/` or `scripts/` dir |

Body sizes are excellent — the heaviest skill (`omnicli`) is ~1098 tokens, well
under the spec's 5000-token recommendation. Average is ~600.

## Warnings, grouped

### 1. `desc-no-trigger` — 18 skills
The spec says the description "should describe both what the skill does **and when
to use it**". Discovery only loads `name` + `description`, so the trigger phrase is
the entire routing surface.

- **Affected:** `zoom-recorder`, `ocr`, `hybrid-browser`, `omnicli`,
  `litellm-vram-switcher`, `nvidia-nim`, `tailscale-ops`, `review-hub`,
  `github-architect`, `agentic-engineering`, `eval-pipeline`, `eval-router`,
  `glitch-orchestra`, `graph-memory`, `guard-hooks`, `jev-decision`,
  `semantic-cache`, `state-compactor`, `subagent-spaces`, `parallel-test-lane`,
  `projects-harness`, `swarm-contract`, `openrouter-free`, `academic-icm`
- **Already compliant (good models):** `canvas-cli`, `cornell-notes`,
  `markitdown-cli`, `edstem-cli`, `skill-factory`, `worktree-harness`,
  `video-miner` — these all carry an explicit "Use for …" / "Use when …" clause.
- **Fix:** append one clause, e.g. for `review-hub`:
  `… Use when reviewing a diff, auditing architecture, or enforcing code-quality rules.`

### 2. `hardcoded-path` — 22 skills
Absolute `/run/media/rodri/AI/skills/...` paths in `SKILL.md` bodies. Breaks
portability and cross-machine reuse (the spec's "cross-product reuse" goal), and
binds the skill to this NTFS mount.
- **Fix:** use skill-root-relative paths (`scripts/foo.py`) per the spec's file-reference
  section, and/or `${SKILL_ROOT}`-style indirection.

### 3. `junk-files` — 4 skills
`__pycache__/` in `cornell-notes`, `jev-decision`, `omnicli`; `.env` in
`canvas-cli`, `nvidia-nim`.
- `.env` is already gitignored (correct), but present on disk.
- `__pycache__` is gitignored too but ships in any raw folder copy.
- **Fix:** `__pycache__` → already ignored; ensure `.gitignore` is enforced in the
  skill folders so raw copies stay clean.

### 4. `nested-skillmd` — 3 skills
`academic-icm`, `video-miner`, `icm-architect` ship nested `AGENTS.md` /
instruction files inside subdirectories. Not a spec violation, but they create a
second, competing instruction surface for agents that auto-load `AGENTS.md`.
- **Fix:** rename to something non-auto-loading (e.g. `references/WORKSPACE.md`)
  or move under `references/`.

### 5. `deep-ref` / `abs-ref` — 2 skills
`icm-architect` has a reference nested more than one level; `okf-architect` uses
an absolute path in a link. Spec: "Keep file references one level deep from SKILL.md."

### 6. Structural — `hybrid-browser`
`hybrid-browser/fast-cdp-rs/target/` contains **1,461 build artifacts / 431 MB** of
Rust build cache inside the skill folder. Also violates this repo's own
`AGENTS.md` rule #4 ("Do not store … heavy build caches here" on the NTFS3 volume).
- **Fix:** move `target/` outside the skill dir (e.g. `CARGO_TARGET_DIR=~/.cache/...`)
  and gitignore it.

---

## Sampled deep-dive (18 skills)

| Skill | Lines | ~Tok | Verdict | Warnings |
|---|---|---|---|---|
| canvas-cli | 86 | 595 | PASS | junk, hardcoded-path |
| cornell-notes | 74 | 472 | PASS | junk, hardcoded-path |
| zoom-recorder | 52 | 487 | PASS | desc-trigger, hardcoded-path |
| markitdown-cli | 81 | 569 | PASS | hardcoded-path |
| edstem-cli | 87 | 602 | PASS | hardcoded-path |
| ocr | 83 | 492 | PASS | desc-trigger, hardcoded-path |
| hybrid-browser | 65 | 434 | PASS | desc-trigger, hardcoded-path + 431MB target/ |
| video-miner | 120 | 810 | PASS | desc-trigger, nested-AGENTS.md |
| omnicli | 162 | 1098 | PASS | desc-trigger, junk |
| litellm-vram-switcher | 52 | 378 | PASS | desc-trigger |
| nvidia-nim | 141 | 962 | PASS | desc-trigger, junk, hardcoded-path |
| tailscale-ops | 60 | 406 | PASS | desc-trigger |
| review-hub | 78 | 567 | PASS | desc-trigger |
| skill-factory | 82 | 695 | PASS | hardcoded-path |
| github-architect | 60 | 527 | PASS | desc-trigger |
| worktree-harness | 58 | 446 | **CLEAN** | — |
| agentic-engineering | 74 | 477 | PASS | desc-trigger |
| eval-pipeline | 28 | 160 | PASS | desc-trigger, hardcoded-path |

## Spec fields this catalogue never uses

- `license` — 0/36. The repo has a top-level `LICENSE` but no skill declares one.
  Worth adding `license: <repo license>` to make each skill independently
  redistributable.
- `compatibility` — 0/36. Several skills have hard environment requirements that
  belong here: `nvidia-nim` (network + API keys), `tailscale-ops` (tailscale daemon),
  `litellm-vram-switcher` / `ocr` (dual RX 9060 XT + Vulkan), `hybrid-browser`
  (Chromium + CDP).
- `allowed-tools` — 0/36. Experimental; `guard-hooks`, `github-architect`, and
  `omnicli` invoke shell commands and would benefit.

## Follow-up: the drift rule, and what it exposed

Added a **drift rule** to `skill-factory`: a SKILL.md and the CLI it drives
describe the same command surface, and the markdown one is written by hand,
so it rots. The catalog's contract is extracted from the code and cannot
rot, so it is the reference.

| Rule | Severity | Meaning |
|---|---|---|
| `flag-drift` | error | SKILL.md passes a flag the target tool does not have |
| `undocumented-flag` | warning | SKILL.md uses a flag no `references/` file explains |
| `stale-flag-doc` | warning | a `references/` flag table lists a flag no tool accepts |

Documented in `engineering/skill-factory/references/drift-rules.md`.

**The rule found a defect in the catalog itself.** The contract extractor
gave every subcommand its *parent's* flags, so `omnicli describe ocr/ocr:read`
never mentioned `--pages`, `--output` or `--prompt` — the flags an agent
actually needed. Measured against each tool's real `--help`:

| | incomplete contracts | flags missing |
|---|---|---|
| before | 186 / 361 | 581 |
| after | 1 / 396 | 2 |

Four extractor bugs, each found by a false positive in the new rule:

1. **Subcommands inherited the parent's flags.** They now get their own
   contract, extracted by running `<script> <sub> --help`.
2. **The usage line was matched case-sensitively.** `parse_help_contract`
   looked for `"usage:"`; omnicli prints `"Usage:"`, so its contracts fell
   back to the parent's. Now case-insensitive.
3. **The `cli` shims had empty contracts.** `~/.local/bin/<skill>` is a
   symlink or a forwarding wrapper; it now inherits the contract of the
   script it points at. The wrapper is never executed — its source is read
   and the delegate is inspected.
4. **Subcommand flags lost the parent's global options.** An argparse
   subparser inherits `--table --project --out --limit --format`; its own
   `--help` does not list them. The contract is now the union.

Also fixed: the contract cache is keyed on the script's mtime, so a parser
change kept serving stale contracts. It now carries a parser version.

**Findings that survived validation — 9 warnings, no errors:**

- `canvas-cli` — `--days`, `--enrollment-state`, `--course-id` used in
  SKILL.md, absent from every `references/` file
- `edstem-cli` — `--course-id`
- `zoom-recorder` — `--course-id` (used on the Canvas pipeline example)
- `hybrid-browser` — `--click`
- `omnicli` — `--rebuild`
- `skill-factory` — `--all`, `--summary`

`flag-drift` is clean across all 36 skills: no SKILL.md invokes a flag its
tool does not have.

**Routing was checked.** The richer script documents changed BM25 ranking,
so the golden eval was re-run: 61/61 top-1 and 61/61 top-3, matching the
baseline. One case had slipped — the `local` virtual skill, which owns the
local LLM endpoint, fell to rank 4 because its description said "coder"
but never "llm". Its description now says what it is.

## Follow-up: the collection is now built to the spec

Three changes, on the reasoning that "when they were normal" was *not*
normal — the pre-retrofit tree at `7d929e5` had **invalid YAML frontmatter**
in `audiocpp` (an unquoted colon in the description), five skills with
non-string `metadata` values, eight hardcoded `~/.gemini/config/skills/...`
paths, and no `skill-factory` gate to catch any of it. Rolling back would
have deleted ten skills and reintroduced a blocker. It was not done.

### 1. `skill-factory` archived

The meta-skill that retrofits other skills is retired to `archived/skill-factory/`
— it is the only skill in the collection about skills rather than a domain
capability, and it is not surfaced to any agent.

### 2. `omnicli/mcp/` is now `omnicli/scripts/mcp_server.py`

The MCP stdio server was a program living in a skill directory, which is not
the shape the spec describes. A skill bundles scripts, so it moved into
`scripts/`. `omnicli mcp` is unchanged and still answers JSON-RPC; the
catalog tool id moved from `omnicli/mcp/server` to
`omnicli/scripts/mcp_server`.

### 3. Every skill declares the full frontmatter

All six agentskills.io fields are now on all 35 active skills:

| Field | Coverage | Content |
| :--- | :--- | :--- |
| `name` | 35/35 | required |
| `description` | 35/35 | required, with a trigger phrase |
| `license` | 35/35 | `Proprietary. Complete terms are in the LICENSE file at the repository root.` |
| `compatibility` | 35/35 | the real requirement — GPU and Vulkan, network access, an API key, a daemon, Podman, ffmpeg, a local inference port |
| `metadata` | 35/35 | provenance; `creator` preserved where a skill already had it |
| `allowed-tools` | 35/35 | the tools the skill may pre-approve, e.g. `Bash(zoom-recorder:*) Bash(ffmpeg:*) Read Write` |

`compatibility` was authored from what each skill's scripts actually import
and which ports they actually dial, not from the prose.

### The drift rules moved with the catalog

They lived in `skill-factory`, which is now archived. They belong with the
catalog they check, so they are now
`workstation-clis/omnicli/tests/skillcheck.py`:

```bash
python3 tests/skillcheck.py contracts   # catalog contract vs the real --help
python3 tests/skillcheck.py drift       # every SKILL.md vs the catalog
```

Current state: **0 contract mismatches** (8 tools have no contract at all —
hand-rolled shell CLIs the extractor correctly declines to run) and **0 drift
errors**, 7 `undocumented-flag` warnings.

The write-up is `docs/skill-drift-rules.md`.

## Final state

| Check | Result |
| :--- | :--- |
| agentskills.io spec blockers | **0** / 35 skills |
| frontmatter fields | 6 / 6 on all 35 skills |
| Catalog contract mismatches | **0** / 401 tools |
| Drift errors | **0** |
| Catalog tests | 39 / 39 |
| MCP conformance | 17 / 17 |
| Golden routing eval | 61/61 top-1, 61/61 top-3 |

## Reproduction

```bash
python3 /tmp/opencode/audit_skills.py            # all skills
python3 /tmp/opencode/audit_skills.py canvas-cli omnicli   # subset
```
Full machine-readable detail: `/tmp/opencode/audit_report.json`
