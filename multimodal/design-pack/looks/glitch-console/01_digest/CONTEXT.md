# Stage 01 · Digest (Evidence & Ingestion)

> **Workspace:** `multimodal/design-pack/looks/glitch-console/01_digest`  
> **Source:** `/run/media/rodri/AI/creator-vault/kem_glitch/2026-10-06_glitch_orchestra_alignment_first/source.mp4`  
> **Goal:** Ingest video evidence across key choreography ranges, crop terminal windows and avatar baselines using nearest-neighbor scaling (preserving discrete pixels), and produce the verifiable `evidence.json` ledger.

---

## 1. Stage Contract

| Field | Specification |
| :--- | :--- |
| **Actor** | Deterministic extraction engine (`ffmpeg` + Python PIL `Image.NEAREST`) |
| **Step Type** | `[D]` (Deterministic Code) + `[H]` (Human verification of frame boundaries) |
| **Inputs** | `source.mp4` (1080×1920 @ 30 fps) |
| **Outputs** | `evidence.json`, `crops/seg1_conductor_01_09/`, `crops/seg2_orchestra_18_26/`, `crops/seg3_progress_37_42/`, `crops/seg4_interaction_52_65/` |
| **Proof** | `python3 -c "import json; d=json.load(open('evidence.json')); assert len(d['segments']) == 4"` exit code 0 |

---

## 2. Ingested Segments & Physical Evidence

1. **`seg1_conductor_01_09` (0:01 – 0:09)**
   - Conductor solo alignment prompt (`> /glitch-orchestra`).
   - Platform bar (solid 2 rows) remains anchored to baseline (`y=596`).
   - Feet strictly grounded; body executes subtle idle breathing/blinks.
   - Outputting tell (`♫`) drifts upward into prompt area.
2. **`seg2_orchestra_18_26` (0:18 – 0:26)**
   - Stage spawn & multi-worker roster alignment.
   - Workers stand on 4 leg stubs; conductor on anchored 2-row base plate.
   - Horizontal head baseline alignment across all agents.
   - 5-step pokeball spawn cadence (flash → oversize → squash → colour fill → settle).
3. **`seg3_progress_37_42` (0:37 – 0:42)**
   - Side-by-side execution state.
   - Thinking sparkles alternate between white and orange clusters overhead.
   - Structured transcript log streaming downward without disturbing sprite baseline.
4. **`seg4_interaction_52_65` (0:52 – 1:05)**
   - Inter-agent packet communication and status board.
   - Discrete 4-dot packet ping across mid-stage communication channel.
   - Top status board counts (`TO DO`, `NEEDS YOU`, `DOING`, `CHECK`).
   - 8-cell stepped progress meter (`.bar__cell--on`).
