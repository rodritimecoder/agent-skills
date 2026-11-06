# `jev-decision` CLI reference

Everything the SKILL.md quickstart leaves out. Paths are relative to the skill root.

---

## Flags

| Flag | Where | Meaning |
| :--- | :--- | :--- |
| `--context` / `--context-file` | every primitive | The facts, inline or on disk. Exactly one is required. |
| `--question` | bool, choice, composite | What to decide. Phrase it as one closed question. |
| `--options` | choice, composite | Candidate answers, space separated (quote each if it contains spaces). |
| `--criteria` | score (required), composite (optional) | What "good" means — the scoring rubric in words. |
| `--image PATH` | all | Screenshot or image. Local path, or a `data:` URL. |
| `--json` | all | Structured output instead of the compact line. Works before or after the subcommand. |
| `--out FILE` | all | Write the JSON to `FILE`, print one pointer line. |
| `--require-server` | all | Exit `3` instead of falling back to the keyword heuristic. |
| `--host`, `--port` | all | Override the endpoint (default `127.0.0.1:8083`; honors `$JEV_HOST`). |

---

## Output shapes

```jsonc
// bool
{"primitive": "bool", "decision": true, "confidence": 0.95,
 "probabilities": {"true": 0.978, "false": 0.022}, "source": "h2o-lightning-4b"}

// choice
{"primitive": "choice", "selection": "parallel_worker_lane", "confidence": 0.99,
 "probabilities": {"parallel_worker_lane": 0.9997, "...": 0.0003}, "source": "..."}

// score
{"primitive": "score", "score": 0.8979,
 "probabilities": {"0.0": 0.0, "0.25": 0.01, "0.5": 0.08, "0.75": 0.2, "1.0": 0.71},
 "source": "..."}

// composite
{"gate": true, "action": "merge_now", "quality_score": 0.9119,
 "confidence": 0.88, "source": "..."}
```

`source` is the served model's id (for example `h2o-lightning-4b` or
`vllm-d3-mini-Q4_K_M.gguf`) when the server answered, `heuristic_fallback`
when the keyword heuristic did. Assert on it in anything that must not guess.

---

## Batch

One `/v1/systemone` request carrying many typed questions. This is the right shape for
"decide 20 things about this document": the facts are sent once, the round trip is paid
once.

```bash
python3 jev_decision.py batch questions.json --out answers.json
```

```json
{"state": "the facts every question shares",
 "questions": {
   "q_bool":   {"type": "bool",   "instructions": "Is the deployment cancelled?"},
   "q_choice": {"type": "choice", "instructions": "Which lane?",
                "options": ["lane_a", "lane_b"]},
   "q_score":  {"type": "score",  "instructions": "How urgent is this?",
                "levels": ["none", "low", "medium", "high"]}}}
```

- `options` is required for `choice`; `levels` is optional for `score` (default
  `0.0 / 0.25 / 0.5 / 0.75 / 1.0`).
- A batch has no heuristic fallback: if the server does not answer, the command exits
  `3`. Partial guessing across twenty questions would be worse than failing.
- Output maps each id to the same shape a single primitive returns.

---

## Context de-duplication (`clean-context`)

The pairwise recipe for a memory/file full of claims that supersede each other: each
candidate pair is a `bool` ("does B supersede A?"), and the newer of a superseding pair
is kept.

```bash
cat > claims.json <<'EOF'
[{"timestamp": "2026-01-01", "text": "Deploy target is AWS ECS."},
 {"timestamp": "2026-06-01", "text": "AWS ECS is obsolete, migrated to local Podman."}]
EOF
python3 jev_decision.py clean-context --claims-file claims.json --json
```

```json
{"total_input_claims": 2, "active_claims_retained": 1, "superseded_count": 1,
 "active": [...], "superseded": [...]}
```

Cost is O(N²) decisions in N claims — fine for tens, not thousands. For a large
transcript, chunk it first (or feed each chunk through `batch`).

---

## Remote and Tailscale

The host may be a Tailscale node; HTTPS and self-signed certificates are handled.

```bash
export JEV_HOST="rodri-x870-taichi-creator.tail2975a8.ts.net"
jev-decision bool --context "Cluster health check" --question "Is the network healthy?"
```

Images are base64-inlined automatically, so a local screenshot path works against a
remote host.
