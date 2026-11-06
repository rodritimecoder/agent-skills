---
name: swarm-contract

description: >
  Dynamic agent swarm governance via the tripartite contract and hard budget ceiling (Glitch Cat Club / Kem Glitch;
  Reel DeW6_fqt-cq). Enforces (1) explicit hit-list goals, (2) strict scorecard schema validation for all workers
  (rejecting vague markdown summaries), and (3) an immutable financial/token spending ceiling that halts execution
  in code before budget overruns.

compatibility: "Requires Python 3.10+. No network access needed."
allowed-tools: "Bash(python3:*) Read Write"
---

# Swarm Contract (`swarm-contract`)

Dynamic multi-agent swarm governance adhering to Kem's (Glitch Cat Club) **Tripartite Swarm Contract**:
1. **The Goal**: Defined deliverables and hit list.
2. **The Scorecard Contract**: Rigid schema every worker must populate (rejecting unstructured markdown chatter).
3. **The Hard Budget**: Non-negotiable token and financial ceiling that deterministically halts execution in code.

---

## 🛠️ CLI Quickstart

```bash
SWARM="python3 /run/media/rodri/AI/skills/swarm-contract/swarm_contract.py"

# 1. Initialize a dynamic swarm with a goal and a $2.00 hard budget
$SWARM init --goal "Audit 20 microservices for CVEs" --budget 2.00 --tokens 200000

# 2. Check budget before spawning subagent
$SWARM check --est-cost 0.05 --est-tokens 5000

# 3. Record worker scorecard upon completion
$SWARM record --scorecard '{"worker_id": "w1", "target": "auth", "status": "pass", "findings": "No CVEs"}' \
              --cost 0.04 --tokens 4200

# 4. View live swarm status & remaining spend
$SWARM status
```

---

---

---

## AGENTS.md rule

## Swarm contract
Before spending, write the contract:
swarm init --goal "<hit list>" --budget <dollars> --tokens <n>
swarm check --est-cost <c> --est-tokens <n>
- Every worker returns a scorecard with the schema, not a markdown summary.
- The budget ceiling is enforced in code. If the check says no, stop — do not find another way.
