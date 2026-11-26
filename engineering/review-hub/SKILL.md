---
name: review-hub

description: >-
  Use this skill when you need to review a git diff, run a code review, audit an architecture
  or repo, or enforce quality rules: dispatch through the `review-hub` CLI (`review-hub review`,
  `review-hub audit`, `review-hub list`, `review-hub inspect`, `review-hub search`). Late-binding
  gateway to 8 suites: Ponytail (minimal diff, YAGNI), pstack (23 playbooks), Poteto (domain
  modeling), Thermo-Nuclear (harsh architectural audit), Unslop (31 AI-tell rules), TypeScript
  (type discipline), No-Comments, and Verification (grounded verification). Supports pre-flight
  response projection (`--project`) and disk buffering (`--out`) to keep context lean.

compatibility: "Requires Python 3.10+. No network access needed."
allowed-tools: "Bash(review-hub:*) Bash(python3:*) Read Write"
---

# Code Review & Architecture Audit Hub (`review-hub`)

`review-hub` is the unified CLI gateway for high-leverage code reviews, architectural audits, and quality enforcement. Instead of polluting context windows with thousands of lines of prompt rules, agents discover and dispatch audits on-demand with pre-flight response projection.

---

## Available scripts

Bundled CLI scripts, referenced relative to the skill root. Run `<command> --help`
for flags and exit codes; structured data goes to stdout, diagnostics to stderr.

- `scripts/update_suites.py` — update_suites.py — Refresh the vendored upstream suites.

## 🏛️ The 8 Core Review Suites & Disciplines

| # | Suite ID | Discipline & Core Philosophy |
|---|---|---|
| 📐 | **`ponytail`** | **Minimalist Engineering & YAGNI**: Deletion beats addition, smallest complete change, no unasked-for wrappers or boilerplate. Sub-suites: `ponytail-review` (diff review), `ponytail-audit` (repo audit), `ponytail-debt` (shortcut/todo tracking), `ponytail-gain` (benchmark savings). |
| 📚 | **`pstack`** | **Rigorous Agent Playbooks**: 23 execution playbooks (Investigation, Hillclimbing, Runtime Forensics, Babysit, Shipping). |
| 🏛️ | **`poteto`** | **Foundational Architecture**: Model the domain in types/state machines, laziness protocol, verified artifacts. |
| ⚡ | **`thermonuclear`** | **Harsh Architectural Audit**: Anti-spaghetti conditionals, 1,000-line ceiling, structural "code judo" deletions. |
| ✍️ | **`unslop`** | **AI Tell Elimination**: 31-rule scanner cutting superficial -ing clauses, corporate hedging, and robotic tone. |
| 🛡️ | **`typescript`** | **TypeScript Best Practices**: Discriminated unions, branded types, constructive modeling, zero `as` casts, schemas before guards. |
| ✂️ | **`no-comments`** | **Comment Discipline**: Strips useless code comments and AI explanations; encodes real constraints into types or runtime assertions. |
| 🔬 | **`verification`** | **Grounded Verification**: Generates and maintains project-local verification harnesses (`verify-<app>`) with Launch, Doctor, Drive, Evidence, Cleanup & Feature Maps. |

---

## 🚀 CLI Commands (`review-hub`)

### 1. View Available Review Suites
```bash
review-hub list
# Or structured JSON
review-hub list --json
```

### 2. Search Suites by Intent
```bash
review-hub search "harsh audit"
review-hub search "delete bloat"
review-hub search "ai writing tells"
```

### 3. Inspect a Single Rubric (Zero Startup Context Freight)
```bash
review-hub inspect ponytail
review-hub inspect thermonuclear
review-hub inspect typescript
```

### 4. Review Git Diff or Target File
```bash
# Review current git diff against Ponytail (minimal diff)
review-hub review ponytail

# Review against a specific file or directory
review-hub review unslop README.md

# Review diff with output buffered to disk (keeps agent context lean)
review-hub review thermonuclear --out /tmp/audit.json

# Review with field projection
review-hub review ponytail --project "status,checks"
```

### 5. Architectural & Repository Audits
```bash
# Run whole-repo debt audit
review-hub audit debt

# Run whole-repo health and vulnerability scan
review-hub audit ponytail-audit

# Run architectural limit audit
review-hub audit thermonuclear
```

### 6. Run All Core Suites Sequentially
```bash
review-hub all
review-hub all --json
review-hub all --out /tmp/full-review.json
```

---

## Exit codes

`review`, `order`, `audit` and `all` accept `--fail-on {none,warning,violation}`.
The default is **`warning`**, so a run that prints findings also fails a gate.

| Worst status | `--fail-on warning` (default) | `--fail-on violation` | `--fail-on none` |
|---|---|---|---|
| `OK` | 0 | 0 | 0 |
| `WARNING` | 1 | 0 | 0 |
| `VIOLATION` | 1 | 1 | 0 |
| error (unknown suite, usage) | 2 | 2 | 2 |

`--out` still writes the full report and `--json` still prints the same object;
only the process exit code follows the status. Unknown suites print to stderr
and exit 2 without a traceback.
