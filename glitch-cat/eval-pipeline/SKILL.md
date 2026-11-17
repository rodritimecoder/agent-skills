---
name: eval-pipeline

description: >
  Step-level propagation risk mitigation and intermediate artifact ledger. Tags every step
  explicitly as [D] (Deterministic Code), [P] (Probabilistic Model), or [H] (Human), forcing disk
  serialization of intermediate states (step_01.json) and halting compound downstream failures via
  automated assertion gates.

compatibility: "Requires Python 3.10+. No network access needed."
allowed-tools: "Bash(python3:*) Read Write"
---

# Eval Pipeline (`eval-pipeline`)

Step-level propagation risk shield derived from **Kem Glitch (Glitch Cat Club)**'s architecture in Reel [`DeHK65INHqh`](https://www.instagram.com/reel/DeHK65INHqh/).

---

## 🎯 Doctrine role: schema and vocabulary, not a runner

`eval-pipeline` is the **`[D]` / `[P]` / `[H]` step-risk doctrine plus its artifact
schema**. It defines how a multi-step job is tagged, where intermediate state is
serialized, and what a failure record must contain so a downstream step can never
consume an unverified result. Loading it makes those rules binding on the job.

It is **not** the harness that enforces the gates. `eval_pipeline.py` is a reference
implementation: `verify-sample` runs an in-memory three-step demo, and `audit` reads a
ledger someone else wrote. Neither can gate your work.

For **enforced** gates — holdouts registered before the build, hash-checked on
validation, and refusing a gate that was edited to fit the code — use
**`kem-dev-loop holdout`**. Consistency check: if `eval-pipeline` and
`kem-dev-loop holdout` disagree, the enforcement wins.

## 🏛️ The Tripartite Step Taxonomy

1. **`[D]` Deterministic Code**: Fast, cheap, exact (AST parsing, schema checking, regex).
2. **`[P]` Probabilistic Model**: Generative synthesis, clustering, semantic inference.
3. **`[H]` Human in the Loop**: Final sign-off or subjective taste.

An unchecked drift in Step 1 poisons all downstream steps (**Propagation Risk**). By serializing intermediate artifacts to disk and asserting boundaries at each handoff, failures halt immediately at the exact failing step.

---

## 🛠️ CLI Quickstart

```bash
PIPE="python3 /run/media/rodri/AI/skills/eval-pipeline/eval_pipeline.py"

# 1. Audit recorded step artifacts in ledger (exits non-zero on any failed step)
$PIPE audit --ledger-dir .eval_ledger

# 2. Run self-diagnostic verification pipeline
$PIPE verify-sample
```

`audit` reads `step_*.json` artifacts whether they use this module's `step_*` field
names or the `stage_*` names written by stage runners, prints `stage_name`/`status` as
stored, and exits non-zero when any artifact carries `"status": "failed"`. `skipped` is
reported but is not a failure. An unreadable artifact, a missing or unknown status, or a
ledger with no artifacts also exits non-zero, so the gate never passes vacuously.
`--json` emits the same verdict as a machine-readable report.

## 📁 Artifact schema

Each step writes `step_NN_<name>.json` before the next step may read it:

| Field | Meaning |
| :--- | :--- |
| `step_index` / `stage` | Position in the pipeline |
| `step_name` / `stage_name` | Step identity (`step_*` from `pipeline_core`, `stage_*` from stage runners) |
| `step_type` | `D`, `P`, or `H` |
| `status` | `passed`/`ok` on success, `failed` on a tripped gate, `skipped` when no worker ran |
| `output` | Serialized result handed to the next step |
| `failure_reason` / `errors` | Why the gate tripped — required on any failure record |
| `timestamp` | ISO-8601 UTC write time |

## AGENTS.md rule

## Pipeline: tag every step and gate it
When a task has more than one step, tag each step [D] (deterministic), [P] (probabilistic) or [H] (human).
- Serialize every step's output to disk before the next step reads it.
- A [P] step needs a deterministic assertion after it. A gate that cannot fail is not a gate.
- Stop at the first failed gate. Do not compound downstream on an unverified result.
