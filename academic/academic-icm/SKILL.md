---
name: academic-icm

description: >
  Unified Academic ICM (Interpretable Context Methodology) Suite & Orchestrator. Unifies Canvas LMS
  ingestion (canvas-cli), Zoom cloud lecture & slide extraction (zoom-recorder), active-recall Cornell
  notes (cornell-notes), and OKF curriculum architecture into a single late-binding academic hub.

compatibility: "Requires the canvas-cli, zoom-recorder and cornell-notes skills, and network access for the material it ingests."
allowed-tools: "Bash(academic-icm:*) Bash(canvas-cli:*) Bash(python3:*) Read"
---

# Academic ICM (`academic-icm`)

> **Unified Academic Intelligence Suite & ICM Pipeline Orchestrator for University Knowledge Workspaces.**  
> Solves the seam between raw Canvas LMS downloads, Zoom lecture recordings, Markdown conversions, Cornell study sheets, and the OKF Knowledge Cosmos graph.

> [!NOTE]
> **Superseded by [`academic-pipeline-v2`](../academic-pipeline-v2/SKILL.md)**: The v2 pipeline inverts the architecture by sifting early with parallel classifiers, keeping structure in OKF v0.2 folders, and producing 3 focused HTML targets (`graph.html`, `anki.html`, `cornell.html`) instead of the monolithic v1 cosmos.

---

## 🏛️ Integrated Academic Modules & Commands

`academic-icm` serves as the single late-binding hub for all university academic workflows:

```bash
# 1. Canvas LMS API Integration (courses, assignments, grades, modules, announcements)
academic-icm canvas courses --summary
academic-icm canvas modules <course_id>
# Or via backward-compatible shim: canvas-cli ...

# 2. Zoom Cloud Recording & Slide Keyframe Extraction
academic-icm zoom --url <zoom_rec_url> [--passcode <code>] [--keyframes] [--ocr]
# Or via backward-compatible shim: zoom-recorder ...

# 3. Knowledge Graph & Multimodal Memory (Stage 2: EmbeddingGemma-2 768d vector)
academic-icm graph index [--corpus <dir>]
academic-icm graph search "Thevenin equivalent" --table
academic-icm graph recall "Supernode" --hops 3
academic-icm graph build-graph

# 4. Active-Recall Cornell Notes HTML & Anki TSV Generation (Stage 3)
academic-icm cornell <notes_cornell.json> [--anki]
# Or via backward-compatible shim: cornell-notes ...

# 5. Spaced Repetition (SRS) Review Engine
academic-icm srs review <notes_cornell.json>

# 6. List Integrated Modules & Rubrics
academic-icm modules
```

---

## 🏛️ The 4-Stage Architecture of Academic ICM

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│   Canvas LMS    │ ────> │   MarkItDown    │ ────> │  Graph Memory   │ ────> │  Cornell Notes  │
│  (Data Source)  │       │ (Doc Converter) │       │ (RAG & KG Walk) │       │  (Active Study) │
└─────────────────┘       └─────────────────┘       └─────────────────┘       └─────────────────┘
  canvas-cli                markitdown-cli            graph-memory              cornell-notes
  - API downloads           - PDF/PPTX/DOCX/XLSX      - 768d Multimodal Vector  - 6–8 Active cues
  - Course pages            - Clean Markdown            (EmbeddingGemma-2)      - Interactive HTML
  - Quizzes & Files         - Math & Code syntax      - Hybrid BM25 + Vector    - Anki TSV decks
  - Zoom recordings                                   - Video & Slide Indexing  - SRS review CLI
                                                      - SQLite Knowledge Graph
