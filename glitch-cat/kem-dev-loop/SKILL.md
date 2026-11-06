---
name: kem-dev-loop
description: >
  Kem Glitch's 6-phase autonomous AI development lifecycle (Glitch Cat Club; Reel DemLMidtxxj).
  Enforces: (1) upfront complexity classification (Fast vs Full route), (2) human plan approval
  for intent, (3) hidden anti-sycophancy holdouts, (4) parallel vertical slices, (5) grounded
  human-persona validation before code review, and (6) final human intent check.
compatibility: "Requires python3, git, and local decision model (:8083)."
allowed-tools: "Bash(kem-dev-loop:*) Bash(jev:*) Bash(review-hub:*) Bash(git:*) Read Write"
---

# Kem Dev Loop (`kem-dev-loop`)

> **Kem Glitch's 6-phase production engineering lifecycle from Glitch Cat Club (Reel `DemLMidtxxj`).**  
> Acts as the master orchestrator coordinating `eval-router`, `worktree-harness`, `frontend-uat`, and `review-hub` into a repeatable, anti-sycophantic development system.

---

## 🏛️ The 6-Phase Lifecycle

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  1. CLASSIFY     │ ──> │  2. INTENT &     │ ──> │  3. PARALLEL     │
│  Fast vs Full    │     │     HOLDOUTS     │     │     BUILD        │
└──────────────────┘     └──────────────────┘     └──────────────────┘
     eval-router             plan.md approval         worktree-harness
                                                             │
                                                             ▼
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  6. PRODUCTION   │ <── │  5. CODE REVIEW  │ <── │  4. GROUNDED     │
│     & INTENT     │     │     (Decoupled)  │     │     VALIDATE     │
└──────────────────┘     └──────────────────┘     └──────────────────┘
     human gate              review-hub               verification / CDP
```

---

## 🛠️ CLI Quickstart

```bash
# 1. Classify an incoming task (Fast Route vs Full Route)
kem-dev-loop route "Refactor auth middleware to use JWT with Redis sessions"

# 2. Initialize a feature run with isolated plan and hidden holdouts
kem-dev-loop init user-auth-refactor

# 3. Add hidden holdout scenarios (builders NEVER see these)
cat << 'EOF' > .kem-loop/user-auth-refactor/holdouts/test_expired_session.py
def test_expired_session():
    # builder agent cannot inspect or game this
    ...
EOF

# 4. Run grounded validation (runs your suite + every holdout; logs evidence per gate)
kem-dev-loop validate user-auth-refactor --test "pytest tests/test_auth.py"

# 4b. UI work: prove the app with hands and eyes, not a screenshot claim
verify-app doctor --json
verify-app run --pass .verify/pass.json

# 5. Decoupled code review (refuses until phase 4 has actually passed)
kem-dev-loop review --suite ponytail src/auth/
kem-dev-loop review --suite unslop src/auth/

# 6. Human evaluates alignment with original 'Why & Why Not' before git push
```

### Routing fails closed

`route` runs a deterministic pre-screen before it spends a model call. Any
cross-cutting surface (`auth`, `session`, `jwt`, `migration`, `schema`, `api`,
`payment`, `security`, `refactor`, `deploy`, …) forces `FULL_ROUTE` with no model
consulted.

Only genuinely ambiguous tasks reach the decision model, and a task is granted
autonomy (`FAST_ROUTE`) only when the model picks *small* at **≥75 % confidence**
from a live server. Everything else routes to the human gate:

| Condition | Route | Reported as |
| :--- | :--- | :--- |
| Cross-cutting keyword hit | `FULL_ROUTE` | `deterministic` |
| Model says *complex* | `FULL_ROUTE` | `jev` |
| Model says *small* below 75 % | `FULL_ROUTE` | `jev` |
| Decision server down (keyword fallback) | `FULL_ROUTE` | `degraded` ⚠️ |
| `jev` not installed | `FULL_ROUTE` | `unavailable` ⚠️ |

A dead server never reads as a calibrated decision. The output names its source
and confidence, and `DEGRADED` says so out loud. The asymmetry is deliberate:
a needless plan review costs minutes, a skipped one costs intent.

### Gates that can actually fail

- `validate` **executes** every file in `holdouts/` (`.py` via pytest, `.sh` via
  bash, `.js` via node) and records stdout, stderr and exit code per gate.
- No `--test` and no holdouts is a **refusal**, not a pass. There is nothing to fail.
- A missing pytest is reported as an environment fault and does not burn a retry.
- Two failed validations is the cap; a third needs `--force`, because adversarial
  death loops are the thing this loop exists to avoid.
- `review` refuses to run against a run whose `meta.json` has
  `validation_passed: false`. Pass `--run <name>` when `.kem-loop/` holds more than
  one run.


---

## 🛡️ Key Architectural Invariants

1. **Anti-Sycophancy via Holdouts:**
   When coding agents inspect their own test assertions during authoring, they exhibit sycophancy—hardcoding dummy mocks and fragile heuristics to pass the test. Holdout scenarios are isolated in `.kem-loop/<run>/holdouts/` and executed strictly at validation time.
2. **Validation First, Code Review Second:**
   Never mix code review into functional testing. Prove that software works for a real human persona first by driving the live app (`verify-app run` from the `verification` skill: real viewport, console, network, latency and pixels). `frontend-uat` is the sub-second click loop; `verification` is the durable PASS/FAIL artifact. Once proven functional, run `review-hub` for type discipline and clean architecture.
3. **No Adversarial Death Loops:**
   Infinite critic-writer loops burn context and money. Every validation rejection must carry hard serialized failure evidence (screenshots, stdout/stderr, traces) back to the builder with strict retry caps (max 2 iterations).
4. **Human Retains the "Why and Why Not":**
   Models excel at building but naturally drift away from business constraints. The human explicitly approves `plan.md` upfront on complex work, and validates intent at the finish line.

---

## 📚 References
- [`references/architecture.md`](references/architecture.md) — Complete blueprint, Mermaid diagrams, and reel transcript notes.
