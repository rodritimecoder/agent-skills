---
name: review-hub

description: >
  Unified Code Review, Architecture Audit, and Quality Enforcement Gateway. Late-binding
  dispatch hub for 8 core engineering review suites: Ponytail (minimal diff & YAGNI), pstack (23 playbooks),
  Poteto Mode (domain modeling & discipline), Thermo-Nuclear (harsh architectural audit),
  Unslop (31 AI tell elimination rules), TypeScript (type discipline), No-Comments (comment constraints),
  and Verification (grounded verification). Provides full pre-flight response projection (--project)
  and disk buffering (--out) to eliminate context bloat.

compatibility: "Requires Python 3.10+. No network access needed."
allowed-tools: "Bash(review-hub:*) Bash(python3:*) Read Write"
---

# Code Review & Architecture Audit Hub (`review-hub`)

`review-hub` is the unified CLI gateway for high-leverage code reviews, architectural audits, and quality enforcement. Instead of polluting context windows with thousands of lines of prompt rules, agents discover and dispatch audits on-demand with pre-flight response projection.

---

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