```

---

## 🏛️ The 4 Invariants of Academic ICM

1. **Strict Stem Inheritance (No Creative Renaming)**:

   - When generating Cornell notes from a source Markdown note, the output stem **must** match the source Markdown file stem:
     - Source: `Week_1/markdown/48520_topic_1_and_2.md`
     - Output JSON: `outputs/json/48520_topic_1_and_2_cornell.json`
     - Output HTML: `outputs/html/48520_topic_1_and_2_cornell.html`
     - Output Anki: `outputs/anki/48520_topic_1_and_2_anki.tsv`
2. **Explicit Source Linkage**:
   - Every `_cornell.json` must record `"source": "<rel_path_to_markdown>"` so the curriculum compiler can link by path fallback.
3. **Curated Curriculum Hierarchy**:
   - `CURRICULUM_TREE.md` defines the virtual chronological outline (`Week 01 → Week 02 → ...`). Prune administrative noise (empty links, welcome announcements) so the Knowledge Cosmos reflects actual learning milestones.
4. **5-Stage Verification & Unbiased 0-Context Gate**:
   - `academic-icm verify [week]` enforces Kem Glitch's step-level propagation risk shield across 5 discrete gates:
     1. Gate 1: Asset Doctor `[D]` (MIME validation, video size, Zoom passcode check).
     2. Gate 2: Markdown & KaTeX Syntax `[D]` (balance of delimiters, zero `.vtt` video links).
     3. Gate 3: Cornell JSON & Anti-VTT Invariant `[D]` (strict exclusion of subtitle files as video).
     4. Gate 4: Web Cosmos & Study Portal Compilation `[D]` (HTML & Anki sync, zero `.vtt` in DOM).
      5. Gate 5: Unbiased 0-Context Acceptance Judge `[P]` (local h2o-lightning-4b JEV decision evaluation).

---

## 🚀 CLI Commands

### 1. Run 5-Stage Verification & Unbiased Judge
```bash
# Verify entire curriculum corpus across all 5 gates
academic-icm verify

# Verify a specific week (e.g. Week 5)
academic-icm verify 5

# Auto-repair fixable defects (e.g. normalize relative source paths)
academic-icm verify --fix

# Target a specific gate (1: asset, 2: markdown, 3: cornell-json, 4: web, 5: uat/judge)
academic-icm verify 5 --stage 3
```

### 2. Run Smart Cognitive & Visual Audit (AGY 3.8 Flash + h2o-lightning-4b Vision)
```bash
# Deep cognitive audit on a specific note
academic-icm smart-check Week06_Phasors_cornell.json

# Deep cognitive & visual audit on all notes for a week
academic-icm smart-check --week 6

# Smart audit with machine-readable JSON scorecard
academic-icm smart-check --week 9 --json
```

### 3. Check Coverage & Detect Orphans
```bash
academic-icm status
# or target a specific vault
academic-icm status /run/media/rodri/AI/University/notes
```
Prints curriculum coverage table by subject, total card count, and lists orphaned notes.

### 2. Scaffold a New Note from Markdown
```bash
# Auto-generates matching _cornell.json template with pre-filled source and inherited stem
academic-icm scaffold "48520 - Electronics and Circuits/Week_2/markdown/week_2_topic_notes.md"
```

### 3. Build HTML & Anki TSV from JSON
```bash
academic-icm build-note "48520 - Electronics and Circuits/outputs/json/week_2_topic_notes_cornell.json"
```

### 4. Deep Audit & Linting
```bash
academic-icm audit
```
Verifies stem alignment, minimum cue depth (6–8 cues), LaTeX formula delimiters (`$$...$$` or `$...$`), and HTML/TSV synchronization.

### 5. Recompile Knowledge Cosmos & Study Portal
```bash
academic-icm compile
```
Compiles `CURRICULUM_TREE.md` into:
- **`viz.html`**: Dual-Mode Knowledge Cosmos (`📅 Canvas Constellations` ⟷ `🌌 Semantic Web`).
- **`cornell_index.html`**: Active-recall study portal with self-quiz launch buttons.

### 6. Repair Known Stem Drift
```bash
academic-icm sync-orphans
```
Renames and aligns historical stem mismatches so previously unlinked notes attach to the graph.

### 7. Launch Local Study Portal Server
```bash
academic-icm serve --port 8765
```
Previews the interactive portal and D3 Cosmos at `http://localhost:8765/`.

### 8. Auto-Stamp Video Solution Timestamps
```bash
# Preview timestamp matching across notes without modifying files
academic-icm stamp-video "48520 - Electronics and Circuits" --dry-run

# Auto-stamp cues in a specific note or entire subject
academic-icm stamp-video "48520 - Electronics and Circuits/outputs/json/Week_5_Topic_Notes_cornell.json"

# Recompile the curriculum tree so video drawers are activated in Study Portal & Anki cards
academic-icm compile
```
Extracts timestamps from `.vtt` and `_transcript.md` using BM25 semantic chunking, binds them to local MP4s, Zoom cloud recordings, or YouTube walkthroughs, and appends `[▶ MM:SS](url#t=sec)` directly to active-recall cues.
