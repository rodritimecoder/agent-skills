# Agent Skills (`agent-skills`)

[![Spec](https://img.shields.io/badge/spec-agentskills.io-blue.svg)](https://agentskills.io/specification)
[![Code Mode](https://img.shields.io/badge/runtime-Code--Mode%20%7C%20Omnicli-orange.svg)](orchestration/omnicli/references/code-mode-sdk.md)
[![Verification](https://img.shields.io/badge/verification-Kem%20Gates%20%28Rule%207%29-green.svg)](glitch-cat/kem-thought/SKILL.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A production-engineered collection of **55+ autonomous AI agent skills** unified into a single open architecture.

Built on the open [agentskills.io](https://agentskills.io) specification, powered by Cloudflare's **Code Mode** pattern via `omnicli`, and governed by **Kem Glitch's Grounded Verification** principles to eliminate LLM prompt context bloat.

---

## 🏛️ Foundational Architecture

This collection unifies four core production engineering disciplines:

1. **[Agent Skills Open Specification](https://agentskills.io/specification)**:
   Every skill declares standard YAML frontmatter (`name`, `description`), progressive disclosure (`SKILL.md` under 500 lines, detailed logic in `scripts/` and `references/`), and relative asset resolution. Drop-in compatible with Claude Code, Cursor, Gemini CLI, Pi Agent, Boxxy Claw, OpenCode, and GitHub Copilot.

2. **Cloudflare Code Mode + Uber MCP Gateway (`omnicli`)**:
   Instead of multi-turn chat loops dumping raw terminal output into prompt history, tools generate a typed Python SDK (`omnicli_tools.py`). Agents execute Python scripts (`omnicli exec`) in local sandboxes, filtering megabytes of data in memory and emitting only concise, synthesized answers to the prompt.

3. **Kem Glitch Grounded Verification (Rule 7: Zero Context Bloat)**:
   A gate that cannot fail is not a gate. Every CLI tool accepts `--json` for machine-parseable stdout, routes progress logs to `stderr`, and enforces negative control probes (`test $? -ne 0` on mutated inputs).

4. **Argparse Metavar Typing**:
   CLI arguments specify semantic placeholders (`metavar="N"`, `metavar="TIMEOUT"`, `metavar="SCORE"`, `choices=[...]`), allowing the AST and contract parsers to expose strictly typed Python parameters (`int`, `float`, `Literal[...]`) instead of untyped strings.

---

## 📂 Domain Breakdown

```
agent-skills/
├── surface/                  # Flat discovery layout (symlinks for instant harness mounting)
├── glitch-cat/               # Kem Glitch autonomous software factory & verification tools
├── academic/                 # Canvas LMS, Zoom extraction, OKF v0.2, and Cornell study notes
├── multimodal/               # Document layout analysis, bounding box grounding, vision OCR
├── hardware/                 # Local dual-GPU inference, audio.cpp STT/TTS, Genesis 35B
├── orchestration/            # Omnicli late-binding gateway, subagent sandboxes, review hub
└── engineering/              # Playwright CDP automation, Leasebox multiplayer files
```

### 1. `glitch-cat/` (Autonomous Engineering & Verification)
* **`kem-dev-loop`**: Kem's 6-phase development lifecycle: Fast/Full route classification, hidden holdouts, parallel vertical slices, and human intent alignment.
* **`verification`**: Hands-and-eyes verification gate. Real viewport driving, CDP network/console exception monitoring, Storybook state walking, and pixel diffs.
* **`frontend-uat`**: Sub-second clickable target loop powered by local decision model probability gating.
* **`graph-memory`**: Deterministic k-hop SQL walk over graph knowledge + BM25 and vector reciprocal rank fusion (RRF).
* **`state-compactor`**: Zero-degradation state ledger with memory line caps and `cgate` context-gated file inspections.
* **`swarm-contract`**: Tripartite agent contract enforcing hard financial and token spending ceilings in code.
* **`parallel-test-lane`**: Partitions regression test suites into sequential-isolated vs. parallel lanes.
* **`projects-harness`**: Multi-agent coordinator with dual-provenance envelopes and atomic memory updates.

### 2. `academic/` (University Learning & Knowledge Representation)
* **`canvas-cli`**: Read Canvas LMS courses, assignments, submissions, gradebooks, announcements, and files with handwritten PDF OCR stroke detection.
* **`okf-architect`**: Open Knowledge Format (OKF v0.2) curriculum architecture, concept graph visualizer, and strict audit validator.
* **`zoom-recorder`**: Transcript, slide keyframe, and metadata extraction from Zoom cloud recordings without admin API credentials.
* **`cornell-notes`**: Converts Markdown notes into print-ready active-recall Cornell HTML with spaced repetition self-quiz modes.
* **`edstem-cli`**: Forum thread search, discussion reading, and cloud workspace filesystem synchronization.

### 3. `multimodal/` (Vision, OCR, and Media Mining)
* **`clip-box`**: Bounding box localization engine returning 4-corner coordinates with calibrated presence gating.
* **`doc-layout`**: PP-DocLayoutV3 region classification (25 layout types) paired with vision OCR.
* **`kem-ocr`**: MiniCPM-OCR with Jev structural verification and corrupted-candidate holdouts.
* **`video-miner`**: Verbatim speech-to-text, perceptual keyframe deduplication, and structured note distillation from video.

### 4. `hardware/` & `orchestration/` (Inference & Workstation Infrastructure)
* **`omnicli`**: Unified gateway: BM25 tool search, progressive contract inspection, and Code-Mode execution.
* **`review-hub`**: Multi-suite review gateway bundling Ponytail (minimal diffs), pstack playbooks, and Unslop.
* **`audiocpp`**: High-speed local speech-to-text and voice narration.
* **`subagent-spaces`**: Rootless CPU-pinned containerized worker sandboxes.

---

## 🚀 Quickstart

### Method A: Traditional Agent Discovery (`agentskills.io`)
Point your agent harness at the flat `surface/` directory:

* **OpenCode**: In `~/.config/opencode/opencode.json`:
  ```json
  {
    "skills": ["/path/to/agent-skills/surface"]
  }
  ```
* **Claude Code / Gemini CLI / Cursor / Pi**: Symlink or copy `surface/` into your harness skills path:
  ```bash
  ln -s /path/to/agent-skills/surface ~/.gemini/config/skills
  ```

### Method B: Cloudflare Code Mode (`omnicli`)
Execute multi-step workflows in local memory without prompt context bloat:

```python
#!/usr/bin/env python3
from omnicli_tools import canvas_cli, graph_memory_recall

# 1. Fetch data through strongly typed Python SDK
assignments = canvas_cli(command="assignments", limit=5, json=True)

# 2. Query knowledge graph in memory
facts = graph_memory_recall(command="exam topics", hops=2, top_k=3)

# 3. Only the synthesized result enters the model prompt
print("Retrieved assignments and study facts without context poisoning.")
```

Run inside the Bubblewrap sandbox:
```bash
omnicli exec plan.py
```

---

## 🛡️ License

Released under the [MIT License](LICENSE).
