# Forge & Control (`references/forge.md`)

This reference covers generating a project-local verification harness (`forge`) and proving that the gate can fail before trusting it (`control`).

---

## 🏗️ `forge` — Project-Local Harness Generator

Reel [`DfCsHxbtV3J`](https://www.instagram.com/reel/DfCsHxbtV3J/): *"There isn't one skill I can hand you because verification only works when it's built for your own project. So I've made you a skill that builds your skill."*

### 1. Workflow

```bash
# 1. Interview the repo (Dry-run: writes nothing; prints 5 answers and tool card)
verify-app forge .

# 2. Approve detected tools and write files
verify-app forge . --apply

# 3. Wire into the project's instruction file (AGENTS.md by default)
verify-app forge . --apply --adopt
verify-app forge . --apply --adopt --instructions CLAUDE.md
```

### 2. How `forge` Answers the Five Questions
`forge` inspects the codebase directly without prompting the user:
- **Project Markers**: `package.json`, `pyproject.toml`, `Cargo.toml`, `requirements.txt`.
- **Surfaces & Routes**: Next.js, Remix, SvelteKit, Astro pages, FastAPI/Flask/Express decorators, static HTML.
- **Existing Drivers**: Playwright, Cypress, Storybook, Sentry.
- **Active Harness**: Detects `.opencode/`, `.claude/`, or defaults to `.agents/`.

Any question that cannot be deterministically answered from the code is emitted as an **open question** (`exit 4`). It never guesses.

### 3. Generated Files

```
.agents/skills/verify-<app>/     ← default portable Agent Skills location
├─ SKILL.md                      six H2: Launch · Doctor · Drive · Evidence · Cleanup · Helpers
├─ features/
│  ├─ README.md                  baseline, driving conventions, proof rules, entry contract
│  └─ <feature>.md               one page per detected route / endpoint / command (top 5)
└─ scripts/verify                a shim onto the global verify-app, refusing if absent

.verify/pass.json                the five-question skeleton, named for this app
```

- **Harness Portability**: Defaults to `.agents/skills` (OpenCode and standard agents). `--harness opencode` writes `.opencode/skills/`, `--harness claude` writes `.claude/skills/`, `--out DIR` overrides destination.
- **Adoption (`--adopt`)**: Appends an idempotent entry under `## Verification` in `AGENTS.md` (or `--instructions FILE`).
- **Safety**: Existing `SKILL.md` is never overwritten. Hand edits are preserved.

### 4. What `forge` Deliberately Does NOT Do
- **It does not launch your app**: The `Launch` section documents the detected command but marks it as unexecuted.
- **It does not mark unproven gates as passed**: A freshly generated skill remains a draft until: launch → doctor → drive one feature → evidence → cleanup.

---

## 🔴 `control` — Proving the Gate Can Fail

> *"It breaks one feature on purpose to make sure it can catch it and then puts it back exactly as it was, because a check you've never seen fail doesn't prove anything."* — [01:21]

### 1. Command

```bash
verify-app control --file src/app.js \
  --find "Order confirmed" --replace "Order failed" \
  --pass .verify/pass.json
```

### 2. Execution Sequence
1. **Target Verification**: `--find` must appear **exactly once** in `--file`. Ambiguous targets abort immediately.
2. **Red Run**: Mutates the file, runs the gate, asserts `verdict == "fail"`.
3. **Exact Rollback**: Reverts bytes in a `finally` block and verifies the SHA-256 matches the original byte-for-byte.
4. **Green Run**: Re-runs the gate on restored code, asserts `verdict == "pass"`.

```
PASS  control  src/app.js
  red    fail (1)  expected a failing gate
  restore 74c4d2086c92  exact
  green  pass (0)
```

### 3. Protected Files & Safety
`control` unconditionally refuses to touch:
- Files outside the repository boundary
- `.git/`, `node_modules/`, `.venv/`, `vendor/`
- Environment secrets: `.env*`, `*.pem`, `*.key`, `*.p12`, `*.keystore`
