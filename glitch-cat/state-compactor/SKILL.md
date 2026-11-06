---
name: state-compactor

description: >
  Zero-loss state protocol for long agent sessions: continuous writes to .agent_state.json and
  STATE.md while the context is still sharp, so a fresh window can be rehydrated with 100%
  fact parity, plus cgate for context-gated reading of large files through a local LLM. Use
  when a long session is getting confused or drifting, to keep the facts straight across a
  compaction, to hand state to a subagent, or to slice a huge file instead of reading it
  whole. It preserves facts rather than summarising them away.

compatibility: "Requires the local Qwen3.6-35B Genesis LLM on :8080 for `cgate query` projection (see the `local-llm` skill). `cgate view` and `cgate grep` need no server."
allowed-tools: "Bash(state-compactor:*) Bash(python3:*) Read Write"
---

# State Compactor & Context Rot Shield — Zero-Degradation Long Context Protocol

```
   Traditional LLM Compaction (Lossy & Toxic):
   [Chat History (80k tokens)] ──► LLM Summarizer ──► [Hallucinated/Degraded Summary] ──► Context Poisoning

   Kem Glitch State Protocol (Zero-Loss):
   [Agent Execution] ──────────► Continuous Write to .agent_state.json & STATE.md while sharp
                                        │
   [Compaction Threshold Hit] ──────────▼
   [Fresh Context Window]    ◄── Inject Structured State File (100% Fact Parity)

   Context Gating (cgate):
   [Raw Large Files / Grep]   ──► cgate view / grep / query (local LLM :8080) ──► 5-15 Token-Clean Lines
```

---

## ⚡ Grounded Architecture (Reels `DdyqnietB8C` & `DaCtZ6FtkjI`)

1. **Context Rot & Token Exhaustion:** Long conversations degrade reasoning, drop earlier constraints, and burn context windows on massive log files or code dumps.
2. **Context Poisoning:** Native auto-compaction triggers too late, runs an uncontrolled LLM summary over past turns, compresses an error into "fact", and poisons all subsequent turns.
3. **The State File Solution (`state-compactor`):** Continuous writing of ground-truth facts, invariants, decisions, and negative constraints into `.agent_state.json` and mirrored in human-readable `STATE.md`.
4. **The Retrieval Gating Solution (`cgate`):** Reading full files to find a 2-line detail bloats context. `cgate` uses AST symbol extraction and the local **Qwen3.6-35B Genesis LLM (`:8080`)** to project only what is strictly needed into the prompt.

---

## 🛠️ Usage

### 1. Context Gating with `cgate` (Prevents Context Bloat)

```bash
# View file with automatic context guarding (symbols outline + preview if file > 35 lines)
cgate view path/to/file.py

# Extract ONLY a specific function or class definition via AST without reading the whole file
cgate view path/to/file.py --symbol MyClass
cgate view path/to/file.py --lines 45-80

# Outline all classes/functions and their line spans
cgate outline path/to/file.py

# Context-safe ripgrep (groups by file, limits output, prevents 500-line terminal spills)
cgate grep "def parse_asr" /run/media/rodri/AI/skills/

# Ask the local LLM (:8080) a question about a file and get a concise 2-sentence response
cgate query path/to/file.py "What does the get_outline function return?"
```

---

### 2. State Ledger with `state-compactor` (Prevents Context Poisoning)

```bash
# Initialize in current workspace
state-compactor init --goal "Build distributed Raft engine" --limit 30000

# Automated command wrapping: runs command, logs fact on success (0), logs forbidden rule on failure
state-compactor wrap --fact "Unit tests passing cleanly" --done "Implement snapshotting" -- pytest tests/test_raft.py

# Record facts, decisions, invariants, and negative constraints manually
state-compactor record --fact "cgate query uses the local LLM on :8080"
state-compactor record --decision "Use SQLite over Redis for zero dependencies"
state-compactor record --forbidden "Do NOT edit ~/.gemini downstream directly; edit /run/media/rodri/AI/skills/"
state-compactor record --task "Add snapshotting unit tests"
state-compactor record --done "Scaffold Raft state machine"

# Check compaction threshold
state-compactor check

# Generate clean zero-loss handover prompt for next agent or post-compaction
state-compactor compact --out /tmp/handover_prompt.md

# Inspect current state ledger
state-compactor inspect
```

---

---

---

## AGENTS.md rule

## State: read the ledger, not the pile
When you need the current state of a long-running task, run:
cgate outline <file>            # symbols and shape
cgate view <file> --symbol <Name>   # one symbol
- Do not read whole files into context. Slice them.
- The authoritative state is `.agent_state.json` and `STATE.md`; update them one fact per line.
- Never let an old summary overwrite a newer fact. Supersede in place.
