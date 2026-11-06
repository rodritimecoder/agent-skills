# Autonomous Subagent Delegation & Model Hierarchy

Multi-Tier Model Routing, Rate-Limit Defense, and Compute Partitioning.

---

## 1. The Delegation Hierarchy Matrix

To maintain high throughput, avoid concurrency throttling (429s), and minimize cost, subagent workloads are partitioned across 4 distinct compute tiers:

```
┌────────────────────────────────────────────────────────────────────────┐
│  Tier 0: Frontier Architect (Antigravity / Gemini Harness Lead)       │
│  - System Planning & Task Decomposition (tasks.json)                  │
│  - Complex Cross-File Judgements & Final User Signoff                 │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
        ┌───────────────────────────┴───────────────────────────┐
        ▼                                                       ▼
┌───────────────────────────────────┐   ┌───────────────────────────────────┐
│ Tier 1: High-Speed Parallel Coder │   │ Tier 2: Heavy-Reasoning Coder     │
│ - gemini-3.5-flash-lite           │   │ - nvidia/nemotron-3-ultra (550B)  │
│ - 15 RPM Free Tier, ~1.2s Latency │   │ - Deep architectural refactoring  │
│ - Component logic & unit tests    │   │ - Complex algorithmic transforms  │
└─────────────────┬─────────────────┘   └─────────────────┬─────────────────┘
                  │                                       │
                  └───────────────────┬───────────────────┘
                                      ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Tier 3: Calibrated Decision & Gating Routers                         │
│  - inception/mercury-decide:free (via /api/alpha/decisions, P(choice)) │
│  - nvidia/nemotron-3.5-lightning:free (fast classification)            │
│  - h2o-lightning-4b (:8083) (Zero-cost local calibrated + vision)     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  Tier 4: Zero-Cost Offline Local Failover                              │
│  - Qwen3.6-35B-A3B Uncensored Genesis (:8080 on dual RX 9060 XT)      │
│  - Nemotron 3.5 RNNT ASR (:8081) / Kokoro TTS                          │
│  - LightOnOCR-3-0.8B (:8085) / DeskForge-Qwen3.5-4B (:8088)              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Model Capabilities & Routing Contracts

| Role | Primary Model | Fallback | Protocol / Endpoint |
| :--- | :--- | :--- | :--- |
| **Frontier Architect** | Antigravity Native / Gemini | Local Genesis 35B | Interactive Agent Harness |
| **Fast Subagent Worker** | `gemini-3.5-flash-lite` | `nemotron-3.5-lightning:free` | `generativelanguage.googleapis.com` |
| **Heavy Logic Worker** | `nvidia/nemotron-3-ultra-550b-a55b:free` | `qwen-2.5-coder-32b:free` | `openrouter.ai/api/v1/chat` |
| **Discrete Decisions** | `inception/mercury-decide:free` | `h2o-lightning-4b` (`:8083`) | `openrouter.ai/api/alpha/decisions` |
| **Vector Embeddings** | `liquid/lfm-2.5-embedding-350m:free` | `bge-small-en-v1.5` (`:8087`) | `openrouter.ai/api/v1/embeddings` |
| **Speech-to-Text (ASR)** | Local Nemotron 3.5 ASR (`:8081`) | Whisper Fallback | `audio.cpp` server |
| **Speech Generation (TTS)**| `fish-audio/s2.1-pro-free:free` | Local Kokoro TTS (`:8081`) | `openrouter.ai/api/v1/audio/speech` |

---

## 3. Sandboxing & Resource Partitioning

Subagent processes are isolated at the operating system level to prevent CPU starvation or runaway RAM consumption:

### CPU Thread Topology (16-Thread Ryzen)
Using [`subagent-spaces`](../subagent-spaces/SKILL.md), 16 hardware threads are divided into pinned zones:
- **Cores 0–3 (Host Desktop)**: Dedicated exclusively to Host OS, display server, and GPU driver interrupts.
- **Cores 4–15 (Worker Pool)**: 12 threads dynamically partitioned into:
  - **12 Micro-Spaces**: 1-thread / 1GB RAM spaces for lightweight subagent loops (`subagent-spaces run --cores 4 ...`).
  - **3 Coarse Quad-Core Slots**: Slot 1 (`4–7`), Slot 2 (`8–11`), Slot 3 (`12–15`).
  - **Full Throttle Slot**: All 12 threads for parallel compiles (`make -j12`).

### Browser Sandbox Strategy (Single vs. Multi-Browser)
- **Code Refactoring & Feature Building**: Employ **One Dedicated Verification Officer** running Podman Chromium (`:9222`). Other workers write pure code and unit tests with zero browser overhead.
- **Parallel Web Scraping & Multi-Role Testing**: Spawn up to **3 isolated `BrowserContext` sessions** within a single Chromium daemon (Admin vs. Member vs. Guest) to conserve RAM (~350 MB total vs. 2 GB for 3 heavy browser containers).
