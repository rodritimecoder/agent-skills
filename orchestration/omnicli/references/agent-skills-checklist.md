# Agent Skills Authoring & `omnicli` Compatibility Checklist

Reference checklist combining the open [Agent Skills specification](https://agentskills.io/specification), [description optimization guide](https://agentskills.io/skill-creation/optimizing-descriptions), and [script authoring guide](https://agentskills.io/skill-creation/using-scripts) with `omnicli`'s catalog indexing and Code Mode runtime (`omnicli exec`).

---

## 1. Directory Structure & Progressive Disclosure

```
my-skill/
├── SKILL.md          # Required: YAML frontmatter + concise core instructions
├── scripts/          # Optional: self-contained CLI entrypoints (Python / JS / Shell / binaries)
├── references/       # Optional: deep-dive docs loaded on demand (e.g. REFERENCE.md)
└── assets/           # Optional: templates, lookup tables, images, static schemas
```

- **Metadata tier (~100 tokens at startup):** `name` + `description` loaded across all skills.
- **Instructions tier (<5,000 tokens / <500 lines recommended):** Keep `SKILL.md` focused on workflow, defaults, and quickstart commands. Move exhaustive tables/rubrics into `references/`.
- **Resources tier (on demand):** `omnicli describe <skill>` returns the frontmatter and section outline with per-section token estimates; `omnicli describe <skill> --section "<heading>"` or `--doc <name>` reads one piece without loading the whole file.
- **Keep library code out of `scripts/`:** Put shared helpers in `modules/` or `assets/` (or omit executable bit/shebang) and keep tests under `tests/` (`test_*.py`, `*_test.*`, `*.test.*`) so `omnicli` only catalogs runnable CLI entrypoints.

---

## 2. Frontmatter Specification (`SKILL.md`)

```yaml
---
name: my-skill
description: >
  What this skill achieves for the user. Use this skill when <intent/triggers>,
  even if the user does not name <domain keyword> explicitly.
compatibility: "Optional environment prerequisites (<= 500 chars)."
metadata:
  bins: [optional-local-bin-alias]
  docs: "references/*.md"
---
```

- **`name` (required):**
  - 1–64 characters.
  - Lowercase ASCII/unicode alphanumeric and single hyphens only: `^[a-z0-9]+(?:-[a-z0-9]+)*$`.
  - No leading/trailing `-` and no consecutive `--`.
  - **Must match the parent directory name** (`my-skill/SKILL.md` -> `name: my-skill`).
- **`description` (required):**
  - 1–1024 characters hard cap.
  - Must state both **what the skill does** and **when to use it**, with specific user-facing keywords.
- **`compatibility` (optional):**
  - 1–500 characters if present; include only real system/runtime/network requirements.
- **`metadata` (optional):**
  - String-to-string / `omnicli` extensions (`bins` for `~/.local/bin` command aliases not named after the skill; `docs` globs for extra searchable markdown playbooks).
- **`allowed-tools` / `license` (optional):**
  - Experimental pre-approved tool list / short license identifier.

---

## 3. Optimizing `description` for Reliable Triggering

1. **Use imperative phrasing:** Frame as an instruction to the agent (`"Use this skill when..."`, `"MUST USE for:"`) rather than passive third-person (`"This skill does..."`).
2. **Focus on user intent, not internal mechanics:** Match how users phrase their goal ("pull lecture recordings", "verify UI layout") rather than internal module names.
3. **Cover implicit & adjacent triggers:** Call out cases where the user doesn't name the format/tool directly (`"even if they don't explicitly mention 'CSV' or 'analysis'"`).
4. **Prevent keyword overfitting (`omnicli eval` discipline):**
   - Split trigger evals into ~60% train / ~40% validation (`golden_eval.json` vs `paraphrase_eval.json`).
   - Add realistic **should-trigger** prompts (formal, casual, typos, implicit domain) and hard **should-not-trigger** near-neighbors.
   - Audit curated aliases against eval queries with `python3 tests/overfit_check.py` so proper nouns live in `catalog/aliases.json` instead of polluting descriptions.

---

## 4. Writing Scripts for Agentic Use & `omnicli` Code Mode

Both **Python** and **JavaScript/Node** (plus Shell, Deno, Bun, Go, Rust) are first-class script targets in `omnicli`. Keep plan orchestration (`omnicli exec`) in JavaScript, and choose whichever runtime fits best for a skill's own `scripts/`:

### Runtime conventions
- **One-off package tools:** Pin exact versions (`uvx ruff@0.8.0`, `npx eslint@9.0.0`, `bunx`, `deno run`, `go run`).
- **Python (`scripts/*.py`):** Use PEP 723 `# /// script` headers or the skill's `.venv`, `if __name__ == "__main__":`, and `argparse` (gives `omnicli` automatic exact `inputSchema` extraction).
- **JavaScript / Node (`scripts/*.mjs` or `*.js`):**
  - Mark executable (`chmod +x`) with `#!/usr/bin/env node` (or `#!/usr/bin/env -S ...` inside `scripts/` / `bin/`).
  - Use Node's built-in `parseArgs` from `node:util` (`import { parseArgs } from "node:util"` or `require("node:util")`) so `omnicli`'s runtime probe extracts your flags cleanly, OR implement `--omni-schema`.
  - Keep internal helpers/libraries/tests non-executable (`0644`) or in `assets/` / `tests/` / `*.test.mjs` / `*.min.js` so they are never indexed as tools.

### Agentic CLI Design Contract
1. **Non-interactive (fail fast):** Never prompt on stdin (`input()`, `readline.createInterface` without non-interactive flags). Missing required parameters must print an actionable error + example usage to `stderr` and exit non-zero.
2. **Document `--help` with a `Usage:` line:** Print `Usage: <script> [options] ...`, flags, positionals, subcommands, and exit codes on `--help` / `-h` with **zero side effects** during help output.
3. **Structured `--json` output:** Support `--json` emitting clean, valid JSON to `stdout`; keep progress logs, warnings, and errors on `stderr`.
4. **Typed schemas (`--omni-schema` / `argparse` / `node:util` `parseArgs`):**
   - For CLIs in Bash, Rust, Go, Deno, Bun, or custom JS parsers, optionally support `--omni-schema` (mentioned in `--help` or source) printing an MCP-compatible JSON Schema to `stdout` and exiting `0`:
     ```json
     {
       "type": "object",
       "properties": {
         "limit": { "type": "integer", "x-flag": "--limit", "default": 20, "description": "Max items" },
         "format": { "type": "string", "x-flag": "--format", "enum": ["json", "md"], "default": "json" },
         "target": { "type": "string", "x-positional": true, "x-positional-index": 0 }
       },
       "required": ["target"],
       "additionalProperties": false
     }
     ```
   - `omnicli` turns `inputSchema` directly into TypeScript declarations (`omnicli spec --stubs`, `omnicli_tools.d.ts`) and runtime pre-flight validators inside `omnicli exec`.
5. **Bounded output & safe defaults:** Support `--limit` / `--offset` / `--fields` (or `--output FILE`) for list commands, `--dry-run` for stateful/destructive operations, idempotent re-runs, and clear metavars (`PORT`, `N`, `SECONDS`, `{a,b}`) when using regex-parsed `--help`.

---

## 5. Verification Commands

Run these inside `orchestration/omnicli/` after creating or updating any skill:

```bash
# 1. Rebuild catalog & inspect generated typed surface
omnicli index --rebuild
omnicli spec --skill <skill-name> --stubs

# 2. Agent Skills spec + description + script-readiness lint
python3 tests/verify_agent_skills.py --skill <skill-name> --strict

# 3. Code Mode typing & JSON-output contract gate
python3 scripts/verify_code_mode.py --skill <skill-name>

# 4. Catalog contract & SKILL.md flag-drift audit
python3 tests/skillcheck.py all

# 5. MANDATORY after any move/import/entrypoint change — the index gate is not a smoke test:
#    every affected CLI must print help and exit 0 (including ~/.local/bin symlinks).
for cli in <affected entrypoints>; do python3 "$cli" --help >/dev/null || echo "BROKEN: $cli"; done
```
