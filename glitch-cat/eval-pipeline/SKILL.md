---
name: eval-pipeline

description: >
  Step-level propagation risk mitigation and intermediate artifact ledger (Glitch Cat Club / Kem Glitch;
  Reel DeHK65INHqh). Tags every step explicitly as [D] (Deterministic Code), [P] (Probabilistic Model), or [H] (Human),
  forcing disk serialization of intermediate states (step_01.json) and halting compound downstream failures via
  automated assertion gates.

compatibility: "Requires Python 3.10+. No network access needed."
allowed-tools: "Bash(python3:*) Read Write"
---

# Eval Pipeline (`eval-pipeline`)

Step-level propagation risk shield derived from **Kem Glitch (Glitch Cat Club)**'s architecture in Reel [`DeHK65INHqh`](https://www.instagram.com/reel/DeHK65INHqh/).

---

## 🏛️ The Tripartite Step Taxonomy

1. **`[D]` Deterministic Code**: Fast, cheap, exact (AST parsing, schema checking, regex).
2. **`[P]` Probabilistic Model**: Generative synthesis, clustering, semantic inference.
3. **`[H]` Human in the Loop**: Final sign-off or subjective taste.

An unchecked drift in Step 1 poisons all downstream steps (**Propagation Risk**). By serializing intermediate artifacts to disk and asserting boundaries at each handoff, failures halt immediately at the exact failing step.

---

## 🛠️ CLI Quickstart

```bash
PIPE="python3 /run/media/rodri/AI/skills/eval-pipeline/eval_pipeline.py"

# 1. Audit recorded step artifacts in ledger
$PIPE audit --ledger-dir .eval_ledger

# 2. Run self-diagnostic verification pipeline
$PIPE verify-sample
```

---

---

---

## AGENTS.md rule

## Pipeline: tag every step and gate it
When a task has more than one step, tag each step [D] (deterministic), [P] (probabilistic) or [H] (human).
- Serialize every step's output to disk before the next step reads it.
- A [P] step needs a deterministic assertion after it. A gate that cannot fail is not a gate.
- Stop at the first failed gate. Do not compound downstream on an unverified result.
