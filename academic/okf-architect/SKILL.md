---
name: okf-architect

description: Autonomous Open Knowledge Format (OKF v0.2) architect and validator. Design, scaffold, validate, and maintain agent-friendly knowledge bundles adhering to Google's Open Knowledge Format specification. Use whenever asked to create an OKF bundle, validate OKF compliance, scaffold concepts with provenance, trust tiers, and lifecycle signals, generate progressive-disclosure index.md and log.md files, or structure knowledge for AI agents and cross-organizational exchange.

compatibility: "Requires Python 3.10+. No network access needed."
allowed-tools: "Bash(okf-architect:*) Bash(python3:*) Read Write"
---

# OKF Architect (`okf-architect`)

Build, maintain, and certify **Open Knowledge Format (OKF v0.2)** bundles.

OKF Architect structures knowledge corpora, domain catalogs, and connected concepts into portable, verified markdown bundles for human inspection and autonomous agent navigation.

Specification reference: [Google Cloud Platform Knowledge Catalog OKF v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) (mirrored locally in `references/SPEC.md`).

---

## 🏛️ Core Principles of OKF v0.2

1. **Human & Agent Readable**: Zero schema registry or bespoke SDK required. Plain UTF-8 Markdown with YAML frontmatter. If you can `cat` a file, you can read it; if you can `git clone` a repository, you can distribute it.
2. **First-Class Provenance & Trust**:
   - `sources`: External or internal inputs with objective credibility signals (`author`, `usage_count`, `last_modified`).
   - `generated`: Who or what generated the content (`by: <actor>`, `at: <datetime>`).
   - `verified`: Who confirmed it against sources. Trust tiers:
     - No `verified` ⇒ **unverified**
     - Verified by process/agent ⇒ **machine-confirmed**
     - Verified by `human:<id>` ⇒ **human-reviewed**
3. **Lifecycle & Freshness**:
   - `status`: `draft` | `stable` | `deprecated`.
   - `stale_after`: ISO 8601 absolute timestamp (`now >= stale_after` triggers staleness).
4. **Progressive Disclosure**:
   - `index.md`: Directory-level catalogs providing quick summaries before diving into individual concept files.
   - `log.md`: Chronological history of additions, updates, and deprecations.
5. **Attested Computations (`type: Attested Computation`)**:
   - Attaches sanctioned executable logic (`runtime: python | bigquery | ...`) to concepts, ensuring agents execute blessed logic rather than improvising math or queries.

---

## 🚀 CLI Automation & Usage

The skill provides an automated zero-dependency CLI at `scripts/okf_architect.py`.
Run these from this skill's directory; the paths inside are relative to it.

```bash
# 1. Validate an existing OKF bundle directory against spec v0.2
python3 scripts/okf_architect.py validate [bundle_path]

# 2. Scaffold a brand new, spec-compliant OKF bundle
python3 scripts/okf_architect.py scaffold [target_path] --title "My Domain Knowledge" --domain "Engineering"

# 3. Refresh or rebuild all index.md listings for progressive disclosure
python3 scripts/okf_architect.py index [bundle_path]

# 4. Generate standalone interactive knowledge graph (viz.html)
python3 scripts/okf_architect.py viz [bundle_path]

# 5. Compile CURRICULUM_TREE.md into Canvas Constellations & Cornell Study Portal
python3 scripts/okf_architect.py compile-tree [bundle_path] [--init]
```

---

## 📁 Standard OKF Bundle Layout

```text
bundle-root/
├── index.md                 # Root catalog with okf_version: "0.2" frontmatter
├── log.md                   # Chronological update log (YYYY-MM-DD)
├── overview.md              # Root entry concept
├── concepts/                # Grouped concept documents
│   ├── index.md             # Subdirectory progressive disclosure index
│   ├── architecture.md      # Frontmatter + body
│   └── data_pipeline.md
└── references/              # Mirrored schemas, source docs, and attester code
    ├── index.md
    └── sources.md
```

---

## 📝 Concept Frontmatter Standard

Every `.md` file (except reserved `index.md` and `log.md`) represents a **Concept**:

```yaml
---
type: Concept                  # REQUIRED
title: Concept Display Name    # Recommended
description: One sentence summary for search snippets and index generation
resource: https://...          # Optional canonical resource URI
tags: [tag1, tag2]
status: stable                 # draft | stable | deprecated
stale_after: 2026-12-31T00:00:00Z
generated:
  by: okf-architect/v0.2
  at: 2026-10-13T00:00:00Z
verified:
  - by: human:rodri
    at: 2026-10-13T00:00:00Z
sources:
  - id: source-doc
    resource: https://...
    title: Canonical Source
    author: human:maintainer
    last_modified: 2026-10-01T00:00:00Z
---

# Concept Title
Body text with conventional headings (`# Schema`, `# Examples`, `# Computation`).
```
